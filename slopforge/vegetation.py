"""Trees and shrubs from approved bark and foliage: procedural geometry (blender/vegetation.py), the bark's tiling
maps, and a 2 x 2 leaf atlas built from foliage cut-outs."""
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import json
import numpy as np
from PIL import Image

from .backends.blender import blender_environment
from .manifest import asset_key
from .paths import blender_executable, tool_root
from .provenance import file_sha256

SPECIES = ("oak", "birch", "pine", "shrub")
# Per-quarter tints, so repeated sprigs vary across a crown.
ATLAS_TINTS = ((1.0, 1.0, 1.0), (0.94, 1.0, 0.86), (0.92, 0.98, 0.84), (0.88, 0.95, 0.82))


def build_leaf_atlas(cutouts, destination, size=2048):
    """A 2 x 2 atlas: each quarter holds one cut-out, centred and fitted, with its own tint. Fewer than four
    cut-outs repeat with different tints."""
    if not cutouts:
        raise ValueError("A leaf atlas needs at least one foliage cut-out")
    half = size // 2
    atlas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for quarter in range(4):
        with Image.open(cutouts[quarter % len(cutouts)]) as image:
            image = image.convert("RGBA")
        image.thumbnail((half - 24, half - 24), Image.LANCZOS)
        pixels = np.asarray(image).astype(np.float64)
        pixels[..., :3] *= ATLAS_TINTS[quarter]
        image = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8))
        # UV quarter (column, row) counted from the bottom, as vegetation.py assigns them.
        x, y = (quarter % 2) * half, (1 - quarter // 2) * half
        atlas.paste(image, (x + (half - image.width) // 2, y + (half - image.height) // 2), image)
    atlas.save(destination)


def _ready(manifest, asset_type, name, output):
    asset = manifest["assets"].get(asset_key(asset_type, name))
    if not asset or asset.get("status") != "ready" or not asset.get("outputs", {}).get(output):
        raise ValueError(f"{asset_type} {name!r} is not approved; approve it before building vegetation")
    return asset


def make_vegetation(root, config, manifest, name, species, height, seed, bark, foliage):
    """Build and publish one tree or shrub; returns its manifest record."""
    if species not in SPECIES:
        raise ValueError(f"Species must be one of {', '.join(SPECIES)}, got {species!r}")
    if not height > 0:
        raise ValueError("Vegetation height must be positive")
    root = Path(root).resolve()
    bark_asset = _ready(manifest, "tiling_material", bark, "tiling_basecolor")
    leaves = [_ready(manifest, "foliage", item, "image") for item in foliage]
    folder = root / config["asset_pipeline"]["output_root"] / "Vegetation" / name
    materials = folder / "Materials"
    materials.mkdir(parents=True, exist_ok=True)
    outputs = {"fbx": folder / f"{name}.fbx", "report": folder / f"{name}_report.json",
               "leaves": materials / f"{name}_leaves.png", "bark_basecolor": materials / f"{name}_bark_basecolor.png",
               "bark_normal": materials / f"{name}_bark_normal.png"}
    build_leaf_atlas([root / item["outputs"]["image"] for item in leaves], outputs["leaves"])
    shutil.copy2(root / bark_asset["outputs"]["tiling_basecolor"], outputs["bark_basecolor"])
    shutil.copy2(root / bark_asset["outputs"]["tiling_normal"], outputs["bark_normal"])
    subprocess.run([blender_executable(config, root), "--background", "--python-exit-code", "1", "--python",
                    str(tool_root() / "blender/vegetation.py"), "--", str(outputs["fbx"]), str(outputs["report"]),
                    species, f"{height:g}", str(seed)], check=True, env=blender_environment(), stdout=subprocess.DEVNULL)
    report = json.loads(outputs["report"].read_text())
    key = asset_key("vegetation", name)
    record = {"id": manifest["assets"].get(key, {}).get("id") or str(uuid.uuid4()), "name": name, "type": "vegetation",
              "status": "ready", "updated_at": datetime.now(timezone.utc).isoformat(),
              "description": f"{species}, {height:g} m, seed {seed}",
              "generator": {"tool": "blender/vegetation.py", "species": species, "height": height, "seed": seed},
              "sources": {"bark": {"name": bark, "sha256": file_sha256(root / bark_asset["outputs"]["tiling_basecolor"])},
                          "foliage": [{"name": item["name"], "sha256": file_sha256(root / item["outputs"]["image"])}
                                      for item in leaves]},
              "outputs": {role: path.relative_to(root).as_posix() for role, path in outputs.items()},
              "validation": {"status": "passed", "errors": [], "warnings": [], "measured": report}}
    manifest["assets"][key] = record
    return record
