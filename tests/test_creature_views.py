"""B2: a creature's video2rig settings from its rig record and type declarations (no Blender, no video2rig)."""
import math

import numpy as np
import pytest

from slopforge.creature_views import creature_config, framing, outside_panels, range_violations
from tests.test_creature_rig import NAMES

LIMITS = {"Spine": 35, "Chest": 35, "Neck": 45, "Head": 60, "HeadEnd": 60, "Tail": 160, "Scapula": 160,
          "UpperArm": 160, "FrontPaw": 150, "FrontToes": 90, "Thigh": 130, "HindPaw": 100, "HindToes": 90}
RIGGING = {"names": NAMES, "fit_bones": [name for name in NAMES.values() if name != "HeadEnd"], "facing": "-Y"}


def test_creature_json_declares_fit_bones_hinges_and_every_range():
    config = creature_config("wolf", RIGGING, LIMITS)
    assert config["name"] == "wolf" and config["root_bone"] == "Hips" and config["facing"] == "-Y"
    assert config["fit_bones"] == RIGGING["fit_bones"]
    assert config["hinges"] == {"Shin.L": "back", "Shin.R": "back", "Forearm.L": "front", "Forearm.R": "front"}
    # every fitted bone but the root and the hinges gets a range, from its role's declared limit
    assert set(config["joints"]) == set(RIGGING["fit_bones"]) - {"Hips"} - set(config["hinges"])
    assert config["joints"]["FrontPaw.L"] == {"range": pytest.approx(math.radians(150))}
    assert config["joints"]["Spine2"] == {"range": pytest.approx(math.radians(35))}
    assert config["joints"]["Tail1"] == {"range": pytest.approx(math.radians(160))}


def test_a_range_comes_from_the_declaration_not_the_bones_name():
    # video2rig would cap a bone called "...Paw" at its 'paw' prior (100 degrees); the declaration decides here
    assert creature_config("wolf", RIGGING, {**LIMITS, "HindPaw": 120})["joints"]["HindPaw.R"]["range"] == \
        pytest.approx(math.radians(120))


def test_a_fitted_bone_without_a_declared_limit_refuses():
    with pytest.raises(ValueError, match="no declared joint limit for FrontToes"):
        creature_config("wolf", RIGGING, {key: value for key, value in LIMITS.items() if key != "FrontToes"})


def test_an_end_bone_takes_its_own_role_or_its_chains():
    rigging = {**RIGGING, "fit_bones": RIGGING["fit_bones"] + ["HindToesEnd.L", "HeadEnd1"]}
    joints = creature_config("wolf", rigging, LIMITS)["joints"]
    assert joints["HindToesEnd.L"]["range"] == pytest.approx(math.radians(90))     # HindToes's
    assert joints["HeadEnd1"]["range"] == pytest.approx(math.radians(60))          # HeadEnd's


def test_panel_widths_follow_each_views_span():
    # render_start: one scale for both panels, each panel's span (front: width, side: length, three-quarter:
    # .77 length + .64 width) over its pixel width; splitting 1920 px by span gives the finest common scale
    chosen = framing({"views": ["three-quarter", "side"]}, length=1.0, width=0.35)
    assert chosen["views"] == ["three-quarter", "side"] and sum(chosen["widths"]) == 1920
    assert chosen["widths"][0] / chosen["widths"][1] == pytest.approx((0.77 + 0.64 * 0.35) / 1.0, rel=0.01)
    assert framing({"views": ["front", "side"]}, length=1.0, width=0.35)["widths"][0] < 600
    assert chosen["margin_wide"] == 1.45 and chosen["margin"] == 1.8


def test_declared_widths_and_views_are_checked():
    assert framing({"views": ["front", "side"], "widths": [640, 1280]}, 1, 0.3)["widths"] == [640, 1280]
    for bad in ({"views": ["front"]}, {"views": ["front", "front"]}, {"views": ["back", "side"]},
                {"views": ["front", "side"], "widths": [640, 1000]}, {"views": ["front", "side"], "widths": [0, 1920]}):
        with pytest.raises(ValueError):
            framing(bad, 1, 0.3)


CAMERAS = {"frame_px": [1920, 1080], "views": [
    {"name": "v2r_side", "width_px": 960, "height_px": 1080, "type": "ortho", "location": [10, 0, 0.5],
     "right": [0, -1, 0], "up": [0, 0, 1], "forward": [-1, 0, 0], "ortho_width": 1.6, "ortho_height": 1.8, "x0_px": 0},
    {"name": "v2r_front", "width_px": 960, "height_px": 1080, "type": "ortho", "location": [0, -10, 0.5],
     "right": [1, 0, 0], "up": [0, 0, 1], "forward": [0, 1, 0], "ortho_width": 1.6, "ortho_height": 1.8,
     "x0_px": 960}]}


def test_points_leaving_a_panel_are_counted_per_view():
    inside = np.array([[0.0, 0.0, 0.5], [0.3, 0.5, 1.2]])
    assert outside_panels(CAMERAS, inside) == {}
    beyond = np.array([[0.0, 0.79, 0.5], [0.0, 0.9, 0.5], [0.95, 0.0, 0.5]])   # y past the side panel, x past the front
    assert outside_panels(CAMERAS, beyond) == {"v2r_side": 1, "v2r_front": 1}


def test_a_motion_past_a_declared_range_is_refused():
    joints = {"FrontPaw.L": {"range": math.radians(150)}, "Tail1": {"range": math.radians(30)}}
    angles = {"FrontPaw.L": np.array([0, 90, 148]), "Tail1": np.array([0, 20, 31]), "Hips": np.array([0, 50, 90])}
    assert range_violations(angles, joints) == {"Tail1": {"frames": 1, "max_degrees": 31.0, "range_degrees": 30.0}}
    assert range_violations({"Tail1": np.array([0, 29.9])}, joints) == {}
