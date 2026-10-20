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
   matte non-metals, and emissive regions shown switched off as opaque surfaces.

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
   colour, and undeclared-colour emitters use large near-white regions (pale paper or glass).
   Small flecks are removed, and the candidate records `emission_source: declared_emissive_mask`. Without an emissive
   declaration the emission map is black. The surface-swatch route (`processing/make_pbr_maps.py`) enables emission
   only when the material prompt contains one of the whole words emissive, emission, glowing, glow, luminous or LED;
   `sealed` or `ledge` does not count.

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
| Emissive region declared but no near-white region found | Warning |
| Near-black or single-colour base color/roughness map, or mismatched map sizes | Warning |
| UV area, out-of-range UVs, components and topology | Measured by the Blender inspection |

Thresholds other than the declared-material mismatch are informational: the
[quality contract](QUALITY_CONTRACT.md) requires project-declared acceptance thresholds,
and none are declared yet.

## Known limits

- **Glowing parts:** image-to-3D reconstructs glowing or translucent regions as empty space.
  Concepts must show emissive parts unlit as opaque surfaces; then they reconstruct as solid
  panels. Finding them again in the base color is only reliable for distinct colours
  (`emissive#rrggbb`) or genuinely pale regions: TRELLIS.2 bakes a dark albedo, so off-white
  paper next to light stone may not be found and the asset stays unlit (warned).
- **Glossy non-metals:** polished stone or glazed concepts can be decoded as metal; the
  declared-material check catches this, and matte wording in the concept prevents it.
- **Mac route:** on the local Mac (MPS) route, every observed metallic map was zero, including
  on metal parts. Treat Mac metallic output as unreliable until it is checked on a metal asset.
- **Hidden faces:** single-image conditioning guesses faces the concept does not show and can copy
  front details onto them (the showcase relay's plain back got a copper disc and lens); describe the back
  and sides in the concept prompt. The experimental `h100_multiview` profile generates side and back views
  from the approved concept and its prompt and reconstructs from all four; on one relay run the copied disc
  was gone, but the generated back invented a vent, the plate colour faded, and the crate's views never
  agreed well enough to run. See [multi-view conditioning](WORKFLOWS.md#multi-view-conditioning-props).
- **Thin parts:** hollow rings, wires and paper-thin parts reconstruct as torn sheets; the
  reconstruction rules ask for chunky thick-walled forms.
- **Mesh repair:** Blender's voxel remesh needs closed volumes and erased thin open parts
  (planks, handles, lattices); the H100 TRELLIS.2 graphs therefore remesh on the GPU and pass
  `--no-voxel-repair`. Other workflows still use the Blender voxel repair.
- **Small debris:** tiny detached components are reported but not removed automatically, because
  size alone cannot separate debris from small intended parts such as rivets.

See the [material showcase](media/material-showcase-2026-10/README.md) for generated examples
and the [quality tiers](QUALITY-TIERS.md) for resolution settings and the diagnosis record.
