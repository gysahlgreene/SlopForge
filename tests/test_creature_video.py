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
    assert "Left half: a fixed camera in front of the red fox and to its right" in prompt
    assert "at the red fox's right side" in prompt and "{" not in prompt


def test_the_types_start_frame_is_149s_view_pair():
    """The views and panels the walks were generated from: front and side, equal panels."""
    assert TYPE["views"] == ["front", "side"] and TYPE["widths"] == [960, 960]


@pytest.mark.parametrize("change, message", [
    (lambda t: t["video_motions"].pop("walk"), "no video motion 'walk'"),
    (lambda t: t["video_motions"]["walk"].update(frames=120), "frames"),
    (lambda t: t["video_motions"]["walk"].update(retries=-1), "retries"),
    (lambda t: t["video_motions"]["walk"].update(prompt="no panels"), "{left}"),
    (lambda t: t["video_intake"].pop("max_video_turn"), "max_video_turn"),
    (lambda t: t["video_intake"].update(min_video_motion_share=True), "min_video_motion_share"),
    (lambda t: t.pop("video_workflow"), "video_workflow"),
])
def test_bad_or_missing_declarations_are_refused(change, message):
    asset_type = copy.deepcopy(TYPE)
    change(asset_type)
    with pytest.raises(ValueError, match=message):
        video_settings(asset_type, "walk")


def test_a_view_without_wording_is_refused():
    with pytest.raises(ValueError, match="top"):
        video_prompt(video_settings(TYPE, "walk"), description="wolf", name="wolf", views=["top", "side"], side="left")
