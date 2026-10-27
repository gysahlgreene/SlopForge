"""B2 for creatures: the video2rig settings of a rigged creature, and the checks on its views and known motions
(AI motion sources plan, package B2; docs/CREATURES.md). Pure Python and NumPy: no Blender, no video2rig.

- creature_config: creature.json from the rig record (B1's generic names, fit_bones, facing) and the creature type's
  declared joint limits (#139, #140): every fitted bone but the root and the knees and elbows (one-way hinges) gets
  `joints.<bone>.range` from its role's declared limit, never from a prior keyed to its name.
- framing: render_start's view pair and framing (#142), the panel widths split by each view's span.
- outside_panels: points of a pose or motion that leave a panel of the start cameras.
- range_violations: frames of a known motion past a joint's declared range (exam v1: the truth stays inside them).
"""
import math
import re

import numpy as np

VIEWS = ("front", "side", "three-quarter", "top")
FRAME_WIDTH = 1920
HINGES = {"Shin": "back", "Forearm": "front"}   # knees fold back, elbows forward: video2rig's hinges dict


def _role(bone):
    """Spine2 -> Spine, Tail3 -> Tail, FrontPaw.L -> FrontPaw, HeadEnd1 -> HeadEnd."""
    return re.sub(r"\d+$", "", re.sub(r"\.[LR]$", "", bone))


def creature_config(name, rigging, limits):
    """creature.json for video2rig. `limits` are the type's joint limits in degrees by role; an end bone without its
    own takes its chain's (HindToesEnd -> HindToes). Raises ValueError for a fitted bone with no declared limit."""
    fit = list(rigging["fit_bones"])
    hinges = {bone: HINGES[_role(bone)] for bone in fit if _role(bone) in HINGES}
    joints = {}
    for bone in fit:
        if bone == "Hips" or bone in hinges:   # the root carries the body; a hinge's own declaration bounds it
            continue
        role = _role(bone)
        limit = limits.get(role, limits.get(role[:-3]) if role.endswith("End") else None)
        if limit is None:
            raise ValueError(f"no declared joint limit for {role} (bone {bone}): add it to the type's joint_limits")
        joints[bone] = {"range": math.radians(limit)}
    return {"name": name, "root_bone": "Hips", "facing": rigging["facing"], "fit_bones": fit, "hinges": hinges,
            "joints": joints}


def framing(settings, length, width):
    """render_start's views and framing. Without declared widths, the 1920 px frame is split by each view's span
    across its panel (render_start: front its width, side its length, three-quarter .77 length + .64 width, top its
    width), since one scale serves both panels and the widest span per pixel sets it."""
    views = list(settings.get("views") or ("three-quarter", "side"))
    if len(views) != 2 or len(set(views)) != 2 or not set(views) <= set(VIEWS):
        raise ValueError(f"views must be two different of {', '.join(VIEWS)}, got {views!r}")
    margin, margin_wide = float(settings.get("margin", 1.8)), float(settings.get("margin_wide", 1.45))
    if not 1 <= margin <= 4 or not 0 <= margin_wide <= 4:
        raise ValueError(f"margin must be 1 to 4 and margin_wide 0 to 4, got {margin} and {margin_wide}")
    widths = settings.get("widths")
    if widths is None:
        span = {"front": width, "side": length, "three-quarter": 0.77 * length + 0.64 * width, "top": width}
        first = 2 * round(FRAME_WIDTH * span[views[0]] / (span[views[0]] + span[views[1]]) / 2)
        widths = [first, FRAME_WIDTH - first]
    if (len(widths) != 2 or not all(isinstance(item, int) and item >= 160 for item in widths)
            or sum(widths) != FRAME_WIDTH):
        raise ValueError(f"widths must be two whole pixel widths of at least 160 adding up to {FRAME_WIDTH}, "
                         f"got {widths!r}")
    side = settings.get("side", "left")
    if side not in ("left", "right"):
        raise ValueError(f"side must be left or right, got {side!r}")
    return {"views": views, "widths": list(widths), "margin": margin, "margin_wide": margin_wide, "side": side}


def outside_panels(cameras, points):
    """{view name: points outside its panel} for world points seen through cameras.json's orthographic views."""
    points = np.asarray(points, float).reshape(-1, 3)
    counts = {}
    for view in cameras["views"]:
        offset = points - np.asarray(view["location"], float)
        x = (offset @ np.asarray(view["right"], float) / view["ortho_width"] + 0.5) * view["width_px"]
        y = (0.5 - offset @ np.asarray(view["up"], float) / view["ortho_height"]) * view["height_px"]
        out = int(((x < 0) | (x > view["width_px"]) | (y < 0) | (y > view["height_px"])).sum())
        if out:
            counts[view["name"]] = out
    return counts


def range_violations(angles, joints):
    """{bone: frames past its declared range, the largest turn, the range} for a known motion's per-frame turns from
    the start pose (degrees, by bone); bones without a declared range (the root, hinges) are not checked here."""
    found = {}
    for bone, series in angles.items():
        if bone not in joints:
            continue
        limit = math.degrees(joints[bone]["range"])
        series = np.asarray(series, float)
        over = series > limit + 1e-6
        if over.any():
            found[bone] = {"frames": int(over.sum()), "max_degrees": round(float(series.max()), 3),
                           "range_degrees": round(limit, 3)}
    return found
