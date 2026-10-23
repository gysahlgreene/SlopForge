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
1. **Seams** (`seams` on the asset type, `cut` by default):
   - **`cut`** makes the tile seamless left to right, then top to bottom. Each pass rolls the image by half, so its
     edges wrap, then covers the seam this leaves down the middle with the image's own middle, joined along a
     least-difference path on each side. Every pixel is the source's own.
   - **`repaint`** lets the image model repaint the seam cross from the surface's prompt
     (`image_seamless_inpaint_api.json`), for patterned surfaces such as dressed stone.
   - **Found in the live run:** on meadow grass, `repaint` painted a darker, busier cross that showed as bands every
     repeat, so `cut`, which made the approved prototype's ground and bark, is the default.
   - **Found by a test:** the prototype covered both seams of a fully rolled image at once. Inside the bands, that ran
     the source's own edges out to the tile's edges, leaving a short seam there; one direction at a time doesn't.
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

## Trees and shrubs

`vegetation` builds a tree or shrub from an approved bark `tiling_material` and one to four `foliage` cut-outs:

```sh
slopforge vegetation oak_a --species oak --height 10 --seed 11 --bark oak_bark --foliage oak_sprig --foliage oak_sprig2
```

**What it makes**, in `<output>/Vegetation/<name>/`:
- `<name>.fbx`, built by `blender/vegetation.py`:
  - a tapered trunk that branches twice (oak, birch) or in level whorls narrowing to a point (pine), or several
    leafy stems (shrub);
  - bark UVs in metres, 1.5 m per repeat;
  - crossed leaf cards, each showing one quarter of a 2 × 2 leaf atlas, with normals pointing out from the crown,
    so Unity lights the canopy as one volume and not as flat cards;
  - two material slots, `Bark` and `Leaves`, scaled to exactly the requested height;
- `Materials/<name>_leaves.png`, the atlas: each foliage cut-out in a quarter, with a different tint, repeating if
  fewer than four;
- the bark's base colour and normal map, and a report of faces, leaf cards and dimensions.

The manifest records a `vegetation` asset with the species, height, seed, and the hashes of its bark and foliage.
Oaks, birches and pines run 2,900–4,900 faces and shrubs about 600–800, most of them leaf cards.

**Limits:** the scene builder creates the Unity materials for bark and leaves (alpha-clipped, both sides drawn);
there is no standalone Unity prefab yet. No wind, LODs or billboards.

## Scenes

A recipe can carry a `scene` block, which `scene-render` assembles in Unity. The shipped
[`moorland_ruin`](../templates/recipes/moorland_ruin.yaml) recipe is the 2026-10-23 prototype that the owner
approved: rocks, a broken stone chapel, a camp of props, meadow and heather, and oak, birch and pine groves.

```sh
slopforge recipe run moorland_ruin --name moor
# approve each child; publish the 3D children with approve-texture
slopforge scene-render moor            # add --stills-only to skip the flythrough
```

**The scene block** works in metres within the dressed area (x east, z north). Every height in it is above the
ground. It holds:
- **`terrain`:** size, relief, noise, hills, a winding path, and layers. The first layer is the base; the others claim
  their share by slope, by distance from the path, or as noise patches.
- **`plants`:** each tree or shrub's species, height, seed, bark and foliage; `scene-render` builds any that are
  missing with `vegetation`.
- **`scatter`:** models and plants placed in an area, a cluster, around a point or along the path's edges, at a
  random turn and scale, sunk a little into the ground.
- **`grass`:** blade geometry, coloured from a layer's texture, dense near each still's camera and thinning away.
- **`cover`:** foliage cards such as wildflowers and heather, by layer weight, noise, and distance from a point.
- **`structures`:** pieces at fixed positions, turns and aligned edges, with `turn: auto` turning an L corner's open
  side inward, floor tiles, rubble, and props scaled to a height `above_floor`.
- **`lighting`:** sun, sky, fog, colour grade, ambient occlusion, and global illumination from adaptive probe
  volumes with sky occlusion.
- **`cameras`:** named stills and a flythrough through keys.

**What `scene-render` does:**
1. **In Python** (`slopforge/scene.py`, tested without Unity): the heightmap, the layer weights, every scatter and
   cover placement, the grass density grid, the structures, and the camera paths. Nothing is scattered within 4.5 m
   of the flythrough's path or a still's camera.
2. **In Unity** (`slopforge/unity_natural_scene.py`): it builds the terrain, materials, objects, cards and blades,
   sets the lighting, bakes the global illumination, reopens the scene so the baked data loads, and renders.

**Changing the layout after the children exist:** `scene-render` reads the scene block from the project's recipe
file (`ai/recipes/<recipe>.yaml`), not from the run's copy, so a turn, camera or light can change without
regenerating anything. It checks the block against the run's children before building, and the report records
`scene_source` and `scene_sha256`. Without the file, the run's own copy is used.

**Outputs** go to `ai/assets/scenes/<run>/`: `stills/<name>.png` (1600 × 900), `frames/` (1280 × 720),
`flythrough.mp4` and `flythrough.gif` when ffmpeg is installed, and `report.json`. The scene is saved at
`<output>/Scenes/<run>.unity`, and the recipe run records a `scene.render` artifact.

**Project-wide settings it changes**, which other scenes in the project share:
- the URP asset's light probe system becomes Adaptive Probe Volumes;
- shadow distance becomes 160 m, with four cascades;
- every renderer's Screen Space Ambient Occlusion takes the scene's settings.

**Found while building it:**
- **YAML 1.1 reads the key `on` as `true`.** A prop's height above the floor and the grass layer were both silently
  lost. Scene validation now refuses any key that reads as true or false.
- **Tiles need sunken ground.** At grass level, the terrain drew over the floor tiles' slightly domed tops, so the
  ground sinks 0.3 m under each tile.
- **Turning a model's own transform dropped its FBX axis rotation** and laid cliff chunks on their sides. Every
  object gets an identity root, as kit prefabs do.
- **Batch-mode renders don't draw terrain detail grass:** 296,000 painted tufts showed none. Grass is mesh geometry.
- **A frame without a field of view renders at 0 degrees.** The first live flythrough was 360 frames of flat colour.
  Every frame now carries the flythrough's `fov` (default 50).
- **A module sized by height alone keeps whatever facing the reconstruction gave it.** The prototype's arch came out
  long along y and the live run's along x, so the same `turn` showed it side-on. Declare a horizontal size for any
  piece whose facing matters: the long side then turns onto x, and the layout's turn holds.
- **TRELLIS sometimes textures a mesh mostly black,** even on the side the concept shows. The live cliff's view
  from the concept's side had 0.48 of the concept's median lightness; the other 17 live models had 0.71–1.20. The
  black is in TRELLIS's own texture, not the bake. The colour checks compare only hue and saturation, so it
  published. Three lightness measures over 125 published models did not separate it from accepted timber modules,
  whose dark beams on light plaster shift those measures, so there is no check yet. Next check: label those 125
  concept-side views by eye and calibrate against the labels. Until then, review each 3D child's preview for black
  patches before publishing it.

**Measured:** a stills-only render of the full scene over the prototype's assets took 82 s, with 145 objects,
2.0 million grass blades, 6,600 cover cards and a 34 s lighting bake.

**Limits:**
- Rendering only: no Play mode, frame-rate or memory check. Grass is plain meshes, not GPU-instanced details, which
  would likely be too heavy for a game at this density.
- No wind, LODs or impostors.
- Placements are seeded and repeatable, but differ from the prototype's, which used Unity's random numbers.
