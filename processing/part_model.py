"""Generate a weapon as separate parts with OmniPart (MIT), from the concept cutout and the parts' SAM masks.

Usage: python part_model.py request.json   (run from the OmniPart checkout, in its environment; see
scripts/install-omnipart.sh and docs/WEAPONS.md)

request.json: {"image": concept cutout (RGBA), "masks": {part name: mask PNG (L, 255 inside)},
               "parts": [{"name", "kind"}], "seed": int, "out_dir": folder, "steps": 25, "cfg": 7.5}

Writes <out_dir>/parts.glb (one mesh node per part, named), parts.json (each part's kind, box, voxel count and
mask coverage; the backend's identity), voxel_coords.npy, boxes_vis.glb and mask.exr.

OmniPart's own layout stage (its 3D part boxes) runs NVIDIA PartField, which is licensed for non-commercial use
only. It is never called: the boxes come from the parts' 2D masks mapped onto the object's occupied voxels
(part_boxes), and only the MIT part-synthesis stage runs.
"""
import json
import sys

import numpy as np
from PIL import Image

GRID = 64  # OmniPart's sparse structure resolution; boxes are in its [-0.5, 0.5] frame


def part_ids(alpha, masks, parts):
    """Label every object pixel with a part id: declared parts first (earlier wins where masks overlap), then the
    body, then, for each slide, the body pixels above its bottom line as a static `<slide>_rear` part (a pistol's
    hammer and beavertail), so the body's box stops at the slide line and the slide's box is not contested."""
    ids = np.zeros(alpha.shape, np.int32)
    table = []
    for index, part in enumerate(parts, 1):
        ids[np.asarray(masks[part["name"]], bool) & alpha & (ids == 0)] = index
        table.append({"name": part["name"], "kind": part["kind"], "id": index})
    body = len(parts) + 1
    ids[alpha & (ids == 0)] = body
    table.append({"name": "body", "kind": "body", "id": body})
    for part in [entry for entry in table if entry["kind"] == "slide"]:
        rows = np.flatnonzero((ids == part["id"]).any(axis=1))
        if not len(rows):
            continue
        above = np.zeros(alpha.shape, bool)
        above[: rows.max() + 1] = True
        rear = (ids == body) & above
        if rear.any():
            ids[rear] = len(table) + 1
            table.append({"name": f"{part['name']}_rear", "kind": "static", "id": len(table) + 1})
    return ids, table


def object_frame(alpha, coords):
    """How the concept maps onto the occupied voxel grid: (x_sign, (u0, u1, v0, v1), lo, hi).

    (u0, u1, v0, v1) is the object's pixel extent; lo and hi its voxel extent in the [-0.5, 0.5] frame. Image columns
    run along grid x, mirrored when x_sign is -1 (the sign whose (x, z) footprint overlaps the silhouette better);
    image rows run down grid z; the thickness is y.
    """
    xyz = np.asarray(coords)[:, 1:]
    low, high = xyz.min(0), xyz.max(0)
    rows, cols = np.nonzero(alpha)
    u0, u1, v0, v1 = int(cols.min()), int(cols.max()), int(rows.min()), int(rows.max())
    footprint = np.zeros((high[2] - low[2] + 1, high[0] - low[0] + 1), bool)
    footprint[xyz[:, 2] - low[2], xyz[:, 0] - low[0]] = True
    silhouette = Image.fromarray(np.asarray(alpha[v0:v1 + 1, u0:u1 + 1], np.uint8) * 255)
    silhouette = np.asarray(silhouette.resize((footprint.shape[1], footprint.shape[0]), Image.NEAREST)) > 0
    silhouette = silhouette[::-1]  # image row 0 is the top; grid z grows upwards

    def overlap(candidate):
        return (footprint & candidate).sum() / max((footprint | candidate).sum(), 1)
    sign = 1 if overlap(silhouette) >= overlap(silhouette[:, ::-1]) else -1
    return sign, (u0, u1, v0, v1), (low + 0.5) / GRID - 0.5, (high + 0.5) / GRID - 0.5


def _ordered(ids, table):
    """OmniPart orders part ids bottom-up (load_bottom_up_mask): the part reaching the lowest image row first."""
    return sorted(table, key=lambda entry: -np.flatnonzero((ids == entry["id"]).any(axis=1)).max())


def _grid_span(ids, entry, frame):
    """A part's mask extent mapped onto the grid: (xa, xb), (za, zb) in the [-0.5, 0.5] frame."""
    sign, (u0, u1, v0, v1), lo, hi = frame
    rows, cols = np.nonzero(ids == entry["id"])
    ua, ub = (cols.min() - u0) / max(u1 - u0, 1), (cols.max() - u0) / max(u1 - u0, 1)
    va, vb = (rows.min() - v0) / max(v1 - v0, 1), (rows.max() - v0) / max(v1 - v0, 1)
    xa, xb = lo[0] + ua * (hi[0] - lo[0]), lo[0] + ub * (hi[0] - lo[0])
    if sign < 0:
        xa, xb = lo[0] + hi[0] - xb, lo[0] + hi[0] - xa
    return (xa, xb), (hi[2] - vb * (hi[2] - lo[2]), hi[2] - va * (hi[2] - lo[2]))


def part_boxes(ids, table, frame):
    """One axis-aligned box per part in OmniPart's bottom-up order, spanning the object's full thickness."""
    lo, hi = frame[2], frame[3]
    boxes = []
    for entry in _ordered(ids, table):
        (xa, xb), (za, zb) = _grid_span(ids, entry, frame)
        boxes.append([[xa, lo[1], za], [xb, hi[1], zb]])
    return np.asarray(boxes, np.float32)


def coverage(ids, table, frame, part_voxels):
    """For each declared hinge or slide: the share of its mask's grid cells (x, z) that hold one of its voxels."""
    sign, (u0, u1, v0, v1), lo, hi = frame
    low = np.rint((lo + 0.5) * GRID - 0.5).astype(int)
    high = np.rint((hi + 0.5) * GRID - 0.5).astype(int)
    report = {}
    for entry in table:
        if entry["kind"] not in ("hinge", "slide"):
            continue
        rows, cols = np.nonzero(ids == entry["id"])
        u = (cols - u0) / max(u1 - u0, 1)
        if sign < 0:
            u = 1 - u
        x = np.rint(low[0] + u * (high[0] - low[0])).astype(int)
        z = np.rint(high[2] - (rows - v0) / max(v1 - v0, 1) * (high[2] - low[2])).astype(int)
        cells = set(zip(z.tolist(), x.tolist()))
        voxels = np.asarray(part_voxels.get(entry["name"], np.zeros((0, 4), int)))
        held = set(zip(voxels[:, 3].tolist(), voxels[:, 1].tolist())) if len(voxels) else set()
        report[entry["name"]] = len(cells & held) / len(cells) if cells else 0.0
    return report


if __name__ == "__main__":
    raise SystemExit("part_model.py main is added in the next step")
