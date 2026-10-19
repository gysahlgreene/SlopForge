# Template characters (experimental)

Single-image 3D generators produce lumpy faces, fused hands and clothing that tears when rigged. For
realistic humans this experimental route builds the character from an open, rig-ready human template
instead, and uses the generated character only as a reference for shape and colour. It is not yet a
pipeline stage: the steps below are run by hand, and garment and face choices are made per character.

## What it produces

A MakeHuman base body (clean topology, real eyes, eyelids, teeth, tongue and hands, Unreal-style
`game_engine` skeleton), library garments, hair and beard with their own UVs and bone weights, the
concept's face baked into the skin, garment colours taken from the generated outfit, procedural knee
pads, and a CMU walk through `blender/retarget_mocap.py`. On the 2026-10-19 realistic mercenary it
removed the lumpy face, fused fingers and cloth tearing of the generated character; it is plainer than the
concept (library cuts, fewer gear details) and slimmer than its burly build.

## Requirements (outside Git)

- Blender 5.1 with the [MPFB](https://static.makehumancommunity.org/mpfb.html) extension (GPL-3.0) in an
  isolated profile (`BLENDER_USER_RESOURCES`), and the CC0 asset packs `makehuman_system_assets`,
  `hair01`, `bodyparts01/04/05`, `gloves01`, `shirts01`, `pants01`, `shoes01`, `suits01/02/05` unpacked into
  MPFB's user data folder. Use only `_cc0` packs unless attribution is tracked.
- A Python with `scipy` (nearest-surface lookups) and `mediapipe` with `face_landmarker.task` (Apache-2.0)
  for face alignment.

## Steps

1. `blender/template_character/make_human.py` builds the base: macros (gender, age, muscle, weight,
   proportions, race), face targets (for example `head/head-square`, `chin/chin-width-incr`), the
   `game_engine` rig, then assets (eyes, lashes, teeth, tongue, hair, beard, garments). **The rig must be
   added before the assets**, or MPFB gives them no bone weights and they stay still while the body walks.
2. `blender/template_character/dress_bake.py` poses the template onto the generated SkinTokens rig, looks
   up each garment texel's nearest point on the generated outfit (`processing/template_nearest_solve.py`),
   recolours each garment UV island with the median colour found there (`mode: island_median`), adds the
   garment's ambient occlusion and low-frequency grime at constant mean brightness, tucks trousers into
   tall boots, rebuilds hair-card materials, and returns the rig to MPFB's rest pose.
3. Face: `face_render.py` renders the template face front-on (orthographic, lit and unlit),
   `processing/template_face_warp.py` warps a refined concept face onto it with MediaPipe landmarks,
   `face_bake.py` bakes it into the skin texture (visibility from the front, MPFB helper geometry excluded)
   and tints the rest of the skin to match; `apply_face.py` applies it and can tint hair and eyes.
4. `accessories.py` adds procedural knee pads conformed to the trousers and rigidly bound to the shins.
5. Retarget a `.blend` rig directly with `blender/retarget_mocap.py` (FBX loses MPFB node materials).

## Lessons

- Ray-cast selected-to-active baking from the generated outfit smeared colour at grazing angles; a
  nearest-surface lookup does not. Copying the generated texture texel by texel also copied its baked
  highlights and blotches, so garments take one median colour per UV island and keep their own fabric.
- Medians keep a texture's pure hue (the jacket came out lime); `saturation` restores the muted look.
- MPFB stacks hide-under-clothes masks before the armature modifier; move the armature to the top before
  applying a pose, or the body's hands are left behind.
- Cutting accessories out of the generated mesh, by protrusion or by anatomical region, gave ragged,
  torn-looking patches. Modelled procedural parts are clean.
- Front-landmark least-squares fitting of MPFB face targets barely moved the landmark error (7.1 to 6.6 px
  of 1024) and chose contradictory target pairs; the differences that matter (brow depth, jaw mass, age) are
  set by hand for now.
