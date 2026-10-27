"""B1 for creatures: a raw rig checked against the creature's limb declaration (AI motion sources plan, package B1;
docs/CREATURES.md).

Pure NumPy, so the checks run and are tested without Blender; blender/creature_rig.py measures a rig into the arrays
`structure` reads: skin vertices and triangles in metres (z up), per-vertex weights by bone, bone names, parent names
(None for the root) and joint heads. A glTF skin has joints, not bone tails, so a bone is checked by its head.
"""
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
