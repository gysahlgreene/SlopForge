"""The motion exam (B3; docs/CREATURES.md, "The motion exam, v1"): a known motion rendered through the creature's
cameras, read back by video2rig, and compared with its truth. Spike #129's exam_compare.py without Blender:
blender/exam_pose.py poses the truth and the fit on the armature, and this measures and judges them.

Every distance is a share of the creature's height. The fit is matched to the truth by its times."""
import math
import re

import numpy as np

# exam v1, owner-ruled 2026-10-27 (D5, D7) from the spike's four clips: synthetic motion only, revisable with evidence
EXAM_V1 = {"bone_median_deg": ("<=", 5), "worst_body_median_deg": ("<=", 10), "worst_body_p95_deg": ("<=", 25),
           "worst_tail_p95_deg": ("<=", 40), "joint_rel_median": ("<=", 0.025), "joint_rel_p95": ("<=", 0.10),
           "detection_side": (">=", 0.85), "detection_other": (">=", 0.45), "limb_tips_best_view": (">=", 0.95),
           "swap_worst": ("<=", 0.15), "views_body_pct": ("<=", 1.5), "views_limbs_pct": ("<=", 2.0)}
# owner ruling 2026-10-30: the swap rate leaves out the shoulder blades (on B1's wolf they sit close together and the
# fit reads the gait's 3-degree chest sway on the wrong side in about half the frames, every leg pair at 0.06 or
# under); their rate is measured and recorded, not judged
SWAP_UNJUDGED = re.compile(r"^Scapula")
CONFIDENCE = 0.4   # under it video2rig's fit treats a reading as unsure (reader/fit.py SETTINGS bridge_conf)


def _stats(values):
    values = np.asarray(values, float)
    return {"median": round(float(np.median(values)), 4), "p95": round(float(np.percentile(values, 95)), 4),
            "max": round(float(values.max()), 4)}


def _angle(u, v):
    cosine = np.dot(u, v) / max(np.linalg.norm(u) * np.linalg.norm(v), 1e-12)
    return math.degrees(math.acos(float(np.clip(cosine, -1, 1))))


def _twin(name):
    """(the name with its side blanked, "L" or "R"): Thigh.L or Thigh_L at the end, or Left/Right inside."""
    name = re.sub(r"_\d+$", "", name)
    match = re.search(r"([._])([LR])$", name)
    if match:
        return name[:match.start()] + match.group(1) + "#", match.group(2)
    for side, word in (("L", "Left"), ("R", "Right")):
        if word in name:
            return name.replace(word, "#"), side
    return None, None


def compare(posed, *, moved, reader=None, conf=CONFIDENCE):
    """The exam's numbers for one clip. `posed` is blender/exam_pose.py's record: names, parents, root, fps, height,
    up and forward (armature space), true_heads/true_tails per truth frame, fit_heads/fit_tails per fitted frame and
    the fit's times. `moved`: the bones the truth moves. `reader`: video2rig's reader.npz (conf, views, keypoints)."""
    names, height = list(posed["names"]), float(posed["height"])
    index = {name: k for k, name in enumerate(names)}
    true_heads, true_tails = np.asarray(posed["true_heads"], float), np.asarray(posed["true_tails"], float)
    fit_heads, fit_tails = np.asarray(posed["fit_heads"], float), np.asarray(posed["fit_tails"], float)
    frame_of = np.rint(np.asarray(posed["times"], float) * float(posed["fps"])).astype(int)
    pairs = [(k, int(i)) for k, i in enumerate(frame_of) if 0 <= i < len(true_heads)]
    if not pairs:
        raise ValueError(f"no fitted frame falls in the truth's {len(true_heads)} frames: the fit's times are not the "
                         "known motion's")
    root = index[posed["root"]]
    ends = [name for name in moved if not any(parent == name and child in moved
                                              for child, parent in zip(names, posed["parents"]))]
    joints = [(name, 0) for name in moved] + [(name, 1) for name in ends]
    fit, true = (fit_heads, fit_tails), (true_heads, true_tails)
    position, relative, all_position, all_relative = {}, {}, [], []
    for name, end in joints:
        j, key = index[name], name + (".tail" if end else "")
        raw = [np.linalg.norm(fit[end][k][j] - true[end][i][j]) / height for k, i in pairs]
        # the body's travel taken out (every joint less the root's head, fit and truth alike): video2rig's steps turn
        # a walk on the spot into travel, which an in-place truth does not have
        rel = [np.linalg.norm((fit[end][k][j] - fit_heads[k][root]) - (true[end][i][j] - true_heads[i][root])) / height
               for k, i in pairs]
        position[key], relative[key] = _stats(raw), _stats(rel)
        all_position += raw
        all_relative += rel
    up, forward = np.asarray(posed["up"], float), np.asarray(posed["forward"], float)
    lateral = np.cross(up, forward)
    lateral /= np.linalg.norm(lateral)
    travel = np.array([fit_heads[k][root] - true_heads[i][root] for k, i in pairs]) / height
    root_travel = {"last_frame_heights": {"forward": round(float(travel[-1] @ forward), 3),
                                          "up": round(float(travel[-1] @ up), 3),
                                          "lateral": round(float(travel[-1] @ lateral), 3)},
                   "max_heights": round(float(np.linalg.norm(travel, axis=1).max()), 3)}
    rotation, all_rotation = {}, []
    for name in moved:
        j = index[name]
        angles = [_angle(fit_tails[k][j] - fit_heads[k][j], true_tails[i][j] - true_heads[i][j]) for k, i in pairs]
        rotation[name] = _stats(angles)
        all_rotation += angles
    detect, per_view, views = {}, {}, []
    if reader is not None:
        confidence, views = np.asarray(reader["conf"], float), [str(view) for view in reader["views"]]
        for k, (label, bone, along) in enumerate(reader["keypoints"]):
            if bone in moved and (along == 0.0 or label.endswith(".tip")):
                detect[label] = round(float((confidence[:, :, k] >= conf).all(1).mean()), 4)
                # a joint behind the chest in the front view (the hips, the tail's root) is never read there
                per_view[label] = {view: round(float((confidence[:, v, k] >= conf).mean()), 4)
                                   for v, view in enumerate(views)}
    twins = {}
    for name in moved:
        key, side = _twin(name)
        if key:
            twins.setdefault(key, {})[side] = name
    # a near/far swap puts one leg's pose on its twin: measured in the body's side plane (the hips' own side offset
    # would hide it) and only where the true twins stand more than 2 % of the height apart there
    side_plane = np.eye(3) - np.outer(lateral, lateral)
    swap = {}
    for key, pair in sorted(twins.items()):
        if set(pair) != {"L", "R"}:
            continue
        left, right = index[pair["L"]], index[pair["R"]]
        hits = seen = 0
        for k, i in pairs:
            fl, fr, tl, tr = (side_plane @ x for x in (fit_tails[k][left], fit_tails[k][right], true_tails[i][left],
                                                       true_tails[i][right]))
            if np.linalg.norm(tl - tr) <= 0.02 * height:
                continue
            seen += 1
            hits += np.linalg.norm(fl - tr) + np.linalg.norm(fr - tl) < np.linalg.norm(fl - tl) + np.linalg.norm(fr - tr)
        swap[f"{pair['L']}/{pair['R']}"] = {"rate": round(hits / seen, 4) if seen else None, "frames_counted": seen}
    worst = max(rotation, key=lambda name: rotation[name]["p95"])
    return {
        "frames_true": len(true_heads), "frames_fitted": len(frame_of), "frames_compared": len(pairs),
        "truth_frames_compared": len({i for _, i in pairs}),
        "height_armature_units": round(height, 5),
        "summary": {"joint_position_error": _stats(all_position), "joint_position_error_root_relative": _stats(all_relative),
                    "root_travel": root_travel, "bone_rotation_error_degrees": _stats(all_rotation),
                    "joint_detection_rate_mean": round(float(np.mean(list(detect.values()))), 4) if detect else None,
                    "joint_detection_rate_mean_per_view": {
                        view: round(float(np.mean([rates[view] for rates in per_view.values()])), 4)
                        for view in views} if per_view else None,
                    "near_far_swap_rate_max": max((item["rate"] for item in swap.values() if item["rate"] is not None),
                                                  default=None),
                    "worst_bone": worst, "worst_bone_p95_degrees": rotation[worst]["p95"]},
        "joint_position_error": position, "joint_position_error_root_relative": relative, "root_travel": root_travel,
        "bone_rotation_error_degrees": rotation,
        "joint_detection_rate": {"confidence_limit": conf, "per_joint": detect, "per_joint_per_view": per_view},
        "near_far_swap_rate": swap,
    }


def measures(exam, check, *, limb_ends):
    """Exam v1's twelve measures from one clip's exam and video2rig's check.json (D7's view disagreement), and the
    shoulder blades' swap rate, recorded but not judged (SWAP_UNJUDGED). A tail bone has "Tail" in its name; the limb
    ends are each declared leg's last bone."""
    summary, bones = exam["summary"], exam["bone_rotation_error_degrees"]
    body = {name: value for name, value in bones.items() if "Tail" not in name}
    tail = {name: value for name, value in bones.items() if "Tail" in name}
    views = summary["joint_detection_rate_mean_per_view"] or {}
    side = next((value for view, value in views.items() if view.endswith("side")), None)
    other = next((value for view, value in views.items() if not view.endswith("side")), None)
    per_view = exam["joint_detection_rate"]["per_joint_per_view"]
    tips = [max(per_view[f"{bone}.tip"].values()) for bone in limb_ends if f"{bone}.tip" in per_view]
    rates = {pair: item["rate"] for pair, item in exam["near_far_swap_rate"].items() if item["rate"] is not None}
    judged = [rate for pair, rate in rates.items() if not SWAP_UNJUDGED.match(pair)]
    blades = [rate for pair, rate in rates.items() if SWAP_UNJUDGED.match(pair)]
    return {"bone_median_deg": summary["bone_rotation_error_degrees"]["median"],
            "worst_body_median_deg": max(value["median"] for value in body.values()),
            "worst_body_p95_deg": max(value["p95"] for value in body.values()),
            "worst_tail_p95_deg": max((value["p95"] for value in tail.values()), default=0.0),
            "joint_rel_median": summary["joint_position_error_root_relative"]["median"],
            "joint_rel_p95": summary["joint_position_error_root_relative"]["p95"],
            "detection_side": side, "detection_other": other,
            "limb_tips_best_view": min(tips) if len(tips) == len(limb_ends) else None,
            "swap_worst": max(judged, default=None), "swap_shoulder_blades": max(blades, default=None),
            # a check that read no view disagreement has none to judge: unread, so failed
            "views_body_pct": None if check.get("body") is None else check["body"] * 100,
            "views_limbs_pct": None if check.get("limbs") is None else check["limbs"] * 100}


def judge(measured):
    """Exam v1's verdict: every measure within its limit. A measure that could not be read fails."""
    failures = [name for name, (op, limit) in EXAM_V1.items()
                if measured.get(name) is None or not (measured[name] <= limit if op == "<=" else measured[name] >= limit)]
    return {"status": "failed" if failures else "passed", "measured": dict(measured),
            "limits": {name: list(rule) for name, rule in EXAM_V1.items()}, "failures": failures}
