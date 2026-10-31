"""B1 in real Blender: a four-legged fixture GLB checked, named, finished and posed by blender/creature_rig.py."""
import json
import math
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


WEIGHTS_PROBE = """import bpy, json
out = []
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        names = {g.index: g.name for g in obj.vertex_groups}
        rows = [[(names[g.group], round(g.weight, 6)) for g in v.groups if g.weight > 0] for v in obj.data.vertices]
        out.append({"mesh": obj.name, "armatures": sum(m.type == 'ARMATURE' for m in obj.modifiers), "weights": rows,
                    "rest": [list(obj.matrix_world @ v.co) for v in obj.data.vertices]})
print('PROBE' + json.dumps(out))
"""


def probe_weights(blend):
    out = subprocess.run([BLENDER, "--background", str(blend), "--python-expr", WEIGHTS_PROBE], capture_output=True,
                         text=True).stdout
    return json.loads(next(line[5:] for line in out.splitlines() if line.startswith("PROBE")))


@pytest.mark.skipif(not Path(BLENDER).is_file(), reason="Blender is not installed")
def test_the_skin_can_be_weighted_again_by_bone_heat_on_a_voxel_proxy(tmp_path):
    """Owner ruling 2026-10-30 (#154): the model's own weights stretch the wolf's chest and face; weights from bone
    heat on a closed voxel proxy of the skin (the character route's bind_with_proxy), four influences at most, cut
    that 3-5x. The skin stays where it was; only the weights change."""
    rig = creature(extra=0)
    fixture = {"vertices": rig["vertices"].tolist(), "triangles": rig["triangles"].tolist(), "bones": rig["bones"],
               "parents": rig["parents"], "heads": rig["heads"].tolist(),
               "leads": [rig["bones"][k] for k in rig["weights"].argmax(1)]}
    source, raw = str(tmp_path / "source.fbx"), str(tmp_path / "raw.glb")
    blender(tmp_path, {"action": "fixture", "fixture": fixture, "source": source, "raw": raw})
    report = blender(tmp_path, {"action": "check", "raw": raw, "limbs": LIMBS, "limits": LIMITS,
                                "views": {view: str(tmp_path / f"{view}.png") for view in ("front", "side")}})
    poses = deformation_poses(set(report["names"].values()))
    finished = {}
    for weights in ("skintokens", "proxy_heat"):
        out = tmp_path / weights
        out.mkdir()
        finished[weights] = blender(out, {
            "action": "finish", "source": source, "raw": raw, "names": report["names"], "facing": report["facing"],
            "rigged_model": str(out / "rig.fbx"), "blend": str(out / "rig.blend"), "poses": poses,
            "pose_images": [str(out / f"pose_{k}.png") for k in range(len(poses))], "skin_weights": weights})
    assert finished["skintokens"]["skin_weights"] == {"method": "skintokens"}
    bound = finished["proxy_heat"]["skin_weights"]
    assert bound["method"] == "voxel_proxy_bone_heat" and bound["influences_max"] <= 4
    before, after = probe_weights(tmp_path / "skintokens/rig.blend"), probe_weights(tmp_path / "proxy_heat/rig.blend")
    assert [mesh["mesh"] for mesh in before] == [mesh["mesh"] for mesh in after]
    for old, new in zip(before, after):
        assert new["armatures"] == 1
        assert np.allclose(old["rest"], new["rest"], atol=1e-6)                   # the skin did not move
        assert all(1 <= len(row) <= 4 and abs(sum(w for _, w in row) - 1) < 1e-4 for row in new["weights"])
        assert any(len(row) > 1 for row in new["weights"])                       # blended, not the fixture's one bone
        assert sorted({name for row in new["weights"] for name, _ in row}) <= sorted(NAMES.values())


@pytest.mark.skipif(not Path(BLENDER).is_file(), reason="Blender is not installed")
def test_the_finish_straightens_a_turned_head_and_makes_it_the_rest_pose(tmp_path):
    """Owner's choice 2026-10-31: the finish turns Neck1..Head about the vertical until the muzzle is on the body's
    line, and that pose becomes the rest pose; the skin follows its weights, the legs and body stay where they were."""
    from tests.test_creature_rig import turned_head
    rig = turned_head()
    fixture = {"vertices": rig["vertices"].tolist(), "triangles": rig["triangles"].tolist(), "bones": rig["bones"],
               "parents": rig["parents"], "heads": rig["heads"].tolist(),
               "leads": [rig["bones"][k] for k in rig["weights"].argmax(1)]}
    source, raw = str(tmp_path / "source.fbx"), str(tmp_path / "raw.glb")
    blender(tmp_path, {"action": "fixture", "fixture": fixture, "source": source, "raw": raw})
    report = blender(tmp_path, {"action": "check", "raw": raw, "limbs": LIMBS, "limits": LIMITS,
                                "views": {view: str(tmp_path / f"{view}.png") for view in ("front", "side")}})
    assert report["status"] == "passed" and report["measured"]["rig_head_turn"] > 0.1
    poses = deformation_poses(set(report["names"].values()))
    finished = {}
    for straighten in (False, True):
        out = tmp_path / f"straighten_{straighten}"
        out.mkdir()
        finished[straighten] = blender(out, {
            "action": "finish", "source": source, "raw": raw, "names": report["names"], "facing": report["facing"],
            "rigged_model": str(out / "rig.fbx"), "blend": str(out / "rig.blend"), "poses": poses,
            "pose_images": [str(out / f"pose_{k}.png") for k in range(len(poses))], "straighten_head": straighten})
    assert finished[False]["head"] == {"straightened": False}
    head = finished[True]["head"]
    assert head["straightened"] and head["turn_before"] > 0.1 and head["turn_after"] < 0.005
    assert head["yaw_before"] == pytest.approx(math.degrees(math.atan2(0.15, 0.28)), abs=1.5)
    assert abs(head["yaw_after"]) < 1.0
    before, after = probe_weights(tmp_path / "straighten_False/rig.blend"), probe_weights(tmp_path / "straighten_True/rig.blend")
    rest_before, rest_after = np.array(before[0]["rest"]), np.array(after[0]["rest"])
    moved = np.linalg.norm(rest_after - rest_before, axis=1)
    hind = np.array([rest[1] > 0.3 and rest[2] < 0.42 for rest in rest_before])   # the hind legs' skin
    assert moved[hind].max() < 1e-5 and moved.max() > 0.05                           # legs stay; the head turned
    assert after[0]["armatures"] == 1
