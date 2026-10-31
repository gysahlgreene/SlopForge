"""B5's video settings for a creature type and the prompt for one motion (docs/CREATURES.md, "Video generation"):
data in the type, not code, and the walk template is #149's continuous-walk prompt (variant e)."""
import copy
from pathlib import Path

import pytest
import yaml

from slopforge.creature_video import video_prompt, video_settings

ROOT = Path(__file__).resolve().parents[1]
TYPE = yaml.safe_load((ROOT / "templates/asset_types/creature.yaml").read_text())

# #149's variant e, the wording that gave full cycles at 121 frames (private record; quoted here as the regression)
E_PROMPT = (
    "Split-screen video from two synchronised fixed cameras filming the same grey wolf with grey, cream and tan fur at "
    "the same moment, in a plain grey studio with a level floor and soft constant lighting. Left half: a fixed camera "
    "straight in front of the wolf; the wolf keeps facing this camera the whole time, its nose pointing straight at "
    "it. Right half: a fixed camera at the wolf's left side; the wolf keeps its left side to this camera the whole "
    "time, its head to the left of the picture. The wolf walks continuously on the spot for the whole clip, from the "
    "first frame to the last, at a calm, steady walking pace, and never stops: all four legs step in turn, left hind, "
    "left fore, right hind, right fore, again and again, each foot lifting clear of the floor and being set down "
    "again, its body staying in the same place and pointing the same way; it never turns, never rotates and never "
    "changes direction. Its head stays forward and its tail hangs relaxed. It has exactly four legs. Both halves show "
    "the same wolf at the same moment, moving together. Static cameras, no zoom, no cuts, no camera shake, no slow "
    "motion, no motion blur. Keep the whole body inside the frame the whole time; nothing crosses the dark line "
    "between the two halves. No visual effects of any kind: no dust, no smoke, no debris, no sparks, no particles, "
    "no speed lines, no motion trails, no light trails, no motion blur, no camera shake. Every limb stays sharp, the "
    "flat floor stays perfectly clean, and every foot stays clearly visible in every frame.")


def test_the_walk_template_is_149s_continuous_walk_prompt():
    settings = video_settings(TYPE, "walk")
    prompt, negative = video_prompt(settings, description="Grey wolf with grey, cream and tan fur", name="wolf",
                                    views=["front", "side"], side="left")
    assert prompt == E_PROMPT
    for word in ("turning", "rotating", "standing still", "pausing", "stopping", "dust", "motion blur", "second wolf"):
        assert word in negative


def test_walk_defaults_are_121_frames_the_wan_graph_and_every_intake_limit():
    settings = video_settings(TYPE, "walk")
    assert settings["frames"] == 121 and settings["workflow"] == "workflows/video_wan22_i2v_api.json"
    assert settings["retries"] >= 1
    assert set(settings["limits"]) == {"max_video_duplicate_share", "max_video_frame0_difference", "min_video_presence",
                                       "max_video_backdrop_drift", "min_video_motion_share", "max_video_turn",
                                       "max_video_view_disagreement", "max_video_limb_disagreement"}


def test_the_prompt_names_the_projects_own_view_pair():
    prompt, _ = video_prompt(video_settings(TYPE, "walk"), description="red fox", name="red fox",
                             views=["three-quarter", "side"], side="right")
    # render_start's three-quarter camera is always at the creature's front left, whichever side the side camera takes
    assert "Left half: a fixed camera in front of the red fox and to its left" in prompt
    assert "at the red fox's right side" in prompt and "{" not in prompt


def test_the_types_start_frame_is_front_and_side_with_a_narrow_front_panel():
    """2026-10-30: the owner judged front + side with the wolf drawn larger "significantly better" (three-quarter +
    side crossed its legs). The front view needs little width, so the side panel takes two thirds."""
    assert TYPE["views"] == ["front", "side"] and TYPE["widths"] == [640, 1280]


@pytest.mark.parametrize("change, message", [
    (lambda t: t["video_motions"].pop("walk"), "no video motion 'walk'"),
    (lambda t: t["video_motions"]["walk"].update(frames=120), "frames"),
    (lambda t: t["video_motions"]["walk"].update(retries=-1), "retries"),
    (lambda t: t["video_motions"]["walk"].update(prompt="no panels"), "{left}"),
    (lambda t: t["video_intake"].pop("max_video_turn"), "max_video_turn"),
    (lambda t: t["video_intake"].update(min_video_motion_share=True), "min_video_motion_share"),
    (lambda t: t.pop("video_workflow"), "video_workflow"),
    (lambda t: t["video_motions"]["walk"].update(fit_joint_limits={"FrontPaw": 0}), "fit_joint_limits"),
    (lambda t: t["video_motions"]["walk"].update(fit_joint_limits={"FrontPaw": 170}), "fit_joint_limits"),
    (lambda t: t["video_motions"]["walk"].update(fit_joint_limits={"Wing": 30}), "fit_joint_limits"),
])
def test_bad_or_missing_declarations_are_refused(change, message):
    asset_type = copy.deepcopy(TYPE)
    change(asset_type)
    with pytest.raises(ValueError, match=message):
        video_settings(asset_type, "walk")


def test_a_view_without_wording_is_refused():
    with pytest.raises(ValueError, match="top"):
        video_prompt(video_settings(TYPE, "walk"), description="wolf", name="wolf", views=["top", "side"], side="left")


def test_the_types_framing_draws_the_wolf_larger_than_149s():
    """B5's live gate: at margin_wide 1.45 the side panel's length set the scale (the wolf 344 px tall) and four clips
    failed video2rig's check; at #149's scale (margin 1.8) the same seeds passed. 2026-10-30: at margin 1.4, the wolf
    about 1.3x larger again, the owner judged its walk "significantly better". render_start sets the orthographic
    height to the larger of height x margin and length x margin_wide x 1080 / panel width: the height still sets it."""
    height, length = 0.780, 1.000                       # the B1 wolf's skin
    panel = TYPE["widths"][TYPE["views"].index("side")]
    ortho = max(height * TYPE["margin"], length * TYPE["margin_wide"] * 1080 / panel)
    assert ortho == pytest.approx(height * TYPE["margin"])
    assert height * 1.8 / ortho == pytest.approx(1.29, abs=0.01)          # larger than #149's framing
    assert TYPE["margin_wide"] >= 1.2                  # a longer creature still keeps a fifth of room in its side panel


def test_the_walk_is_fitted_within_walk_sized_paw_ranges():
    """2026-10-30: the reader trains on the type's wide joint limits (a fox folds its front paws 148 deg), but a walk
    fitted within them let noisy toe readings snap a front paw up to 118 deg in one frame; fitted within 90 / 60 deg,
    at most 78 (the owner's choice, fit D). The ranges are the walk's alone, each within the type's own."""
    settings = video_settings(TYPE, "walk")
    assert settings["fit_joint_limits"] == {"FrontPaw": 90, "FrontToes": 60}
    assert all(value <= TYPE["joint_limits"][role] for role, value in settings["fit_joint_limits"].items())
