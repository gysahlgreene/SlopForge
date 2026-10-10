# M0 Package 2: Fingerprint-Based Invalidation and Safe Prop Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement plan task-by-task. Steps use checkbox (`- [ ]`) syntax tracking progress.
>
> **Goal:** Reuse prop work only when its recorded semantic inputs and persisted artifacts prove compatibility, and resume at the earliest incomplete or stale stage.
>
> **Architecture:** Add a small prop-specific reuse policy over Package 1's ordered stage records and artifact references. Keep prior stage outcomes immutable; append reuse decisions and record reuse as a new execution stage linked to the original content-addressed artifacts. Apply the policy at prop approval, recipe resume for model children, and the existing processed-mesh reuse caller used by `retexture`.
>
> **Tech Stack:** Python, existing schema-v4 JSON manifest, `unittest`/pytest fixtures and mocks, existing ComfyUI/Blender boundaries.
>
> **Spec:** `docs/CORE-PIPELINE-AUDIT.md`, Package 2; contracts in `docs/PRODUCT_CONTRACT.md`, `docs/PIPELINE_CONTRACT.md`, and `docs/QUALITY_CONTRACT.md`.

## Global Constraints

- Limit behavior to the existing prop route and its recipe/model callers; do not add a generic DAG scheduler, cache, workflow engine, global retry policy, or qualification behavior.
- Preserve Package 1 execution identity, ordered stage journal, project-relative artifact references, hashes, and explicit unknown provenance.
- Artifact paths locate files; recorded SHA-256 plus artifact IDs and derivation references establish identity.
- Keep stage outcome history immutable. A previous `succeeded` remains historical truth; record whether its output is currently reusable in a separate append-only decision.
- Do not claim visual, structural, readiness, or runtime qualification from a reuse decision.
- Use deterministic fixtures and mocks. No live inference is required.

## Review Focus

- The same bytes and semantic stage inputs remain reusable after manifest reload; test in Task 1.
- A changed selected concept or geometry workflow/settings cannot reuse its mesh descendants; test in Task 2.
- Material-only settings changes retain a compatible processed mesh but rebuild material and later outputs; test in Task 2.
- Missing, replaced, moved, duplicate-named, or hash-mismatched artifacts cannot pass on path/status; tests in Tasks 1 and 4.
- Unknown legacy lineage and interrupted/failed stages preserve valid upstream work without turning old success into current success; tests in Tasks 2 and 3.

## Files and Responsibilities

- Create `slopforge/pipelines/reuse.py`: prop stage compatibility, artifact integrity, and earliest stale boundary policy. This is a fixed prop-stage policy, not a caller-defined dependency engine.
- Modify `slopforge/manifest.py`: append a durable reuse-decision record without changing the recorded stage result.
- Modify `slopforge/pipelines/model.py`: apply stage-local checks while approving/resuming props; require proof before `retexture` passes a processed mesh to Blender as reusable.
- Modify `slopforge/backends/blender.py`: preserve its current subprocess interface; its caller must pass `reuse_stage_mesh=True` only after the prop policy proves source and settings identity. No independent path-existence reuse remains.
- Modify `slopforge/recipes.py`: validate prop/model child evidence before treating completed/approved as reusable; leave non-prop recipe handlers and their existing semantics out of this package.
- Modify `slopforge/cli.py`: add an explicit `--resume` option to model `approve`, using its candidate argument and the latest compatible interrupted execution; reject a mismatch with an actionable error.
- Create `tests/test_prop_reuse.py`: policy and end-to-end deterministic invalidation/resume cases.
- Modify `tests/test_mesh_pbr.py`, `tests/test_prop_lineage.py`, and `tests/test_recipes.py`: pin caller behavior and regressions at existing fixtures.
- Modify `docs/ASSET-OUTPUTS.md` and `docs/CORE-PIPELINE-AUDIT.md`: document reuse evidence, stale-decision history, limitations, and Package 2 exit status after implementation evidence exists.

## Invalidation Semantics

The stage names and output ownership below follow the current prop journal described in `docs/ASSET-OUTPUTS.md` and `slopforge/pipelines/model.py`. A matching stage can be reused only if its semantic input references/settings match the requested stage and every required output exists at its recorded path with the recorded hash. Its output `derived_from` IDs and hashes must agree with the stage inputs. A same-named file elsewhere is not a match. Relocation is unsupported in this package; a moved file is missing until regenerated at the recorded project-relative path.

| Stage/output | Compatibility evidence | Invalidated by | Does not invalidate | Descendants to recompute |
| --- | --- | --- | --- | --- |
| `concept_generation` candidate image | Candidate execution identity, prompt/variation/seed/workflow identity, candidate artifact ID/hash, image file hash | Brief/prompt/style/reference/workflow/seed change or content mismatch | Mesh/material settings | Candidate selection and all downstream stages that consume that candidate; other concept candidates remain intact |
| Selected concept and `conditioning_preparation` images | Selected candidate artifact ID/hash plus conditioning strategy/tool settings and both output hashes | Selected concept bytes/selection, conditioning route or relevant preparation settings | Mesh settings and material-only settings | Mesh workflow and all its descendants |
| `mesh_workflow_execution` and worker boundaries `mesh_raw_acquisition`, `mesh_preparation`, `mesh_output_acquisition` | Exact concept/conditioning refs, effective workflow identity/bindings, seed, generation settings and each output hash; compare only recorded facts available to the same execution | Concept/conditioning change, model workflow/effective bindings/profile/seed/generation settings change, source mesh mismatch, or relevant known backend identity change | Material prompt/settings, material scale, preview/export settings | Geometry change invalidates raw/prepared/final mesh, materials/maps, assembly/previews, publication |
| `material_generation` and `material_map_acquisition` | Exact mesh and concept refs (or mesh-PBR texture refs), workflow identity/seed/prompt, material-generation or map settings, output hashes | Mesh/concept source change, material workflow/prompt/seed/settings change, map content mismatch | Geometry-generation and Blender geometry-preparation settings | Material change invalidates maps, assembly/previews/export, final publication; mesh remains reusable |
| `material_assembly_export` | Exact processed mesh and map refs plus face budget, UV/scale/Blender processing settings; hashes for FBX, blend, validation, and each preview | Any assembly input or processing setting/output integrity change | Concept/material generation inputs if their consumed artifact refs remain identical | Rebuild assembly outputs, then publication |
| `final_publication` | Selected material candidate refs and published file hashes, including Unity material and exported maps/model | Candidate selection/content, publication inputs/settings, missing or changed published file | Preview validity where publication does not consume previews | Republish only; do not regenerate geometry/materials |

When a preview is missing or corrupt while the candidate mesh/maps remain valid, rerun `material_assembly_export` to recreate the owned assembly outputs; do not rerun inference. When a final published asset remains valid but a candidate preview is missing, preserve publication and rerun only candidate assembly. When provenance needed for a cross-execution comparison is unknown or absent, do not infer a match: recompute from the earliest affected stage while retaining earlier artifacts whose identity is independently proven. A material-only change can reuse the exact mesh artifact even if unobservable provider weight/node revisions remain `unavailable`; unknown facts remain recorded limits and cannot be treated as evidence that a changed backend is the same backend.

## Task 1: Add the prop reuse and integrity policy

**Files:**
- Create: `slopforge/pipelines/reuse.py`
- Modify: `slopforge/manifest.py`
- Create: `tests/test_prop_reuse.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- `artifact_integrity(project_root: Path, reference: dict) -> tuple[bool, str | None]`: checks the recorded project-relative file exists, is readable, and hashes to `reference["sha256"]`; it never searches by basename.
- `stage_reuse_decision(project_root: Path, stage: dict, *, inputs: list[dict], settings: dict) -> dict`: returns `{"reusable": bool, "reasons": list[str]}` after matching stage name, ordered input artifact IDs/hashes, exact settings, output integrity, and output derivation links. `running`, `pending`, or `failed` stages are not reusable.
- `earliest_stale_stage(project_root: Path, stages: list[dict], requested: dict[str, tuple[list[dict], dict]]) -> str | None`: walks the fixed Package 1 prop stage order, with the existing mesh-PBR versus swatch branches, and returns the first absent/incomplete/incompatible stage. It does not mutate the manifest.
- `record_reuse_decision(execution: dict, stage_name: str, stage_attempt: int | None, requested_identity_sha256: str, decision: dict) -> dict` in `manifest.py`: appends a timestamped decision containing the prior stage/attempt, requested identity digest, reusable flag, and reasons. It leaves `status`, timestamps, inputs, outputs, and error of the prior stage untouched.

- [ ] **Step 1: Write failing policy tests**

Add `test_identical_semantic_inputs_and_intact_artifact_are_reusable`, `test_changed_input_or_settings_is_stale`, `test_missing_or_hash_mismatched_output_is_stale`, `test_same_basename_different_content_is_not_substituted`, `test_nonterminal_stage_is_not_reusable`, and `test_reuse_decision_appends_without_rewriting_success_history`. Use temporary files and manifest-shaped dicts; assert reasons identify missing, hash mismatch, lineage mismatch, or semantic mismatch.

- [ ] **Step 2: Run the focused tests and confirm expected failures**

Run: `python -m pytest tests/test_prop_reuse.py tests/test_manifest.py -q`

Expected: FAIL because the policy and append-only manifest helper do not exist.

- [ ] **Step 3: Implement the minimal fixed-stage policy**

Create only the interfaces above. Use `provenance.file_sha256`; compare artifact IDs/hashes and settings directly. Encode the stage ordering/branch points from the table in this module; do not introduce an extensible graph API.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_prop_reuse.py tests/test_manifest.py -q`

Expected: PASS, including proof that the original `succeeded` record is unchanged after a stale decision is appended.

- [ ] **Step 5: Commit**

```bash
git add slopforge/pipelines/reuse.py slopforge/manifest.py tests/test_prop_reuse.py tests/test_manifest.py
git commit -m "feat: add prop artifact reuse policy"
```

## Task 2: Apply fingerprints to prop approval, resume, and stage invalidation

**Files:**
- Modify: `slopforge/pipelines/model.py`
- Modify: `slopforge/cli.py`
- Test: `tests/test_prop_reuse.py`
- Test: `tests/test_prop_lineage.py`

**Interfaces:**
- `model.approve(..., resume: bool = False)` and CLI `approve ... --resume`: on resume, use the selected candidate and persisted semantic identity/seeds from the latest matching incomplete execution; compare current requested stage settings before adopting any prior outputs. If the request differs, fail with the first stale stage and reason. Without `--resume`, preserve explicit fresh-generation behavior.
- Reuse of a prior artifact creates a current execution stage record with the artifact reference preserved and an append-only reuse decision pointing to its original execution/stage. It does not edit prior stage status or create a new artifact hash.
- Current stage input/settings fingerprints must be assembled at the existing boundaries: selected concept/conditioning, model workflow and mesh generation, material workflow/maps, Blender assembly/export, and publication. Existing execution identity is retained as the run summary; a changed material-only request may adopt compatible mesh stages by their stage-local fingerprints.

- [ ] **Step 1: Add failing deterministic invalidation/resume cases**

In `tests/test_prop_reuse.py`, add `test_identical_execution_reuses_completed_outputs`, `test_selected_concept_change_invalidates_mesh_material_and_publication`, `test_material_only_change_reuses_mesh_and_rebuilds_descendants`, `test_geometry_settings_change_invalidates_geometry_and_descendants`, `test_processing_settings_change_invalidates_assembly_only`, `test_missing_preview_rebuilds_assembly_without_inference`, `test_interruption_resumes_at_earliest_incomplete_stage`, `test_failed_stage_retries_without_regenerating_valid_ancestors`, and `test_prior_succeeded_status_does_not_override_fingerprint_mismatch`. Inject failures at existing mockable boundaries; assert call counts, first recomputed stage, persisted decision, and preserved prior history.

- [ ] **Step 2: Run the focused cases and confirm expected failures**

Run: `python -m pytest tests/test_prop_reuse.py tests/test_prop_lineage.py -q`

Expected: FAIL because approval always starts fresh work and has no `--resume` path or stage comparison.

- [ ] **Step 3: Implement stage-local matching at current prop boundaries**

Wire `earliest_stale_stage` and the compatibility decision into `model.approve`. Preserve generated seeds from the interrupted execution on resume. Reuse valid concept/conditioning/mesh/material stages only at the first boundary their inputs and settings prove compatible; otherwise run from that boundary. Keep the existing attempt loop behavior and do not change global retry policy. Make `--resume` reject stale requests before expensive inference and report the earliest required stage.

- [ ] **Step 4: Run the focused cases**

Run: `python -m pytest tests/test_prop_reuse.py tests/test_prop_lineage.py -q`

Expected: PASS; the eight cases above show independent concept, geometry, processing, and material invalidation boundaries, plus interruption and failed-stage recovery.

- [ ] **Step 5: Commit**

```bash
git add slopforge/pipelines/model.py slopforge/cli.py tests/test_prop_reuse.py tests/test_prop_lineage.py
git commit -m "feat: resume props from the earliest stale stage"
```

## Task 3: Guard recipe resume and the `retexture` processed-mesh cache

**Files:**
- Modify: `slopforge/recipes.py`
- Modify: `slopforge/pipelines/model.py`
- Test: `tests/test_recipes.py`
- Test: `tests/test_mesh_pbr.py`
- Test: `tests/test_prop_reuse.py`

**Interfaces:**
- Add `model.prop_child_reuse_decision(project_root: Path, asset: dict, child_stage: dict, child: dict, config: dict) -> dict`; it returns the reuse decision using the child execution's semantic identity, selected candidate and all referenced candidate outputs. `recipes._execute()` must not skip a prop/model child solely because recipe status is `completed` or `approved`; stale prop children become pending for regeneration while preserving their old stage and artifacts. Non-model child behavior remains unchanged.
- Add `model.processed_mesh_reuse_decision(project_root: Path, asset: dict, source_mesh: dict, processing_settings: dict) -> dict`; `retexture` may pass the processed `.blend` to `process_model(..., reuse_stage_mesh=True)` only when the file hash, source mesh artifact ID/hash, and effective Blender processing settings match a succeeded `mesh_preparation`/`material_assembly_export` record. Unknown/legacy lineage returns not reusable and regenerates from the source GLB.

- [ ] **Step 1: Add failing caller regressions**

Add `test_completed_prop_recipe_child_with_changed_inputs_is_regenerated`, `test_recipe_resume_reuses_intact_child_after_manifest_reload`, `test_retexture_reuses_processed_mesh_only_for_matching_source_and_settings`, and `test_retexture_rebuilds_missing_or_unknown_lineage_mesh`. In `tests/test_mesh_pbr.py`, assert `reuse_stage_mesh` is false for stale/missing lineage and true only for exact mesh/settings/hash identity.

- [ ] **Step 2: Run caller tests and confirm expected failures**

Run: `python -m pytest tests/test_recipes.py tests/test_mesh_pbr.py tests/test_prop_reuse.py -q`

Expected: FAIL because recipe resume currently trusts status and `retexture`/its material candidate currently trust file existence.

- [ ] **Step 3: Implement the two caller checks**

Use the Task 1 policy. In recipes, apply it only to prop/model children backed by Package 1 lineage; legacy or unknown lineage is rerun conservatively. In `retexture`, bind the reusable processed mesh to the exact `mesh.glb`/prepared-mesh reference and settings before invoking Blender; absence of proof falls back to processing the raw source GLB.

- [ ] **Step 4: Run the caller tests**

Run: `python -m pytest tests/test_recipes.py tests/test_mesh_pbr.py tests/test_prop_reuse.py -q`

Expected: PASS; intact children and exact processed meshes are reused, changed/missing/unknown inputs rerun from the correct boundary.

- [ ] **Step 5: Commit**

```bash
git add slopforge/recipes.py slopforge/pipelines/model.py tests/test_recipes.py tests/test_mesh_pbr.py tests/test_prop_reuse.py
git commit -m "fix: verify prop recipe and retexture reuse"
```

## Task 4: Complete manifest round-trip matrix and document the limits

**Files:**
- Modify: `tests/test_prop_reuse.py`
- Modify: `tests/test_manifest.py`
- Modify: `docs/ASSET-OUTPUTS.md`
- Modify: `docs/CORE-PIPELINE-AUDIT.md`

**Interfaces:**
- No new runtime interface. Reuse decisions and artifact references must survive `save_manifest()`/`load_manifest()` and produce the same next-stage decision.
- `docs/ASSET-OUTPUTS.md` documents the specific prop invalidation boundaries and the distinction between historical stage success and current reuse validity. The audit's Package 2 exit criteria are marked complete only after all deterministic checks pass; record remaining unknown backend identity and unsupported relocation as limits.

- [ ] **Step 1: Add final deterministic persistence/legacy matrix tests**

Add `test_legacy_unknown_provenance_does_not_reuse_unproven_mesh`, `test_manifest_reload_preserves_same_reuse_decision`, `test_missing_artifact_recomputes_at_owning_stage`, `test_hash_mismatch_recomputes_at_owning_stage`, and `test_duplicate_filename_with_different_content_is_not_reused`. Cover Package 2's 13 required behaviors across the cases in Tasks 1–4: identical inputs; concept change; material-only change; geometry change; processing change; missing artifact; hash mismatch; stale prior `succeeded`; interruption; failed-stage retry; retexture lineage; legacy unknowns; reload stability.

- [ ] **Step 2: Run the full deterministic regression set and confirm expected failures**

Run: `python -m pytest tests/test_prop_reuse.py tests/test_prop_lineage.py tests/test_mesh_pbr.py tests/test_recipes.py tests/test_manifest.py -q`

Expected: FAIL first for the new legacy/reload or duplicate-path assertions if any requested edge remains uncovered; after implementation, no live inference or Unity/Blender installation is needed for this suite.

- [ ] **Step 3: Finish documentation from verified behavior**

Update the two documents with the actual implemented stage behavior, unsupported relocation, conservative legacy handling, unavailable provider-fact limits, and exactly which missing previews trigger assembly rerun versus publication. Do not mark any asset or pipeline qualified.

- [ ] **Step 4: Verify the package and documentation**

Run: `python -m pytest tests/test_prop_reuse.py tests/test_prop_lineage.py tests/test_mesh_pbr.py tests/test_recipes.py tests/test_manifest.py -q`, then `make verify`.

Expected: focused tests and canonical verification PASS; report any existing skips. This verifies deterministic software behavior only, not inference quality or visual/Unity acceptance.

- [ ] **Step 5: Commit**

```bash
git add tests/test_prop_reuse.py tests/test_manifest.py docs/ASSET-OUTPUTS.md docs/CORE-PIPELINE-AUDIT.md
git commit -m "test: cover prop invalidation and safe resume"
```

## Package 2 Audit Exit-Criterion Mapping

| Audit criterion | Owning task/evidence |
| --- | --- |
| Compare Package 1 input/config/output fingerprints; invalidate descendants in order; earliest incomplete/stale stage; reject corrupt/missing outputs | Tasks 1–2: policy and stage matrix tests |
| Preserve superseded evidence and approvals only while artifact hashes still match | Tasks 1–2: append-only reuse decisions; publication hash checks |
| Changing selected concept/workflow/mesh/processing settings restarts at earliest affected stage and preserves valid ancestors | Task 2: concept, geometry, processing, and material-only tests |
| Simulate interruption, missing output, altered cached `.blend`, completed recipe with changed inputs | Tasks 2–3: interruption, artifact integrity, retexture, recipe child tests |
| No reuse from status, candidate count, path, or existence alone | Tasks 1–3: stale-success, recipe, and `.blend` lineage tests |
| Deterministic tests cover each invalidation boundary | Tasks 1–4: `tests/test_prop_reuse.py`, plus caller regression files |

## Self-Review

- Stage order and outputs are grounded in `docs/ASSET-OUTPUTS.md`, `slopforge/pipelines/model.py`, `slopforge/recipes.py`, and the existing `retexture` call into `process_model`; the plan covers generation, selection, mesh attempts, material routes, previews, publication, interruption, and manifest reload.
- Interfaces are consistent: Task 1 owns the policy and append-only journal helper; Tasks 2–3 consume it; Task 4 adds no runtime API.
- Package 3 failure classification/retry redesign, Package 4 readiness/qualification, live inference, providers, non-prop categories, and unrelated features are excluded.
- Runtime/backend provenance that Package 1 cannot observe remains explicitly unknown; a changed known workflow/config invalidates its dependent stages, while unobservable weights/node revisions are reported as a reproducibility limit rather than fabricated identity.

