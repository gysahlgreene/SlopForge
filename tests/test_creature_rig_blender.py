"""B1 in real Blender: a four-legged fixture GLB checked, named, finished and posed by blender/creature_rig.py."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

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
