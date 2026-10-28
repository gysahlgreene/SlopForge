"""B6's gait measures on an extracted creature motion (docs/CREATURES.md, "Extraction and bake"): plants per leg, the
period, the stride, the in-place travel removal and the loop window. Pure NumPy; the Blender bake samples the rig and
calls these."""
import numpy as np
import pytest

from slopforge.creature_gait import GaitError, gait, in_place, loop_window, swings

FPS = 16.0


def walk(seconds=7.5, period=1.2, speed=0.4, height=0.8, lift=0.06):
    """A synthetic four-legged walk: each foot swings for 30 % of the period (lifting `lift` m), legs a quarter period
    apart; the root travels forward at `speed` with a small sideways sway."""
    times = np.arange(int(seconds * FPS) + 1) / FPS
    phase = {"front.L": 0.0, "hind.R": 0.25, "front.R": 0.5, "hind.L": 0.75}
    feet = {}
    for leg, offset in phase.items():
        cycle = ((times / period) - offset) % 1.0
        feet[leg] = np.where(cycle < 0.3, lift * np.sin(np.pi * cycle / 0.3), 0.0)
    root = np.stack([0.01 * np.sin(2 * np.pi * times / period), -speed * times, np.full_like(times, 0.5)], 1)
    return times, feet, root, height


def test_a_swing_needs_to_pass_the_lift_share_and_come_back_under_the_plant_share():
    lift = np.array([0, 0.02, 0.05, 0.04, 0.02, 0.005, 0, 0.02, 0.005, 0.0])   # shares of the height
    assert [(start, end) for start, end, _ in swings(lift)] == [(2, 5)]         # the 0.02 bump is jitter, not a step


def test_the_period_is_the_median_interval_between_one_legs_plants():
    times, feet, root, height = walk()
    result = gait(feet, times, height)
    assert result["period_s"] == pytest.approx(1.2, abs=1 / FPS)
    assert min(len(plants) for plants in result["plants"].values()) >= 5
    assert result["cycles"] == min(len(plants) for plants in result["plants"].values())


def test_each_foot_is_measured_from_its_own_resting_height():
    """#149's g2 fit: one foot sinks 8 mm under the floor in a few frames, and the hind feet's lowest bone tails rest
    about 1 cm up; a shared floor at the lowest point would leave the hind feet never planted."""
    times, feet, root, height = walk()
    feet["hind.L"] = feet["hind.L"] + 0.011
    feet["front.L"] = np.where((times > 2.0) & (times < 2.4), -0.008, feet["front.L"])
    result = gait(feet, times, height)
    assert min(len(plants) for plants in result["plants"].values()) >= 5


def test_a_leg_that_never_plants_twice_has_no_period():
    times, feet, root, height = walk(seconds=2.0)
    feet["hind.L"] = np.zeros_like(times)
    with pytest.raises(GaitError, match="hind.L") as caught:
        gait(feet, times, height)
    assert caught.value.code == "motion_no_cycle"


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


def test_no_whole_period_fits_is_refused():
    times = np.arange(10) / FPS
    with pytest.raises(GaitError) as caught:
        loop_window(np.tile([1.0, 0, 0, 0], (10, 1, 1)), times, 1.2)
    assert caught.value.code == "motion_no_cycle"
