"""B5 intake for generated two-view creature clips (AI motion sources plan, package B5; docs/CREATURES.md): measured
before anything reads the clip, fail-closed. Pure Python and NumPy, except `read_clip` (ffprobe and ffmpeg).

- measure: every intake number of a clip against its start image and start cameras (per panel and overall).
- judge: the numbers against the creature type's declared limits, in B0's validation shape (artifact_kind video;
  failures._KIND_CODES), so a refused clip is a retryable candidate_quality failure.
- timing: the clip's frame times for video2rig, at the measured rate (video2rig otherwise assumes Seedance's cadences
  and reads Wan's 16 fps as 24, so the motion plays 1.5x fast; #149).

The limits were set from #149's 40 Wan clips, whose verdicts are known: docs/CREATURES.md ("Video intake").
"""
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

INSET = 4            # pixels kept off each panel edge (render_start's divider)
BORDER = 12          # the backdrop sampled from the panel's top and side strips (the floor and its shadow are below)
SILHOUETTE = 24      # a pixel this far (max channel) from the frame's backdrop belongs to the creature
MOVED = 25           # a pixel this far from frame 0 has moved
DUPLICATE = 0.1      # a step under this share of the clip's large steps repeats the frame before it

CHECKS = (  # (code, metric, limit, what failed) in the order a reviewer reads them
    ("video_frame_rate", "video_duplicate_share", "max_video_duplicate_share",
     "the clip repeats frames: {:.0%} duplicated (the container's rate is not the motion's)"),
    ("video_frame0", "video_frame0_difference", "max_video_frame0_difference",
     "frame 0 is not the start image (mean difference {:.1f} grey levels)"),
    ("video_creature_missing", "video_presence", "min_video_presence",
     "a panel loses the creature: it shows in frame 0 and {:.0%} of the frames at most"),
    ("video_backdrop_drift", "video_backdrop_drift", "max_video_backdrop_drift",
     "the backdrop's brightness moves up to {:.1f} grey levels from frame 0's"),
    ("video_still", "video_motion_share", "min_video_motion_share",
     "a panel stands still: {:.2%} of its pixels move"),
    ("video_turned", "video_turn", "max_video_turn",
     "the creature turns in a panel: its outline's shape changes by {:.2f} (log of the width-to-height ratio)"),
)


def read_clip(path):
    """(frames as uint8 [n, height, width, 3], the container's frame rate)."""
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout)["streams"][0]
    numerator, denominator = (float(v) for v in probe["r_frame_rate"].split("/"))
    if not numerator or not denominator:
        raise ValueError(f"{Path(path).name} states no frame rate ({probe['r_frame_rate']})")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, probe["height"], probe["width"], 3), numerator / denominator


def _panels(cameras, width):
    scale = width / cameras["frame_px"][0]
    return [(view["name"], int(round(view["x0_px"] * scale)) + INSET,
             int(round((view["x0_px"] + view["width_px"]) * scale)) - INSET) for view in cameras["views"]]


def _duplicate_share(frames):
    """Share of steps that repeat the frame before (a 24 fps clip in a 60 fps container repeats 3 of 5); a still clip
    has no large steps to compare with and repeats nothing on purpose."""
    steps = np.array([np.abs(frames[k].astype(np.int16) - frames[k - 1]).mean() for k in range(1, len(frames))])
    large = np.percentile(steps, 90)
    return float((steps < DUPLICATE * large).mean()) if large > 0.5 else 0.0


def _panel(frames, x0, x1):
    panel = frames[:, :, x0:x1].astype(np.float32)
    n = len(panel)
    strips = np.concatenate([panel[:, :BORDER].reshape(n, -1, 3), panel[:, :, :BORDER].reshape(n, -1, 3),
                             panel[:, :, -BORDER:].reshape(n, -1, 3)], 1)
    backdrop = np.median(strips, 1)                                          # per frame, so drift moves with it
    level = backdrop.mean(1)
    drift = float(np.abs(level - level[0]).max())          # a step after frame 0 and a steady darkening alike
    mask = np.abs(panel - backdrop[:, None, None, :]).max(3) > SILHOUETTE
    moved = (np.abs(panel - panel[0]).max(3) > MOVED).mean((1, 2))
    aspect, colour = np.full(n, np.nan), np.full((n, 3), np.nan)
    for t in range(n):
        ys, xs = np.nonzero(mask[t])
        if len(xs) >= 50:
            (x_lo, x_hi), (y_lo, y_hi) = np.percentile(xs, [1, 99]), np.percentile(ys, [1, 99])
            aspect[t] = (x_hi - x_lo + 1) / (y_hi - y_lo + 1)
            colour[t] = panel[t][mask[t]].mean(0)
    # frame 0 is every other measure's reference: a panel without the creature there has none to give
    seen = ~np.isnan(aspect)
    presence = float(seen.mean()) if seen[0] else 0.0
    turn = np.abs(np.log(aspect / aspect[0])) if seen[0] else np.zeros(n)
    shift = np.linalg.norm(colour - colour[0], axis=1) if seen[0] else np.zeros(n)
    later = seen & (np.arange(n) > 0)
    return {"backdrop_drift": round(drift, 2), "motion_share": round(float(np.median(moved[1:])), 4),
            "presence": round(presence, 4),
            "turn": round(float(np.percentile(turn[later], 90)), 3) if later.any() else 0.0,
            "identity_drift": round(float(np.percentile(shift[later], 90)), 2) if later.any() else 0.0}


def measure(frames, container_fps, start, cameras):
    """Every intake number of a clip: `start` is the start image (any size; compared at the clip's), `cameras` the
    start cameras.json (panels found by their x0 and width, scaled to the clip)."""
    frames = np.asarray(frames)
    n, height, width = frames.shape[:3]
    if n < 2:
        raise ValueError(f"a clip needs at least two frames, got {n}")
    start = np.asarray(Image.fromarray(np.asarray(start, np.uint8)).convert("RGB").resize((width, height),
                                                                                        Image.BILINEAR), np.float32)
    duplicate = _duplicate_share(frames)
    panels = {name: _panel(frames, x0, x1) for name, x0, x1 in _panels(cameras, width)}
    return {"video_frames": int(n), "video_container_fps": float(container_fps),
            "video_duplicate_share": round(duplicate, 4),
            "video_content_fps": round(float(container_fps) * (1 - duplicate), 3),
            "video_frame0_difference": round(float(np.abs(frames[0].astype(np.float32) - start).mean()), 2),
            "video_presence": min(p["presence"] for p in panels.values()),
            "video_backdrop_drift": max(p["backdrop_drift"] for p in panels.values()),
            "video_motion_share": min(p["motion_share"] for p in panels.values()),
            "video_turn": max(p["turn"] for p in panels.values()),
            "video_identity_drift": max(p["identity_drift"] for p in panels.values()),
            "panels": panels}


def judge(measured, limits):
    """B0's validation shape: every check past its declared limit is an error with its code, in CHECKS' order."""
    missing = [limit for _, _, limit, _ in CHECKS if limit not in limits]
    if missing:
        raise ValueError(f"video intake limits not declared: {', '.join(missing)}")
    errors, codes = [], []
    for code, metric, limit, words in CHECKS:
        value, bound = measured[metric], limits[limit]
        if (value < bound) if limit.startswith("min_") else (value > bound):
            errors.append(words.format(value))
            codes.append(code)
    return {"status": "failed" if errors else "passed", "errors": errors, "failure_codes": codes,
            "artifact_kind": "video", "measured": measured,
            "limits": {limit: limits[limit] for _, _, limit, _ in CHECKS}}


def timing(frames, fps, *, container_fps):
    """video2rig's work/<clip>/timing.json for a clip of `frames` frames at `fps`."""
    return {"content": f"{fps:g}fps, measured by SlopForge's intake (container {container_fps:g} fps)",
            "source": "slopforge.video_intake", "times": [round(k / fps, 6) for k in range(frames)]}


def write_timing(work, frames, fps, *, container_fps):
    path = Path(work) / "timing.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(timing(frames, fps, container_fps=container_fps)))
    return path
