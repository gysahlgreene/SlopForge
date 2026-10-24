# Materials and textures

SlopForge generates mesh-aware PBR materials together with the 3D model. The goal is a
correct material on the first generation: the brief declares what each region is made
of, the concept is drawn so the 3D model can read it, and the material stage checks the
result against that declaration before anyone reviews it.

## How a material is made

1. **Brief.** The agent writes a specific concept prompt (`--image-prompt`) and declares
   each material region with a repeatable `--material`:

   ```sh
   slopforge --project <project> generate prop power_relay "Alien power relay" \
     --image-prompt "One chunky sci-fi power relay unit: matte dark graphite housing, turquoise glazed-ceramic front plate, copper coupling rings, a small amber glass lens; complete three-quarter view, isolated on a plain light-grey background." \
     --material "housing=nonmetal: matte dark graphite composite" \
     --material "front plate=nonmetal: turquoise glazed ceramic" \
     --material "couplings=metal: polished copper" \
     --material "lens=emissive: amber glass"
   ```

   Classes are `nonmetal`, `metal`, `emissive` and `glass`. `emissive#rrggbb` and `glass#rrggbb` give a
   coloured emitter's or tinted glass's colour in the concept, so the material stage can find it. Without a
   colour, the region is found as the map's pale near-neutral area (clear glass, pale paper). Declarations are stored on the asset
   record and apply to every later stage.

2. **Concept.** SlopForge appends reconstruction rules and the declared regions to every
   3D concept prompt, including agent-authored and recipe prompts: complete centred
   object, soft even studio lighting with no baked highlights, distinct material regions,
   matte non-metals, and emissive regions described only by their unlit look: "a solid opaque
   surface with a dull matte finish in its own flat daytime colour". The rule does not name the
   glow; when it said "switched off, not glowing", every lantern concept drew the panels lit.

3. **Geometry and maps.** The TRELLIS.2 workflow generates the shape and a voxel texture
   field. On the H100 profile the raw shape (often tens of millions of faces in open,
   non-manifold double shells) is remeshed on the GPU with ComfyUI's UDF `RemeshMesh` at
   resolution 384 and decimated to the face budget with `DecimateMesh`. Blender then only
   unwraps UVs, and ComfyUI bakes base color, roughness and metallic maps onto those UVs.
   The final tier uses a 1536 shape upsample and 4096² maps.

4. **Normal map.** The H100 TRELLIS.2 workflows save the full-detail remeshed shape
   (`save_detail`), and Blender's Cycles bake writes a tangent-space normal map from it onto
   the repaired, UV-mapped mesh (`normal_source: blender_mikktspace_bake`). Blender and Unity
   shade with MikkTSpace tangents; ComfyUI's `BakeNormalMapFromMesh` uses Lengyel tangents, and
   the mismatch showed as white speckle across characters (8.5% of normal texels strongly
   tilted, against 1.1% for the Blender bake on the same input and seed). Other workflows still record `normal_source: neutral_placeholder`; `approve-texture`
   refuses a 1×1 placeholder normal unless `--allow-placeholder-normal` is passed.

5. **Concept projection (characters).** Asset types with `concept_projection: front` (the
   `character` type) project their front A-pose concept orthographically onto the base color of
   surfaces that face the camera and are not hidden from it, keeping the voxel bake elsewhere
   (`native_material/basecolor_voxel.png`; candidates record `basecolor_source` and the
   `concept_projection` report). The voxel bake turns eyes into slits; the projection carries the
   concept's eyes, brows, beard and print. A reconstruction whose proportions differ from the
   concept by more than 5% is left unprojected (`status: skipped`; on 2026-10-19 the dwarf, whose
   model came out wider than its slightly turned concept, at 7.8%). A skipped projection adds a
   validation warning, so the candidate is `passed_with_warnings` and review sees that its base
   color is the voxel bake only. Visibility is softened over
   mesh neighbours but only ever lowered, so nothing is painted onto surfaces hidden from the front.
   The projected colors include the concept's soft studio shading, and features can sit a few
   concept pixels off the sculpted forms: in close-ups a brow can cross a hair strand or a concept
   strand can land on the forehead. A gate that kept the voxel color where it disagreed with a
   blurred concept removed those strands but also the eyes the voxel bake had lost, so it was dropped.

6. **Emission.** When a region is declared `emissive`, the material stage builds the
   emission map from the base color: texels near a declared `#rrggbb` colour glow in that
   colour, and undeclared-colour emitters use large pale near-neutral regions (pale paper or glass:
   every channel at least 150 and at least 1.3 times the map's median, capped at 225 so a paper lampshade that
   is most of the map is still found; channels within 25 of each other).
   Small flecks are removed, and the candidate records `emission_source: declared_emissive_mask`. The bake's
   colour is not reliable: one amber lens concept baked dark rust, dark grey-brown and olive on three seeds. So
   each emitter declared with a colour (`emissive#rrggbb`) is also found in the approved concept, where its colour
   holds, and carried onto the texture. Pale emitters are not projected: on a live lantern the pale rule took
   granite highlights in the concept and 90% of the projected texels were stone, while the paper itself baked
   pale enough for the colour rule. `blender/concept_view.py` renders the mesh along the view that best fits the concept silhouette
   (front half of the view sphere; skipped below 0.9 overlap), as base colour and float UV coordinates.
   `slopforge/emitters.py` then:
   - keeps the largest matching blob for a declared colour, which drops glints on parts of a similar hue;
   - grows that blob over connected pixels of the declared hue;
   - maps it onto the render through the silhouettes' bounding boxes, and marks the texels the render shows there.

   A texel glows when either way finds it. The candidate records `emission_projection` (status, view, overlap, texture
   fraction per target). A candidate
   whose base color is missing any one declared emitter fails with `emitter_missing` (`emissive_fraction` is the
   smallest declared emitter's share of the map, so a found lens cannot hide missing panels), a retryable quality code, so the next
   mesh seed is tried within the tier's attempt budget. Before any mesh inference, `approve` applies the same rule
   to the approved concept's cutout (flattened onto black) and stops with a `configuration` failure
   (`emitter_preflight`) when a declared emitter is not visible there, because the bake follows the concept and
   every seed would miss it. Without an emissive
   declaration the emission map is black. The surface-swatch route (`processing/make_pbr_maps.py`) enables emission
   only when the material prompt contains one of the whole words emissive, emission, glowing, glow, luminous or LED;
   `sealed` or `ledge` does not count. In Unity the Lit material is marked emissive
   (`globalIlluminationFlags = BakedEmissive`) as well as given the `_EMISSION` keyword: URP's
   material validation derives the keyword from those flags, and a new material starts as
   `EmissiveIsBlack`, so until 2026-10-20 URP silently dropped it and emitters that glowed in
   Blender stayed dark in Unity. The import now fails if Unity still disables `_EMISSION`.

7. **Glass.** Image-to-3D cannot reconstruct see-through glass. On 2026-10-22 a potion bottle drawn as clear
   glass with liquid reconstructed as shattered shards, with no cork. The same bottle drawn as "a solid
   smooth green surface, nothing visible through it" came out whole. A brass lantern's clear globe came out as
   a pale opaque shell with either wording. So the concept rule for `glass` asks for "a solid smooth glossy
   surface in its own tint with a faint sheen; nothing visible through it and nothing inside it".
   - **Material stage:** it finds the glass in the base colour by its declared tint, or as the pale region,
     and gives those texels alpha 0.35, roughness 0.05 and metallic 0.
   - **Retry:** a candidate where no glass is found fails as `glass_missing`, and the next seed is tried.
   - **Blender:** faces whose UV centre falls on glass alpha go onto a second material, `<name>_Glass`, which
     shares the maps. The review renders show the glass see-through.
   - **Unity:** a separate transparent URP Lit material, `<material>_Glass.mat`, is made for those faces,
     and the import fails if it is not assigned. The rest stays opaque with depth writes.
   - **Runtime cost:** a glass prop costs two materials (draw calls), not one, and the owner accepted that on
     2026-10-22. A single transparent material with depth writes forced on would have kept one, but URP's
     Lit material setup turns depth writes off again for transparent surfaces.
   - **Tint:** tinted glass needs its tint declared. A pale-amber globe was found on 0.1% of its map by the
     pale rule. Tinted glass is matched by hue at any lightness, because glass bakes with dark shading. On one
     bottle, colour distance found 44% of the glass and left it blotchy, while the tint's hue found 84% (98%
     on a later bottle).
   - **Prompt wording:** describe glass in `--image-prompt` by its solid look, for example "its green glass
     drawn as a solid smooth green surface with a faint sheen, nothing visible through the glass". The word
     "glass" alone draws it see-through, and the class rule appended to the prompt did not change that: six
     concepts with an extra reconstruction rule looked as translucent as six without. A see-through concept
     can still reconstruct as shards on some seeds.
   - **Shattered meshes:** a shattered seed now fails on its fit to the concept's outline (`concept_fit`,
     below), and the next seed is tried. One shattered bottle had passed every other check, with one part.
     Projects created before 2026-10-22 need `min_concept_fit: 0.8` added to their `ai/asset_types/prop.yaml`.
   - **Whole-glass objects are not reliable.** With the solid wording, three seeds of one bottle gave two
     whole bottles, which just missed the saturation check at 0.587 and 0.554 of the concept's, and one
     shattered mesh. Glass parts held in an opaque frame, such as the lantern's globe, came out whole.

8. **Metallic.** When the brief declares materials and none is `metal`, the material stage
   writes a zero metallic map: declared non-metals are dielectrics, and a metal/roughness
   material gives them metallic 0 whether they are matte or glossy. TRELLIS.2 decodes glossy
   non-metals as partly metallic. On 2026-10-20 a glazed jug declared entirely non-metal
   decoded at 0.38 and 0.60 on the glaze and about 0.2 on the cork and twine. No texel was
   fully metallic, so the earlier fully-metallic gate missed it. Metallic scales the diffuse
   colour down, which darkened the cobalt glaze towards navy; its base color was also decoded
   darker than the concept (median glaze RGB 29,46,75 against 39,59,104). The generator's map stays in
   the mesh attempt's `native_material/metallic.png`. The candidate records
   `metallic_source: declared_nonmetal`, and its validation records the generator's mean as
   `material_maps.metallic.generator_mean` next to the final `mean`. A brief that declares a
   metal region keeps the generator's map (`metallic_source: generator`), because nothing maps
   a declaration to texels; so does a brief with no declarations, as with emission.
   Verified on 2026-10-20 (H100, `final`, two fresh jug runs and one crate run). Both jug
   maps were zero, from generator means of 0.47 and 0.22. One jug was re-rendered with only
   the generator's map restored: its glaze measured median RGB 4,38,67, against 10,62,101
   with the zero map. The crate kept its generator map (mean 0.04), with metallic texels on
   the grey iron brackets.

9. **Assembly and review.** Blender wires the maps into a Principled BSDF, exports FBX
   and renders front, side, rear and three-quarter previews. Flat props are viewed from
   above so they are not rendered edge-on. For a lit turntable of any material candidate,
   run `blender --background --python blender/render_turntable.py -- <name>_preview.blend <frames>`
   and `python3 scripts/turntable_gif.py <frames> <name>.gif`.

## Checks before review

Material-map checks run on every native candidate and are recorded in its validation:

| Check | Result |
| --- | --- |
| Metallic map ≥ 90% fully metallic and the brief declares no materials | Warning |
| Emissive region declared but no matching pale or declared-colour region found (`emissive_fraction` 0) | Candidate fails (`emitter_missing`); the next mesh seed is tried within the budget |
| Glass declared but no matching pale or declared-tint region found (`glass_fraction` 0) | Candidate fails (`glass_missing`); the next mesh seed is tried within the budget |
| Mesh fits the concept's outline under `min_concept_fit` (props: 0.8) | Candidate fails (`concept_fit`): shattered reconstructions fitted 0.71–0.75, whole props 0.86–0.99; the next mesh seed is tried. The fit comes from the concept view the colour check renders |
| UV area under an asset type's optional `min_uv_area` | Candidate fails (`uv_area_budget`). No bundled type sets it: with 4-texel padding, shattered meshes (0.11–0.12) and whole organic props (0.10–0.19) overlap |
| Near-black or single-colour base color/roughness map, or mismatched map sizes | Warning |
| UV area, out-of-range UVs, components and topology | Measured by the Blender inspection |

Thresholds other than the declared-material checks are informational: the
[quality contract](QUALITY_CONTRACT.md) requires project-declared acceptance thresholds,
and none are declared yet.

## Known limits

- **Glowing parts:** image-to-3D reconstructs glowing or translucent regions as empty space, and
  a glow drawn in the concept bakes into the albedo at a seed-dependent level. Concepts must show
  emissive parts unlit as opaque surfaces. Until 2026-10-20 the concept rule named the glow ("shown
  switched off ..., not glowing"), and all 30 lantern concepts drew the paper panels lit. TRELLIS.2
  then baked them flat at about 200 or 253, mottled at 157-173, or not at all (dense slats with warm
  slivers of paper, or empty cavities): 4 of 11 lantern candidates on record had no findable panel.
  Two cut-off changes (225, then 150 and 1.3 times the map's median) fixed the pale levels but not
  the misses. Controlled tests (fixed seeds, private evidence) showed the rule wording was the lever:
  describing only the unlit look drew 9 of 12 lantern concepts unlit instead of 0 of 12, and kept
  a coloured amber lens amber and solid. With the same mesh seed, an unlit concept never baked a
  smaller panel than its lit counterpart (5 pairs: 0 → 0.7%, 0.07 → 1.35%, 0.94 → 2.41%, 1.71 → 1.71%,
  1.34 → 1.53% of the map). A seed that still bakes no panel now fails `emitter_missing` and the next
  seed is tried. Three fresh lantern runs on the new rule each found the panels on the first mesh
  attempt, and they glow in Blender and the Unity URP preview. Limits:
  - about a quarter of lantern concepts are still drawn lit or partly lit; concept selection does
    not check this;
  - on mottled panels the fleck filter drops some panes, so a few panes can stay dark;
  - a body as pale as its emitter (pale marble, white cloth or plate armour) cannot be separated
    by colour, so every seed fails `emitter_missing`; declare the emitter's colour instead;
  - the other way round, a large pale near-neutral part that is not an emitter (a light stone cap,
    white trim) on a darker body can glow when the brief declares an undeclared-colour emitter;
  - removing "light box" and "unlit in daylight" from the brief made no clear difference (3 of 12
    concepts lit or partly lit either way).
- **Glossy non-metals:** TRELLIS.2 decodes polished stone and glazes as partly or fully
  metallic. Declaring every region non-metal zeroes the map (step 7). A brief that also
  declares metal keeps the generator's values everywhere, including any false metal on
  its glossy non-metal regions.
- **Mac route:** on the local Mac (MPS) route, every observed metallic map was zero, including
  on metal parts. Treat Mac metallic output as unreliable until it is checked on a metal asset.
- **Hidden faces:** single-image conditioning guesses faces the concept does not show and can copy
  front details onto them (the showcase relay's plain back got a copper disc and lens); describe the back
  and sides in the concept prompt. The experimental `h100_multiview` profile generates side and back views
  from the approved concept and its prompt and reconstructs from all four; on one relay run the copied disc
  was gone, but the generated back invented a vent, the plate colour faded, and the crate's views never
  agreed well enough to run. See [multi-view conditioning](WORKFLOWS.md#multi-view-conditioning-props).
- **UV padding:** mesh preparation pads UV islands by 4 texels at the atlas size, then re-packs them with
  Blender's concave packer. The old 0.003 margin (12 texels at 4096) spent a noisy organic surface's atlas on
  padding: a tree stump unwrapped into about 10,600 islands and used 4.4% of its map, so its texture was
  effectively about 800² of a 4096² atlas. Re-unwrapped, the stump went to 19%, a crate 0.30 → 0.55 and a jug
  0.54 → 0.65, with unchanged stretch. Padding of 4 texels starts to bleed between neighbouring islands at the
  third mip level (1024 for a 4096 atlas), so distant seams can show faint colour lines.
  [Coverage evidence](media/props-coverage-2026-10/README.md).
- **Thin parts:** hollow rings, wires and paper-thin parts reconstruct as torn sheets; the
  reconstruction rules ask for chunky thick-walled forms.
- **Mesh repair:** Blender's voxel remesh needs closed volumes and erased thin open parts
  (planks, handles, lattices); the H100 TRELLIS.2 graphs therefore remesh on the GPU and pass
  `--no-voxel-repair`. Other workflows still use the Blender voxel repair.
- **Colour drift:** TRELLIS.2 samples the texture without guidance (`cfg 1.0`), so its colour wanders from
  seed to seed. On one cobalt jug concept, four seeds kept the hue to within a CIE hue difference (dH*) of
  4.6, and the protocol's seed baked teal (9.9). The base colour map was the generator's output byte for
  byte, so the drift is not SlopForge processing. Raising the texture `cfg` to 3 did not keep the hue
  closer, and it shifted lightness by up to 20 (darker jugs, brighter crates), so the graph is unchanged.
  New projects' `prop` type compares the base colour with the approved concept: median CIELAB chromaticity
  of the concept's object pixels against the base colour rendered, unlit, from the concept's fitted view
  (`blender/concept_view.py`, silhouette fit at least 0.8). A dH* above 4 (`colour_hue_shift`), or less
  than 0.6 of the concept's saturation (`colour_desaturated`), fails the candidate, and the next seed is
  tried. The whole atlas is the wrong comparison: it includes hidden insides and bases. In the v4 protocol
  it gave a cobalt jug 0.42 of the concept's saturation, against 0.83 from the concept's side, and a teal
  jug a hue difference of 3.9, against 6.3. When no view fits, hue is checked on the atlas, and a warning
  records that saturation was not checked. Overall lightness is not compared, because the concept is lit and
  the map is albedo. Near-grey concepts (chroma under 10) are not checked for hue or saturation. One dominant colour is compared, so a small part that
  drifted is not caught. The crate's wood comes out about 9° yellower and 13–34% less saturated on every
  seed. It passes the check, and retrying would not fix it.
- **Dark textures:** TRELLIS.2 sometimes textures a mesh mostly black on the side its concept shows: the
  moorland cliff and the M2-v3 S2 pillar, both near-grey concepts the hue check skips. From the same fitted
  view, `concept_darkened_share` crops the concept and the map to the object, averages them onto 8 to 24-cell
  grids, and counts cells lit in the concept (L* over 30) but under 0.6 of its lightness in the map. Above 0.4
  (`max_concept_darkened_share`), the candidate fails as `colour_darkened` and the next seed is tried; near-grey
  concepts are checked too. Comparing by position is what separates black patches from dark oak beams on plaster,
  which are dark in the concept as well. Calibration, cause and limits: [dark-texture check](media/dark-texture-check-2026-10/README.md).
- **Thin parts:** the concept-fit check fills each row of the outline between its outer edges, so it cannot see a
  missing bowstring, guard or handle. `concept_thin_recall` takes the concept's thin parts, meaning what a
  morphological opening (radius 3 cells on a 256-cell grid) removes from its unfilled mask, and measures the share of
  them the mesh covers from the concept's side. It is recorded for every model with a fitted view. A type that sets
  `min_concept_thin_recall` fails a candidate below it as `thin_feature_missing`, and the next seed is tried.
  - **Not calibrated yet:** of 147 kept props and modules, only six had thin parts covering at least 1% of the
    object. Those were lanterns, stumps and a canister, and all kept 0.76–1.0 of them.
  - **So no type declares a limit:** weapons will supply the failing cases.
- **Detached components:** on six 2026-10-20 H100 props, every component besides the main body
  (3–25 per prop, 7–39% of the triangles) was hidden inside it. Removing them changed no pixel in eight
  views, from the sides, above and below. Mesh preparation now removes enclosed components for props as well as
  characters (`remove_enclosed_components`), before UV unwrapping, so they no longer take atlas space. A live crate
  then came out as one component, as did a jug and a lantern. Components outside the main surface are not
  removed, because size alone cannot separate debris from small intended parts such as rivets. New projects'
  `prop` type allows at most five parts (`max_components: 5`, owner-declared on 2026-10-21); a mesh with
  more fails as `component_budget` and the next seed is tried. The GPU graph still decimates to the
  budget before the hidden parts are removed, so their share is lost rather than spent on visible detail.
  Do not enable the remesh's `sign_mode.drop_enclosed_components` to fix this: it added a quarter more
  visible faces to a crate and a lantern, but deleted a jug's handle and stopper (2026-10-21).
  Decimating the detail remesh in Blender after removing hidden parts followed the surface 2.7–7.7× more
  closely, but with the baked normal map the shaded result looked nearly the same, so it is not used.

See the [material showcase](media/material-showcase-2026-10/README.md) for generated examples
and the [quality tiers](QUALITY-TIERS.md) for resolution settings and the diagnosis record.
