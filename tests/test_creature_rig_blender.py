"""B1 in real Blender: a four-legged fixture GLB checked, named, finished and posed by blender/creature_rig.py."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from slopforge.creature_rig import deformation_poses
from tests.test_creature_rig import LIMBS, LIMITS, NAMES, creature

ROOT = Path(__file__).resolve().parents[1]
BLENDER = (os.environ.get("BLENDER_BIN") or shutil.which("blender")
           or "/Applications/Blender.app/Contents/MacOS/Blender")


def blender(tmp_path, request):
    path = tmp_path / f"{request['action']}.json"
    request["report"] = str(tmp_path / f"{request['action']}_report.json")
    path.write_text(json.dumps(request))
    process = subprocess.run([BLENDER, "--background", "--factory-startup", "--python",
                              str(ROOT / "blender/creature_rig.py"), "--", str(path)], capture_output=True, text=True)
    assert process.returncode == 0, process.stdout[-3000:] + process.stderr[-3000:]
    return json.loads(Path(request["report"]).read_text())


@pytest.mark.skipif(not Path(BLENDER).is_file(), reason="Blender is not installed")
def test_a_fixture_quadruped_is_checked_named_and_finished(tmp_path):
    rig = creature(extra=0)
    fixture = {"vertices": rig["vertices"].tolist(), "triangles": rig["triangles"].tolist(), "bones": rig["bones"],
               "parents": rig["parents"], "heads": rig["heads"].tolist(),
               "leads": [rig["bones"][k] for k in rig["weights"].argmax(1)]}
    source, raw = str(tmp_path / "source.fbx"), str(tmp_path / "raw.glb")   # creature rig's source is the published FBX
    blender(tmp_path, {"action": "fixture", "fixture": fixture, "source": source, "raw": raw})

    views = {view: str(tmp_path / f"{view}.png") for view in ("front", "side")}
    report = blender(tmp_path, {"action": "check", "raw": raw, "limbs": LIMBS, "limits": LIMITS, "views": views})
    assert report["status"] == "passed", report["errors"]
    assert report["facing"] == "-Y" and report["names"] == NAMES
    assert all(Path(path).stat().st_size for path in views.values())

    poses = deformation_poses(set(report["names"].values()))
    images = [str(tmp_path / f"pose_{k}.png") for k in range(len(poses))]
    finished = blender(tmp_path, {"action": "finish", "source": source, "raw": raw, "names": report["names"],
                                  "facing": report["facing"], "rigged_model": str(tmp_path / "rig.fbx"),
                                  "blend": str(tmp_path / "rig.blend"), "poses": poses, "pose_images": images})
    assert finished["status"] == "complete"
    assert sorted(finished["bone_names"]) == sorted(NAMES.values())
    assert finished["lateral_x_min"] > 0.99            # every bone's local X lies across the body
    assert finished["material_coverage"]["base_color"] > 0
    assert (tmp_path / "rig.fbx").stat().st_size and (tmp_path / "rig.blend").stat().st_size
    assert all(Path(path).stat().st_size for path in images)
    # the skin is opaque: Blender's FBX import wired the published base colour's Color into Alpha, and Cycles (video2rig's
    # studio) drew the B1 wolf see-through
    probe = ("import bpy\nfor m in bpy.data.materials:\n    for n in (m.node_tree.nodes if m.use_nodes else []):\n"
             "        if n.type == 'BSDF_PRINCIPLED':\n            print('ALPHA', m.name, len(n.inputs['Alpha'].links), "
             "n.inputs['Alpha'].default_value)\n")
    checked = subprocess.run([BLENDER, "--background", str(tmp_path / "rig.blend"), "--python-expr", probe],
                             capture_output=True, text=True).stdout
    alphas = [line.split()[-2:] for line in checked.splitlines() if line.startswith("ALPHA")]
    assert alphas and all(links == "0" and float(value) == 1.0 for links, value in alphas), alphas
    # lit as the material previews (the wolf's: mean luminance 138): one sun left its near side dark (64), the
    # character review's lights, made for a 1.8 m humanoid, blew it out (218)
    rest = np.asarray(Image.open(images[0]).convert("RGB"), float)
    creature_pixels = np.abs(rest - rest[2, 2]).sum(2) > 12
    assert 100 < (rest[creature_pixels] @ (0.2126, 0.7152, 0.0722)).mean() < 190
