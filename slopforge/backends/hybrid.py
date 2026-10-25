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

from ..part_split import align, label_faces, part_distances
from ..paths import blender_executable, tool_root
from ..provenance import file_sha256
from .blender import blender_environment
from .omnipart import run_omnipart

MAX_ALIGNMENT_ERROR = 0.03  # of the surface's longest side: the parts sit on the surface, not beside it


def _blender(config, root, script, request_path):
    subprocess.run([blender_executable(config, root), "--background", "--python-exit-code", "1", "--python",
                    str(tool_root() / "blender" / script), "--", str(request_path)], check=True,
                   env=blender_environment())


def split_surface(project_root, config, surface, parts_glb, concept, masks, parts, work_dir):
    """Label every face of `surface` (a GLB) with its part and rewrite `surface` as one node per part; the
    unsplit surface is kept beside it as <stem>_whole.glb. parts: the declared parts; masks: {part: mask PNG}.
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
    request.write_text(json.dumps({"surface": str(whole), "parts": str(parts_glb), "concept": str(concept),
                                   "masks": {name: str(path) for name, path in masks.items()}, "out": str(graph),
                                   "repaired": str(repaired)}))
    _blender(config, root, "hybrid_graph.py", request)
    data = np.load(graph)
    names = [str(n) for n in data["part_names"]]
    vertices = {n: data[f"part_vertices_{n}"] for n in names}
    triangles = {n: data[f"part_triangles_{n}"] for n in names}
    span = float(np.ptp(data["surface_vertices"], 0).max())
    # recorded, then gated in validation (apply_hybrid_split): a candidate rejected there is retried with a seed
    matrix, offset, error = align(np.concatenate(list(vertices.values())), data["surface_vertices"])
    placed = [(vertices[n] @ matrix.T + offset, triangles[n]) for n in names]
    distances = part_distances(data["centres"], placed)
    moving = [part["name"] for part in parts if part["kind"] in ("hinge", "slide") and part["name"] in names]
    areas_by_part = {n: float(np.linalg.norm(np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]), axis=1).sum())
                     for n, (v, t) in zip(names, placed)}
    moving.sort(key=lambda n: -areas_by_part[n])  # larger first: a trigger is cut from what a slide leaves
    votes = {n: data[f"mask_{n}"] for n in moving if f"mask_{n}" in data.files}
    labels = label_faces(distances / span, names, data["pairs"], data["lengths"], data["angles"], data["areas"],
                         masks=votes, moving=moving)
    shares = {n: round(float(np.mean(labels == n)), 4) for n in ["body", *moving]}
    np.save(work_dir / "labels.npy", labels.astype(str))
    apply_request = work_dir / "hybrid_apply_request.json"
    apply_request.write_text(json.dumps({"surface": str(repaired), "labels": str(work_dir / "labels.npy"),
                                         "out": str(surface)}))
    _blender(config, root, "hybrid_apply.py", apply_request)
    pairs = data["pairs"]
    cut = labels[pairs[:, 0]] != labels[pairs[:, 1]]
    report = {"alignment_error": round(error / span, 4), "shares": shares,
              "cut_length": round(float(data["lengths"][cut].sum() / span), 3),
              "parts": {name: {"kind": next((p["kind"] for p in parts if p["name"] == name), "body"),
                               "id": index + 1} for index, name in enumerate(["body", *moving])},
              "tools": {script: file_sha256(tool_root() / "blender" / script)
                        for script in ("hybrid_graph.py", "hybrid_apply.py")}}
    report["parts"]["body"]["kind"] = "body"
    (work_dir / "hybrid.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def generate_hybrid_parts(project_root, config, cutout, surface, metadata, seed, parts, masks_dir,
                          texture_size=2048, steps=25, cfg=7.5):
    """After TRELLIS.2 has written `surface` and `metadata` (generation.json): OmniPart's parts for the same
    concept, the split, and the record of both in generation.json and parts/parts.json for the final pass."""
    surface, metadata, masks_dir = Path(surface), Path(metadata), Path(masks_dir)
    out = surface.parent / "parts"
    omnipart = run_omnipart(config, cutout, parts, masks_dir, out, seed, texture_size, steps, cfg)
    masks = {part["name"]: masks_dir / f"{part['name']}.png" for part in parts if part["kind"] in ("hinge", "slide")}
    report = split_surface(project_root, config, surface, out / "parts.glb", cutout, masks, parts, out)
    # the final pass reads the part table from parts.json (prepare_model.py --parts-json) and closes the openings
    (out / "parts.json").write_text(json.dumps({"parts": report["parts"], "close_openings": True,
                                                "omnipart": omnipart}, indent=2) + "\n")
    info = json.loads(metadata.read_text())
    info["part_model"] = "hybrid"
    info["parts"] = report["parts"]
    info["hybrid"] = {key: report[key] for key in ("alignment_error", "shares", "cut_length", "tools")}
    info["part_generator"] = {"backend": omnipart.get("backend", {}), "model_weights": omnipart.get("model_weights", {}),
                              "seed": seed}
    for output in info.get("outputs") or []:  # the surface is rewritten as nodes: its recorded hash follows it
        if output.get("path") == surface.name:
            output["sha256"] = file_sha256(surface)
    info.setdefault("outputs", []).append({"path": surface.stem + "_whole.glb",
                                           "sha256": file_sha256(surface.with_name(surface.stem + "_whole.glb")),
                                           "kind": "mesh.whole"})
    metadata.write_text(json.dumps(info, indent=2) + "\n")
    return report
