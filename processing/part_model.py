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
import re
import struct
import sys
from collections import namedtuple
from pathlib import Path

import numpy as np
from PIL import Image

GRID = 64  # OmniPart's sparse structure resolution; boxes are in its [-0.5, 0.5] frame


def part_ids(alpha, masks, parts):
    """Label every object pixel with a part id: declared parts first (earlier wins where masks overlap), then the
    body. A body speck resting on a slide (body all the way down to the slide's top in its column: a pistol's
    sights) is the slide's, since it moves with it; the hammer behind the slide and the frame under it stay body."""
    ids = np.zeros(alpha.shape, np.int32)
    table = []
    for index, part in enumerate(parts, 1):
        ids[np.asarray(masks[part["name"]], bool) & alpha & (ids == 0)] = index
        table.append({"name": part["name"], "kind": part["kind"], "id": index})
    body = len(parts) + 1
    ids[alpha & (ids == 0)] = body
    table.append({"name": "body", "kind": "body", "id": body})
    for part in [entry for entry in table if entry["kind"] == "slide"]:
        slide = ids == part["id"]
        resting = np.zeros(alpha.shape, bool)
        for row in range(alpha.shape[0] - 2, -1, -1):  # scanning upwards: a body pixel rests on the slide when the pixel under it does
            resting[row] = (ids[row] == body) & (slide[row + 1] | resting[row + 1])
        ids[resting] = part["id"]
    return ids, table


Frame = namedtuple("Frame", "sign bbox lo hi axis")


def object_frame(alpha, coords):
    """How the concept maps onto the occupied voxel grid.

    bbox is the object's pixel extent (u0, u1, v0, v1); lo and hi its voxel extent in the [-0.5, 0.5] frame. Image
    columns run along the horizontal grid axis `axis` (0 or 1: OmniPart lays a weapon along either), mirrored when
    sign is -1; of the four, the one whose (axis, z) footprint overlaps the silhouette best. Image rows run down
    grid z; the other horizontal axis is the thickness.
    """
    xyz = np.asarray(coords)[:, 1:]
    low, high = xyz.min(0), xyz.max(0)
    rows, cols = np.nonzero(alpha)
    u0, u1, v0, v1 = int(cols.min()), int(cols.max()), int(rows.min()), int(rows.max())
    best = None
    for axis in (0, 1):
        footprint = np.zeros((high[2] - low[2] + 1, high[axis] - low[axis] + 1), bool)
        footprint[xyz[:, 2] - low[2], xyz[:, axis] - low[axis]] = True
        silhouette = Image.fromarray(np.asarray(alpha[v0:v1 + 1, u0:u1 + 1], np.uint8) * 255)
        silhouette = np.asarray(silhouette.resize((footprint.shape[1], footprint.shape[0]), Image.NEAREST)) > 0
        silhouette = silhouette[::-1]  # image row 0 is the top; grid z grows upwards
        for sign, candidate in ((1, silhouette), (-1, silhouette[:, ::-1])):
            score = (footprint & candidate).sum() / max((footprint | candidate).sum(), 1)
            if best is None or score > best[0]:
                best = (score, sign, axis)
    _score, sign, axis = best
    return Frame(sign, (u0, u1, v0, v1), (low + 0.5) / GRID - 0.5, (high + 0.5) / GRID - 0.5, axis)


def _ordered(ids, table):
    """OmniPart orders part ids bottom-up (load_bottom_up_mask): the part reaching the lowest image row first."""
    return sorted(table, key=lambda entry: -np.flatnonzero((ids == entry["id"]).any(axis=1)).max())


def _grid_span(ids, entry, frame):
    """A part's mask extent mapped onto the grid: (ha, hb) along the horizontal axis, (za, zb) up, in [-0.5, 0.5]."""
    sign, (u0, u1, v0, v1), lo, hi, axis = frame
    rows, cols = np.nonzero(ids == entry["id"])
    ua, ub = (cols.min() - u0) / max(u1 - u0, 1), (cols.max() - u0) / max(u1 - u0, 1)
    va, vb = (rows.min() - v0) / max(v1 - v0, 1), (rows.max() - v0) / max(v1 - v0, 1)
    ha, hb = lo[axis] + ua * (hi[axis] - lo[axis]), lo[axis] + ub * (hi[axis] - lo[axis])
    if sign < 0:
        ha, hb = lo[axis] + hi[axis] - hb, lo[axis] + hi[axis] - ha
    return (ha, hb), (hi[2] - vb * (hi[2] - lo[2]), hi[2] - va * (hi[2] - lo[2]))


def part_boxes(ids, table, frame):
    """One axis-aligned box per part in OmniPart's bottom-up order, spanning the object's full thickness."""
    lo, hi, axis = frame.lo, frame.hi, frame.axis
    other = 1 - axis
    boxes = []
    for entry in _ordered(ids, table):
        (ha, hb), (za, zb) = _grid_span(ids, entry, frame)
        box_lo, box_hi = [0.0, 0.0, za], [0.0, 0.0, zb]
        box_lo[axis], box_hi[axis] = ha, hb
        box_lo[other], box_hi[other] = lo[other], hi[other]
        boxes.append([box_lo, box_hi])
    return np.asarray(boxes, np.float32)


def coverage(ids, table, frame, part_voxels):
    """For each declared hinge or slide: the share of its mask's grid cells that hold one of the sparse structure's
    voxels inside its box. Diagnostic only: a thin lever barely registers in a 64-cell structure even when the
    synthesised part is fine, so the gate projects the generated mesh instead (prepare_model.py)."""
    sign, (u0, u1, v0, v1), lo, hi, axis = frame
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
        h = np.rint(low[axis] + u * (high[axis] - low[axis])).astype(int)
        z = np.rint(high[2] - (rows - v0) / max(v1 - v0, 1) * (high[2] - low[2])).astype(int)
        cells = set(zip(z.tolist(), h.tolist()))
        voxels = np.asarray(part_voxels.get(entry["name"], np.zeros((0, 4), int)))
        held = set(zip(voxels[:, 3].tolist(), voxels[:, 1 + axis].tolist())) if len(voxels) else set()
        report[entry["name"]] = len(cells & held) / len(cells) if cells else 0.0
    return report


def glb_json(path):
    """The JSON chunk of a GLB."""
    data = Path(path).read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20:20 + length])


def pack_glb(doc, binary):
    """A GLB from a glTF document and its binary chunk (both padded to 4 bytes)."""
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    binary = binary + b"\0" * (-len(binary) % 4)
    chunks = struct.pack("<II", len(text), 0x4E4F534A) + text
    if binary:
        chunks += struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks


def name_parts(merged, destination, names):
    """OmniPart's merged GLB has geometry_0 (its box visualisation) then geometry_i per box in order: drop the
    first, name the rest after their parts, and return each part's triangle count."""
    data = Path(merged).read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + length])
    binary = data[20 + length + 8:] if len(data) > 20 + length else b""
    keep = [index for index, node in enumerate(doc["nodes"]) if node.get("name") != "geometry_0"]
    remap = {old: new for new, old in enumerate(keep)}
    faces = {}
    for old in keep:
        node = doc["nodes"][old]
        numbered = re.fullmatch(r"geometry_(\d+)", node.get("name", ""))
        if not numbered:  # merge_parts' "world" root and anything else stays as it is
            continue
        index = int(numbered.group(1)) - 1
        node["name"] = names[index]
        if "mesh" in node:
            mesh = doc["meshes"][node["mesh"]]
            mesh["name"] = names[index]
            faces[names[index]] = sum(doc["accessors"][primitive["indices"]]["count"] // 3
                                      for primitive in mesh["primitives"] if "indices" in primitive)
    doc["nodes"] = [doc["nodes"][old] for old in keep]
    for node in doc["nodes"]:
        if "children" in node:
            node["children"] = [remap[child] for child in node["children"] if child in remap]
    for scene in doc.get("scenes", []):
        scene["nodes"] = [remap[index] for index in scene["nodes"] if index in remap]
    Path(destination).write_bytes(pack_glb(doc, binary))
    return faces


def _omnipart(request, out_dir, boxes_for, mask_path):
    """OmniPart's sparse structure, then its MIT part synthesis in the boxes we build; returns the voxel
    coordinates, each box's voxels, and the backend's identity. Runs in the OmniPart checkout."""
    import os
    import subprocess
    import torch
    sys.path.insert(0, os.getcwd())
    from modules.inference_utils import gen_mesh_from_bounds, load_img_mask, merge_parts, prepare_part_synthesis_input
    from modules.part_synthesis.pipelines import OmniPartImageTo3DPipeline
    from modules.part_synthesis.process_utils import save_parts_outputs
    seed, steps, cfg = int(request["seed"]), int(request.get("steps", 25)), float(request.get("cfg", 7.5))
    pipe = OmniPartImageTo3DPipeline.from_pretrained("omnipart/OmniPart")
    pipe.to("cuda")
    _white, black, ordered_mask, vis = load_img_mask(request["image"], str(mask_path))
    vis.save(out_dir / "img_mask_vis.png")
    torch.manual_seed(seed)
    coords = pipe.get_coords(black, num_samples=1, seed=seed,
                             sparse_structure_sampler_params={"steps": steps, "cfg_strength": cfg}).cpu().numpy()
    np.save(out_dir / "voxel_coords.npy", coords)
    _frame, boxes = boxes_for(coords)
    np.save(out_dir / "bboxes.npy", boxes)
    gen_mesh_from_bounds(boxes).export(str(out_dir / "boxes_vis.glb"))
    inputs = prepare_part_synthesis_input(str(out_dir / "voxel_coords.npy"), str(out_dir / "bboxes.npy"), ordered_mask)
    result = pipe.get_slat(black, inputs["coords"], [inputs["part_layouts"]], inputs["masks"], seed=seed,
                           slat_sampler_params={"steps": steps, "cfg_strength": cfg},
                           formats=["mesh", "gaussian", "radiance_field"], preprocess_image=False)
    save_parts_outputs(result, output_dir=str(out_dir), simplify_ratio=0.3, save_video=False, save_glb=True,
                       textured=True)
    merge_parts(str(out_dir))
    all_coords = inputs["coords"]
    all_coords = all_coords.cpu().numpy() if hasattr(all_coords, "cpu") else np.asarray(all_coords)
    if all_coords.shape[1] == 3:
        all_coords = np.concatenate([np.zeros((len(all_coords), 1), all_coords.dtype), all_coords], 1)
    part_voxels = [all_coords[layout] for layout in inputs["part_layouts"][1:]]
    version = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    backend = {"provider": "omnipart", "version": version or "unknown", "device": torch.cuda.get_device_name(0)}
    ref = Path.home() / ".cache/huggingface/hub/models--omnipart--OmniPart/refs/main"
    return coords, part_voxels, backend, {"omnipart/OmniPart": ref.read_text().strip() if ref.is_file() else "unknown"}


def main(request_path):
    request = json.loads(Path(request_path).read_text())
    out_dir = Path(request["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(request["image"]) as image:
        alpha = np.asarray(image.convert("RGBA"))[..., 3] > 0
    masks = {}
    for name, path in request["masks"].items():
        with Image.open(path) as mask:
            masks[name] = np.asarray(mask.convert("L").resize(alpha.shape[::-1], Image.NEAREST)) > 127
    ids, table = part_ids(alpha, masks, request["parts"])
    try:  # load_img_mask reads the ids as a 3-channel EXR
        import os
        os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
        import cv2
        mask_path = out_dir / "mask.exr"
        cv2.imwrite(str(mask_path), np.stack([ids.astype(np.float32)] * 3, -1))
    except ImportError:
        mask_path = out_dir / "mask.png"
        Image.fromarray(ids.astype(np.uint8)).save(mask_path)
    frames = {}

    def boxes_for(coords):
        frames["frame"] = object_frame(alpha, coords)
        return frames["frame"], part_boxes(ids, table, frames["frame"])
    coords, part_voxels, backend, weights = _omnipart(request, out_dir, boxes_for, mask_path)
    ordered = _ordered(ids, table)
    voxels = {entry["name"]: part_voxels[index] if index < len(part_voxels) else coords[:0]
              for index, entry in enumerate(ordered)}
    covered = coverage(ids, table, frames["frame"], voxels)
    faces = name_parts(out_dir / "mesh_textured.glb", out_dir / "parts.glb", [entry["name"] for entry in ordered])
    boxes = part_boxes(ids, table, frames["frame"])
    report = {"seed": request["seed"], "x_sign": frames["frame"].sign, "axis": frames["frame"].axis,
              "backend": backend, "model_weights": weights,
              "parts": {entry["name"]: {"kind": entry["kind"], "id": entry["id"],
                                        "faces": faces.get(entry["name"], 0),
                                        "box": boxes[index].tolist(), "voxels": int(len(voxels[entry["name"]])),
                                        "structure_coverage": covered.get(entry["name"])}
                        for index, entry in enumerate(ordered)}}
    (out_dir / "parts.json").write_text(json.dumps(report, indent=2) + "\n")
    print("[INFO] parts " + ", ".join(f"{name} structure coverage {item['structure_coverage']}" for name, item in report["parts"].items()))


if __name__ == "__main__":
    main(sys.argv[1])
