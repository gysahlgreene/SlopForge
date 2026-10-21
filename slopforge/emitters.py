"""Find declared emitters in the approved concept and carry them onto the mesh's texture.

TRELLIS.2 bakes an emitter's colour per seed (an amber lens came out dark rust, dark grey-brown or olive on three
seeds of one concept), so colour matching on the bake misses it, while the concept shows it in its declared colour.
`blender/concept_view.py` renders the mesh along the view that best fits the concept silhouette, as base colour and
UV coordinates; here the concept's emitter pixels are mapped onto that render and looked up in its UV pass.
"""
import colorsys

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

HUE_TOLERANCE = 15     # degrees around the declared colour's hue that still belong to the emitter (shading)
MIN_SATURATION = 0.35  # below this a pixel is grey or white, not the emitter's colour
KEEP_RELATIVE = 0.25   # pale panels: blobs below this share of the largest are flecks, not further panes


def _flat(concept):
    """RGB of the cutout on black: background removal keeps the backdrop colour under transparent pixels."""
    return np.asarray(Image.alpha_composite(Image.new("RGBA", concept.size, (0, 0, 0, 255)), concept).convert("RGB"))


def concept_emitter_mask(concept, match, seed_mask):
    """Concept pixels of one declared emitter.

    seed_mask is the pipeline's colour rule on the concept (emitter_colour_mask), which catches only the
    emitter's brightest pixels plus glints elsewhere. For a declared colour only the largest blob is kept and
    grown over connected pixels of its hue, so the shaded body is covered; a kept glint would grow over a whole
    part of similar hue (copper caps next to an amber lens). Pale panels keep every sizeable blob.
    """
    labels, count = ndimage.label(seed_mask)
    if not count:
        return seed_mask
    sizes = ndimage.sum(seed_mask, labels, range(1, count + 1))
    if match is None:  # pale emitters (paper) have no hue to grow along, and often several panes
        return np.isin(labels, 1 + np.flatnonzero(sizes >= KEEP_RELATIVE * sizes.max()))
    seed = labels == 1 + int(np.argmax(sizes))
    rgb = _flat(concept).astype(float) / 255
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    high, low = rgb.max(-1), rgb.min(-1)
    saturation = np.where(high > 0, (high - low) / np.maximum(high, 1e-6), 0)
    hue = (np.degrees(np.arctan2(np.sqrt(3) * (g - b), 2 * r - g - b)) + 360) % 360
    declared = colorsys.rgb_to_hsv(*(value / 255 for value in match))[0] * 360
    near = np.minimum(abs(hue - declared), 360 - abs(hue - declared)) <= HUE_TOLERANCE
    alpha = np.asarray(concept)[..., 3] > 127
    grown, _ = ndimage.label((near & (saturation > MIN_SATURATION) & alpha) | seed)
    keep = np.unique(grown[seed])
    return np.isin(grown, keep[keep > 0])


def project_to_texture(concept, emitter, view_base, view_uv, texture_size):
    """Texture-space mask (PIL "L") of the concept emitter pixels, through the fitted render.

    The concept silhouette's bounding box is mapped onto the render's; each emitter pixel takes the UV of the
    surface the render shows there, so hidden surfaces never receive it.
    """
    concept_alpha = np.asarray(concept)[..., 3] > 127
    render_alpha = np.asarray(view_base)[..., 3] > 127
    if not concept_alpha.any() or not render_alpha.any() or not emitter.any():
        return Image.new("L", texture_size)
    cy, cx = np.nonzero(concept_alpha)
    ry, rx = np.nonzero(render_alpha)
    sx = (rx.max() - rx.min()) / max(cx.max() - cx.min(), 1)
    sy = (ry.max() - ry.min()) / max(cy.max() - cy.min(), 1)
    ey, ex = np.nonzero(emitter)
    px = np.clip(np.round(rx.min() + (ex - cx.min()) * sx).astype(int), 0, render_alpha.shape[1] - 1)
    py = np.clip(np.round(ry.min() + (ey - cy.min()) * sy).astype(int), 0, render_alpha.shape[0] - 1)
    seen = render_alpha[py, px] & (view_uv[py, px, 3] > 0.5)
    width, height = texture_size
    u = np.clip((view_uv[py[seen], px[seen], 0] * width).astype(int), 0, width - 1)
    v = np.clip(((1 - view_uv[py[seen], px[seen], 1]) * height).astype(int), 0, height - 1)
    mask = np.zeros((height, width), np.uint8)
    mask[v, u] = 255
    # A render pixel covers a few texels; close the gaps without reaching across UV chart seams.
    return Image.fromarray(mask).filter(ImageFilter.MaxFilter(3))
