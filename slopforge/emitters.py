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


def _flat(concept):
    """RGB of the cutout on black: background removal keeps the backdrop colour under transparent pixels."""
    return np.asarray(Image.alpha_composite(Image.new("RGBA", concept.size, (0, 0, 0, 255)), concept).convert("RGB"))


def concept_emitter_mask(concept, match, seed_mask, every_blob=False):
    """Concept pixels of one emitter declared with a colour (match).

    seed_mask is the pipeline's colour rule on the concept (emitter_colour_mask), which catches only the
    emitter's brightest pixels plus glints elsewhere. Only the largest blob is kept and grown over connected
    pixels of its hue, so the shaded body is covered; a kept glint would grow over a whole part of similar hue
    (copper caps next to an amber lens). every_blob keeps each one ungrown, for a small emitter of several spots (two
    eyes, a flickering glow).
    """
    labels, count = ndimage.label(seed_mask)
    if not count:
        return seed_mask
    sizes = ndimage.sum(seed_mask, labels, range(1, count + 1))
    if every_blob:
        # A small emitter is its spots alone: grown, round 25's furnace heart spread over the bronze chest around it
        # (2,240 heart pixels grew to 21,343).
        return seed_mask
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
    # Every render pixel looks up the concept pixel it shows, so the emitter is covered without gaps however the
    # concept, render and texture sizes compare: one texel per concept pixel left round 25's firebox as dim specks on
    # a 4096 texture (0.045% of the map).
    py, px = np.nonzero(render_alpha & (view_uv[..., 3] > 0.5))
    ex = np.round(cx.min() + (px - rx.min()) / sx).astype(int)
    ey = np.round(cy.min() + (py - ry.min()) / sy).astype(int)
    inside = (ex >= 0) & (ex < emitter.shape[1]) & (ey >= 0) & (ey < emitter.shape[0])
    seen = np.zeros(len(px), bool)
    seen[inside] = emitter[ey[inside], ex[inside]]
    width, height = texture_size
    u = np.clip((view_uv[py[seen], px[seen], 0] * width).astype(int), 0, width - 1)
    v = np.clip(((1 - view_uv[py[seen], px[seen], 1]) * height).astype(int), 0, height - 1)
    mask = np.zeros((height, width), np.uint8)
    mask[v, u] = 255
    # A render pixel covers a few texels; close the gaps without reaching across UV chart seams.
    size = max(3, 2 * int(np.ceil(texture_size[0] / render_alpha.shape[1])) + 1)
    return Image.fromarray(mask).filter(ImageFilter.MaxFilter(size))
