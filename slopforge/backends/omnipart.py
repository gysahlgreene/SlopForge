"""Generate a weapon with moving parts as separate parts through OmniPart (docs/WEAPONS.md, Moving parts).

processing/part_model.py runs on the part-mask host in OmniPart's own environment (scripts/install-omnipart.sh)
and returns one textured mesh per part; blender/prepare_parts.py then reduces the parts and bakes one base-colour
atlas and a metallic atlas, so the material stage sees what the TRELLIS route gives it: a textured mesh with four
maps. The final pass (prepare_model.py --parts-json) tags, orients and separates the parts.
"""
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from ..failures import StageFailure
from ..paths import blender_executable, tool_root
from ..provenance import file_sha256
from ..remote_tool import run_remote_tool
from ..unity_material import derive_part_maps, part_metal
from .blender import blender_environment

OMNIPART_ENV = {"SPCONV_ALGO": "native", "ATTN_BACKEND": "xformers"}  # the H100 recipe (2026-10-25)


MIN_PART_CELLS = 3  # the R2 rifle's 1.7- and 2.2-cell parts never came out (2026-10-25); a 3.3-cell trigger did


def part_cells(cutout, masks_dir, declared):
    """Each declared part's narrow extent in cells of OmniPart's structure: 64 cells over its 1.2x square crop of the
    object. A part under a few cells has no voxels of its own, and no seed gives it a shape."""
    with Image.open(cutout) as image:
        alpha = np.asarray(image.convert("RGBA"))[..., 3] > 0
    rows, cols = np.nonzero(alpha)
    cell = max(cols.max() - cols.min() + 1, rows.max() - rows.min() + 1) * 1.2 / 64
    cells = {}
    for part in declared:
        with Image.open(Path(masks_dir) / f"{part['name']}.png") as mask:
            inside = (np.asarray(mask.convert("L").resize(alpha.shape[::-1], Image.NEAREST)) > 127) & alpha
        ys, xs = np.nonzero(inside)
        cells[part["name"]] = 0.0 if not len(ys) else min(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) / cell
    return cells


def run_omnipart(config, cutout, parts, masks_dir, out, seed, texture_size=2048, steps=25, cfg=7.5):
    """OmniPart on the part-mask host: one textured mesh per declared part (hinge, slide, grip) and the body, as
    `out`/parts.glb (nodes named after the parts) with `out`/parts.json. Checks the environment and each part's
    size on OmniPart's grid first. Returns parts.json's report."""
    tools = config["asset_pipeline"].get("tools", {})
    host, python, checkout = tools.get("parts_host"), tools.get("omnipart_python"), tools.get("omnipart_checkout")
    if not (host and python and checkout):
        raise StageFailure("configuration", "A weapon with moving parts is generated as parts by OmniPart, and no "
                           "OmniPart environment is configured", operation="part_model_preflight",
                           remedy="set tools.parts_host, tools.omnipart_python and tools.omnipart_checkout "
                                  "(scripts/install-omnipart.sh), or remove part_model from ai/asset_types/weapon.yaml "
                                  "to cut the parts from one mesh instead; see docs/WEAPONS.md")
    masks_dir, out = Path(masks_dir), Path(out)
    declared = [{"name": part["name"], "kind": part["kind"]} for part in parts
                if part["kind"] in ("hinge", "slide", "grip")]
    small = {name: cells for name, cells in part_cells(cutout, masks_dir, declared).items() if cells < MIN_PART_CELLS}
    if small:
        raise StageFailure("configuration", "Part(s) too small for part-level generation: " + ", ".join(
            f"{name} spans {cells:.1f} cells" for name, cells in small.items()) +
            f" of OmniPart's 64-cell structure (at least {MIN_PART_CELLS} cells across its narrow side)",
            operation="part_size_preflight",
            remedy="draw the part larger on the concept (about 5% of the object's longer side), declare a larger "
                   "moving assembly, or drop the part; see docs/WEAPONS.md, Moving parts")
    uploads = {"concept.png": Path(cutout), **{f"{part['name']}.png": masks_dir / f"{part['name']}.png"
                                                for part in declared}}
    request = {"image": "concept.png", "masks": {part["name"]: f"{part['name']}.png" for part in declared},
               "parts": declared, "seed": seed, "texture_size": texture_size, "steps": steps, "cfg": cfg}
    run_remote_tool(host, python, tool_root() / "processing/part_model.py", request, uploads, {".": out},
                    label="omnipart", cwd=checkout, env=OMNIPART_ENV)
    return json.loads((out / "parts.json").read_text())


def generate_part_model(project_root, config, cutout, name, destination, metadata, seed, parts, masks_dir,
                        face_budget, materials, finish, texture_size=2048, steps=25, cfg=7.5):
    """Write `destination` (the processed parts GLB, one named node per part), processed_mesh.blend beside it, the
    four maps, and `metadata` (generation.json) for a weapon whose parts are given by `masks_dir/<name>.png`.
    face_budget is the reduction target (the caller leaves headroom for moving parts); steps and cfg are OmniPart's
    sampler settings for both its sparse structure and its parts (its defaults 25 and 7.5)."""
    root = Path(project_root).resolve()
    destination, metadata, masks_dir = Path(destination), Path(metadata), Path(masks_dir)
    out = destination.parent / "parts"
    run_omnipart(config, cutout, parts, masks_dir, out, seed, texture_size, steps, cfg)
    report = json.loads((out / "parts.json").read_text())
    metal = part_metal([{"name": part, "kind": item["kind"]} for part, item in report["parts"].items()], materials)
    atlas, metal_atlas = destination.parent / "atlas.png", destination.parent / "metal_atlas.png"
    normal_atlas = destination.parent / "normal_atlas.png"
    command = [blender_executable(config, root), "--background", "--python-exit-code", "1", "--python",
               str(tool_root() / "blender/prepare_parts.py"), "--", str(out / "parts.glb"), str(destination),
               str(destination.parent / "processed_mesh.blend"), "--parts-json", str(out / "parts.json"),
               "--face-budget", str(face_budget), "--basecolor-output", str(atlas), "--metallic-output",
               str(metal_atlas), "--texture-size", str(texture_size), "--normal-output", str(normal_atlas)]
    for part, value in metal.items():
        command.extend(("--metal", f"{part}={value}"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True, env=blender_environment())
    maps = derive_part_maps(atlas, metal_atlas, finish, destination.parent, normal=normal_atlas)
    metadata.write_text(json.dumps({
        "workflow": None, "seed": seed, "model": "omnipart", "part_model": "omnipart", "name": name,
        "backend": report.get("backend", {}),
        "provenance": {"model_weights": report.get("model_weights", {})},
        "textured": True, "textures": {key: path.name for key, path in maps.items()},
        "parts": report["parts"], "x_sign": report.get("x_sign"),
        "tool_sha256": {"part_model.py": file_sha256(tool_root() / "processing/part_model.py"),
                        "prepare_parts.py": file_sha256(tool_root() / "blender/prepare_parts.py")},
    }, indent=2) + "\n")
