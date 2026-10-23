"""A kit's shared look: its approved texture sets every module's average tint, and its declared roughness their finish.

Modules made one at a time disagreed (sandy columns beside grey walls, docs/media/kit-scene-2026-10). Baking every
module's colour from one swatch fixed that but flattened them to grey clay; the owner chose, on 2026-10-23, each
module's own generated colours with only their average tint matched (docs/media/kits-hue-match-2026-10).
"""
from pathlib import Path

import numpy as np
from PIL import Image

from .failures import StageFailure
from .validation import _lab


def kit_texture(root, manifest, asset):
    """The approved kit texture's path for a kit module with a shared material, else None.

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
            "tint from it", operation="kit_material_preflight",
            remedy=f"approve a concept for {name} (slopforge approve {name} <number>), then approve this module again")
    return path


def match_roughness(path, target, keep=0.6):
    """Move a kit module's roughness map to the kit's declared mean, keeping its own variation softened to `keep`.

    M2-v1 run K1 (2026-10-23): TRELLIS decoded the flagstone floor at roughness 0.22 beside walls at 0.67, so Unity
    showed a glossy floor reflecting the sky.
    """
    with Image.open(path) as image:
        mode = image.mode
        pixels = np.asarray(image.convert("L")).astype(np.float32) / 255
    covered = pixels > 0.002  # black UV padding outside the islands takes the kit's value, for Unity's mips
    mean = float(pixels[covered].mean()) if covered.any() else 1.0
    result = np.where(covered, target * (1 - keep + keep * pixels / mean), target)
    Image.fromarray(np.clip(result * 255 + 0.5, 0, 255).astype(np.uint8)).convert(mode).save(path)


def _srgb_from_lab(lab):
    """sRGB 0-255 of an (N, 3) array of CIELAB (D65) values; the inverse of validation._lab."""
    fy = (lab[:, 0] + 16) / 116
    f = np.stack([fy + lab[:, 1] / 500, fy, fy - lab[:, 2] / 200], 1)
    xyz = np.where(f ** 3 > 0.008856, f ** 3, (f - 16 / 116) / 7.787) * [0.95047, 1.0, 1.08883]
    linear = xyz @ np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]]).T
    srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.clip(linear, 0, None) ** (1 / 2.4) - 0.055)
    return np.clip(srgb * 255, 0, 255)


def match_hue(basecolor, reference):
    """Shift a module's average CIELAB a and b to the kit texture's, keeping its lightness and its variation.

    Returns the shift. UV padding outside the islands (near black) is left alone.
    """
    with Image.open(reference) as image:
        target = _lab(np.asarray(image.convert("RGB").resize((256, 256))).reshape(-1, 3).astype(np.float64)).mean(0)[1:]
    with Image.open(basecolor) as image:
        rgb = np.asarray(image.convert("RGB")).astype(np.float64)
    flat = rgb.reshape(-1, 3)
    covered = flat.sum(1) > 15
    lab = _lab(flat[covered])
    shift = target - lab[:, 1:].mean(0)
    lab[:, 1:] += shift
    flat[covered] = _srgb_from_lab(lab)
    Image.fromarray(flat.reshape(rgb.shape).round().astype(np.uint8)).save(basecolor)
    return [round(float(value), 3) for value in shift]
