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

   Classes are `nonmetal`, `metal` and `emissive`; `emissive#rrggbb` gives a coloured
   emitter's colour in the concept so the material stage can find it. Declarations are stored on the asset
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
   every channel at least 150 and at least 1.3 times the map's median, channels within 25 of each other).
   Small flecks are removed, and the candidate records `emission_source: declared_emissive_mask`. A candidate
   whose base color has no matching region fails with `emitter_missing`, a retryable quality code, so the next
   mesh seed is tried within the tier's attempt budget. Without an emissive
   declaration the emission map is black. The surface-swatch route (`processing/make_pbr_maps.py`) enables emission
   only when the material prompt contains one of the whole words emissive, emission, glowing, glow, luminous or LED;
   `sealed` or `ledge` does not count. In Unity the Lit material is marked emissive
   (`globalIlluminationFlags = BakedEmissive`) as well as given the `_EMISSION` keyword: URP's
   material validation derives the keyword from those flags, and a new material starts as
   `EmissiveIsBlack`, so until 2026-10-20 URP silently dropped it and emitters that glowed in
   Blender stayed dark in Unity. The import now fails if Unity still disables `_EMISSION`.

7. **Assembly and review.** Blender wires the maps into a Principled BSDF, exports FBX
   and renders front, side, rear and three-quarter previews. Flat props are viewed from
   above so they are not rendered edge-on. For a lit turntable of any material candidate,
   run `blender --background --python blender/render_turntable.py -- <name>_preview.blend <frames>`
   and `python3 scripts/turntable_gif.py <frames> <name>.gif`.

## Checks before review

Material-map checks run on every native candidate and are recorded in its validation:

| Check | Result |
| --- | --- |
| Metallic map ≥ 50% fully metallic while the brief declares no metal | Candidate fails (`material_mismatch`); revise the concept so non-metals read as matte |
| Metallic map ≥ 90% fully metallic with no metal declared or no declarations | Warning |
| Emissive region declared but no matching pale or declared-colour region found (`emissive_fraction` 0) | Candidate fails (`emitter_missing`); the next mesh seed is tried within the budget |
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
  - removing "light box" and "unlit in daylight" from the brief made no clear difference (3 of 12
    concepts lit or partly lit either way).
- **Glossy non-metals:** polished stone or glazed concepts can be decoded as metal; the
  declared-material check catches this, and matte wording in the concept prevents it.
- **Mac route:** on the local Mac (MPS) route, every observed metallic map was zero, including
  on metal parts. Treat Mac metallic output as unreliable until it is checked on a metal asset.
- **Hidden faces:** single-image conditioning guesses faces the concept does not show and can copy
  front details onto them; describe the back and sides in the concept prompt.
- **Thin parts:** hollow rings, wires and paper-thin parts reconstruct as torn sheets; the
  reconstruction rules ask for chunky thick-walled forms.
- **Mesh repair:** Blender's voxel remesh needs closed volumes and erased thin open parts
  (planks, handles, lattices); the H100 TRELLIS.2 graphs therefore remesh on the GPU and pass
  `--no-voxel-repair`. Other workflows still use the Blender voxel repair.
- **Small debris:** tiny detached components are reported but not removed automatically, because
  size alone cannot separate debris from small intended parts such as rivets.

See the [material showcase](media/material-showcase-2026-10/README.md) for generated examples
and the [quality tiers](QUALITY-TIERS.md) for resolution settings and the diagnosis record.
