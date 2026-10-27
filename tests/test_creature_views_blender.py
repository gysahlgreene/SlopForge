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
