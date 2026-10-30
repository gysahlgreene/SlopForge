"""B3b's posing in real Blender, on the B1 fixture quadruped: a known motion posed as its own fit reads no error, at
the rig's height and facing. Spike #129's own data reproduces exactly too (private oracle, docs/CREATURES.md)."""
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pytest

from slopforge import creature_exam
from tests.test_creature_bake_blender import walk  # noqa: F401
from tests.test_creature_rig_blender import BLENDER

ROOT = Path(__file__).resolve().parents[1]


def pose(blend, folder, fit):
    request = {"truth": str(folder), "fit": str(fit), "facing": "-Y", "out": str(folder / "posed.npz"),
               "report": str(folder / "pose.json")}
    (folder / "request.json").write_text(json.dumps(request))
    done = subprocess.run([BLENDER, str(blend), "--background", "--factory-startup", "--python",
                           str(ROOT / "blender/exam_pose.py"), "--", str(folder / "request.json")],
                          capture_output=True, text=True)
    assert (folder / "pose.json").is_file(), done.stdout[-2000:] + done.stderr[-2000:]
    return json.loads((folder / "pose.json").read_text()), np.load(folder / "posed.npz")


def test_a_known_motion_posed_as_its_own_fit_reads_no_error(walk, tmp_path):  # noqa: F811
    knees = [chain[1] for chain in walk["chains"].values()]
    frames, names = 12, ["Hips", *knees]
    quats = np.tile([1.0, 0, 0, 0], (frames, len(names), 1))
    for i in range(frames):
        half = math.radians(30) * math.sin(2 * math.pi * i / frames) / 2
        quats[i, 1] = (math.cos(half), math.sin(half), 0, 0)      # one knee bends and straightens
    folder = tmp_path / "exam"
    folder.mkdir()
    np.savez(folder / "poses.npz", bones=np.array(names), root=np.array("Hips"), quats=quats,
             root_location=np.zeros((frames, 3)))
    (folder / "truth.json").write_text(json.dumps({"root": "Hips", "fps": 24, "facing": "-Y", "moved_bones": names}))
    np.savez(tmp_path / "fit.npz", bones=np.array(names), root=np.array("Hips"), quaternions=quats,
             root_location=np.zeros((frames, 3)), times=np.arange(frames) / 24.0)
    # render_poses' labels are the truth's heads: labels naming every bone at the origin first (a large gap), then
    # the heads that posing read, which the truth must match exactly
    from tests.test_creature_rig import NAMES
    np.savez(folder / "labels.npz", names=np.array(list(NAMES.values())), heads=np.zeros((frames, len(NAMES), 3)))
    report, posed = pose(walk["blend"], folder, tmp_path / "fit.npz")
    assert report["status"] == "complete" and report["label_gap"] > 0.1
    np.savez(folder / "labels.npz", names=posed["names"], heads=posed["true_heads"])
    report, posed = pose(walk["blend"], folder, tmp_path / "fit.npz")
    assert report["status"] == "complete" and report["label_gap"] == pytest.approx(0, abs=1e-6)

    record = {key: (posed[key].tolist() if posed[key].dtype.kind in "US" else posed[key]) for key in posed.files}
    record.update(root=str(posed["root"]), fps=float(posed["fps"]), height=float(posed["height"]))
    assert record["height"] == pytest.approx(0.95, abs=0.01)            # the fixture is 0.95 m tall
    assert np.allclose(record["forward"], [0, -1, 0], atol=1e-6) and np.allclose(record["up"], [0, 0, 1], atol=1e-6)
    exam = creature_exam.compare(record, moved=record["moved"])
    assert exam["frames_compared"] == frames and exam["summary"]["bone_rotation_error_degrees"]["max"] == 0
    assert exam["summary"]["joint_position_error"]["max"] == 0
    # the bent knee really moved its bone between frames: the posing reads the motion, not the rest pose
    knee = record["names"].index(knees[0])
    assert np.linalg.norm(posed["true_tails"][3, knee] - posed["true_tails"][0, knee]) > 0.01
