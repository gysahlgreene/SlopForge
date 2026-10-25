"""Generate a weapon with moving parts as separate parts through OmniPart (docs/WEAPONS.md, Moving parts).

processing/part_model.py runs on the part-mask host in OmniPart's own environment (scripts/install-omnipart.sh)
and returns one textured mesh per part; blender/prepare_parts.py then reduces the parts and bakes one base-colour
atlas and a metallic atlas, so the material stage sees what the TRELLIS route gives it: a textured mesh with four
maps. The final pass (prepare_model.py --parts-json) tags, orients and separates the parts.
"""
import json
import subprocess
from pathlib import Path

from ..failures import StageFailure
from ..paths import blender_executable, tool_root
from ..provenance import file_sha256
from ..remote_tool import run_remote_tool
from ..unity_material import derive_part_maps, part_metal
from .blender import blender_environment

OMNIPART_ENV = {"SPCONV_ALGO": "native", "ATTN_BACKEND": "xformers"}  # the H100 recipe (2026-10-25)


def generate_part_model(project_root, config, cutout, name, destination, metadata, seed, parts, masks_dir,
                        face_budget, materials, finish, texture_size=2048):
    """Write `destination` (the processed parts GLB, one named node per part), processed_mesh.blend beside it, the
    four maps, and `metadata` (generation.json) for a weapon whose parts are given by `masks_dir/<name>.png`.
    face_budget is the reduction target (the caller leaves headroom for moving parts)."""
    root = Path(project_root).resolve()
    tools = config["asset_pipeline"].get("tools", {})
    host, python, checkout = tools.get("parts_host"), tools.get("omnipart_python"), tools.get("omnipart_checkout")
    if not (host and python and checkout):
        raise StageFailure("configuration", "A weapon with moving parts is generated as parts by OmniPart, and no "
                           "OmniPart environment is configured", operation="part_model_preflight",
                           remedy="set tools.parts_host, tools.omnipart_python and tools.omnipart_checkout "
                                  "(scripts/install-omnipart.sh); see docs/WEAPONS.md")
    destination, metadata, masks_dir = Path(destination), Path(metadata), Path(masks_dir)
    declared = [{"name": part["name"], "kind": part["kind"]} for part in parts
                if part["kind"] in ("hinge", "slide", "grip")]
    uploads = {"concept.png": Path(cutout), **{f"{part['name']}.png": masks_dir / f"{part['name']}.png"
                                                for part in declared}}
    request = {"image": "concept.png", "masks": {part["name"]: f"{part['name']}.png" for part in declared},
               "parts": declared, "seed": seed}
    out = destination.parent / "parts"
    run_remote_tool(host, python, tool_root() / "processing/part_model.py", request, uploads, {".": out},
                    label="omnipart", cwd=checkout, env=OMNIPART_ENV)
    report = json.loads((out / "parts.json").read_text())
    metal = part_metal([{"name": part, "kind": item["kind"]} for part, item in report["parts"].items()], materials)
    atlas, metal_atlas = destination.parent / "atlas.png", destination.parent / "metal_atlas.png"
    command = [blender_executable(config, root), "--background", "--python-exit-code", "1", "--python",
               str(tool_root() / "blender/prepare_parts.py"), "--", str(out / "parts.glb"), str(destination),
               str(destination.parent / "processed_mesh.blend"), "--parts-json", str(out / "parts.json"),
               "--face-budget", str(face_budget), "--basecolor-output", str(atlas), "--metallic-output",
               str(metal_atlas), "--texture-size", str(texture_size)]
    for part, value in metal.items():
        command.extend(("--metal", f"{part}={value}"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True, env=blender_environment())
    maps = derive_part_maps(atlas, metal_atlas, finish, destination.parent)
    metadata.write_text(json.dumps({
        "workflow": None, "seed": seed, "model": "omnipart", "part_model": "omnipart", "name": name,
        "backend": report.get("backend", {}),
        "provenance": {"model_weights": report.get("model_weights", {})},
        "textured": True, "textures": {key: path.name for key, path in maps.items()},
        "parts": report["parts"], "x_sign": report.get("x_sign"),
        "tool_sha256": {"part_model.py": file_sha256(tool_root() / "processing/part_model.py"),
                        "prepare_parts.py": file_sha256(tool_root() / "blender/prepare_parts.py")},
    }, indent=2) + "\n")
