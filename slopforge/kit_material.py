"""A kit's shared surface material: one seamless swatch that every module's base colour is baked from.

Each module keeps its own normal map and its own brightness variation; the swatch sets the colour, so modules made
one at a time stop disagreeing (sandy columns beside grey walls, docs/media/kit-scene-2026-10).
"""
from pathlib import Path

import numpy as np
from PIL import Image

from .failures import StageFailure


def make_seamless(source, destination, band=0.25):
    """Write a copy of a swatch that tiles without seams.

    The swatch shifted by half its size has the original's middle at its edges, which wrap cleanly; it is blended in
    near the edges, and the original is kept in the middle, where the shifted copy has its seam.
    """
    with Image.open(source) as image:
        pixels = np.asarray(image.convert("RGB")).astype(np.float32)
    height, width = pixels.shape[:2]
    shifted = np.roll(np.roll(pixels, height // 2, 0), width // 2, 1)
    ramp = lambda size: np.clip(np.minimum(np.arange(size), size - 1 - np.arange(size)) / (size / 2) / band, 0, 1)
    weight = (ramp(height)[:, None] * ramp(width)[None, :])[..., None]
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(pixels * weight + shifted * (1 - weight), 0, 255).astype(np.uint8)).save(destination)


def kit_swatch(root, manifest, asset):
    """(approved swatch path, tile size in metres) for a kit module with a shared material, else None.

    Stops before any inference when the kit's texture is not approved yet.
    """
    spec = asset.get("kit_material")
    if not spec:
        return None
    texture = manifest.get("assets", {}).get(spec["asset_key"], {})
    name = texture.get("name", spec["asset_key"].split(":", 1)[-1])
    path = Path(root) / texture.get("outputs", {}).get("image", "")
    if texture.get("status") != "ready" or not texture.get("outputs", {}).get("image") or not path.is_file():
        raise StageFailure(
            "configuration", f"Kit material {name!r} is not approved, so module {asset.get('name')!r} cannot take its "
            "base colour from it", operation="kit_material_preflight",
            remedy=f"approve a concept for {name} (slopforge approve {name} <number>), then approve this module again")
    return path, float(spec["tile_size"])
