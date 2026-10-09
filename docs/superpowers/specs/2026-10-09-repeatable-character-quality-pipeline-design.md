# Repeatable Character Quality Pipeline

## Status

Draft for review. This design follows the staged, fail-closed pipeline approach approved on 2026-10-09. Implementation and selection of numeric deformation thresholds remain pending review of this document.

## Goal

Make SlopForge's generated humanoid assets reproducible and safe to promote into a game project. Generation remains probabilistic; the system guarantees that an asset is called ready or copied to the game only after it meets its configured visual, structural, material, deformation, and Unity checks. Failed candidates remain inspectable and can be retried from the failing stage.

The current Basalt Warden is the first end-to-end proof case. It must exercise the same pipeline that future characters use, with its source and approved outputs preserved.

## Current system and observed gaps

- SlopForge already separates model generation, material candidates, character readiness, rigging, deformation approval, and Unity validation in its CLI and manifest.
- The H100 Pixal3D workflow is the strongest tested route for this character, but its source mesh still has 10 disconnected components and 265 non-manifold edges after welding. Its face is under-detailed from the available full-body image.
- The recent Rigify experiment fitted a metarig to overall bounds, bypassed the topology rejection for diagnosis, and produced up to 15 bone influences on a vertex. Its arm poses collapse. It is not a shippable rig.
- A separate Basalt candidate has better deformation evidence with SkinTokens, but it is a different source mesh and does not prove this current model will rig well.
- Existing readiness checks establish mesh structure and material links, not face quality, useful material coverage, anatomical joint placement, deformation quality, or game playback.
- The repository currently has in-progress quality/workflow changes in the shared working tree. This design does not replace or discard them.

## Approaches considered

### 1. Keep the current flow and add more candidate retries

This is a small change and improves the odds of finding a good raw output. It does not detect bad joints, texture coverage, or deformation, so a plausible-looking but unusable candidate can still pass too far down the pipeline. Rejected.

### 2. Use a fixed character template for every generated model

This can make skeletons and weights consistent, but it restricts body shape, clothing, and proportions, and still needs robust surface fitting. It is useful as a controlled rigging benchmark, not as the production model-generation strategy. Defer.

### 3. Use staged candidates with evidence-backed, fail-closed gates — recommended

Retain generative freedom but qualify every stage independently. Record exact inputs and tool identities; compare candidates using consistent renders and reports; retry or stop at the failing stage; require human review for visual qualities that metrics cannot establish. Only the final qualified candidate can be promoted. The Warden and a small varied regression set exercise the complete flow.

## Design

### 1. Stage contract and candidate state

Keep the existing manifest/artifact model and extend it only where required. Each run moves through these independently recorded stages:

1. **Brief and concept** — the character brief, intended use, style, silhouette, pose, and required visible details are explicit. A face-quality target requires adequate face evidence, such as a close reference or an intentionally stylized low-detail target.
2. **Geometry** — raw output is retained. Deterministic inspection records bounds, scale, components, open/non-manifold edges, degenerate geometry, thin features, UVs, and preview renders from front, side, rear, and three-quarter views. Any preparation/remesh output is a separate derivative and must be compared with the raw source before acceptance.
3. **Materials** — geometry is held fixed while material candidates are generated. Required PBR maps, dimensions, non-placeholder status, file hashes, UV coverage, and neutral/multi-light previews are checked independently. Missing detail in geometry or reference imagery is not treated as a texture-resolution problem.
4. **Animation readiness** — approved geometry is checked for pose, orientation, scale, limb separation, and joint visibility. A structurally passing mesh still requires visual review before rigging.
5. **Rig and weights** — a selected provider produces a candidate rig. Validate expected humanoid hierarchy, bind pose, bone coverage, weight sums, unweighted vertices, maximum influences, component assignments, and source-to-rig lineage. The production profile defaults to no more than four influences per vertex; helper geometry is classified and reported, never silently discarded.
6. **Deformation** — evaluate a fixed pose suite: neutral/rest, raised arms, shoulder rotation, elbow bend, crouch, leg lift, and a short locomotion sequence. Save per-pose renders, a contact sheet, pose parameters, source hashes, and measurements for joint regions and outlier vertex movement. Numeric metrics can reject gross failures; they cannot approve a visually bad result.
7. **Unity** — import the exact FBX into the pinned Unity version, validate a Humanoid Avatar, evaluate a diagnostic clip through Unity's Animator, and record import/playback results and representative rendered evidence.
8. **Promotion** — only a candidate passing all configured automated checks and required human reviews may replace or enter the project's production asset path. Every previous approved output remains intact if a stage fails.

Every stage has `pending`, `running`, `passed`, `needs_review`, or `failed` state with an explicit reason. Missing reports, unknown required tool identities, changed source hashes, or incomplete evidence cannot be interpreted as a pass. Retry resumes from the failed stage unless its inputs changed; input changes invalidate downstream evidence by hash.

### 2. Quality profiles and reproducibility

Define a versioned character quality profile for each target (initially game-ready humanoid). It specifies scale convention, triangle budget, map contract, accepted component/topology limits, required evidence, weight limits, required Unity checks, and provider versions. Thresholds are calibrated on the regression set rather than invented from one Warden result.

For every candidate, record portable provenance: source and reference hashes, exact resolved ComfyUI workflow JSON/hash, workflow requirements, ComfyUI and custom-node revisions, model/checkpoint hashes, seed, effective node inputs, mesh-preparation settings, texture settings, provider/runtime revision and checkpoint hash, Blender version, Unity version, and deterministic processing parameters. Machine-local paths, credentials, and host-specific configuration are excluded. `unknown` is allowed for exploration but blocks final qualification when the profile requires the value.

Production runs use the pinned tested H100 Pixal3D profile unless a benchmark proves another route better for the same target. Final candidates use the configured multi-candidate budget; candidates are compared using the same review views and tests. The system may rank candidates from measured criteria, but a score never substitutes for a required human visual review.

### 3. Rigging provider and weight policy

Keep the existing provider seam. The Warden proof run evaluates the audited SkinTokens route against the exact current source; it does not reuse weights from another Warden mesh. Rigify's bounds-only fit and automatic weights cannot be marked production-qualified for this profile. If the selected provider emits ambiguous joints, invalid components, or weights outside the profile, the run fails with evidence and does not export a promoted rig.

Post-processing may correct semantic bone naming, influence count, normalization, and known helper objects when deterministic rules apply. It must not claim to repair bad anatomy by renaming bones. Joint placement or skin weights requiring visual judgment are corrected on a candidate rig and re-run through the full deformation suite. No global voxel remesh is used as a default rig fix because it can erase garment and facial detail; localized geometry repair is an explicit, reviewed derivative.

The first implementation should use the best provider already audited in the repository, while keeping provider-specific setup isolated from ComfyUI. Provider choice remains configurable and recorded. A provider only becomes the default after passing the same fixed-mesh comparison, structural checks, deformation suite, and Unity validation.

### 4. Face and material detail contract

Image-to-3D stages cannot reliably recreate facial features that occupy too few pixels in their input. Character briefs therefore carry a target face-detail class. The concept review checks face size and visible features; if the target is not met, request a better close reference or regenerate the concept before spending on mesh/rigging. Texture generation must preserve the approved geometry and cannot be used to mask missing eyes, mouth, or facial shape. This gate reports when the current one-image workflow cannot meet a chosen detail target; a multiview/head-specific workflow is a later option, not an implied capability.

Material acceptance checks the actual maps on the accepted mesh under repeatable neutral and varied lighting. A 4096 atlas alone is not a quality pass. Flat placeholder normals, missing channels required by the quality profile, severe seams, visible projection artifacts, and inconsistent material coverage block promotion or require an explicit profile exception.

### 5. Regression and benchmark set

Use the current Warden source as the first regression case, preserving its hash and material. Add a small, rights-reviewed set of varied humanoids (including different body proportions and clothing) and at least one synthetic fixture with known joint locations and deformation expectations. Run deterministic tests on the fixtures at normal CI cost. Live ComfyUI/model inference, SkinTokens weights, Blender end-to-end, and Unity checks are opt-in integration tiers; their exact inputs, tool identities, and reports are saved. No quality regression is accepted based only on unit tests or a single character.

The Warden is considered fixed only when its current selected source passes the complete rig, deformation, and Unity checks. If it cannot pass without destructive geometry change or loss of material quality, report that limitation and require a new geometry candidate rather than disguising the failure with a lower-detail remesh.

## Failure and approval behavior

- Failed or incomplete stages remain candidates and preserve logs, reports, and previews.
- A changed input hash invalidates all dependent stage approvals and evidence.
- Automatic retry is bounded by the selected tier's candidate budget; exhaustion leaves the asset failed/needs-review with a concrete next action.
- Visual appearance, texture fidelity, component intent, pose quality, and deformation remain human-review decisions. The system may recommend acceptance but never approves them automatically.
- No stage writes over an approved output until the complete candidate passes and the user or project owner approves promotion.

## Scope

Included: the reusable humanoid character pipeline from concept through Unity validation; stage-specific provenance and retries; a quality profile; rig/deformation qualification; repeatable regression fixtures; Warden as the first proof case; documentation and commands that communicate status and the failing criterion.

Not included: guaranteeing every raw AI result is good; automatic approval; general-purpose non-humanoid rigging; a mandatory custom rigging model download; facial sculpting or animation authoring; third-party animation-library retargeting; replacing ComfyUI; automatic changes to a live ComfyUI installation; or changing other existing assets as part of Warden repair.

## Acceptance criteria

1. A character's brief, source image(s), exact generation and texture settings, tool/model identities, and outputs are traceable by hash from concept to Unity asset.
2. Each stage has independent status, report, reproducible previews, and a clear retry/failure reason; changed inputs invalidate downstream approval.
3. A structural readiness pass cannot be mistaken for material, face, deformation, or Unity quality approval.
4. Material-only iteration reuses the same approved geometry; texture maps are independently inspected and required channels cannot be satisfied by silent placeholders.
5. Production rig candidates have valid hierarchy/bind poses, complete normalized weights, no more than four influences per vertex, and classified mesh components.
6. The fixed deformation suite catches missing controls, unchanged expected joints, extreme outlier movement, and invalid weights. Pose images remain required evidence for visual review.
7. The exact FBX passes a Unity Humanoid import and diagnostic Animator playback check before the candidate is described as game-ready.
8. The current Warden either passes these stages or is explicitly blocked with a measured explanation; the original candidate and any approved project output remain unchanged on failure.
9. Normal CI uses synthetic/fixture inputs and needs no GPU, model weights, external provider, or Unity license. Expensive integration checks are opt-in and report missing dependencies as unavailable, never as passed.
10. At least two varied, rights-reviewed humanoid cases pass the same calibrated profile before it is called repeatable beyond the Warden.

## Risks and limits

- Generation is stochastic; this design makes promotion dependable, not every raw sample identical.
- Visual thresholds are subjective and require human review. Early profile thresholds need calibration on more than the Warden.
- SkinTokens has useful comparative evidence but its installation, checkpoint/data rights, and behavior on the current high-detail source still require validation.
- Topology repair or remeshing can improve skinning while reducing silhouette, clothing, UV, or texture quality; every such change must be compared against the source.
- Pinned nodes and checkpoints improve reproducibility but can make updates slower; changing them requires rerunning the regression set.
- A successful Unity Humanoid import and diagnostic motion test do not prove all third-party animations retarget correctly.
