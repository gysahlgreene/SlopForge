# Character Source Geometry Quality Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Goal:** Make generated character geometry review reproducible and keep source visual approval separate from structural readiness, material approval, and rigging. **Architecture:** Add location-aware diagnostics to the existing Blender inspector, build a hash-linked multi-view character source-review package from project artifacts, then record explicit human approval against the exact reviewed inputs and enforce it before rigging. Keep this a follow-up behind M0–M3 and retain the current backend boundary. **Tech Stack:** Python, argparse, Blender Python/bmesh, existing v4 manifest/artifact lineage, pytest/unittest fixtures. **Spec:** `docs/superpowers/specs/2026-10-16-character-source-quality-design.md`

## Global Constraints

- Do not reorder M0–M4 or claim humanoid qualification from Aster-9 alone.
- Do not submit inference, install models/nodes, or bundle third-party weights.
- Keep unknown dependency/model/node identity and license terms `unknown`.
- Do not use aggressive remeshing, welding, or smoothing to hide topology defects.
- Keep appearance approval human-controlled and tied to exact artifact hashes.
- Do not make deformation, animation, performance, runtime, or pipeline-qualification claims.
- Preserve failed/rejected evidence and invalidate affected decisions without erasing history.

## Review Focus

1. **Topology evidence must not modify source geometry:** pin with a Blender fixture that proves vertex/face counts and coordinates are unchanged while warning locations are reported (Task 1).
2. **Topology samples must still map through seam welding:** pin with duplicate-position UV-seam vertices and known boundary/non-manifold edges; reported positions and counts must agree with the inspector summary (Task 1).
3. **A single-image workflow must not masquerade as multi-view conditioning:** pin with one conditioning reference and missing left/rear design references; the review package remains incomplete and says the conditioning route was single-image (Task 2).
4. **Missing, corrupt, or outside-project review files must fail safely:** pin with missing preview, undecodable image, and `../`/symlink escape paths; no approval is recorded (Task 2).
5. **Approval must go stale when any reviewed artifact changes:** pin with an in-place mesh, concept, preview, or map replacement and assert rigging/readiness refuses the stale decision (Task 3).

## File Map

- `blender/inspect_model.py`: extend the existing read-only inspection report with exact component bounds and topology-defect locations.
- `tests/test_character_readiness_blender.py`: extend the deterministic Blender fixture checks for location evidence and non-mutation.
- `slopforge/character_quality.py`: create, validate, and record a character source-review package from existing project artifacts.
- `slopforge/cli.py`: add `character source-review`, `character classify-source`, `character approve-source`, and `character reject-source` commands.
- `slopforge/review.py`: display approved concept views beside corresponding character renders and expose review status/evidence.
- `slopforge/character_readiness.py` and `slopforge/character_rigging.py`: require a current approved source-quality review before readiness approval can authorize rigging.
- `tests/test_character_quality.py`, `tests/test_character_readiness.py`, `tests/test_character_rigging.py`, and `tests/test_review.py`: cover package generation, stale approval, and review display.
- `docs/CHARACTER-RIGGING.md`, `docs/RECIPES.md`, and `docs/WORKFLOWS.md`: document the review command, exact views/inputs, gate boundaries, and provenance limits.

## Plan-wide Decisions

- A source review uses the existing character asset and its selected ready `model.glb` artifact. The selected source identity is the artifact ID and SHA-256, not its path.
- The user supplies approved project-relative design images using repeated `--concept-view VIEW=PATH` values for `front`, `left`, and `rear`; all three are required for a complete visual decision. Existing conditioning references are recorded separately and do not substitute for the approved comparison set.
- Required evidence includes Blender's `front`, `side`, `rear`, and `three_quarter` outputs, the exact source model, the inspection report, and all linked material maps. The reviewer declares at least one concept-critical region and supplies a concept crop and a close-up rendered from the retained Blender candidate for each region; missing pairs keep the report incomplete.
- The source-review report is immutable per review ID. It records SHA-256 for each input and preview, the conditioning route/references, diagnostic findings, classification history, and explicit missing/unknown facts. It records material map identities but does not approve material appearance. Classifications and decisions are appended as separate records.
- `source_quality_reviews` is an additive character asset field; legacy manifests remain readable, but missing review evidence means `not_recorded` and cannot authorize new rigging.
- The implementation uses only retained artifacts and deterministic fixtures. It does not select or change a generation backend, submit inference, or alter Aster-9 files.

---

### Task 1: Report where topology warnings occur

**Files:**
- Modify: `blender/inspect_model.py`
- Test: `tests/test_character_readiness_blender.py`

**Interfaces:**
- Consumes: existing `inspect(source, face_budget) -> dict` and its `measured` counts.
- Produces: `measured.component_details`, `measured.topology_diagnostics`, with deterministic ordering and positions in Blender world coordinates. Each component entry contains object name, component index, vertex/face counts, and bounds. Each topology entry contains object name, defect kind, source vertex indices, endpoint positions, and midpoint; each degenerate face contains object name, polygon index, source vertex indices, center, and area.

- [ ] Add `test_inspection_reports_topology_locations_without_mutation` and `test_topology_diagnostic_edges_map_to_seam_vertex_indices` in `tests/test_character_readiness_blender.py`. Assert component bounds, one boundary edge, one non-manifold edge, one zero-area face, source indices/world positions, count agreement, and unchanged fixture coordinates.
- [ ] Run the focused Blender integration test and confirm the new location assertions fail because those report fields do not exist.
- [ ] Extend the inspector to emit one diagnostic record per measured defect and per connected component. Use the same weld tolerance as the existing summary counts, map each welded diagnostic edge back to all coincident source vertex indices, and do not write changes to the inspected mesh.
- [ ] Assert the summary counts equal the number of corresponding diagnostic records and that source fixture geometry is byte/coordinate equivalent before and after inspection.
- [ ] Run `BLENDER_BIN=/Applications/Blender.app/Contents/MacOS/Blender .venv/bin/python -m pytest -q tests/test_character_readiness_blender.py`.

### Task 2: Build a hash-linked character source-review package

**Files:**
- Create: `slopforge/character_quality.py`
- Modify: `slopforge/cli.py`
- Modify: `slopforge/review.py`
- Test: `tests/test_character_quality.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: Task 1 `measured.component_details` and `measured.topology_diagnostics`; v4 manifest artifact references; selected character `model.glb`; existing `conditioning`; four model preview artifacts; linked material artifacts.
- Produces: `create_character_source_review(project_root, manifest, character_selector, concept_views, critical_regions, *, source_output="model") -> dict`. It appends a review record to `asset["source_quality_reviews"]` and writes immutable `ai/assets/candidates/character/<name>/source_review_<id>/review.json`. The record contains `id`, `status`, `source_artifact`, `concept_views`, `critical_regions`, `conditioning`, `previews`, `material_artifacts`, `inspection`, `findings`, `missing`, and per-file `sha256` values. Each topology/component finding begins `unclassified`; `status` is `incomplete` until all required files validate and otherwise `ready_for_review`; the command never sets approval.
- Produces: `classify_character_source_findings(project_root, manifest, character_selector, review_id, classifications) -> dict`, appending classifications for every finding ID as `intentional`, `repairable`, or `unresolved`. Reclassification appends history and does not erase prior entries.

- [ ] Add `test_source_review_records_exact_hashes_and_four_views`, `test_single_image_route_and_missing_concepts_stay_incomplete`, `test_rejects_missing_or_unsafe_source_review_paths`, and `test_critical_regions_require_matching_concept_and_model_closeups` in `tests/test_character_quality.py`. Cover absent side/rear/three-quarter renders, missing maps, undecodable images, and project-root/symlink escapes; assert incomplete packages contain no approval decision and cannot be marked ready.
- [ ] Add `test_findings_start_unclassified_and_only_accept_valid_classifications` in `tests/test_character_quality.py`. Assert only the three documented values are accepted and an unknown finding ID is rejected.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_character_quality.py tests/test_review.py` and confirm the new API/CLI behavior fails before implementation.
- [ ] Implement `create_character_source_review(...)`; validate project-relative paths, resolve symlinks under the project root, verify all referenced files and formats, hash bytes, and retain missing/unknown facts rather than synthesizing them.
- [ ] Add `slopforge character source-review <name> --concept-view front=<path> --concept-view left=<path> --concept-view rear=<path> --critical-region <name> --concept-crop <name>=<path> --model-closeup <name>=<path>`. Require at least one named critical region and a crop/render pair per region; document that the model close-up is captured from the retained Blender source. Write the report without changing the selected model or any generated candidate.
- [ ] Add `slopforge character classify-source <name> <review-id> --finding <finding-id>=<classification>` (repeatable; classification is exactly `intentional`, `repairable`, or `unresolved`); reject classifications for missing IDs and append, rather than overwrite, classification history.
- [ ] Extend the static review board to show each supplied concept beside its matching render where available, plus the four-view set, close-ups, diagnostic JSON, and source-quality status. Escape all paths and content using the existing safe-link helpers.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_character_quality.py tests/test_review.py` and inspect the rendered review board fixture.

### Task 3: Bind human source approval to current evidence

**Files:**
- Modify: `slopforge/character_quality.py`
- Modify: `slopforge/cli.py`
- Modify: `slopforge/character_readiness.py`
- Modify: `slopforge/character_rigging.py`
- Test: `tests/test_character_quality.py`
- Test: `tests/test_character_readiness.py`
- Test: `tests/test_character_rigging.py`

**Interfaces:**
- Consumes: Task 2 `asset["source_quality_reviews"]` records and recorded hashes.
- Produces: `approve_character_source_review(project_root, manifest, character_selector, review_id, *, approved_by=None) -> dict` and `reject_character_source_review(project_root, manifest, character_selector, review_id, reason) -> dict`. Decisions append to the review's `decisions` list. Approval verifies every input hash is current and every required evidence item exists; it records reviewer, timestamp, decision, and reviewed hash set.

- [ ] Add `test_source_approval_requires_complete_review_and_classification`, `test_source_approval_stales_after_reviewed_artifact_changes`, and `test_ready_or_structural_pass_does_not_imply_visual_approval` in `tests/test_character_quality.py`. Assert approval hashes, rejection reason, and stale state after source/concept/preview/inspection/map replacement.
- [ ] Add `test_unreviewed_legacy_character_cannot_rig` and `test_repairable_or_unresolved_findings_block_rigging` in `tests/test_character_rigging.py`; extend readiness tests to assert fully classified intentional findings still require explicit readiness approval.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_character_quality.py tests/test_character_readiness.py tests/test_character_rigging.py` and confirm the new approval checks fail before implementation.
- [ ] Implement approval/rejection with append-only review history. Recompute and compare the full review input hash set at approval and again at readiness/rigging boundaries; never accept path equality as identity.
- [ ] Add `character approve-source <name> <review-id> --confirm` and `character reject-source <name> <review-id> --reason <text>`; require explicit confirmation and reject missing/stale evidence.
- [ ] Keep geometry visual review separate from structural readiness and material approval. Source approval does not set asset `ready`, mark material approval, pass topology checks, or claim deformation/runtime results.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_character_quality.py tests/test_character_readiness.py tests/test_character_rigging.py`.

### Task 4: Document and verify the character source-quality gate

**Files:**
- Modify: `docs/CHARACTER-RIGGING.md`
- Modify: `docs/RECIPES.md`
- Modify: `docs/WORKFLOWS.md`
- Test: focused suites from Tasks 1–3

**Interfaces:**
- Consumes: Task 1 diagnostic fields and Task 2/3 CLI commands and review-record shape.
- Produces: user instructions for collecting approved concept views, generating and inspecting the source review, approving/rejecting it, and interpreting unavailable provenance facts.

- [ ] Document that character source visual review is required before new rigging, four model views are not substitutes for approved front/left/rear concepts, and a one-image conditioning route remains one-image.
- [ ] Document topology diagnostic positions as evidence for human classification, not automated repair or proof that a disconnected component is debris.
- [ ] Run focused suites from Tasks 1–3 and `make verify PYTHON=.venv/bin/python`; report optional Blender/live skips. Do not run `make verify-live` or submit inference.
- [ ] Review `git diff --check`, `git status`, and the final diff to confirm no generated Aster-9 binaries or private local reports entered Git.

## Completion Criteria

- Every topology warning produced by the inspector has location/component evidence, with inspected geometry unchanged.
- Every component and topology finding in a review is classified; `repairable` or `unresolved` findings cannot clear structural readiness.
- A reproducible source-review report contains approved concept inputs, exact mesh/map/inspection/render hashes, route limitations, and aligned visual evidence.
- Missing or changed evidence cannot be approved or reused as current approval; legacy characters remain unreviewed until explicitly reviewed.
- Structural, visual/material, deformation, runtime, performance, and qualification results remain separate.
- Offline verification passes; live inference and human appearance approval remain unclaimed.

## Issue Tracking

Create one M4 follow-up issue linked to #14, titled **Add evidence-backed character source geometry review**. Include this plan and spec, state that it is blocked behind M0–M3, and list the four task deliverables and completion criteria. Do not close #14 or claim character qualification from this work.
