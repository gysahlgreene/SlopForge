"""B1 for creatures: a raw rig checked against the creature's limb declaration, its generic bone names, the bones
video2rig fits and the deformation review's poses (AI motion sources plan, package B1; docs/CREATURES.md).

Pure NumPy, so the checks run and are tested without Blender; blender/creature_rig.py measures a rig into the arrays
`structure` reads: skin vertices and triangles in metres (z up), per-vertex weights by bone, bone names, parent names
(None for the root) and joint heads. A glTF skin has joints, not bone tails, so a bone is checked by its head.
"""
import re

import numpy as np

FLOOR = 0.04    # video2rig's standing_legs: a foot's skin within 4 % of the height above the floor
INSIDE = 0.5    # a joint whose generalized winding number is above this is inside the skin


def winding_numbers(points, vertices, triangles):
    """Generalized winding number of each point (Jacobson et al. 2013): 1 inside a closed outward skin, 0 outside;
    a triangle soup with overlapping shells is fine."""
    a, b, c = (vertices[triangles[:, k]] for k in range(3))
    out = []
    for point in points:
        x, y, z = a - point, b - point, c - point
        lx, ly, lz = (np.linalg.norm(item, axis=1) for item in (x, y, z))
        det = np.einsum("ij,ij->i", x, np.cross(y, z))
        div = (lx * ly * lz + np.einsum("ij,ij->i", x, y) * lz + np.einsum("ij,ij->i", y, z) * lx
               + np.einsum("ij,ij->i", z, x) * ly)
        out.append(float(np.arctan2(det, div).sum() / (2 * np.pi)))
    return out


def _foot_patches(vertices, floor, height):
    """Connected patches of skin near the floor, largest first: a grid union of the low vertices, cells 3 % of the
    creature's length."""
    cell = 0.03 * max(np.ptp(vertices[:, 0]), np.ptp(vertices[:, 1]))
    cells = {}
    for index in np.flatnonzero(vertices[:, 2] <= floor + FLOOR * height):
        cells.setdefault((int(vertices[index, 0] // cell), int(vertices[index, 1] // cell)), []).append(int(index))
    seen, patches = set(), []
    for start in cells:
        if start in seen:
            continue
        stack, patch = [start], []
        seen.add(start)
        while stack:
            current = stack.pop()
            patch += cells[current]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    near = (current[0] + dx, current[1] + dy)
                    if near in cells and near not in seen:
                        seen.add(near)
                        stack.append(near)
        patches.append(patch)
    return sorted(patches, key=len, reverse=True)


def structure(rig, limbs, limits):
    """The B1 structure report of one raw rig, in B0's validation shape (`artifact_kind: rig`; failures._KIND_CODES):
    one armature and one root; a bone chain of its own, standing on the floor, for every declared ground-contact leg;
    twin legs with the same bone count, off one hub, mirrored within `max_rig_asymmetry` of the height; every joint
    inside the skin; weights normalised with at most four influences; each bone's share of the skin (#139)."""
    vertices = np.asarray(rig["vertices"], float)
    triangles = np.asarray(rig["triangles"], int)
    weights = np.asarray(rig["weights"], float)
    names = list(rig["bones"])
    parent = dict(zip(names, rig["parents"]))
    head = dict(zip(names, np.asarray(rig["heads"], float)))
    kids = {name: [other for other in names if parent[other] == name] for name in names}
    declared = limbs["ground_contact"]
    errors, codes = [], []

    def fail(code, message):
        errors.append(message)
        codes.append(code)

    if rig["armature_count"] != 1:
        fail("rig_structure", f"{rig['armature_count']} armatures, expected one")
    roots = [name for name in names if parent[name] is None]
    if len(roots) != 1:
        fail("rig_structure", f"{len(roots)} root bones, expected one")
    sums, influences = weights.sum(1), (weights > 0).sum(1)
    weighted = sums[sums > 0]
    measured = {"unweighted_vertices": int((sums <= 0).sum()), "max_influences": int(influences.max()),
                "weight_sum_min": float(weighted.min()) if weighted.size else 0.0,
                "weight_sum_max": float(weighted.max()) if weighted.size else 0.0}
    if measured["unweighted_vertices"]:
        fail("rig_weights", f"{measured['unweighted_vertices']} vertices follow no bone")
    if measured["max_influences"] > 4:
        fail("rig_weights", f"a vertex follows {measured['max_influences']} bones; at most four")
    if measured["weight_sum_min"] < 0.99 or measured["weight_sum_max"] > 1.01:
        fail("rig_weights", f"weight sums run {measured['weight_sum_min']:.3f}-{measured['weight_sum_max']:.3f}, "
                            "outside 0.99-1.01")

    floor, height = float(vertices[:, 2].min()), float(np.ptp(vertices[:, 2]))
    patches = _foot_patches(vertices, floor, height)
    # The head end is where the highest skin is; the creature's left is up x forward.
    axis = 0 if np.ptp(vertices[:, 0]) > np.ptp(vertices[:, 1]) else 1
    middle = (vertices[:, axis].max() + vertices[:, axis].min()) / 2
    sign = 1.0 if vertices[vertices[:, 2].argmax(), axis] > middle else -1.0
    forward = np.zeros(3)
    forward[axis] = sign
    left = np.cross((0.0, 0.0, 1.0), forward)

    found, taken = [], set()
    for patch in patches[:declared]:
        lead = names[int(weights[patch].sum(0).argmax())]
        limb = {"patch_vertices": len(patch), "centre": vertices[patch].mean(0).round(4).tolist(), "lead_bone": lead,
                "hub": None, "chain": [], "end": None, "side": None, "problem": None}
        found.append(limb)
        if parent[lead] is None or len(kids[lead]) > 1:
            limb["problem"] = f"its skin follows {lead}, a bone the body branches at"
            continue
        chain = [lead]   # up to the bone the body branches at (the hub), then down the lead's own line
        while parent[chain[0]] is not None and len(kids[parent[chain[0]]]) == 1:
            chain.insert(0, parent[chain[0]])
        limb["hub"] = parent[chain[0]]
        while len(kids[chain[-1]]) == 1:
            chain.append(kids[chain[-1]][0])
        limb["chain"] = chain
        last = [names.index(name) for name in chain[-2:]]
        led = weights[:, last].max(1) > 0.5
        limb["last_two_skin_above_floor"] = float(vertices[led, 2].min() - floor) if led.any() else None
        if limb["hub"] is None:
            limb["problem"] = "its chain reaches the root without branching off the body"
        elif len(chain) < 3:
            limb["problem"] = f"its chain has {len(chain)} bones"
        elif taken & set(chain):
            limb["problem"] = "its chain is another foot's"
        elif limb["last_two_skin_above_floor"] is None or limb["last_two_skin_above_floor"] > FLOOR * height:
            limb["problem"] = "its chain's last two bones do not lead the skin on the floor"
        taken |= set(chain)
    valid = [limb for limb in found if limb["problem"] is None]
    missing = declared - len(valid)
    if missing > limits["max_rig_limbs_missing"]:
        fail("rig_limb_missing", f"{missing} of {declared} declared legs have no chain of their own: "
             + "; ".join(f"the foot at {limb['centre']}: {limb['problem']}" for limb in found if limb["problem"])
             + (f"; {declared - len(found)} feet on the floor not found" if len(found) < declared else ""))

    asymmetry, notes, pairs = 0.0, [], []
    mean = float((vertices @ forward).mean())
    for limb in valid:
        limb["end"] = "front" if np.asarray(limb["centre"]) @ forward > mean else "hind"
    for end in ("front", "hind"):
        pair = [limb for limb in valid if limb["end"] == end]
        if len(pair) != 2:
            if not missing:
                asymmetry = 1.0
                notes.append(f"{len(pair)} {end} legs")
            continue
        twin_left, twin_right = sorted(pair, key=lambda limb: -(np.asarray(limb["centre"]) @ left))
        twin_left["side"], twin_right["side"] = "L", "R"
        plane = head[twin_left["hub"]] @ left
        count = min(len(twin_left["chain"]), len(twin_right["chain"]))
        gap = max(np.linalg.norm(head[a] - (head[b] + 2 * (plane - head[b] @ left) * left))
                  for a, b in zip(twin_left["chain"][:count], twin_right["chain"][:count])) / height
        pairs.append({"end": end, "left": twin_left["chain"], "right": twin_right["chain"],
                      "mirror_gap": float(gap)})
        if len(twin_left["chain"]) != len(twin_right["chain"]):
            asymmetry = 1.0
            notes.append(f"{end} legs have {len(twin_left['chain'])} and {len(twin_right['chain'])} bones")
        elif twin_left["hub"] != twin_right["hub"]:
            asymmetry = 1.0
            notes.append(f"{end} legs leave the body at {twin_left['hub']} and {twin_right['hub']}")
        else:
            asymmetry = max(asymmetry, float(gap))
            if gap > limits["max_rig_asymmetry"]:
                notes.append(f"{end} legs mirror within {gap:.3f} of the height")
    if asymmetry > limits["max_rig_asymmetry"]:
        fail("rig_asymmetric", "; ".join(notes) + f" (limit {limits['max_rig_asymmetry']})")

    winding = winding_numbers([head[name] for name in names], vertices, triangles)
    outside = [name for name, value in zip(names, winding) if value <= INSIDE]
    if len(outside) > limits["max_rig_bones_outside"]:
        fail("rig_bone_outside", f"{len(outside)} joints outside the skin: {', '.join(outside)}")

    measured.update({"rig_limbs_missing": missing, "rig_asymmetry": asymmetry, "rig_bones_outside": len(outside),
                     "armature_count": rig["armature_count"], "bone_count": len(names), "height": height,
                     "foot_patches": [len(patch) for patch in patches]})
    share = weights.sum(0) / weights.sum()
    return {"status": "failed" if errors else "passed", "errors": errors, "failure_codes": codes, "warnings": [],
            "artifact_kind": "rig", "measured": measured, "limits": dict(limits),
            "facing": ("+" if sign > 0 else "-") + "XY"[axis], "limbs": found, "pairs": pairs,
            "joints_outside": outside, "winding": {name: round(value, 3) for name, value in zip(names, winding)},
            "skin_share": {name: float(value) for name, value in zip(names, share)}}


# video2rig's quadruped auto-rig names (autorig/skeleton.py LEG_PLANS): the bone from the body to the limb when a chain
# has one more than the limb's names, then the limb's bones. The tool's name priors read these (spike #129 ruling).
LEG_NAMES = {"hind": (None, ("Thigh", "Shin", "HindPaw", "HindToes")),
             "front": ("Scapula", ("UpperArm", "Forearm", "FrontPaw", "FrontToes"))}
_END = re.compile(r"End\d*(\.[LR])?$")


def bone_names(report, rig):
    """Generic names for a rig whose structure passed, {raw name: name}: video2rig's quadruped names, none of Unity's
    humanoid limb names; a bone past its chain's names is an unfitted ...End. Raises ValueError for a body plan that is
    not a quadruped's: the hind legs off the root (the hips), the front legs off a chest further up one spine, a tail
    at most besides, and one neck."""
    if report["status"] != "passed":
        raise ValueError("only a rig whose structure passed is named")
    names = list(rig["bones"])
    parent = dict(zip(names, rig["parents"]))
    kids = {name: [other for other in names if parent[other] == name] for name in names}
    leads = np.bincount(np.asarray(rig["weights"]).argmax(1), minlength=len(names))
    led = dict(zip(names, leads))
    limbs = report["limbs"]
    legs = {bone for limb in limbs for bone in limb["chain"]}
    hips = next(limb["hub"] for limb in limbs if limb["end"] == "hind")
    chest = next(limb["hub"] for limb in limbs if limb["end"] == "front")
    root = next(name for name in names if parent[name] is None)
    if hips != root:
        raise ValueError(f"the hind legs leave the body at {hips}, not at the root {root} (the head end is read from "
                         f"the highest skin, here {report['facing']}; a tail standing above the head reads the wrong way)")
    spine = [chest]
    while spine[0] != hips:
        if parent[spine[0]] is None:
            raise ValueError(f"the front legs leave the body at {chest}, which is not on a spine from {hips}")
        spine.insert(0, parent[spine[0]])
    if len(spine) < 2:
        raise ValueError(f"the front and hind legs all leave the body at {hips}")

    def line(bone):
        chain = [bone]
        while len(kids[chain[-1]]) == 1:
            chain.append(kids[chain[-1]][0])
        return chain

    rename = {hips: "Hips", chest: "Chest", **{bone: f"Spine{k}" for k, bone in enumerate(spine[1:-1], 1)}}
    tails = [bone for bone in kids[hips] if bone not in legs and bone != spine[1]]
    if len(tails) > 1:
        raise ValueError(f"{len(tails)} chains leave the hips besides the hind legs and the spine")
    rename.update({bone: f"Tail{k}" for k, bone in enumerate(line(tails[0]) if tails else [], 1)})
    necks = [bone for bone in kids[chest] if bone not in legs]
    if len(necks) != 1:
        raise ValueError(f"{len(necks)} chains leave the chest besides the front legs; a quadruped has one neck")
    neck = line(necks[0])
    # a line ending where it branches ends at the skull (its jaw and ears are children); else of the last two, the one
    # leading more skin (spike #129's seed 3: the last but one leads the skull, the last only the jaw), the later on a tie
    head = neck[-1] if kids[neck[-1]] else max(reversed(neck[-2:]), key=lambda bone: led[bone])
    rename.update({bone: f"Neck{k}" for k, bone in enumerate(neck[:neck.index(head)], 1)})
    rename[head] = "Head"
    rename.update({bone: "HeadEnd" + (str(k) if k else "") for k, bone in enumerate(neck[neck.index(head) + 1:])})
    for limb in limbs:
        top, plan = LEG_NAMES[limb["end"]]
        chain, side = list(limb["chain"]), "." + limb["side"]
        if top and len(chain) > len(plan):
            rename[chain.pop(0)] = top + side
        for k, bone in enumerate(chain):
            rename[bone] = (plan[k] if k < len(plan)
                            else plan[-1] + "End" + (str(k - len(plan)) if k > len(plan) else "")) + side
    pending = [root]
    while pending:   # parents before children: what hangs below the head, a leg or the tail is an end
        bone = pending.pop(0)
        pending += kids[bone]
        if bone in rename:
            continue
        base = rename[parent[bone]]
        if base in ("Hips", "Chest") or base.startswith("Spine"):
            raise ValueError(f"{bone} branches off the {base}; a quadruped's body carries only legs, a neck and a tail")
        stem, side = (base[:-2], base[-2:]) if base[-2:] in (".L", ".R") else (base, "")
        stem, k = re.sub(r"End\d*$", "", stem), 0
        while f"{stem}End{k or ''}{side}" in rename.values():
            k += 1
        rename[bone] = f"{stem}End{k or ''}{side}"
    return {name: rename[name] for name in names}


def fit_bones(names, skin_share):
    """The bones video2rig fits (#139), declared rather than left to its auto rule, which drops bones leading under
    0.4 % of the skin (a generated wolf's paws and a shin): every named bone, and every end bone that leads any skin
    (owner ruling, 2026-10-27: a five-bone hind leg's last bone carries the floor skin)."""
    return [name for raw, name in names.items() if not _END.search(name) or skin_share.get(raw, 0) > 0]


# The deformation review's poses (degrees about each bone's local axes: X across the body, pointing to the creature's
# left, so +X turns a bone pointing back upward; Z turns it sideways). The spike's sheet (spike #129), with the tail
# raised rather than tucked under.
_POSES = (("rest", {}),
          ("left fore lifted", {"Scapula.L": (-20, 0, 0), "UpperArm.L": (-35, 0, 0), "Forearm.L": (-70, 0, 0),
                                "FrontPaw.L": (60, 0, 0)}),
          ("right hind lifted", {"Thigh.R": (35, 0, 0), "Shin.R": (60, 0, 0), "HindPaw.R": (-50, 0, 0)}),
          ("head up and turned", {"Neck1": (-20, 0, 0), "Neck2": (-15, 0, 0), "Head": (0, 0, 35)}),
          ("tail up and aside", {"Tail1": (40, 0, 20), "Tail2": (25, 0, 15), "Tail3": (15, 0, 15)}),
          ("spine bent", {f"Spine{k}": (8, 0, 6) for k in range(1, 9)}))


def deformation_poses(available):
    """The review poses for a rig with these bone names, each keeping only the bones it has."""
    return [{"label": label, "rotations": {bone: list(angles) for bone, angles in rotations.items()
                                           if bone in available}}
            for label, rotations in _POSES]


def rig_settings(asset_type):
    """The limb declaration, the B1 limits and the seed count of a creature asset type."""
    limbs = asset_type.get("limbs")
    if limbs != {"ground_contact": 4}:
        raise ValueError(f"asset type {asset_type.get('name')!r}: limbs must be {{ground_contact: 4}}; quadrupeds only "
                         f"(owner decision D12), got {limbs!r}")
    asymmetry = asset_type.get("max_rig_asymmetry")
    if isinstance(asymmetry, bool) or not isinstance(asymmetry, (int, float)) or not 0 <= asymmetry <= 1:
        raise ValueError(f"asset type {asset_type.get('name')!r}: max_rig_asymmetry must be a share of the height "
                         f"from 0 to 1, got {asymmetry!r}")
    seeds = asset_type.get("rig_seeds", 4)
    if isinstance(seeds, bool) or not isinstance(seeds, int) or not 1 <= seeds <= 8:
        raise ValueError(f"asset type {asset_type.get('name')!r}: rig_seeds must be 1 to 8, got {seeds!r}")
    # how the finished skin is weighted: the model's own weights, or bone heat on a voxel proxy (#154)
    weights = asset_type.get("skin_weights") or "skintokens"
    if weights not in ("skintokens", "proxy_heat"):
        raise ValueError(f"asset type {asset_type.get('name')!r}: skin_weights must be skintokens or proxy_heat, "
                         f"got {weights!r}")
    return {"limbs": dict(limbs), "seeds": seeds, "skin_weights": weights,
            "limits": {"max_rig_limbs_missing": 0, "max_rig_asymmetry": asymmetry, "max_rig_bones_outside": 0}}


def check_rig(rig, limbs, limits):
    """structure(), then for a passing rig its generic names and fit_bones; a rig that cannot be named fails."""
    report = structure(rig, limbs, limits)
    if report["status"] == "passed":
        try:
            report["names"] = bone_names(report, rig)
        except ValueError as exc:
            report.update(status="failed", errors=[f"the rig cannot be named: {exc}"], failure_codes=["rig_structure"])
        else:
            report["fit_bones"] = fit_bones(report["names"], report["skin_share"])
    return report
