# SkinTokens Character Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax tracking. **Goal:** Qualify one generated, textured humanoid through normalized geometry, isolated SkinTokens rigging, repeatable deformation review, and real Unity Generic animation playback. **Architecture:** Extend SlopForge's existing character rigging and artifact seams. Blender performs deterministic normalization, texture transfer, structural checks, pose evidence, and FBX export; SkinTokens remains an optional isolated external runtime; Unity Generic playback is a separately reported gate. **Tech Stack:** Python 3.11+, Blender Python API, existing YAML/JSON manifests, Unity Editor batch mode, unittest/pytest already in the repository. **Spec:** `docs/archive/implementation/specs/2026-10-04-skin-tokens-character-pipeline-design.md`

## Global Constraints

- Preserve source and approved artifacts; every processing stage writes a new candidate.
- Keep SkinTokens optional and isolated from ComfyUI; never install dependencies or download checkpoints automatically.
- Keep machine-local executable, checkout, and checkpoint paths out of portable provenance.
- Never infer human approval from provider completion, metrics, renders, or Unity import.
- Keep mesh readiness, material readiness, structural rigging, deformation, Unity Generic import, and animation playback as distinct results.
- Keep Humanoid mapping and cross-character retargeting in #15.
- Do not commit or push; the workspace already contains user changes.

## Review Focus

- A source mesh with multiple objects or disconnected components remains fully classified and is never silently discarded; cover in the normalization Blender integration test.
- A remesh with missing UVs or no source material cannot be reported textured; cover in texture-rebake validation tests.
- SkinTokens absent, revision-mismatched, checkpoint-missing, or returning malformed output fails before candidate artifacts are registered; cover in provider preflight/result tests.
- A rig with helper geometry, unweighted vertices, invalid bind poses, or more than four influences is structurally rejected or explicitly classified; cover in structural report tests.
- Unity can import a Generic FBX without its animation visibly deforming the mesh; cover in the opt-in Unity playback test by evaluating a full-body clip and checking skinned vertex motion.

## File Map

- `slopforge/character_rigging.py`: existing provider selection and candidate artifact recorder; add SkinTokens dispatch and stage status data.
- `slopforge/character_normalization.py`: project paths, approvals, subprocess invocation, and normalization report recording.
- `blender/normalize_character.py`: inspect components, voxel normalize, create UVs, rebake source PBR maps, classify helper objects, and export a new textured candidate.
- `blender/skintokens_character.py`: clean SkinTokens output, transfer material from normalized source, validate weights, make canonical poses, render evidence, and export FBX/report.
- `slopforge/config.py`, `slopforge/doctor.py`: opt-in local runtime settings and read-only preflight.
- `processing/skintokens_compat.py` and its tests: revision-guarded, versioned compatibility overlay for the isolated checkout only, if the pinned runtime still needs the evaluated SDPA adjustments.
- `slopforge/cli.py`: `character normalize`, `character approve-normalization`, `character approve-deformation`, and `character validate-generic` actions, following existing character command patterns.
- `slopforge/unity_animation.py`: Generic import/playback validation for the reviewed rig and a full-body diagnostic clip; do not alter the Humanoid path.
- Tests: extend `tests/test_character_rigging.py`, `tests/test_rigify_provider.py`, and `tests/test_rigify_blender_integration.py`; add `tests/test_character_normalization.py`, `tests/test_skintokens_provider.py`, `tests/test_skintokens_blender_integration.py`, and opt-in `tests/test_skintokens_unity_integration.py`.
- `docs/CHARACTER-RIGGING.md`, `docs/CHARACTER-ANIMATIONS.md`: document actual commands, configuration, gates, and verified evidence only.

## Interfaces

- `normalize_character(project_root, config, manifest, character_selector, *, source_output="model") -> dict`: creates a pending normalized-model artifact and component/material report from a ready, approved model.
- `run_character_rigging(...) -> dict`: dispatches the existing `blender_rigify` provider or configured `skintokens` provider; both return through `record_rigging_result`.
- SkinTokens settings: `asset_pipeline.character_rigging_provider: skintokens` plus `asset_pipeline.tools.skintokens_python`, `skintokens_checkout`, and `skintokens_checkpoint`. Values are local paths and are never copied into manifests.
- SkinTokens result: existing provider provenance plus repository revision, checkpoint SHA-256, and compatibility-overlay version/hash when used; project-relative rig FBX, pose PNGs, structural report, and separate deformation status.
- `validate_generic_character_playback(...) -> dict`: consumes an approved rig and an explicit full-body clip, records Generic import/playback evidence, and never sets or reports a Humanoid Avatar.

---

### Task 1: Normalize and texture the approved character mesh

**Files:**
- Create: `slopforge/character_normalization.py`
- Create: `blender/normalize_character.py`
- Modify: `slopforge/cli.py`
- Modify: `slopforge/config.py` only if a character-specific voxel/face setting is necessary; default to existing character face budget and normalization conventions.
- Test: `tests/test_character_normalization.py`
- Test: `tests/test_character_readiness_blender.py`

**Interfaces:**
- Consumes: `_character_asset`, `_project_file`/contained-path rules, `register_artifact`, Blender executable discovery, and the ready+approved source requirement in `slopforge/character_readiness.py`.
- Produces: `normalize_character(...)` above and a report containing source hash, normalized hash, each source object/component's counts/material assignments, output component mapping, UV status, per-channel bake status, and warnings.

- [ ] **Step 1: Add failing tests for project boundaries and source approval.** In `tests/test_character_normalization.py`, construct a temporary project/manifest with one approved GLB and assert the function rejects an unapproved model, a non-model output, a missing source, an output-root traversal, and an existing candidate output without modifying the source.
- [ ] **Step 2: Run the focused tests and verify the missing normalization entry point is the failure.** Run `pytest tests/test_character_normalization.py -q`.
- [ ] **Step 3: Implement the thin Python orchestration and CLI action.** Mirror `run_character_readiness`: resolve the approved source, allocate a project-local `Characters/<name>/Normalization/` candidate, call Blender with a temporary JSON request/report, register only a successful output as pending review, and clean only newly created outputs on failure. Add `character normalize` and `character approve-normalization`; approval must reject failed texture/geometry reports.
- [ ] **Step 4: Add a Blender synthetic fixture with multiple components and a packed base-color image.** Run `normalize_character.py` against it and assert the source file hash is unchanged, all character components are accounted for, normalized geometry has UVs, the baked image is non-empty and connected to the exported material, and report channel statuses match supplied/missing maps.
- [ ] **Step 5: Implement normalization in Blender.** Import without joining away the source classification, record object/component counts and assignments, apply transforms, voxel remesh the character geometry, remove only degenerate/isolated geometry, create a UV atlas, and use Cycles selected-to-active baking from source geometry/materials to the normalized active mesh. Export a new GLB and texture images. Fail the stage if a supplied source channel cannot be baked; report absent optional channels explicitly. Do not use a concept image as a material fallback.
- [ ] **Step 6: Run the focused pure-Python and Blender integration tests.** Run `pytest tests/test_character_normalization.py tests/test_character_readiness_blender.py -q`; Blender-dependent tests may skip only when Blender is unavailable.
- [ ] **Step 7: Verify generated normalization command help and approval behavior.** Run `slopforge character --help` and add a test that the normalized source remains pending until explicit approval.

### Task 2: Add an isolated, preflighted SkinTokens provider

**Files:**
- Modify: `slopforge/character_rigging.py`
- Modify: `slopforge/config.py`
- Modify: `slopforge/doctor.py`
- Modify: `slopforge/cli.py`
- Create: `processing/skintokens_compat.py` only if the audited pinned runtime still needs the known SDPA compatibility changes.
- Create: `tests/test_skintokens_provider.py`
- Create: `tests/test_skintokens_compat.py` only if the overlay is needed.
- Modify: `tests/test_character_rigging.py`

**Interfaces:**
- Consumes: approved normalized output from Task 1, current `run_character_rigging` dispatch, `record_rigging_result`, and the reviewed SkinTokens source/checkpoint details in `docs/research/unirig-rigging-provider-audit.md`.
- Produces: `skintokens_preflight(config, project_root) -> dict` and an isolated runner that returns the existing rigging result shape plus repository revision/checkpoint hash. If required, `prepare_skintokens_runtime(config, project_root) -> dict` applies the pinned compatibility overlay only after explicit user invocation. The runner must not install, patch, or execute inside ComfyUI.

- [ ] **Step 1: Add tests for runtime settings and preflight.** Cover empty settings, non-executable Python, checkout missing `.git`, unexpected revision, missing checkpoint, checkpoint hash calculation, and valid pinned checkout. Assert reports contain no absolute paths.
- [ ] **Step 2: Run the focused tests and verify they fail before implementation.** Run `pytest tests/test_skintokens_provider.py -q`.
- [ ] **Step 3: Define the local settings in project defaults.** Add the three `tools.skintokens_*` paths as unset values; do not add environment-specific endpoints, auto-install behavior, or checkpoint URLs.
- [ ] **Step 4: Implement read-only doctor/preflight.** Check executable, pinned checkout revision, expected upstream entry point and checkpoint file; return actionable states for unavailable/unverified values. Doctor must not mutate the checkout or trigger model loading.
- [ ] **Step 5: Add a revision-guarded compatibility overlay only if the pinned upstream code still requires it.** Store the exact expected revision and patch digest in SlopForge; test that matching checkouts receive the same patch, repeated preparation is idempotent, and any other revision is rejected without edits. Expose preparation as an explicit command; inference and doctor remain read-only.
- [ ] **Step 6: Implement provider invocation using a temporary request/result file.** Verify the pinned SkinTokens CLI argument contract from the audited upstream `demo.py`; pass only explicit source/output/checkpoint/seed settings; run its configured interpreter with `cwd` set to the isolated checkout; keep stdout/stderr in a project log; fail on missing/empty/malformed output. Do not edit upstream files at runtime.
- [ ] **Step 7: Dispatch `skintokens` from `run_character_rigging` and preserve the existing recorder contract.** Record provider version/revision, checkpoint identifier/hash, and compatibility overlay identity if applied. Extend the recorder's explicit provenance allowlist for these portable identifiers while excluding all configured paths. Require the normalized model artifact to be approved before provider execution.
- [ ] **Step 8: Run provider unit tests and inspect serialized manifest data.** Run `pytest tests/test_skintokens_provider.py tests/test_character_rigging.py -q`; assert serialized provenance contains no local path, hostname, or credential.
- [ ] **Step 9: Add an opt-in external smoke guard.** Require an explicit `SLOPFORGE_RUN_SKINTOKENS=1` and complete local settings; exercise one supplied candidate without downloading weights and report unavailable runtime/checkpoint as blocked.

### Task 3: Validate SkinTokens output, transfer materials, and produce repeatable deformation evidence

**Files:**
- Create: `blender/skintokens_character.py`
- Modify: `slopforge/character_rigging.py`
- Modify: `slopforge/cli.py`
- Create: `tests/test_skintokens_blender_integration.py`
- Modify: `tests/test_character_rigging.py`

**Interfaces:**
- Consumes: SkinTokens output plus normalized textured input from Tasks 1–2; existing `RECOMMENDED_POSES`, rig result recorder, and artifact approval model.
- Produces: report fields for structural rig status, material transfer status, classified helper objects, component counts, maximum influences, unweighted vertices, weight-sum range, bind-pose count, per-pose displacement, pose render paths, and contact sheet. Deformation remains `needs_review` until a new explicit approval action.

- [ ] **Step 1: Add tests for structural-result classification.** Use small report dictionaries to assert missing armature, helper objects, unweighted vertices, weight sum outside tolerance, missing bind pose, and influence count above four each fail structural qualification; valid structure does not imply deformation approval.
- [ ] **Step 2: Run the tests and verify the new result classifier is missing.** Run `pytest tests/test_character_rigging.py -q`.
- [ ] **Step 3: Implement the Blender output cleanup/report stage.** Import the provider result, record every object and component, remove only the known unskinned helper when positively identified, preserve all skinned character components, and fail on any other unclassified geometry. Transfer/rebake each supplied source PBR map from the approved normalized mesh onto the SkinTokens mesh; record per-channel coverage and fail when base color is not transferred.
- [ ] **Step 4: Generate canonical poses from an explicit SkinTokens semantic bone mapping.** Render neutral, T-pose, raised arms, shoulder rotation, elbow bend, crouch, and leg lift from fixed cameras/settings. If a required semantic joint is ambiguous or absent, produce a failed report instead of selecting a guessed bone. Save individual PNGs, a contact sheet, pose parameters, mesh/rigger hashes, structural metrics, and deterministic Blender version.
- [ ] **Step 5: Add `character approve-deformation`.** Require a passing structural report, all canonical images, a contact sheet, and a human confirmation flag; set only deformation approval/status and keep artifacts as reviewable candidates until the existing promote/approve flow is used.
- [ ] **Step 6: Add a Blender integration fixture.** Create a small textured humanoid with several mesh components and one unskinned helper; pass a synthetic SkinTokens-shaped rig through cleanup; assert helper classification, component accounting, rebaked material assignment, normalized weights, each fixed pose's non-zero measured motion, and stable contact-sheet output dimensions.
- [ ] **Step 7: Run focused unit and Blender tests.** Run `pytest tests/test_character_rigging.py tests/test_skintokens_blender_integration.py -q`.

### Task 4: Prove Unity Generic animation playback on the approved SkinTokens rig

**Files:**
- Modify: `slopforge/unity_animation.py`
- Modify: `slopforge/cli.py`
- Create: `tests/test_skintokens_unity_integration.py`
- Modify: `tests/test_animation.py`
- Modify: `tests/test_rigify_blender_integration.py` only to share existing opt-in Unity test utilities if that reduces duplication.

**Interfaces:**
- Consumes: a human-approved rig and deformation report from Task 3, plus an explicit full-body animation FBX with loop/root-motion metadata.
- Produces: `validate_generic_character_playback(...) -> dict`, a Unity batch report proving Generic importer selection, skinned renderer/bones/bind poses, clip discovery, Animator evaluation at multiple normalized times, observed vertex/bone motion, and root-motion setting. Records Unity state separately and never changes rig/deformation approvals.

- [ ] **Step 1: Add tests for gating and report validation.** Assert validation rejects pending/unapproved rig or deformation, missing clip, Humanoid mode, Unity failure, and successful import with zero observed vertex motion; assert all failures leave rig and deformation approval unchanged.
- [ ] **Step 2: Run the focused unit tests and verify the validator is not implemented.** Run `pytest tests/test_animation.py -q`.
- [ ] **Step 3: Add a deterministic full-body diagnostic walk clip generator.** Use the rig's explicit semantic bone map in Blender, key a short looping in-place walk at a fixed frame rate, export an animation FBX, and record loop/root-motion metadata. Do not depend on or expand the #15 animation library.
- [ ] **Step 4: Implement a Unity Editor batch validation script.** Set the model and clip importers to Generic, import the rig, construct an Animator and temporary validation scene, evaluate the clip at start/mid/end, sample the skinned mesh before and during playback, and fail unless expected bones and skinned vertices move. Capture a small set of rendered evidence frames and a JSON report. Do not silently change to Humanoid or accept an import-only pass.
- [ ] **Step 5: Add `character validate-generic` and persist its independent status/evidence.** Require explicit approved inputs, register evidence as candidates, and set `unity_generic_import_status` / `animation_playback_status` separately from `unity_avatar_status`.
- [ ] **Step 6: Add an opt-in Unity integration test.** Gate on `SLOPFORGE_RUN_SKINTOKENS_UNITY=1`; use the already configured Unity project/runtime and approved SkinTokens candidate; verify actual full-body clip evaluation and deformation. Missing Unity installation/license is reported as blocked, never skipped as a pass.
- [ ] **Step 7: Run unit tests and the available Blender/Unity integration tiers.** Run `pytest tests/test_animation.py tests/test_skintokens_unity_integration.py -q`; run the external tiers only when their explicit opt-in variables and dependencies are present.

### Task 5: Document the qualified workflow and reconcile #14 evidence

**Files:**
- Modify: `docs/CHARACTER-RIGGING.md`
- Modify: `docs/CHARACTER-ANIMATIONS.md`
- Modify: `docs/research/unirig-rigging-provider-audit.md`
- Test: `tests/test_character_normalization.py`
- Test: `tests/test_skintokens_provider.py`
- Test: `tests/test_skintokens_blender_integration.py`
- Test: `tests/test_skintokens_unity_integration.py`

**Interfaces:**
- Consumes: commands, statuses, limitations, and evidence actually produced by Tasks 1–4.
- Produces: current user instructions and an honest issue #14 evidence update; do not close #14 unless a generated candidate passes every gate and receives the required human review.

- [ ] **Step 1: Update rigging documentation with normalization, configuration, preflight, review, and failure commands.** Include local setup only; state that the provider is opt-in and no models are downloaded.
- [ ] **Step 2: Document each qualification state separately.** Distinguish declared/preflight/inference/structural/deformation/Generic import/playback; distinguish all successful code paths from externally blocked ones.
- [ ] **Step 3: Add exact test-tier commands and artifact locations.** State which tests require Blender, SkinTokens/checkpoint, Unity, or a human review.
- [ ] **Step 4: Update the provider audit with measured real-candidate outcomes only.** Do not replace the known failed/unapproved candidate evidence until a new source actually passes; do not claim commercial clearance from the repository license alone.
- [ ] **Step 5: Run the full configured normal suite, formatting/lint/type checks that exist, CLI help smoke, Blender integration when available, and explicit external provider/Unity tiers when available.** Record every unavailable tool as blocked with its concrete reason.
- [ ] **Step 6: Review `git diff` and status.** Confirm pre-existing user modifications remain present, no large model/checkpoint or machine-specific endpoint/path entered tracked project files, and candidate artifacts remain unapproved unless the user actually reviews and approves them.

## Self-review

- Spec coverage: normalization, texture rebaking, provider preflight/invocation/provenance, component/helper classification, structural rig checks, canonical deformation poses, human approval, Unity Generic import and actual animation playback, documentation, tiered verification, no auto-download, no ComfyUI mutation, and #15 separation each have an owning task.
- Placeholder scan: no TODO/TBD steps; external SkinTokens command arguments must be taken from the audited pinned upstream entry point, not guessed.
- Type consistency: normalization and playback function signatures are defined above; provider output reuses the existing `record_rigging_result` mapping and explicitly extends its provenance allowlist for portable hashes/revisions.
- Review Focus coverage: source/component, material/UV, provider availability/malformed result, rig integrity, and import-without-motion each have tests in the owning task.
- Execution constraint: the user asked to preserve uncommitted work and avoid commits/pushes, so no plan step stages or commits files despite the generic plan template.
