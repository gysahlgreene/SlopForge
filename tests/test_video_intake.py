"""B5 intake (docs/CREATURES.md): a generated two-view clip is measured before anything reads it, and refused for
duplicated frames, a frame 0 that is not the start image, a drifting backdrop, a panel that stands still or a creature
that turns. Fixture clips are small synthetic two-panel videos: a grey studio, a brown body on four stepping legs."""
import json
import shutil
import subprocess

import numpy as np
import pytest

from slopforge import video_intake as intake
from slopforge.failures import candidate_quality_rejection

W, H = 320, 180                      # the clip; the start frame and cameras are at twice this, as Wan's 1280 of 1920
CAMERAS = {"frame_px": [2 * W, 2 * H], "views": [{"name": "v2r_front", "x0_px": 0, "width_px": W},
                                                 {"name": "v2r_side", "x0_px": W, "width_px": W}]}
LIMITS = {"max_video_duplicate_share": 0.05, "max_video_frame0_difference": 12, "max_video_backdrop_drift": 10,
          "min_video_motion_share": 0.02, "max_video_turn": 0.25}
GREY, BROWN = 150, (120, 85, 50)


def creature(frame, x0, t, *, width, legs=True, colour=BROWN):
    """A body and four legs in the panel starting at x0; walking, the body bobs and the legs lift in turn with t, which
    moves a few per cent of the panel, as #149's walking clips do (4-15 %)."""
    cx, bob = x0 + W // 4, int(round(6 * np.sin(2 * np.pi * t / 8))) if legs else 0
    frame[55 + bob:110 + bob, cx - width // 2:cx + width // 2] = colour
    for k, dx in enumerate(np.linspace(-width // 2, width // 2 - 9, 4).astype(int)):
        lift = int(25 * max(0, np.sin(2 * np.pi * (t / 16 + k / 4)))) if legs else 0
        frame[110 + bob:160 - lift, cx + dx:cx + dx + 9] = colour


def clip(n=81, *, walk=True, turn=False, drift=0, frame0=None, colour_shift=0):
    frames = np.full((n, H, W, 3), GREY, np.uint8)
    for t in range(n):
        frames[t] -= np.uint8(drift if t else 0)
        frames[t, :, W // 2 - 1:W // 2 + 1] = 8                       # render_start's divider
        grow = 1 + 1.5 * t / n if turn else 1                          # the front view's wolf turns side-on
        colour = tuple(max(0, c - colour_shift * t // n) for c in BROWN)
        creature(frames[t], 0, t if walk else 0, width=int(60 * grow), colour=colour, legs=walk)
        creature(frames[t], W // 2, t if walk else 0, width=90, colour=colour, legs=walk)
    start = frames[0].repeat(2, 0).repeat(2, 1) if frame0 is None else frame0
    return frames, start


def test_a_walking_clip_passes_and_records_every_number():
    frames, start = clip()
    measured = intake.measure(frames, 16.0, start, CAMERAS)
    assert measured["video_container_fps"] == 16.0 and measured["video_content_fps"] == 16.0
    assert measured["video_duplicate_share"] == 0 and measured["video_frame0_difference"] < 2
    assert measured["video_backdrop_drift"] < 1 and measured["video_turn"] < 0.1
    assert measured["video_motion_share"] > 0.02
    assert set(measured["panels"]) == {"v2r_front", "v2r_side"} and "video_identity_drift" in measured
    report = intake.judge(measured, LIMITS)
    assert report["status"] == "passed" and report["artifact_kind"] == "video" and not report["errors"]


@pytest.mark.parametrize("make, code", [
    (lambda: clip(walk=False), "video_still"),
    (lambda: clip(turn=True), "video_turned"),
    (lambda: clip(drift=22), "video_backdrop_drift"),
    (lambda: (clip()[0], np.full((2 * H, 2 * W, 3), 40, np.uint8)), "video_frame0"),
])
def test_each_defect_is_refused_with_its_own_retryable_code(make, code):
    frames, start = make()
    report = intake.judge(intake.measure(frames, 16.0, start, CAMERAS), LIMITS)
    assert report["status"] == "failed" and report["failure_codes"] == [code], report
    assert len(report["errors"]) == 1 and candidate_quality_rejection(report)


def test_24_frames_in_a_60_fps_container_are_refused_as_duplicated():
    frames, start = clip(n=48)
    pulldown = np.stack([frames[k] for k in range(48) for _ in range(3 if k % 2 == 0 else 2)])   # 48 -> 120 (24 in 60)
    measured = intake.measure(pulldown, 60.0, start, CAMERAS)
    assert measured["video_duplicate_share"] == pytest.approx(0.6, abs=0.02)
    assert measured["video_content_fps"] == pytest.approx(24, abs=1)
    report = intake.judge(measured, LIMITS)
    assert report["failure_codes"] == ["video_frame_rate"] and candidate_quality_rejection(report)


def test_a_still_clip_is_still_not_duplicated():
    """A clip with no motion repeats no frame on purpose: it is refused as still, not as a frame-rate fault."""
    frames, start = clip(walk=False)
    noisy = np.clip(frames.astype(int) + np.random.default_rng(0).integers(-1, 2, frames.shape), 0, 255).astype(np.uint8)
    measured = intake.measure(noisy, 16.0, start, CAMERAS)
    assert measured["video_duplicate_share"] == 0
    assert intake.judge(measured, LIMITS)["failure_codes"] == ["video_still"]


def test_a_creature_that_changes_its_look_is_recorded_not_refused():
    """The identity swap (#149's variant h): recorded, so a reviewer sees it; frame 0 still matches the start."""
    plain, start = clip()
    swapped, _ = clip(colour_shift=60)
    a, b = (intake.measure(f, 16.0, start, CAMERAS)["video_identity_drift"] for f in (plain, swapped))
    assert b > a + 20
    assert intake.judge(intake.measure(swapped, 16.0, start, CAMERAS), LIMITS)["status"] == "passed"


def test_every_limit_must_be_declared():
    frames, start = clip()
    measured = intake.measure(frames, 16.0, start, CAMERAS)
    for key in LIMITS:
        with pytest.raises(ValueError, match=key):
            intake.judge(measured, {k: v for k, v in LIMITS.items() if k != key})


def test_the_clip_times_are_its_own_rate_for_video2rig():
    """video2rig takes a clip's times from work/<clip>/timing.json when it exists and otherwise assumes Seedance's
    cadences, which read Wan's 16 fps as 24 (#149): the intake writes the measured times."""
    record = intake.timing(81, 16.0, container_fps=16.0)
    assert record["times"][1] == pytest.approx(1 / 16) and record["times"][-1] == pytest.approx(5.0)
    assert len(record["times"]) == 81 and "16" in record["content"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_a_clip_is_read_back_with_its_container_rate(tmp_path):
    frames, _ = clip(n=17)
    path = tmp_path / "walk.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                    "-r", "16", "-i", "-", "-c:v", "libx264", "-crf", "1", "-pix_fmt", "yuv444p", str(path)],
                   input=frames.tobytes(), check=True)
    read, fps = intake.read_clip(path)
    assert fps == 16.0 and read.shape == frames.shape
    assert np.abs(read.astype(int) - frames).mean() < 3
