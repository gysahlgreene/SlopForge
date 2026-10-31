"""B6's gait measures on an extracted creature motion (docs/CREATURES.md, "Extraction and bake"): plants per leg, the
period, the stride, the in-place travel removal and the loop window. Pure NumPy; the Blender bake samples the rig and
calls these."""
import numpy as np
import pytest

from slopforge.creature_gait import GaitError, gait, in_place, loop_window, steps

FPS = 16.0


PHASE = {"front.L": 0.0, "hind.R": 0.25, "front.R": 0.5, "hind.L": 0.75}


def walk(seconds=7.5, period=1.2, speed=0.4, height=0.8, reach=lambda leg, step: 1.0):
    """A synthetic four-legged walk: each foot's forward offset from the hips (m), swinging forward for 30 % of the
    period and sliding back for the rest, legs a quarter period apart; step k of a leg reaches `reach(leg, k)` of a
    stride. The root travels forward at `speed` with a small sideways sway."""
    times = np.arange(int(seconds * FPS) + 1) / FPS
    stride = speed * period
    feet = {}
    for leg, offset in PHASE.items():
        u = times / period - offset
        step, cycle = np.floor(u), u - np.floor(u)
        r = stride * np.array([reach(leg, int(k)) for k in step])
        feet[leg] = np.where(cycle < 0.3, -stride / 2 + r * cycle / 0.3, -stride / 2 + r * (1 - (cycle - 0.3) / 0.7))
    root = np.stack([0.01 * np.sin(2 * np.pi * times / period), -speed * times, np.full_like(times, 0.5)], 1)
    return times, feet, root, height


def one_step_each(seconds=2.0, height=0.8, stride=0.48):
    """Each leg stands, swings forward once (staggered), and stands again: one plant a leg."""
    times = np.arange(int(seconds * FPS) + 1) / FPS
    feet = {}
    for k, leg in enumerate(("front.L", "hind.R", "front.R", "hind.L")):
        start = 0.3 + 0.3 * k
        feet[leg] = np.clip((times - start) / 0.36, 0, 1) * stride - stride / 2
    return times, feet, height


def halves(leg, step):
    """A third of each leg's steps at 30 % reach, staggered so every period holds a partial step."""
    return 0.3 if step % 3 == list(PHASE).index(leg) % 3 else 1.0


def test_a_step_is_a_forward_swing_of_the_foot_past_a_share_of_the_height():
    """2026-10-31: the B1 wolf's feet lift 2-4 % of its height in Wan's walks, so a lift rule found one front step
    where the foot swung forward six times; a step is the foot swinging forward relative to the hips."""
    forward = np.array([0.0, -0.02, -0.04, 0.02, 0.10, 0.18, 0.16, 0.14, 0.15, 0.16, 0.14, 0.12])   # m, height 1
    assert steps(forward, 1.0) == [(2, 5, 0.22)]       # the 2 cm creep at frames 7-9 is under 5 % of the height


def test_the_period_is_the_median_interval_between_one_legs_plants():
    times, feet, root, height = walk()
    result = gait(feet, times, height)
    assert result["period_s"] == pytest.approx(1.2, abs=1 / FPS)
    assert min(len(plants) for plants in result["plants"].values()) >= 5
    assert result["cycles"] == min(len(plants) for plants in result["plants"].values())
    # only swings the clip's ends cut short are partial
    assert all(start == 0 or end == len(times) - 1 for _, start, end in result["partial"])
    a, b = result["clean"]
    assert times[a] < 0.5 and times[b] > 7.0


def test_partial_steps_are_kept_out_of_the_clean_stretch():
    """2026-10-31, owner on walk_s3: "it looks like it takes two steps with a front leg before the other moves". Its
    front legs made half steps (8-23 cm against about 47) while getting going in the clip's first 2.5 s, and the loop,
    the most whole periods that fit, took them in. A step under PARTIAL of its leg's median is partial, and the loop
    is cut from the longest stretch with none."""
    times, feet, root, height = walk(reach=lambda leg, step: 0.3 if leg == "front.L" and step < 2 else 1.0)
    result = gait(feet, times, height)
    assert all(leg == "front.L" or start == 0 or end == len(times) - 1 for leg, start, end in result["partial"])
    assert any(leg == "front.L" and start > 0 for leg, start, _ in result["partial"])
    a, b = result["clean"]
    assert times[a] >= 1.5 and times[b] > 7.0                # after the last half step (1.2-1.56 s), to the end
    assert int((times[b] - times[a]) // result["period_s"]) >= 4


def test_a_leg_with_one_full_step_is_weak_and_the_others_give_the_period():
    times, feet, root, height = walk()
    feet["hind.L"] = np.where((times > 0.7) & (times < 1.5), feet["hind.L"], 0.0)   # one swing, then stands
    result = gait(feet, times, height)
    assert len(result["plants"]["hind.L"]) == 1 and result["cycles"] == 1
    assert result["period_s"] == pytest.approx(1.2, abs=1 / FPS)
    assert result["weak_legs"] == ["hind.L"]


def test_a_leg_that_never_steps_means_no_full_cycle():
    times, feet, root, height = walk()
    feet["hind.L"] = np.zeros_like(times)
    with pytest.raises(GaitError, match="hind.L never planted") as caught:
        gait(feet, times, height)
    assert caught.value.code == "motion_no_cycle" and caught.value.measured == {"motion_min_plants": 0}


def test_no_leg_stepping_twice_means_no_period():
    times, feet, height = one_step_each()
    with pytest.raises(GaitError, match="no leg planted twice") as caught:
        gait(feet, times, height)
    assert caught.value.code == "motion_no_period" and caught.value.measured == {"motion_max_plants": 1}


def test_partial_steps_throughout_leave_no_clean_period():
    times, feet, root, height = walk(reach=halves)
    with pytest.raises(GaitError, match="no clean walk period") as caught:
        gait(feet, times, height)
    assert caught.value.code == "motion_no_clean_period" and caught.value.measured == {"motion_clean_periods": 0}


def test_every_gait_refusal_states_a_limit_its_measure_breaks():
    """B0: a candidate_quality refusal is retryable only when its codes' measures pass their declared limits."""
    from slopforge.failures import candidate_quality_rejection
    from slopforge.creature_gait import GAIT_LIMITS
    still = walk()
    still[1]["hind.L"] = np.zeros_like(still[0])
    halved = walk(reach=halves)
    for times, feet, height in ((still[0], still[1], still[3]), one_step_each(), (halved[0], halved[1], halved[3])):
        with pytest.raises(GaitError) as caught:
            gait(feet, times, height)
        error = caught.value
        assert candidate_quality_rejection({"status": "failed", "errors": [str(error)], "failure_codes": [error.code],
                                            "artifact_kind": "motion", "measured": error.measured,
                                            "limits": GAIT_LIMITS[error.code]})


def test_in_place_removes_the_travel_and_keeps_the_sway():
    times, feet, root, height = walk(speed=0.4)
    still, velocity = in_place(root, times)
    assert velocity == pytest.approx([0.0, -0.4], abs=0.01)
    assert np.abs(still[:, 1] - still[0, 1]).max() < 0.01                 # no forward travel left
    assert np.ptp(still[:, 0]) == pytest.approx(0.02, abs=0.004)          # the sideways sway stays
    assert np.array_equal(still[:, 2], root[:, 2])                        # height untouched


def test_in_place_also_removes_a_travel_that_speeds_up():
    """#149's g2: video2rig's `steps` travel grows from 20 to 29 mm a frame; a straight line through it leaves the
    root surging 21 cm back and forth."""
    times, feet, root, height = walk(speed=0.3)
    root[:, 1] -= 0.02 * times ** 2
    still, _ = in_place(root, times)
    assert np.ptp(still[:, 1]) < 0.02
    assert np.ptp(still[:, 0]) == pytest.approx(0.02, abs=0.004)


def test_the_stride_is_the_travel_per_period():
    times, feet, root, height = walk(speed=0.4, period=1.2)
    result = gait(feet, times, height, root=root)
    assert result["speed_mps"] == pytest.approx(0.4, abs=0.01)
    assert result["stride_m"] == pytest.approx(0.48, abs=0.02)


def test_the_loop_window_is_whole_periods_starting_where_the_seam_matches_best():
    times = np.arange(121) / FPS                                   # 7.5 s
    rotations = np.zeros((121, 2, 4))
    angle = 0.5 * np.sin(2 * np.pi * times / 1.2) + 0.002 * times  # a cycle with a slow drift
    rotations[:, :, 0], rotations[:, :, 3] = np.cos(angle / 2)[:, None], np.sin(angle / 2)[:, None]
    window = loop_window(rotations, times, 1.2)
    assert window["cycles"] == 6                                   # 6 x 1.2 s fits in 7.5 s, 7 does not
    assert times[window["end"]] - times[window["start"]] == pytest.approx(7.2, abs=1 / FPS)
    assert window["seam_deg"] < 2.0


def test_no_whole_period_fits_is_an_error_not_a_clip_measure():
    """gait() refuses a clip with no period first; a window shorter than one period is a caller's error."""
    times = np.arange(10) / FPS
    with pytest.raises(ValueError, match="under one period") as caught:
        loop_window(np.tile([1.0, 0, 0, 0], (10, 1, 1)), times, 1.2)
    assert not isinstance(caught.value, GaitError)


def test_the_loop_window_starts_and_ends_on_keys_the_export_can_hit():
    """import_motion keys a 16 fps clip at a 24 fps scene's frames 0, 1.5, 3, ...: the FBX bakes whole frames, so a
    window from key 5.5 to 176.5 exported as 6-176, one frame short, with a worse seam than the one measured."""
    times = np.arange(121) / FPS
    rotations = np.zeros((121, 2, 4))
    angle = 0.5 * np.sin(2 * np.pi * times / 1.2)
    rotations[:, :, 0], rotations[:, :, 3] = np.cos(angle / 2)[:, None], np.sin(angle / 2)[:, None]
    whole = (np.arange(121) * 1.5) % 1 == 0                       # every other key is on a whole scene frame
    window = loop_window(rotations, times, 1.2, allowed=whole)
    assert whole[window["start"]] and whole[window["end"]]
