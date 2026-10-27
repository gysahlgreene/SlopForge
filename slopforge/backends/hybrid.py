"""Hybrid parts: TRELLIS.2's surface, split into the parts OmniPart finds (docs/WEAPONS.md, Hybrid parts).

OmniPart generates a weapon's parts separately, but on TRELLIS v1 at 64 cells: soft, dark and without small
detail, which the owner rejected (2026-10-25). TRELLIS.2 carries the detail but makes one surface. Here OmniPart
only votes on which part each face of the TRELLIS.2 surface belongs to; the concept masks vote for the faces the
concept's view sees; a graph cut puts each boundary on the surface's own creases (slopforge/part_split.py). The
surface is rewritten as one glTF node per part, which the final pass separates, pivots and closes.
"""
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from ..part_split import align, label_faces, lift_above_rim, merge_islands, part_distances
from ..paths import blender_executable, tool_root
from ..provenance import file_sha256, tool_sha256
from ..providers import rights_of
from .blender import blender_environment
from .omnipart import run_omnipart

MAX_ALIGNMENT_ERROR = 0.03  # of the surface's longest side: the parts sit on the surface, not beside it
MAX_OPEN_PART_STRETCH = 1.15  # the owner, 2026-10-26: a lid may be scaled to fit its opening by at most 15%


def _blender(config, root, script, request_path):
    subprocess.run([blender_executable(config, root), "--background", "--python-exit-code", "1", "--python",
                    str(tool_root() / "blender" / script), "--", str(request_path)], check=True,
                   env=blender_environment())


def split_surface(project_root, config, surface, parts_glb, concept, masks, parts, work_dir, rim_part=None):
    """Label every face of `surface` (a GLB) with its part and rewrite `surface` as one node per part; the
    unsplit surface is kept beside it as <stem>_whole.glb. parts: the declared parts; masks: {part: mask PNG};
    parts_glb: OmniPart's parts, or None for the masks alone (an open picture's part stands clear of the body);
    rim_part: the open part, which also takes the body's faces above its rim (lift_above_rim).
    Returns the split's report (alignment, shares, the cut's length), written to work_dir/hybrid.json."""
    root = Path(project_root).resolve()
    surface, work_dir = Path(surface), Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    whole = surface.with_name(surface.stem + "_whole.glb")
    if not whole.exists():
        whole.write_bytes(surface.read_bytes())
    graph = work_dir / "hybrid_graph.npz"
    request = work_dir / "hybrid_graph_request.json"
    repaired = work_dir / "surface_repaired.glb"
    request.write_text(json.dumps({"surface": str(whole), "parts": str(parts_glb) if parts_glb else None,
                                   "concept": str(concept),
                                   "masks": {name: str(path) for name, path in masks.items()}, "out": str(graph),
                                   "repaired": str(repaired)}))
    _blender(config, root, "hybrid_graph.py", request)
    data = np.load(graph)
    span = float(np.ptp(data["surface_vertices"], 0).max())
    if parts_glb:
        names = [str(n) for n in data["part_names"]]
        vertices = {n: data[f"part_vertices_{n}"] for n in names}
        triangles = {n: data[f"part_triangles_{n}"] for n in names}
        # recorded, then gated in validation (apply_hybrid_split): a candidate rejected there is retried with a seed
        matrix, offset, error = align(np.concatenate(list(vertices.values())), data["surface_vertices"])
        placed = [(vertices[n] @ matrix.T + offset, triangles[n]) for n in names]
        distances = part_distances(data["centres"], placed)
        moving = [part["name"] for part in parts if part["kind"] in ("hinge", "slide") and part["name"] in names]
        areas_by_part = {n: float(np.linalg.norm(np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]),
                                                 axis=1).sum()) for n, (v, t) in zip(names, placed)}
        moving.sort(key=lambda n: -areas_by_part[n])  # larger first: a trigger is cut from what a slide leaves
    else:  # the masks alone vote; no part surface to align
        moving = [part["name"] for part in parts if part["kind"] in ("hinge", "slide")]
        names, error = ["body", *moving], 0.0
        distances = np.zeros((len(data["centres"]), len(names)))
    votes = {n: data[f"mask_{n}"] for n in moving if f"mask_{n}" in data.files}
    dropped = []
    areas = np.asarray(data["areas"], float)
    with Image.open(concept) as image:
        alpha = np.asarray(image.convert("RGBA"))[..., 3] > 0
    for name in list(votes):
        with Image.open(masks[name]) as image:
            share = float((np.asarray(image.convert("L").resize(alpha.shape[::-1])) > 127)[alpha].mean())
        voting = votes[name] != 0
        voted = float(areas[votes[name] > 0].sum() / max(areas[voting].sum(), 1e-12))
        # a mask that lands on far less of the surface than its share of the concept missed its part: a trigger a
        # few per cent of the object wide fell through the fitted view's misregistration and voted against itself
        if share > 0 and voted < 0.25 * share:
            dropped.append(name)
            del votes[name]
    labels = label_faces(distances / span, names, data["pairs"], data["lengths"], data["angles"], data["areas"],
                         masks=votes, moving=moving)
    labels = merge_islands(labels, data["pairs"], data["areas"])  # no speck of one part left inside another
    rim = None
    if rim_part:
        labels, rim = lift_above_rim(labels, data["centres"], span, rim_part)
    shares = {n: round(float(np.mean(labels == n)), 4) for n in ["body", *moving]}
    np.save(work_dir / "labels.npy", labels.astype(str))
    apply_request = work_dir / "hybrid_apply_request.json"
    apply_request.write_text(json.dumps({"surface": str(repaired), "labels": str(work_dir / "labels.npy"),
                                         "out": str(surface)}))
    _blender(config, root, "hybrid_apply.py", apply_request)
    pairs = data["pairs"]
    cut = labels[pairs[:, 0]] != labels[pairs[:, 1]]
    report = {"alignment_error": round(error / span, 4), "shares": shares, "masks_dropped": dropped,
              "cut_length": round(float(data["lengths"][cut].sum() / span), 3),
              "parts": {name: {"kind": next((p["kind"] for p in parts if p["name"] == name), "body"),
                               "id": index + 1} for index, name in enumerate(["body", *moving])},
              "tools": {script: tool_sha256(tool_root() / "blender" / script)
                        for script in ("hybrid_graph.py", "hybrid_apply.py")}}
    report["parts"]["body"]["kind"] = "body"
    if rim is not None:
        report["rim"] = rim
    # the concept's fitted view: whether its masks voted on every face (through the thickness) or on the seen ones
    report["view"] = json.loads(graph.with_suffix(".json").read_text())["view"]
    (work_dir / "hybrid.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def close_open_part(project_root, config, surface, part, work_dir, max_stretch=MAX_OPEN_PART_STRETCH):
    """Turn the open part of a surface generated open shut onto the body and fit it to its opening
    (blender/close_part.py), rewriting `surface`; the open split is kept as <stem>_open.glb. Returns the fit's
    report: the turn, the stretch the face match needed (gated in validation.apply_part_fit) and the seal."""
    surface, work_dir = Path(surface), Path(work_dir)
    opened = surface.with_name(surface.stem + "_open.glb")
    opened.write_bytes(surface.read_bytes())
    request, report = work_dir / "close_request.json", work_dir / "close.json"
    request.write_text(json.dumps({"surface": str(opened), "part": part["name"], "out": str(surface),
                                   "report": str(report), "max_stretch": max_stretch}))
    _blender(config, Path(project_root).resolve(), "close_part.py", request)
    result = json.loads(report.read_text())
    result["tool_sha256"] = tool_sha256(tool_root() / "blender/close_part.py")
    return result


def generate_hybrid_parts(project_root, config, cutout, surface, metadata, seed, parts, masks_dir,
                          texture_size=2048, steps=25, cfg=7.5, open_part=None):
    """After TRELLIS.2 has written `surface` and `metadata` (generation.json): OmniPart's parts for the same
    concept, the split, and the record of both in generation.json and parts/parts.json for the final pass.
    open_part: the hinged part, when the surface was generated open from an open picture: split by its masks
    alone, then closed (close_open_part)."""
    surface, metadata, masks_dir = Path(surface), Path(metadata), Path(masks_dir)
    out = surface.parent / "parts"
    out.mkdir(parents=True, exist_ok=True)
    omnipart = None if open_part else run_omnipart(config, cutout, parts, masks_dir, out, seed, texture_size, steps, cfg)
    masks = {part["name"]: masks_dir / f"{part['name']}.png" for part in parts if part["kind"] in ("hinge", "slide")}
    report = split_surface(project_root, config, surface, None if open_part else out / "parts.glb", cutout, masks,
                           parts, out, **({"rim_part": open_part["name"]} if open_part else {}))
    closed = close_open_part(project_root, config, surface, open_part, out) if open_part else None
    # the final pass reads the part table from parts.json (prepare_model.py --parts-json) and closes the openings
    (out / "parts.json").write_text(json.dumps({"parts": report["parts"], "close_openings": True, "omnipart": omnipart,
        # the lid closed onto the body along its back: the final pass faces the prop away from it
        **({"open_state": {"part": open_part["name"], "hinge": closed["hinge"]["point"]}} if closed else {})},
        indent=2) + "\n")
    info = json.loads(metadata.read_text())
    info["part_model"] = "hybrid"
    info["parts"] = report["parts"]
    info["hybrid"] = {key: report[key] for key in ("alignment_error", "shares", "cut_length", "masks_dropped", "tools",
                                                   "view", "rim") if key in report}
    if omnipart is not None:
        info["part_generator"] = {"backend": omnipart.get("backend", {}),
                                  "model_weights": omnipart.get("model_weights", {}), "seed": seed}
        if isinstance(info.get("output_rights"), list):  # the surface's models, and OmniPart's for the split
            info["output_rights"] = info["output_rights"] + rights_of(config, "omnipart")
    if closed is not None:
        info["open_state"] = {"part": open_part["name"], "close": closed}
    for output in info.get("outputs") or []:  # the surface is rewritten as nodes: its recorded hash follows it
        if output.get("path") == surface.name:
            output["sha256"] = file_sha256(surface)
    info.setdefault("outputs", []).append({"path": surface.stem + "_whole.glb",
                                           "sha256": file_sha256(surface.with_name(surface.stem + "_whole.glb")),
                                           "kind": "mesh.whole"})
    metadata.write_text(json.dumps(info, indent=2) + "\n")
    return report
