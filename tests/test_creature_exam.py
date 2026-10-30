"""B3b: the motion exam's metrics (spike #129's exam_compare, without Blender) and exam v1's limits, on a three-bone
fixture: Hips with a left and a right leg hanging from it, facing +Y with Z up, 1 m tall."""
import math

import numpy as np
import pytest

from slopforge import creature_exam

NAMES = ["Hips", "Leg.L", "Leg.R"]
PARENTS = ["", "Hips", "Hips"]


def walk(frames=10):
    """Truth heads and tails per frame: the legs swing forward and back in opposition, 0.3 m apart sideways."""
    heads, tails = np.zeros((frames, 3, 3)), np.zeros((frames, 3, 3))
    for i in range(frames):
        swing = 0.3 * math.sin(2 * math.pi * i / frames)
        heads[i] = [[0, 0, 0.6], [0.15, 0, 0.6], [-0.15, 0, 0.6]]
        tails[i] = [[0, 0.3, 0.6], [0.15, swing, 0.0], [-0.15, -swing, 0.0]]
    return heads, tails


def posed(true_heads, true_tails, fit_heads=None, fit_tails=None, times=None):
    frames = len(true_heads)
    return {"names": NAMES, "parents": PARENTS, "root": "Hips", "fps": 24.0, "height": 1.0, "up": [0, 0, 1],
            "forward": [0, 1, 0], "true_heads": true_heads, "true_tails": true_tails,
            "fit_heads": true_heads if fit_heads is None else fit_heads,
            "fit_tails": true_tails if fit_tails is None else fit_tails,
            "times": np.arange(frames) / 24.0 if times is None else times}


def turned(heads, tails, bone, degrees):
    """The bone turned about the lateral axis at its head, the frame's other bones as they were."""
    tails = tails.copy()
    a = math.radians(degrees)
    turn = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    j = NAMES.index(bone)
    tails[:, j] = heads[:, j] + (tails[:, j] - heads[:, j]) @ turn.T
    return tails


def test_a_turned_bone_reads_its_angle_and_its_tail_its_distance():
    heads, tails = walk()
    exam = creature_exam.compare(posed(heads, tails, fit_tails=turned(heads, tails, "Leg.L", 30)), moved=NAMES)
    errors = exam["bone_rotation_error_degrees"]
    assert errors["Leg.L"]["median"] == pytest.approx(30, abs=0.01)
    assert errors["Hips"]["max"] == 0 and errors["Leg.R"]["max"] == 0
    # the leg's tail is a free end: each frame it moved by the chord of a 30-degree turn of the leg's length
    lengths = np.linalg.norm(tails[:, 1] - heads[:, 1], axis=1)
    assert exam["joint_position_error"]["Leg.L.tail"]["median"] == pytest.approx(
        np.median(2 * lengths * math.sin(math.radians(15))), abs=1e-4)   # recorded to 4 decimals
    assert exam["summary"]["worst_bone"] == "Leg.L"


def test_travel_counts_in_the_joint_error_but_not_in_the_root_relative_one():
    heads, tails = walk()
    moved = np.array([0, 0.5, 0])
    exam = creature_exam.compare(posed(heads, tails, heads + moved, tails + moved), moved=NAMES)
    assert exam["summary"]["joint_position_error"]["median"] == pytest.approx(0.5)
    assert exam["summary"]["joint_position_error_root_relative"]["max"] == pytest.approx(0, abs=1e-9)
    assert exam["root_travel"]["last_frame_heights"]["forward"] == pytest.approx(0.5)


def test_a_near_far_swap_is_counted_where_the_true_legs_stand_apart():
    heads, tails = walk()
    swapped = tails.copy()
    swapped[:, [1, 2], 1] = tails[:, [2, 1], 1]          # each leg wears its twin's forward swing
    exam = creature_exam.compare(posed(heads, tails, fit_tails=swapped), moved=NAMES)
    pair = exam["near_far_swap_rate"]["Leg.L/Leg.R"]
    # frames 0 and 5 have the legs side by side (less than 2 % of the height apart in the side plane): not counted
    assert pair == {"rate": 1.0, "frames_counted": 8}
    assert exam["summary"]["near_far_swap_rate_max"] == 1.0


def test_the_fit_is_matched_to_the_truth_by_its_times():
    heads, tails = walk()
    # the fit read every other frame, and one time past the truth's end
    times = np.array([0, 2, 4, 6, 8, 12]) / 24.0
    exam = creature_exam.compare(posed(heads, tails, heads[[0, 2, 4, 6, 8, 0]], tails[[0, 2, 4, 6, 8, 0]], times),
                                 moved=NAMES)
    assert (exam["frames_true"], exam["frames_fitted"], exam["frames_compared"]) == (10, 6, 5)
    assert exam["summary"]["joint_position_error"]["max"] == 0


def test_detection_is_the_share_of_frames_read_above_the_confidence_limit():
    heads, tails = walk()
    conf = np.ones((10, 2, 3))
    conf[:4, 0, 2] = 0.1                                       # the right foot unread in the front view for 4 frames
    reader = {"conf": conf, "views": ["v2r_front", "v2r_side"],
              "keypoints": [["hips", "Hips", 0.0], ["foot.L.tip", "Leg.L", 1.0], ["foot.R.tip", "Leg.R", 1.0]]}
    exam = creature_exam.compare(posed(heads, tails), moved=NAMES, reader=reader)
    detection = exam["joint_detection_rate"]
    assert detection["per_joint"] == {"hips": 1.0, "foot.L.tip": 1.0, "foot.R.tip": 0.6}
    assert detection["per_joint_per_view"]["foot.R.tip"] == {"v2r_front": 0.6, "v2r_side": 1.0}
    assert exam["summary"]["joint_detection_rate_mean_per_view"] == {"v2r_front": pytest.approx(0.8667, abs=1e-4),
                                                                    "v2r_side": 1.0}


def scored(**changes):
    """An exam and a check at exam v1's limits, with `changes` to the measures."""
    measured = {"bone_median_deg": 5, "worst_body_median_deg": 10, "worst_body_p95_deg": 25, "worst_tail_p95_deg": 40,
                "joint_rel_median": 0.025, "joint_rel_p95": 0.10, "detection_side": 0.85, "detection_other": 0.45,
                "limb_tips_best_view": 0.95, "swap_worst": 0.15, "views_body_pct": 1.5, "views_limbs_pct": 2.0}
    measured.update(changes)
    return creature_exam.judge(measured)


def test_exam_v1_passes_at_its_limits_and_names_every_measure_past_one():
    assert scored()["status"] == "passed" and scored()["failures"] == []
    verdict = scored(worst_body_p95_deg=155.7, detection_side=0.84)
    assert verdict["status"] == "failed" and verdict["failures"] == ["worst_body_p95_deg", "detection_side"]
    assert verdict["limits"]["worst_body_p95_deg"] == ["<=", 25]
    # a measure that cannot be read fails: no limb-end tips read means none was shown to be read
    assert scored(limb_tips_best_view=None)["failures"] == ["limb_tips_best_view"]


def test_the_measures_come_from_the_exam_and_videorigs_check():
    heads, tails = walk()
    conf = np.ones((10, 2, 3))
    reader = {"conf": conf, "views": ["v2r_front", "v2r_side"],
              "keypoints": [["hips", "Hips", 0.0], ["Leg.L.tip", "Leg.L", 1.0], ["Leg.R.tip", "Leg.R", 1.0]]}
    exam = creature_exam.compare(posed(heads, tails, fit_tails=turned(heads, tails, "Leg.L", 12)), moved=NAMES,
                                 reader=reader)
    # the limb ends are each declared leg's last bone: the reader names keypoints after bones (FrontToes.L.tip on
    # the wolf), so the spike's "Hand"/"Foot" in a label found none on a B1-named rig
    measured = creature_exam.measures(exam, {"body": 0.004, "limbs": 0.011}, limb_ends=["Leg.L", "Leg.R"])
    assert measured["worst_body_median_deg"] == pytest.approx(12, abs=0.01)
    assert measured["worst_tail_p95_deg"] == 0.0          # no tail bones
    assert (measured["detection_side"], measured["detection_other"], measured["limb_tips_best_view"]) == (1.0, 1.0, 1.0)
    assert (measured["views_body_pct"], measured["views_limbs_pct"]) == (pytest.approx(0.4), pytest.approx(1.1))


def test_a_fit_with_no_frame_in_the_truth_is_refused_plainly():
    heads, tails = walk()
    with pytest.raises(ValueError, match="no fitted frame"):
        creature_exam.compare(posed(heads, tails, times=np.arange(10) / 24.0 + 10), moved=NAMES)


def test_the_swap_rate_leaves_out_the_shoulder_blades_and_records_them():
    """Owner ruling 2026-10-30: exam v1's swap rate ignores the shoulder blades. On B1's wolf they sit close together
    and barely move, and the fit reads their 3-degree chest sway on the wrong side in about half the frames, while
    every leg pair stays at 0.06 or under; their rate is still measured and recorded."""
    heads, tails = walk()
    exam = creature_exam.compare(posed(heads, tails), moved=NAMES)
    exam["near_far_swap_rate"].update({"Scapula.L/Scapula.R": {"rate": 0.45, "frames_counted": 68},
                                       "UpperArm.L/UpperArm.R": {"rate": 0.0532, "frames_counted": 92}})
    measured = creature_exam.measures(exam, {"body": 0.004, "limbs": 0.011}, limb_ends=["Leg.L", "Leg.R"])
    assert measured["swap_worst"] == 0.0532 and measured["swap_shoulder_blades"] == 0.45
    assert "swap_shoulder_blades" not in creature_exam.EXAM_V1
