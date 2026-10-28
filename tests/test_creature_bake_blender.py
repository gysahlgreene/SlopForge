"""B6's bake in real Blender: a walk keyed on the B1 fixture quadruped as video2rig's import_motion keys one (the
clip's 16 fps times at the scene's 24, the root's travel in its own axes, speeding up as #149's g2 did), measured,
made in place, cut to its loop, exported as FBX and rendered through two start cameras."""
import json
import subprocess
from pathlib import Path

import pytest

from slopforge.creature_rig import deformation_poses
from tests.test_creature_rig import LIMBS, LIMITS, NAMES, creature
from tests.test_creature_rig_blender import BLENDER, blender

ROOT = Path(__file__).resolve().parents[1]

KEY_WALK = """
import json, math, sys
import bpy
from mathutils import Quaternion, Vector
request = json.loads(open(sys.argv[sys.argv.index('--') + 1]).read())
scene = bpy.context.scene
scene.render.fps, scene.frame_start = 24, 1
rig = next(o for o in scene.objects if o.type == 'ARMATURE')
rig.animation_data_create()
rig.animation_data.action = bpy.data.actions.new('walk_s2')
for bone in rig.pose.bones:
    bone.rotation_mode = 'QUATERNION'
hips = rig.pose.bones['Hips']
to_local = (rig.matrix_world.to_3x3() @ hips.bone.matrix_local.to_3x3()).inverted()
phase = {'front.L': 0.0, 'hind.R': 0.25, 'front.R': 0.5, 'hind.L': 0.75}
for k in range(121):
    t, frame = k / 16, 1 + k / 16 * 24
    hips.location = to_local @ Vector((0.01 * math.sin(2 * math.pi * t / 1.2), -(0.3 * t + 0.02 * t * t), 0))
    hips.keyframe_insert('location', frame=frame)
    for leg, chain in request['legs'].items():
        cycle = (t / 1.2 - phase[leg]) % 1.0
        angle = math.radians(70) * math.sin(math.pi * cycle / 0.3) if cycle < 0.3 else 0.0
        knee = rig.pose.bones[chain[1]]
        knee.rotation_quaternion = Quaternion((1, 0, 0), angle)
        knee.keyframe_insert('rotation_quaternion', frame=frame)
for curve in rig.animation_data.action.layers[0].strips[0].channelbags[0].fcurves:
    for point in curve.keyframe_points:
        point.interpolation = 'LINEAR'
bpy.ops.wm.save_as_mainfile(filepath=request['save'])
"""

PROBE = """
import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=sys.argv[sys.argv.index('--') + 1])
rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
start, end = rig.animation_data.action.frame_range
print('PROBED_FBX', len(rig.pose.bones), int(round(end - start)))
"""


def cameras(path):
    views = [{"name": "v2r_front", "width_px": 960, "height_px": 1080, "type": "ortho", "location": [0, -30, 0.6],
              "right": [1, 0, 0], "up": [0, 0, 1], "forward": [0, 1, 0], "x0_px": 0},
             {"name": "v2r_side", "width_px": 960, "height_px": 1080, "type": "ortho", "location": [30, 0, 0.6],
              "right": [0, 1, 0], "up": [0, 0, 1], "forward": [-1, 0, 0], "x0_px": 960}]
    for view in views:
        view.update(ortho_height=1.6, ortho_width=1.6 * 960 / 1080)
    path.write_text(json.dumps({"frame_px": [1920, 1080], "hover": 0.0, "views": views}))
    return path


def bake(folder, walk, times):
    """blender/bake_extracted_motion.py on the keyed walk; its report and request."""
    folder.mkdir()
    request = {"legs": {leg: chain[-2:] for leg, chain in walk["chains"].items()}, "root_bone": "Hips",
               "fit_bones": sorted(NAMES.values()), "fbx": str(folder / "walk_s2.fbx"),
               "blend": str(folder / "walk_s2.blend"), "renders": str(folder / "renders"),
               "cameras": str(cameras(folder / "cameras.json")), "samples": 4, "times": times,
               "report": str(folder / "bake.json")}
    (folder / "request.json").write_text(json.dumps(request))
    done = subprocess.run([BLENDER, str(walk["blend"]), "--background", "--factory-startup", "--python",
                           str(ROOT / "blender/bake_extracted_motion.py"), "--", str(folder / "request.json")],
                          capture_output=True, text=True)
    assert Path(request["report"]).is_file(), done.stdout[-2000:] + done.stderr[-2000:]
    return json.loads(Path(request["report"]).read_text()), request


@pytest.fixture(scope="module")
def walk(tmp_path_factory):
    """The B1 fixture quadruped, rigged through blender/creature_rig.py, with KEY_WALK's walk on it."""
    if not Path(BLENDER).is_file():
        pytest.skip("Blender is not installed")
    tmp_path = tmp_path_factory.mktemp("walk")
    rig = creature(extra=0)
    fixture = {"vertices": rig["vertices"].tolist(), "triangles": rig["triangles"].tolist(), "bones": rig["bones"],
               "parents": rig["parents"], "heads": rig["heads"].tolist(),
               "leads": [rig["bones"][k] for k in rig["weights"].argmax(1)]}
    source, raw = str(tmp_path / "source.fbx"), str(tmp_path / "raw.glb")
    blender(tmp_path, {"action": "fixture", "fixture": fixture, "source": source, "raw": raw})
    checked = blender(tmp_path, {"action": "check", "raw": raw, "limbs": LIMBS, "limits": LIMITS,
                                 "views": {view: str(tmp_path / f"{view}.png") for view in ("front", "side")}})
    poses = deformation_poses(set(checked["names"].values()))
    blender(tmp_path, {"action": "finish", "source": source, "raw": raw, "names": checked["names"],
                       "facing": checked["facing"], "rigged_model": str(tmp_path / "rig.fbx"),
                       "blend": str(tmp_path / "rig.blend"), "poses": poses,
                       "pose_images": [str(tmp_path / f"pose_{k}.png") for k in range(len(poses))]})
    chains = {f"{limb['end']}.{limb['side']}": [NAMES[bone] for bone in limb["chain"]] for limb in checked["limbs"]}
    keyed = tmp_path / "key.json"
    keyed.write_text(json.dumps({"legs": chains, "save": str(tmp_path / "walk.blend")}))
    script = tmp_path / "key_walk.py"
    script.write_text(KEY_WALK)
    done = subprocess.run([BLENDER, str(tmp_path / "rig.blend"), "--background", "--factory-startup", "--python",
                           str(script), "--", str(keyed)], capture_output=True, text=True)
    assert done.returncode == 0 and (tmp_path / "walk.blend").is_file(), done.stdout[-2000:] + done.stderr[-2000:]
    return {"blend": tmp_path / "walk.blend", "chains": chains, "root": tmp_path}


def test_an_imported_walk_is_measured_made_in_place_cut_to_its_loop_and_exported(walk):
    report, request = bake(walk["root"] / "good", walk, [k / 16 for k in range(121)])
    assert report["status"] == "complete", report.get("errors")

    assert report["period_s"] == pytest.approx(1.2, abs=0.07)
    assert report["window"]["cycles"] >= 4 and report["window"]["seam_deg"] < 5
    assert 0.3 < report["speed_mps"] < 0.5                   # 0.3 m/s speeding up by 0.04 m/s every second
    assert report["stride_m"] == pytest.approx(report["speed_mps"] * report["period_s"], abs=0.002)
    assert report["residual_travel_m"] < 0.03                # 3.4 m of travel removed, the sway kept
    assert sorted(report["plants"]) == ["front.L", "front.R", "hind.L", "hind.R"]
    # the window's ends are keys on whole scene frames, so the FBX bakes exactly the measured loop (16 fps keys sit on
    # every other 24 fps frame)
    window = report["window"]
    assert window["end_frame"] - window["start_frame"] == round((window["end_s"] - window["start_s"]) * 24)
    phases = [item for item in report["renders"] if item["index"] != "seam"]
    seam = [item for item in report["renders"] if item["index"] == "seam"]
    assert len(phases) == 8 and len(seam) == 2 and all(Path(item["path"]).stat().st_size for item in report["renders"])
    assert {item["clip_frame"] for item in seam} == {window["end"]}
    # the review steps through one cycle's phases, not the same phase several cycles apart
    frames = sorted({item["clip_frame"] for item in phases})
    assert len(frames) == 4 and (frames[-1] - frames[0]) / 16 < report["period_s"]
    assert Path(request["blend"]).is_file()

    probe = walk["root"] / "probe.py"
    probe.write_text(PROBE)
    seen = subprocess.run([BLENDER, "--background", "--factory-startup", "--python", str(probe), "--",
                           request["fbx"]], capture_output=True, text=True).stdout
    bones, frames = next(line.split()[1:] for line in seen.splitlines() if line.startswith("PROBED_FBX"))
    assert int(bones) == len(NAMES)
    assert int(frames) == window["end_frame"] - window["start_frame"]


def test_keys_that_are_not_the_clips_frame_times_are_refused(walk):
    """video2rig keyed at its own cadence (#149: Wan's 16 fps read as 24) would make the period 2/3 of the truth and the
    Unity speed 1.5x."""
    report, _ = bake(walk["root"] / "wrong", walk, [k / 24 for k in range(121)])
    assert report["status"] == "error" and "clip's frame times" in report["errors"][0]
    assert "failure_code" not in report                       # the tool's timing, not the clip, is wrong
