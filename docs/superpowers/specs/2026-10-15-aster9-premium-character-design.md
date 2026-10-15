# Aster-9 Premium Character Quality Design

## Goal

Produce an Aster-9 character candidate that reads as a premium, close-up hero
character in Unity, with a crisp silhouette, intentional suit detail, and
distinct, convincing materials. Keep SlopForge free to use under its MIT license
and make the production route runnable with user-supplied compute and
self-hosted models rather than requiring a paid inference service.

This is asset-quality work directed by the user. M0 remains active and this
single character cannot qualify the overall pipeline or another asset category.

## Current evidence

The 2026-10-15 Pixal3D candidate was generated from the front concept only. It
has 26,191 vertices, 29,888 faces, 10 disconnected components, 11 boundary
edges, and 288 non-manifold edges. Its base-color, roughness, and metallic maps
are 4096², but the atlas has visibly uneven, blurred detail; its normal map is a
1×1 neutral placeholder. Blender inspection reported `passed_with_warnings`,
and approval remains pending. It is a useful blockout, not a rigging source.

The existing concept set includes front, side, and rear images. The repo's
current Unity material writer supports Built-in Render Pipeline and URP; HDRP
and custom render pipelines are explicitly unsupported. Existing quality
evidence does not establish a hardware/performance budget for this character.

## Intended route

Use the current generated mesh as a shape reference or blockout, not as the
finished deliverable. Refine the character against the existing multi-view
concepts with a hybrid, art-directed process:

1. Lock the approved concept views and scale as the source of truth for
silhouette, proportions, suit color blocking, and hardware placement.
2. Refine primary forms and suit components in Blender or with existing
self-hosted generation/modeling tools. Keep deliberate separate parts where
they improve shape, material assignment, or eventual deformation; document
intentional disconnected components.
3. Create clean UVs and author a coherent PBR set for the actual mesh. Base color
must not bake in lighting; fabric, rubber, metal, and visor must have distinct
roughness/metallic behavior. Provide a real tangent-space normal map with
detail that survives close-up review. Texture resolution alone is not evidence
of quality.
4. Inspect front, side, rear, three-quarter, and close-up views under neutral
lighting, then import the exact approved candidate into a representative URP
project for material and close-up review.
5. Keep the candidate unrigged until visual/material approval and structural
readiness pass. Rigging, deformation, and runtime playback are later gates with
their own evidence.

The normal production path uses ComfyUI and compatible models that users can
run on their own hardware or a self-controlled GPU host. SlopForge must not
require a paid hosted inference provider. Compute and storage are user supplied;
the project does not promise zero hardware cost.

## Model and project licensing

SlopForge source remains MIT-licensed. Model weights, ComfyUI extensions,
Blender, Unity, and generated assets have separate terms. Do not describe the
entire stack as open source based only on the SlopForge license. Record the
source and license status of exact model artifacts and custom nodes used for a
candidate; keep unknown terms visible and do not bundle or redistribute those
dependencies. The current workflow metadata identifies Pixal3D dependencies,
but says the repackaged TRELLIS.2 VAE artifacts are not independently
verified. Confirm exact terms before presenting that model stack as an
open-source default.

## Quality and approval gates

- **Structural:** finite dimensions and transforms, usable UVs and map links,
  no missing textures, and no unexplained boundary or non-manifold geometry.
  Intentional suit/accessory components are identified rather than silently
  treated as errors. Check topology against the intended character use; a
  generic mesh check is not proof of deformation readiness.
- **Visual/material:** compare the exact candidate to the approved views from
  the required angles and close-up crops. Review silhouette, proportion,
  concept fidelity, seams/hardware, texture sharpness, UV distortion, surface
  separation, and visible defects. The user makes the appearance decision.
- **Unity:** verify the exact exported materials import and render correctly in
  URP. Use the project's actual target profile for performance checks. Until
  that profile supplies hardware and budgets, make no performance-readiness
  claim.
- **Rig/deformation/runtime:** do not start until the user approves the source
  candidate. Evaluate deformation and Unity playback separately; success in
  one gate does not imply success in another.

Record decisions against candidate and map hashes, with source concepts,
generation settings, Blender/ComfyUI/model versions where available, review
renders, and all unchecked gates. Preserve failed and rejected candidates.

## Out of scope

- Another live inference run without fresh user authorization.
- Treating the current Pixal3D candidate as approved or rigging it before the
  quality gates pass.
- A new paid model/API dependency or bundling model weights.
- Declaring all model weights or all third-party components open source without
  verified terms.
- A generic premium-quality guarantee, universal triangle/texture budget, or
  qualification claim for SlopForge, M0, or other assets.
- HDRP support, a new render-pipeline abstraction, or changes to unrelated
  product workflows.

## Open implementation questions

- Which exact modeling/material tools and compatible model weights can meet the
  visual target while retaining clear, usable terms?
- What target Unity project/profile supplies the needed runtime and performance
  requirements? URP is the default compatibility target until the project says
  otherwise; hardware budgets remain unknown.
- Which concrete visual defects in the approved concept are required to be
  modeled geometry versus texture detail?

## Success criteria

- A user can reproduce the documented route using self-hosted inference and
  separately installed tools, without a required paid inference service.
- The exact model/node sources and license status are recorded; uncertain terms
  are not represented as verified.
- The Aster-9 candidate matches the approved views, has resolved structural
  warnings, and shows crisp, differentiated PBR materials in close-up review.
- The same candidate renders with correct material bindings in Unity URP.
- The user approves the exact visual/material candidate before rigging begins.
- Structural, visual/material, deformation, runtime, and pipeline-repeatability
  claims remain separate and evidence-backed.
