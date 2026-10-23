# Natural environments

Rocks, terrain, trees and ground cover, made from briefs and assembled in Unity with SlopForge's structures and
props. This guide grows with the pipeline steps; the prototype that set its direction is the 2026-10-23 moorland
scene (owner decisions: rocks and terrain first, then trees and foliage).

## What generates well, and how

| Element | Route | Why |
| --- | --- | --- |
| Rocks, boulders, cliff chunks, ruin pieces | `prop` or `architecture` through TRELLIS, like any 3D asset | Irregular objects reconstruct well; their backs read as built, not invented |
| Ground and bark surfaces | `tiling_material` images | One tiling surface covers any area at a fixed texel density |
| Leaves, needles, grass, flowers, shrubs | `foliage` cut-outs on cards | Thin leaves don't reconstruct; a card with a cut-out does |
| Tree trunks and branches | procedural geometry with a `tiling_material` bark | Branch structure is easy to generate exactly |

## Tiling materials

`tiling_material` is an image type. Approval turns the chosen surface into a seamless 2048 × 2048 tile and derives
its maps, beside the published image in `<output>/Materials/<name>/`:
- `basecolor.png`, with joints and pits darkened slightly;
- `normal.png` (OpenGL, as Unity expects), `roughness.png` and `height.png`.

The steps, in `slopforge/surface.py`:
1. **Seams:** the image is rolled by half its size, so its seams cross the middle. The image model repaints that
   cross from the surface's own prompt (`image_seamless_inpaint_api.json`), and every other pixel is kept. In the
   prototype this made the stone texture tile. Its grass, dirt, gravel and rock layers were instead joined along
   least-difference cut paths, which also tiled. The two haven't been compared side by side.
2. **Resolution:** RealESRGAN's 4× upscale (`image_upscale_esrgan_api.json`) is mixed 35% with a plain Lanczos
   resize. Alone, it smeared granite's fine speckle into paint-like strokes. Both resizes wrap at the edges: a plain
   resize clamps there and leaves a faint seam.
3. **Brightness:** broad brightness drift is flattened, so repeats don't show as light and dark squares.

The asset records the source hash, both remote prompt ids and workflow hashes, and each map's hash.

Write the prompt as a flat surface: "Seamless tileable texture of …, seen from directly above, flat top-down
orthographic view filling the whole frame, evenly lit, no shadows, no horizon, no perspective". Bark is front-facing
instead of top-down.

## Foliage

`foliage` is an image type. Approval removes the background (the same rembg step as 3D inputs) and crops the image to
the plant, so the published PNG is an RGBA cut-out. Brief one plant element on white, seen from the side: "a single
tuft of tall wild meadow grass … isolated on a plain pure white background, crisp edges, no ground, no shadow".

Leaves read best as a sprig, not a single leaf: a rosette of leaves seen from above looked like a flower on a tree.

**Limits:** this records what was built and checked on 2026-10-23; trees, scenes and their Unity materials follow.
