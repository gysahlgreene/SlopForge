"""B2 in real Blender: known motions of the B1 fixture quadruped, seeded, byte-stable and inside the declared ranges."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from slopforge.creature_views import creature_config
from tests.test_creature_rig import LIMBS, LIMITS as RIG_LIMITS, creature
from tests.test_creature_rig_blender import BLENDER, blender
from tests.test_creature_views import LIMITS

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not Path(BLENDER).is_file(), reason="Blender is not installed")


@pytest.fixture(scope="module")
def rigged(tmp_path_factory):
    """The fixture quadruped through B1's check and finish: its rig .blend and creature.json."""
    tmp = tmp_path_factory.mktemp("rigged")
    rig = creature(extra=0)
    fixture = {"vertices": rig["vertices"].tolist(), "triangles": rig["triangles"].tolist(), "bones": rig["bones"],
               "parents": rig["parents"], "heads": rig["heads"].tolist(),
               "leads": [rig["bones"][k] for k in rig["weights"].argmax(1)]}
    source, raw = str(tmp / "source.fbx"), str(tmp / "raw.glb")
    blender(tmp, {"action": "fixture", "fixture": fixture, "source": source, "raw": raw})
    views = {view: str(tmp / f"{view}.png") for view in ("front", "side")}
    report = blender(tmp, {"action": "check", "raw": raw, "limbs": LIMBS, "limits": RIG_LIMITS, "views": views})
    blender(tmp, {"action": "finish", "source": source, "raw": raw, "names": report["names"], "facing": report["facing"],
                  "rigged_model": str(tmp / "rig.fbx"), "blend": str(tmp / "rig.blend"), "poses": [],
                  "pose_images": []})
    return tmp / "rig.blend", creature_config("fixture", report, LIMITS)


def synth(tmp, blend, config, name, **options):
    request = {"creature": config, "out": str(tmp / f"{name}.npz"), "truth": str(tmp / f"{name}.json"),
               "report": str(tmp / f"{name}_report.json"), **options}
    (tmp / f"{name}_request.json").write_text(json.dumps(request))
    process = subprocess.run([BLENDER, str(blend), "--background", "--factory-startup", "--python",
                              str(ROOT / "blender/synth_motion.py"), "--", str(tmp / f"{name}_request.json")],
                             capture_output=True, text=True, env={**os.environ, "SLOPFORGE_PACKAGE_ROOT": str(ROOT)})
    return process, json.loads(Path(request["report"]).read_text())


def test_a_seeded_motion_is_byte_stable_and_inside_its_ranges(rigged, tmp_path):
    blend, config = rigged
    for name in ("a", "b"):
        process, report = synth(tmp_path, blend, config, name, kind="random", seed=3, frames=48)
        assert report["status"] == "complete", process.stdout[-2000:] + process.stderr[-2000:]
    assert (tmp_path / "a.npz").read_bytes() == (tmp_path / "b.npz").read_bytes()
    motion = np.load(tmp_path / "a.npz")
    assert motion["quats"].shape == (48, len(config["fit_bones"]) + 1, 4)     # every bone; HeadEnd is not fitted
    truth = json.loads((tmp_path / "a.json").read_text())
    assert max(truth["max_turn_degrees"]["FrontPaw.L"]) <= 150 and truth["moved_bones"] == config["fit_bones"]
    assert truth["max_turn_degrees"]["Shin.L"][1:] == [0.0, 0.0]          # a knee folds about X only
    other, _ = synth(tmp_path, blend, config, "c", kind="random", seed=4, frames=48)
    assert (tmp_path / "c.npz").read_bytes() != (tmp_path / "a.npz").read_bytes()
    process, report = synth(tmp_path, blend, config, "gait", kind="gait", frames=48)
    assert report["status"] == "complete", process.stdout[-2000:]


def test_the_gait_keeps_its_timing_in_seconds_at_another_frame_rate(rigged, tmp_path):
    """Review 2026-10-30: the exam renders its gait at the rate clips are delivered at (Wan: 16 fps); frame 16 at
    16 fps is the pose of frame 24 at 24 fps (one second in)."""
    blend, config = rigged
    for name, fps, frames in (("at24", 24, 48), ("at16", 16, 32)):
        process, report = synth(tmp_path, blend, config, name, kind="gait", frames=frames, fps=fps)
        assert report["status"] == "complete", process.stdout[-2000:] + process.stderr[-2000:]
    assert json.loads((tmp_path / "at16.json").read_text())["fps"] == 16
    at24, at16 = np.load(tmp_path / "at24.npz")["quats"], np.load(tmp_path / "at16.npz")["quats"]
    assert len(at16) == 32 and np.allclose(at16[16], at24[24], atol=1e-5) and np.allclose(at16[30], at24[45], atol=1e-5)


def test_the_gait_swings_one_bone_a_leg_and_curls_no_end_bone(rigged, tmp_path):
    """2026-10-30, B3's exam on the B1 wolf: the gait swung both Scapula and UpperArm (B1's front legs have a scapula;
    the spike's rig had none) and flexed HindToesEnd with HindToes (B1 fits skin-leading end bones; the spike moved
    none), so a front leg kicked level and the toes flicked out of the frame."""
    blend, config = rigged
    config = {**config, "fit_bones": [*config["fit_bones"], "HeadEnd"]}      # an end bone fitted, as B1 fits the wolf's
    process, report = synth(tmp_path, blend, config, "gait", kind="gait", frames=48)
    assert report["status"] == "complete", process.stdout[-2000:] + process.stderr[-2000:]
    turns = json.loads((tmp_path / "gait.json").read_text())["max_turn_degrees"]
    assert turns["UpperArm.L"][0] > 10 and turns["Thigh.L"][0] > 10            # the leg swings, from the shoulder
    assert turns["Scapula.L"] == [0.0, 0.0, 0.0] and turns["Scapula.R"] == [0.0, 0.0, 0.0]
    ends = [name for name in turns if name.endswith(("ToesEnd.L", "ToesEnd.R", "HeadEnd"))]
    assert ends and all(turns[name] == [0.0, 0.0, 0.0] for name in ends), {name: turns[name] for name in ends}


def test_a_motion_past_a_declared_range_is_refused(rigged, tmp_path):
    blend, config = rigged
    tight = {**config, "joints": {**config["joints"], "Tail1": {"range": np.radians(5)}}}
    # the random motion keeps inside 0.9 of a range; the gait sways the tail 12 degrees whatever its range
    process, report = synth(tmp_path, blend, tight, "gait", kind="gait", frames=48)
    assert report["status"] == "error" and "Tail1" in report["errors"][0], process.stdout[-2000:]
    assert not (tmp_path / "gait.npz").exists()


def test_blender_euler_zyx_is_videorigs_intrinsic_xyz():
    """synth_motion composes X @ Y @ Z and reads the channels back with to_euler('ZYX'); video2rig bounds them as
    scipy's as_euler('XYZ'). The angles must round-trip, past 90 degrees too."""
    expr = ("import math\nfrom mathutils import Quaternion\nfor a, b, c in ((0.3, -0.5, 1.1), (2.4, 0.2, -0.4)):\n"
            "    q = Quaternion((1, 0, 0), a) @ Quaternion((0, 1, 0), b) @ Quaternion((0, 0, 1), c)\n"
            "    print('EULER', *[round(v, 6) for v in q.to_euler('ZYX')], a, b, c, *[round(v, 6) for v in q])\n")
    out = subprocess.run([BLENDER, "--background", "--factory-startup", "--python-expr", expr], capture_output=True,
                         text=True).stdout
    rows = [list(map(float, line.split()[1:])) for line in out.splitlines() if line.startswith("EULER")]
    from scipy.spatial.transform import Rotation
    for x, y, z, a, b, c, w, qx, qy, qz in rows:
        assert (x, y, z) == pytest.approx((a, b, c), abs=1e-5)
        x_, y_, z_, w_ = Rotation.from_euler("XYZ", [a, b, c]).as_quat()      # scipy: x y z w
        sign = 1 if w * w_ >= 0 else -1
        assert (w, qx, qy, qz) == pytest.approx((sign * w_, sign * x_, sign * y_, sign * z_), abs=1e-5)
    assert len(rows) == 2


V2R = Path(os.environ.get("SLOPFORGE_VIDEO2RIG_CHECKOUT", Path.home() / "SlopForgeVideo2rig/video2rig"))


@pytest.mark.skipif(not (V2R / "blender/render_start.py").is_file(), reason="video2rig's checkout is not installed")
def test_the_start_cameras_project_as_blender_renders_them(rigged, tmp_path):
    """Plan B2: the wrapped render's cameras.json projects as the camera maths says, to under half a pixel, and the
    skin's projected box is the silhouette render_start drew."""
    from slopforge.backends import video2rig
    from slopforge.creature_views import framing, project
    blend, config = rigged
    settings = {"asset_pipeline": {"tools": {"blender": BLENDER}, "providers": {"video2rig": {
        "python": shutil.which("python3"), "checkout": str(V2R)}}}}
    chosen = {**framing({"views": ["three-quarter", "side"]}, length=1.65, width=0.3), "facing": config["facing"]}
    argv = video2rig.command(settings, tmp_path, "render_start", tmp_path / "v2r", blend=blend, framing=chosen)
    assert subprocess.run(argv + ["--samples", "4"], capture_output=True, text=True).returncode == 0
    cameras = json.loads((tmp_path / "v2r/start/cameras.json").read_text())
    rig = creature(extra=0)
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import bpy, json, sys\nfrom mathutils import Matrix, Vector\nfrom bpy_extras.object_utils import "
        "world_to_camera_view\ncams, points = json.load(open(sys.argv[-2])), json.load(open(sys.argv[-1]))\n"
        "scene = bpy.context.scene\nout = {}\nfor v in cams['views']:\n"
        "    data = bpy.data.cameras.new(v['name']); data.type = 'ORTHO'\n"
        "    data.ortho_scale = max(v['ortho_width'], v['ortho_height'])\n"
        "    cam = bpy.data.objects.new(v['name'], data); scene.collection.objects.link(cam)\n"
        "    r, u, f = Vector(v['right']), Vector(v['up']), Vector(v['forward'])\n"
        "    cam.matrix_world = Matrix.Translation(Vector(v['location'])) @ "
        "Matrix((r, u, -f)).transposed().to_4x4()\n"
        "    scene.render.resolution_x, scene.render.resolution_y = v['width_px'], v['height_px']\n"
        "    bpy.context.view_layer.update()\n"
        "    out[v['name']] = [[c.x * v['width_px'], (1 - c.y) * v['height_px']] for c in "
        "(world_to_camera_view(scene, cam, Vector(p)) for p in points)]\n"
        "print('PROJECTED', json.dumps(out))\n")
    (tmp_path / "cams.json").write_text(json.dumps(cameras))
    (tmp_path / "points.json").write_text(json.dumps(rig["heads"].tolist()))
    out = subprocess.run([BLENDER, "--background", "--factory-startup", "--python", str(probe), "--",
                          str(tmp_path / "cams.json"), str(tmp_path / "points.json")], capture_output=True, text=True)
    blender_px = json.loads(next(line for line in out.stdout.splitlines() if line.startswith("PROJECTED"))[10:])
    from PIL import Image
    start = np.asarray(Image.open(tmp_path / "v2r/start/start.png").convert("RGB"), float)
    for view in cameras["views"]:
        ours = project(view, rig["heads"])
        assert np.abs(ours - np.array(blender_px[view["name"]])).max() < 0.5, view["name"]
        # the skin's projected box is the silhouette render_start drew: the fixture's tan against its grey studio
        panel = start[:, view["x0_px"]:view["x0_px"] + view["width_px"]]
        drawn = np.argwhere(panel.max(2) - panel.min(2) > 30)
        skin = project(view, rig["vertices"])
        assert np.abs([drawn[:, 1].min() - skin[:, 0].min(), drawn[:, 1].max() - skin[:, 0].max(),
                       drawn[:, 0].min() - skin[:, 1].min(), drawn[:, 0].max() - skin[:, 1].max()]).max() < 2.5
