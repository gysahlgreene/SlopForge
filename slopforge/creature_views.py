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
ROOT_BONE = "Hips"   # B1's generic name for the bone that carries the body
HINGES = {"Shin": "back", "Forearm": "front"}   # knees fold back, elbows forward: video2rig's hinges dict
# video2rig's own limits on a hinge (creature.py bounds): the bend one way from straight up to 2.7 rad, the twist about
# the bone 1.4 rad on an elbow and 0.45 on a knee, the sideways turn 0.2 rad; degrees
HINGE_LIMITS = {"Forearm": (154.7, 80.2, 11.5), "Shin": (154.7, 25.8, 11.5)}


def _role(bone):
    """Spine2 -> Spine, Tail3 -> Tail, FrontPaw.L -> FrontPaw, HeadEnd1 -> HeadEnd."""
    return re.sub(r"\d+$", "", re.sub(r"\.[LR]$", "", bone))


def _limit(limits, bone):
    """A bone's declared limit: its role's; an end bone without one takes its chain's (Tail3End -> Tail), then the
    type's `End` (an end off a hinge, such as a dewclaw off a shin)."""
    role = _role(bone)
    if not role.endswith("End"):
        return limits.get(role)
    chain = re.sub(r"\d+$", "", role[:-3])
    return next((limits[key] for key in (role, chain, "End") if key in limits), None)


def creature_config(name, rigging, limits):
    """creature.json for video2rig. `limits` are the type's joint limits in degrees by role (_limit). Raises
    ValueError for a fitted bone with no declared limit."""
    fit = list(rigging["fit_bones"])
    hinges = {bone: HINGES[_role(bone)] for bone in fit if _role(bone) in HINGES}
    joints = {}
    for bone in fit:
        if bone == ROOT_BONE or bone in hinges:   # the root carries the body; a hinge's own declaration bounds it
            continue
        limit = _limit(limits, bone)
        if limit is None:
            raise ValueError(f"no declared joint limit for {_role(bone)} (bone {bone}): add it, or an End limit for "
                             "end bones, to the type's joint_limits")
        joints[bone] = {"range": math.radians(limit)}
    return {"name": name, "root_bone": ROOT_BONE, "facing": rigging["facing"], "fit_bones": fit, "hinges": hinges,
            "joints": joints}


def framing(settings, length, width):
    """render_start's views and framing. Without declared widths, the 1920 px frame is split by each view's span
    across its panel (render_start: front its width, side its length, three-quarter .77 length + .64 width, top its
    width), since one scale serves both panels and the widest span per pixel sets it."""
    views = list(settings.get("views") or ("three-quarter", "side"))
    if len(views) != 2 or len(set(views)) != 2 or not set(views) <= set(VIEWS):
        raise ValueError(f"views must be two different of {', '.join(VIEWS)}, got {views!r}")
    margin, margin_wide = float(settings.get("margin", 1.4)), float(settings.get("margin_wide", 1.2))
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


def project(view, points):
    """Panel pixels (x right, y down) of world points through one of cameras.json's orthographic views."""
    offset = np.asarray(points, float).reshape(-1, 3) - np.asarray(view["location"], float)
    return np.stack([(offset @ np.asarray(view["right"], float) / view["ortho_width"] + 0.5) * view["width_px"],
                     (0.5 - offset @ np.asarray(view["up"], float) / view["ortho_height"]) * view["height_px"]], -1)


def outside_panels(cameras, points):
    """{view name: points outside its panel} for world points seen through cameras.json's orthographic views."""
    counts = {}
    for view in cameras["views"]:
        x, y = project(view, points).T
        out = int(((x < 0) | (x > view["width_px"]) | (y < 0) | (y > view["height_px"])).sum())
        if out:
            counts[view["name"]] = out
    return counts


def range_violations(channels, joints, hinges):
    """{bone: frames past its limits, the largest channel turn, the limit} for a known motion's per-frame turns from
    the start pose: degrees about the bone's X (bend, across the body), Y (twist) and Z (sideways), intrinsic XYZ, as
    video2rig bounds each channel (p0 +- range). A declared range bounds all three; a hinge has video2rig's own limits
    (HINGE_LIMITS); the root is free."""
    found = {}
    for bone, series in channels.items():
        if bone in joints:
            limit = np.full(3, math.degrees(joints[bone]["range"]))
        elif bone in hinges:
            limit = np.array(HINGE_LIMITS[_role(bone)])
        else:
            continue
        turns = np.abs(np.asarray(series, float).reshape(-1, 3))
        over = (turns > limit + 1e-6).any(1)
        if over.any():
            worst = int(np.argmax((turns / limit).max(1)))
            channel = int(np.argmax(turns[worst] / limit))
            found[bone] = {"frames": int(over.sum()), "max_degrees": round(float(turns[worst, channel]), 3),
                           "range_degrees": round(float(limit[channel]), 3)}
    return found


def motion_settings(asset_type):
    """A creature type's B2 declarations: joint limits by role, the view pair and framing, the training poses."""
    name = asset_type.get("name")
    limits = asset_type.get("joint_limits")
    if (not isinstance(limits, dict) or not limits or not all(
            isinstance(role, str) and isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 < value <= 180 for role, value in limits.items())):
        raise ValueError(f"asset type {name!r}: joint_limits must map bone roles to degrees above 0 and at most 180")
    poses = asset_type.get("training_poses", 3000)
    if isinstance(poses, bool) or not isinstance(poses, int) or not 100 <= poses <= 20000:
        raise ValueError(f"asset type {name!r}: training_poses must be 100 to 20000, got {poses!r}")
    return {"joint_limits": dict(limits), "training_poses": poses,
            **{key: asset_type[key] for key in ("views", "widths", "margin", "margin_wide", "side") if key in asset_type}}
