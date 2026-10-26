"""Label a generated surface's faces as parts: votes from part-level generation and the concept masks, a boundary
that follows the surface's own creases (docs/WEAPONS.md, Hybrid parts).

The surface is TRELLIS.2's, which carries the detail; OmniPart's parts only vote on which part each face belongs
to, and the concept masks vote for the faces the concept's camera sees. A graph cut then puts each boundary where
cutting is cheapest: along a crease of the surface (a slide's groove, a lid's seam), not across a smooth panel.
"""
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import breadth_first_order, maximum_flow

SCALE = 1_000_000  # maximum_flow works on integers: costs are scaled and rounded
MOVING = ("slide", "hinge")  # cut in this order: a slide before a trigger, so a trigger is cut from what is left


def binary_cut(n, cost_in, cost_out, pairs, weights):
    """Minimum-energy in/out labelling of n nodes: cost_in[i] if node i is in, cost_out[i] if out, weights[k] when
    the nodes of pairs[k] disagree. Returns a boolean array, True for in."""
    source, sink = n, n + 1
    rows = np.concatenate([np.full(n, source), np.arange(n), pairs[:, 0], pairs[:, 1]])
    cols = np.concatenate([np.arange(n), np.full(n, sink), pairs[:, 1], pairs[:, 0]])
    # an edge source->i is cut when i ends out (pays cost_out); i->sink is cut when i stays in (pays cost_in)
    caps = np.nan_to_num(np.concatenate([cost_out, cost_in, weights, weights]), nan=0.0, posinf=0.0)
    caps = np.maximum(caps, 0)
    scale = min(SCALE, 1e9 / max(float(caps.max(initial=0)), 1e-12))  # the sum along a path stays inside int32
    caps = np.rint(caps * scale).astype(np.int32)
    keep = caps > 0
    graph = csr_matrix((caps[keep], (rows[keep], cols[keep])), shape=(n + 2, n + 2))
    graph.sum_duplicates()
    flow = maximum_flow(graph, source, sink).flow
    residual = graph - flow
    residual.data = np.where(residual.data > 0, residual.data, 0)
    residual.eliminate_zeros()
    # reverse edges with positive flow also carry residual capacity
    reverse = (flow.T > 0).astype(np.int32) if hasattr(flow, "T") else None
    if reverse is not None:
        residual = residual + reverse
    reached = breadth_first_order(residual, source, directed=True, return_predecessors=False)
    inside = np.zeros(n + 2, bool)
    inside[reached] = True
    return inside[:n]


def crease_weights(lengths, angles, lam, sigma):
    """Cutting across an edge costs its length (relative to the mean) times exp(-(angle/sigma)^2): a crease is
    nearly free to cut along, a smooth surface is not."""
    angles = np.nan_to_num(np.asarray(angles, float), nan=0.0)  # a degenerate face's angle: treat as smooth
    return lam * (lengths / lengths.mean()) * np.exp(-(angles / sigma) ** 2)


def label_faces(distances, names, pairs, lengths, angles, areas, masks=None, lam=2.0, sigma=25.0, tau=0.01,
                mask_weight=25.0, moving=None):
    """Each face's part. distances[i, k]: face i's distance to OmniPart's part names[k] (weapon lengths);
    masks[name][i]: +1 the concept sees face i inside that part's mask, -1 outside, 0 unseen. tau is the distance
    difference that counts as one unit of evidence, at most 20; a mask vote weighs more (`mask_weight`), so where the
    concept sees a face its mask decides and OmniPart only where it does not (at 3 units OmniPart outvoted the mask
    where it disagreed: a live pistol's slide lost its rear on its far side, recall 0.82, a chest's lid its planks,
    0.22-0.31; at 25, 0.99 and 1.00 with no more spill, 2026-10-25). Faces start as body; each moving part (in
    `moving`'s order, larger first, so a trigger is cut from what a slide leaves) is cut from the rest."""
    names = list(names)
    pairs = np.asarray(pairs)
    area = np.asarray(areas, float) / np.mean(areas)
    weights = crease_weights(np.asarray(lengths, float), angles, lam, sigma)
    labels = np.array(["body"] * len(area), dtype=object)
    remaining = np.arange(len(area))
    moving = [name for name in (moving or MOVING) if name in names]
    for part in moving:
        rivals = [n for n in names if n != part and (n not in moving or moving.index(n) > moving.index(part))]
        gap = (distances[:, names.index(part)] - distances[:, [names.index(r) for r in rivals]].min(1)) / tau
        gap = np.clip(np.nan_to_num(gap), -20, 20)  # OmniPart's evidence is capped before the mask's is weighed
        if masks is not None and part in masks:
            vote = np.asarray(masks[part], float)
            # OmniPart's parts vary by seed: its vote counts as far as its part agrees with the mask where the mask
            # votes for it (the share of those faces nearest its part; on a live pistol seed its slide was a speck at
            # the muzzle, 6%, and its far-off distances outvoted a mask that covered the slide)
            voted = vote > 0
            if voted.any():
                nearest = np.argmin(distances, axis=1) == names.index(part)
                gap = gap * float(np.clip(nearest[voted].mean() / 0.5, 0.1, 1.0))
            gap = gap - mask_weight * vote
        gap = np.clip(np.nan_to_num(gap), -20, 20)  # 20 units is decisive; a wider range only drowns the creases
        index = {node: k for k, node in enumerate(remaining)}
        keep = np.array([a in index and b in index for a, b in pairs], bool)
        sub_pairs = np.array([(index[a], index[b]) for a, b in pairs[keep]], int).reshape(-1, 2)
        inside = binary_cut(len(remaining), (area * np.maximum(gap, 0))[remaining],
                            (area * np.maximum(-gap, 0))[remaining], sub_pairs, weights[keep])
        labels[remaining[inside]] = part
        remaining = remaining[~inside]
    return labels


def _quarter_turns():
    """The 24 rotations that map the axes onto the axes (signed permutations with determinant +1)."""
    import itertools
    turns = []
    for order in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            matrix = np.zeros((3, 3))
            for row, (column, sign) in enumerate(zip(order, signs)):
                matrix[row, column] = sign
            if np.linalg.det(matrix) > 0:
                turns.append(matrix)
    return turns


def _fit_bounds(points, target):
    """Per-axis scale and offset that put points' bounds on target's."""
    low, high = points.min(0), points.max(0)
    tlow, thigh = target.min(0), target.max(0)
    scale = (thigh - tlow) / np.maximum(high - low, 1e-9)
    return np.diag(scale), tlow - low * scale


def align(source, target, iterations=20, subsample=4000, seed=0):
    """A transform (matrix, offset) that lays source points (one generator's output) on target points (another's
    output for the same concept): the best of the 24 quarter turns with bounds fitted, then refined by iterative
    closest points (rotation and uniform scale). Two generators need not share a frame: TRELLIS.2 laid a pistol
    along Y where OmniPart laid it along X (2026-10-25). Returns (matrix, offset, mean distance to the target)."""
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(seed)
    src = source[rng.choice(len(source), min(subsample, len(source)), replace=False)]
    tgt = target[rng.choice(len(target), min(subsample, len(target)), replace=False)]
    tree = cKDTree(tgt)

    def error(points):
        return 0.5 * (tree.query(points)[0].mean() + cKDTree(points).query(tgt)[0].mean())

    best = None
    for turn in _quarter_turns():
        turned = src @ turn.T
        scale, offset = _fit_bounds(turned, tgt)
        matrix = scale @ turn
        candidate = (error(src @ matrix.T + offset), matrix, offset)
        if best is None or candidate[0] < best[0]:
            best = candidate
    _, matrix, offset = best
    for _ in range(iterations):  # similarity refinement (Umeyama) on nearest-point pairs
        moved = src @ matrix.T + offset
        pairs = tgt[tree.query(moved)[1]]
        mu_m, mu_p = moved.mean(0), pairs.mean(0)
        a, b = moved - mu_m, pairs - mu_p
        u, sigma, vt = np.linalg.svd(b.T @ a / len(a))
        d = np.diag([1, 1, np.sign(np.linalg.det(u @ vt))])
        rotation = u @ d @ vt
        scale = np.trace(np.diag(sigma) @ d) / max((a ** 2).sum() / len(a), 1e-12)
        step = scale * rotation
        matrix, offset = step @ matrix, step @ offset + mu_p - step @ mu_m
    return matrix, offset, float(error(src @ matrix.T + offset))


def part_distances(centres, parts, samples=60000, seed=0):
    """Each centre's distance to each part's surface, the part given as (vertices, triangles) in the centres'
    frame, measured to points sampled over the part's surface by area (dense enough for millimetre votes)."""
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(seed)
    out = np.zeros((len(centres), len(parts)))
    for k, (vertices, triangles) in enumerate(parts):
        corners = np.asarray(vertices)[np.asarray(triangles)]
        areas = 0.5 * np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1)
        chosen = rng.choice(len(corners), samples, p=areas / areas.sum())
        weights = rng.dirichlet((1, 1, 1), samples)
        points = np.einsum("sk,skd->sd", weights, corners[chosen])
        out[:, k] = cKDTree(np.concatenate([points, np.asarray(vertices)])).query(centres)[0]
    return out


def merge_islands(labels, pairs, areas, min_share=0.1):
    """Each label's connected regions but its largest, when smaller than `min_share` of that label's area, take the
    label most of their neighbours have: a speck of slide inside the frame would be a loose piece of its own once the
    parts are separated (live seeds failed the component budget with 22-233 pieces, 2026-10-25)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    labels = np.array(labels, dtype=object)
    pairs = np.asarray(pairs)
    areas = np.asarray(areas, float)
    n = len(labels)
    same = labels[pairs[:, 0]] == labels[pairs[:, 1]]
    graph = coo_matrix((np.ones(int(same.sum())), (pairs[same, 0], pairs[same, 1])), shape=(n, n))
    count, region = connected_components(graph, directed=False)
    region_area = np.bincount(region, weights=areas, minlength=count)
    region_label = {r: labels[i] for i, r in enumerate(region)}
    largest = {}
    for r in range(count):
        name = region_label[r]
        if name not in largest or region_area[r] > region_area[largest[name]]:
            largest[name] = r
    total = {name: sum(region_area[r] for r in range(count) if region_label[r] == name) for name in largest}
    small = {r for r in range(count) if r != largest[region_label[r]] and region_area[r] < min_share * total[region_label[r]]}
    if not small:
        return labels
    neighbours = {r: {} for r in small}
    for a, b in pairs:
        for x, y in ((a, b), (b, a)):
            r = region[x]
            if r in small and region[y] != r:
                other = labels[y]
                neighbours[r][other] = neighbours[r].get(other, 0) + 1
    out = labels.copy()
    for r in small:
        if neighbours[r]:
            out[region == r] = max(neighbours[r], key=neighbours[r].get)
    return out


def lift_above_rim(labels, centres, span, part):
    """Body faces standing clear above the body's rim, given to the open `part`: an open lid's mask misses its hinge
    knuckles and band ends on its back edge, and left with the body they stop it closing (OPEN1, 2026-10-25). The rim
    is the most populated height in the top tenth of the body's faces (z up). Returns (labels, report)."""
    labels = np.array(labels, copy=True)
    body = labels == "body"
    z = centres[body, 2]
    heights = np.linspace(np.percentile(z, 90), np.percentile(z, 99.5), 200)
    rim = max(heights, key=lambda h: int((np.abs(z - h) < 0.005 * span).sum()))
    above = body & (centres[:, 2] > rim + 0.015 * span)
    labels[above] = part
    return labels, {"rim_height": round(float(rim), 4), "moved_faces": int(above.sum())}
