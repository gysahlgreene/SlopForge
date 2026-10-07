# SkinTokens character pipeline design

## Status

Draft for review. This design implements the remaining #14 work only. #15 Humanoid mapping and animation-library retargeting remain separate.

## Goal

Take an approved generated humanoid model through topology normalization, usable UV/PBR preservation, SkinTokens rigging, repeatable deformation evidence, and Unity Generic animation validation. Keep generation, structural riggability, deformation quality, Unity import, and animation playback as independent recorded results.

The final qualification artifact remains a candidate until a person reviews the source appearance, texture, component report, and deformation contact sheet. Automation must never approve it.

## Current system

- `slopforge/character_readiness.py` records source mesh inspection and an explicit human acceptance of that report.
- `slopforge/character_rigging.py` owns the provider selection and typed candidate-artifact recording seam. `blender_rigify` is the only integrated provider.
- `blender/prepare_model.py --mesh-only` voxel-remeshes and exports geometry before its material stage. It does not preserve/rebake a source material onto the remeshed mesh.
- SkinTokens has only been run from a disposable H100 checkout. Its tested path needed an isolated Python environment, an SDPA compatibility shim, and a local attention-setting edit. It emitted a generic 28-bone rig with normalized weights, but also a helper Icosphere and nine connected components in the main mesh. The cleaned FBX imported into Unity as Generic; no Unity animation was tested.
- The Unity Generic importer/controller/prefab code exists in `slopforge/unity_animation.py`. The current Unity smoke evidence is fixture based, not a SkinTokens character playback.

## Approaches considered

### 1. Put SkinTokens inside the production ComfyUI environment

This would reuse the existing remote machine but mix its Python/CUDA requirements with ComfyUI and make an optional provider affect unrelated image workflows. The live ComfyUI installation also must remain unchanged during this work. Rejected.

### 2. Add a ComfyUI-UniRig graph as the SkinTokens adapter

This keeps provider execution inside the existing ComfyUI client but introduces the wrapper's extra runtime and does not reduce model/data licensing questions. The tested SkinTokens CLI already works in an isolated environment. Rejected for the first integration.

### 3. Add a thin SlopForge adapter for an isolated SkinTokens checkout — recommended

Keep SkinTokens as an optional external runtime with user-configured checkout, interpreter, and checkpoint. SlopForge invokes it through the existing `run_character_rigging` result seam, records repository/checkpoint identity, and never downloads weights. Blender owns mesh normalization, texture rebaking, helper cleanup, canonical pose generation, and FBX export. This follows the successful evaluation while keeping ComfyUI and the CLI independent of provider-specific details.

## Design

### Character mesh normalization

Add a character-specific normalization operation using the existing Blender toolchain. It consumes a ready, approved source model, preserves that source unchanged, and writes a project-local derivative candidate with source lineage and hashes.

The operation will:

1. Report each source mesh object and connected component, including vertex/face counts, bounds, UV layers, materials, texture maps, and whether its geometry is skinned. It will not silently delete source geometry.
2. Apply configured transforms, weld only within the existing documented tolerance, perform the configured voxel remesh, remove degenerate/isolated faces, and produce fresh UVs for the normalized mesh.
3. Rebake available source PBR material channels from the original mesh onto the normalized UV layout with Blender's selected-to-active baking. Preserve base color and any supplied roughness, metallic, and normal maps; record absent channels. If source maps are absent, allow the existing surface-material candidate workflow to provide a source image, then bake that image. A concept image is not a surface-material fallback.
4. Run mesh readiness and texture-coverage inspection on the derivative. Preserve all classified character components. Any helper or component removal must be based on explicit deterministic evidence such as absence of an armature modifier/skin weights and be recorded in the processing report.

Normalization status and material status are recorded separately from source model generation and later rigging. Failed baking must leave source and previously approved outputs unchanged.

### SkinTokens provider

Add `skintokens` to the existing provider selection, without adding a general plugin system. The provider configuration supplies the isolated Python executable, SkinTokens checkout, and checkpoint path. These paths are machine-local configuration and must not enter portable asset provenance.

Doctor/preflight will report checkout revision, runtime availability, required checkpoint presence and SHA-256, and the known compatibility overlay. It will not install dependencies, modify ComfyUI, or download model weights. The compatibility overlay must be versioned and reproducible from SlopForge; applying it must be limited to the configured isolated checkout and fail clearly on an unexpected upstream revision.

Invocation uses a recorded seed and sampling settings. Provider output is treated as untrusted candidate data: Blender removes only the known unskinned helper object after recording it, validates the armature and weights, transfers/rebakes normalized-source materials onto the output mesh, and exports project-local GLB/FBX candidates. The source model and intermediate SkinTokens output are retained for inspection.

Provenance records the SkinTokens repository revision, checkpoint identifier/hash, runtime version, seed/settings, source artifact/hash, normalization artifact/hash, and deterministic Blender steps. It excludes hostnames, absolute paths, credentials, and environment-specific directories.

### Structural rigging and deformation QA

Keep separate fields for:

- `model_generation_status`
- `mesh_normalization_status`
- `material_status`
- `animation_readiness_status`
- `rigging_status`
- `deformation_status`
- `unity_generic_import_status`
- `animation_playback_status`

Successful provider execution means a rig exists; it does not mean deformation passes. A structural report validates hierarchy, bind poses, per-vertex weight sums, unweighted vertices, maximum influences, and component-to-bone coverage. Prototype default is four influences per vertex. Non-humanoid rigs remain outside this qualification.

Generate a fixed pose suite from a provider-derived humanoid semantic bone map: neutral, arms raised, shoulder rotation, elbow bend, crouch, leg lift, and a full-body locomotion pose. Save individual PNGs, one contact sheet, per-pose vertex displacement, source rig hash, Blender/provider versions, and pose parameters. If semantic mapping is ambiguous or required bones are missing, fail QA with an actionable report rather than guessing. Metrics make the run repeatable; they do not replace human visual review.

All rig and pose artifacts remain candidates. Human approval updates deformation status; provider success alone cannot mark it approved.

### Unity Generic validation

After a rig is explicitly approved, use the existing animation library and Generic Unity setup path. Add a Unity batch/editor validation for this real generated SkinTokens FBX that imports one full-body clip, creates a Generic AnimatorController/prefab, evaluates the clip across its range, and asserts that expected skinned transforms and vertices change while root-motion behavior matches clip metadata. Save the import/playback report and representative rendered frames as candidate evidence.

This stage must not set Humanoid mode or claim Avatar validity. Humanoid mapping and cross-character retargeting stay in #15. Unity-generated `.meta` files remain Unity-owned.

## Failure behavior and review gates

- Missing checkout, wrong revision, incompatible runtime, missing checkpoint, or hash mismatch fails preflight before model inference.
- Invalid geometry, missing UVs, failed map rebake, unexpected components, invalid hierarchy/weights, or missing canonical poses leaves the rig unqualified and reports the measured cause.
- Unity Generic import or playback failure is recorded separately and cannot be reported as rigging success.
- Every stage writes to a new candidate path. Existing approved source/final artifacts remain intact on failure.
- Human approval is required for the normalized textured character and for deformation evidence before Unity qualification. Approval cannot be inferred from passing metrics or tests.

## Non-goals

- No automatic model/checkpoint download or changes to the production ComfyUI environment.
- No automatic approval, Humanoid Avatar mapping, reusable animation-library expansion, or cross-character retargeting; those remain #15.
- No AI-generated motion model, non-humanoid rigging, semantic component deletion, or general provider/plugin SDK.
- No claim of commercial suitability while training-data/model provenance remains unresolved. SkinTokens remains opt-in and experimental until that review is complete.

## Acceptance criteria for #14

1. A representative generated humanoid remains traceable to its approved source through normalization, material rebake, rig, pose evidence, Unity import, and playback.
2. Normalization produces a readable component report, usable UVs, and connected PBR maps on the normalized mesh; no object-like concept image is tiled as a substitute for material.
3. SkinTokens runs from an isolated, preflighted runtime without editing or installing into ComfyUI. The same input, revision, checkpoint, settings, and seed are recorded in provenance.
4. The final rig has a valid hierarchy and bind poses, no unweighted character vertices, normalized weights, no more than four influences per vertex in the prototype profile, and no unclassified helper geometry.
5. All canonical deformation poses and a contact sheet are generated deterministically. The results remain pending human review until explicitly approved.
6. The approved rig imports into Unity as Generic and a full-body animation visibly changes the character through a Unity-evaluated clip. The batch report confirms import and playback behavior; no Humanoid claim is made.
7. Unit, Blender integration, provider integration, and opt-in Unity validation tiers are documented. Normal CI requires no H100, model weights, or Unity installation.
8. #14 remains open until the generated candidate receives the required human review. The repository and GitHub status report every failure and any licensing blocker honestly.

## Verification tiers

- **Unit:** configuration/preflight validation; deterministic component and texture metadata; provider result validation; weight/hierarchy checks; canonical pose selection; stage status separation; provenance portability.
- **Blender integration:** synthetic textured humanoid exercises remesh, UV/material rebake, helper classification, SkinTokens-output cleanup, standard poses, and FBX export.
- **External provider integration:** opt-in, uses an already installed isolated SkinTokens runtime and explicitly configured checkpoint. It never runs in normal CI.
- **Unity integration:** opt-in batch/editor import and actual Generic clip evaluation/playback on the SkinTokens candidate. It must report a missing Unity editor/license as blocked, not success.
- **Visual review:** human checks texture coverage, component classification, pose contact sheet, and the rendered Unity playback before approving the candidate.

## Risks

- Voxel remesh changes geometry. Selected-to-active bake may miss details on large silhouette changes; the rebake report and preview must expose misses instead of silently retaining a mislabeled texture.
- SkinTokens uses generic bone names and may emit variable component structures. Semantic pose mapping must fail closed when it cannot identify required joints.
- The successful evaluation required local compatibility changes. A pinned overlay may become stale as upstream changes; preflight must check exact revision before applying it.
- SkinTokens' MIT code/checkpoint labels do not resolve all training-data/commercial-rights concerns. This design keeps it optional and does not bundle model weights.
- A valid Unity import can still look wrong. Playback rendering and human review remain part of qualification.
