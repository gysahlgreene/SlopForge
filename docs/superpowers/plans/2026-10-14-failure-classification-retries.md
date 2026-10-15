# M0 Package 3 — failure classification and bounded retries

> **Status:** Codex/Luna implementation plan. Implementation is underway on `m0/failure-classification-retries` in [PR #36](https://github.com/gysahlgreene/SlopForge/pull/36); this plan's PR #35 remains open with its required review pending. Supersedes the repository-local October 11 draft, `2026-10-11-failure-classification-retries.md`, which is ignored rather than tracked in Git.
>
> **For agentic workers:** Codex/Luna owns planning and independent review; local Pi with Qwen3.6 writes most implementation. Use the [provenance skill](../../../.agents/skills/slopforge-provenance/SKILL.md) and its [task template](../../../.agents/skills/slopforge-provenance/templates/pi-qwen-implementation-task.md) for each bounded task. Execute sequentially using `executing-plans`; no subagents, Astra, Sol, or Mira. Codex reviews each task before the next one and reviews the whole branch before integration.

**Goal:** Report the earliest prop-stage failure with retained evidence and a useful remedy, and spend further generation attempts only on explicit candidate-quality rejections within existing budgets.

**Architecture:** Add a small shared failure vocabulary used by orchestration and workers. Carry structured failures across subprocess boundaries, attach them to the existing schema-v4 journal, and change the existing candidate loops rather than adding a scheduler or nested retry engine. Keep Package 2 reuse checks authoritative for all recovered artifacts.

**Tech stack:** Python standard library, existing atomic JSON manifests, ComfyUI HTTP client, subprocess workers, unittest/pytest fixtures and mocks. No new dependencies.

**Spec:** [Core pipeline audit, Package 3](../../CORE-PIPELINE-AUDIT.md#package-3--stage-failure-classification-and-bounded-retries), [Pipeline contract](../../PIPELINE_CONTRACT.md#failure-reporting-and-recovery), [Quality contract](../../QUALITY_CONTRACT.md), and [Product contract](../../PRODUCT_CONTRACT.md). The contracts govern; the old draft is reference material.

**Baseline:** Start implementation from clean `main` containing Package 1 PR #25, Package 2 PR #32 (`405cc38`), and guardrails PR #34 (`5e3b544`). Tracking: [issue #31](https://github.com/gysahlgreene/SlopForge/issues/31), [M0 epic #26](https://github.com/gysahlgreene/SlopForge/issues/26), milestone 1. Use implementation branch `m0/failure-classification-retries`.

## Global constraints

- Limit new behavior to the existing prop concept, conditioning, mesh, material, assembly, and publication paths. Shared helpers must preserve other asset categories.
- Preserve Package 1 identity/history and Package 2 adoption, invalidation, hashing, and publication rollback. Failure evidence is additive schema-v4 metadata; it does not enter semantic identity hashes.
- Keep existing stage runtime statuses `pending`, `running`, `succeeded`, `failed` and execution statuses `running`, `succeeded`, `failed`. Represent blocked/not-run dependencies as separate evidence, as permitted by the Pipeline contract.
- Fail before expensive inference for known configuration/environment defects. Preserve failed artifacts and successful upstream stages; never promote rejected outputs.
- Only the candidate-quality allowlist below permits automatic retries. No exception-message matching, generic ComfyUI retry, backoff service, implicit approval, or recipe-level retry loop.
- Keep `earliest_stale_stage` hardening in issue #28 outside this package. Do not add production callers of that helper.
- Do not implement Packages 4–6, new providers/categories, live qualification, appearance heuristics, or Unity runtime features. M0 remains incomplete.
- After two attempts without materially new evidence, stop edits, record the last correct/first incorrect boundary, and define the next discriminating check.

## Current gaps this plan fixes

- `model.approve()` advances its mesh loop after every generation exception. A subprocess exit does not identify whether the worker failed during shape inference, Blender preparation, material inference, or download.
- `_generate_material_candidate()` swallows all exceptions into a candidate error; `_native_material_candidate()` lets exceptions escape. This gives the two routes different retry behavior.
- Validation rejection can coexist with a journal stage marked succeeded, including prop concept images and material assembly.
- `_journal_stage()` and outer handlers catch `Exception`, leaving `KeyboardInterrupt` without a terminal record. Hard termination can leave a running journal.
- Worker and local material boundaries can share a stage name/attempt (for example worker `material_generation` and native candidate retention both numbered 1). Failure attribution must not choose a matching record by status or list order.
- Recipes retain text errors but no stable prop failure class. Adding a recipe retry loop would multiply the atomic pipeline's generation budget.

## Decisions and retained data

### Failure vocabulary

Use these exact category values. The boundary that knows the operation selects the category; a plain untyped exception defaults to `unknown`. Do not infer stochastic failure from exception wording.

| Category | Concrete trigger | Automatic retry | Remedy |
| --- | --- | --- | --- |
| `configuration` | Missing workflow, invalid node/model choice, invalid override, graph wiring or resume prerequisite | No | Correct the named configuration/input, run doctor/preflight, then explicitly resume or start a new execution |
| `environment` | Missing executable; service connection failure; unusable local runtime | No | Restore the named service/tool and explicitly retry the command |
| `inference` | Prompt rejected/execution failed, history timeout, malformed service response, download transport failure | No | Inspect retained prompt ID/service evidence; resolve uncertain remote work before a new submission |
| `candidate_quality` | Complete valid inspection rejects only allowlisted generated topology thresholds | Yes, within remaining mesh slots | Try the next recorded mesh seed; on exhaustion revise brief/settings in a new execution |
| `processing_validation` | Blender/map/publication failure, missing/corrupt artifact, invalid image, missing metrics, malformed provenance | No | Repair the named stage/prerequisite; explicitly resume with Package 2 identity checks |
| `interruption` | Keyboard interrupt or recovered record without a persisted completion | No | Inspect retained state and explicitly resume; do not assume remote inference stopped |
| `unknown` | Untyped exception, worker crash, missing/malformed/mismatched failure report | No | Preserve the case and inspect the failing boundary before another attempt |

Add `failure_codes: list[str]` alongside the existing validation `errors` list in `validate_model_outputs()`, with one code per error, and `limits` containing the supplied `max_components`, `max_nonmanifold_edges`, and `max_boundary_edges` (null when unspecified). Codes are produced where errors are added, never parsed from their text. Use `missing_artifact`, `inspection_invalid` (also for inspector-reported errors), `metric_invalid` (also for missing metrics), `surface_invalid`, `bounds_invalid`, `uv_missing`, `material_missing`, `transform_invalid`, `texture_missing`, `face_budget`, `component_budget`, `nonmanifold_budget`, and `boundary_budget`.

Only `component_budget`, `nonmanifold_budget`, and `boundary_budget` are candidate-quality codes. Every other diagnostic is non-retryable. A candidate-quality decision requires a complete valid inspection, finite nonnegative metrics, a declared finite nonnegative threshold for each rejection, a nonempty code list aligned with string errors, and all codes in that allowlist. Each named metric must actually exceed its retained threshold. Booleans are not numeric metrics/thresholds. Missing or legacy codes, invalid containers, contradictory codes/measurements, and mixed failures fail closed. This does not loosen validation or qualify appearance.

Shared module: `slopforge/failures.py` (workers/backends must not import orchestration from `slopforge/pipelines/`). Define:

```python
class StageFailure(RuntimeError):
    def __init__(self, category: str, message: str, *, operation: str,
                 remedy: str, stage: str | None = None,
                 stage_id: str | None = None, evidence: dict | None = None): ...

def failure_record(error: Exception | KeyboardInterrupt, *, stage: str,
                   attempt: int | None, operation: str,
                   stage_id: str | None = None) -> dict: ...

def should_retry(failure: dict, *, used: int, limit: int) -> bool: ...

def candidate_quality_rejection(validation: dict) -> bool: ...
```

`failure_record` returns JSON-safe fields `category`, `stage`, `stage_id`, `attempt`, `operation`, `message`, `remedy`, `retryable`, `exception_type`, `evidence`. An explicitly reported worker leaf stage takes precedence over the parent's fallback stage. A `candidate_quality` record must carry its validation report in `evidence["validation"]`; `retryable` is derived by the quality predicate, never trusted from a worker boolean. Invalid records/counters reject retries without raising. `used` and `limit` are positive integers, not booleans; retry requires `used < limit`. `str(StageFailure)` includes stage when known, category, message, and remedy for existing CLI error paths.

New stages created by `start_stage()` gain an additive UUID `id`. Use `(execution_id, stage_id)` for new failure references; validate the entire relevant collection and ID uniqueness before lookup. Pass the parent's exact mesh-stage ID in worker journal context. The worker reuses that explicit stage handle when entering the parent-owned boundary; other boundaries receive fresh handles rather than selecting by name/status. Local material helpers finish the handle they started. Legacy records are not rewritten to invent IDs: a legacy name/attempt lookup is permitted only when the whole collection proves one unique match, otherwise report ambiguous evidence and stop. Adopted stages receive new IDs with explicit origin references. This does not relax Package 2's existing name/attempt uniqueness requirements for artifact reuse.

Attach the record to the failed stage as `failure`; retain its existing string `error`. An execution has `failure` only when terminally failed, pointing to its earliest leaf failure. A recovered failed attempt remains in history if a later candidate succeeds. Preflight failures before an execution exists go into asset `last_failure` with `attempt: null`; preserve an existing approved asset/status and do not fabricate a started execution. Clear that compatibility field when a later invocation succeeds; historical journal evidence remains.

### Retry budgets and resume

- `model_candidates` bounds fresh mesh submissions; stored mesh seeds determine their order. Attempt numbers are artifact/journal IDs, not budget counters.
- Concept `count` and `material_candidates`/retexture `count` describe planned candidates. They do not grant extra backend retries. A fatal boundary failure stops remaining planned candidates after persisting completed and failed records.
- A topology-only rejection in assembly may advance to the next mesh slot. Stop remaining surface variants for that rejected mesh: more materials cannot repair its topology. An inference, native-map, image-validation, or assembly-processing failure never advances the mesh loop.
- Persist `retry_decisions` on the execution: `scope` (`mesh`), `scope_sha256`, `stage`, `stage_id`, `attempt`, `category`, `used`, `limit`, `action` (`next_candidate`, `stop`, `exhausted`), and `next_seed_index` (null when stopped). A retry uses a fresh attempt directory and the next unused recorded seed; it never overwrites the failed candidate.
- Before each actual mesh submission, persist stage `attempt_slot` with `scope_sha256`, `seed_index`, and `origin_execution_id`. Compute the scope using existing `execution_identity` over input artifact IDs/hashes, mesh settings excluding the individual seed, the ordered seed array, and the budget. This groups the same mesh request across resume without using the whole execution hash: a changed material prompt must not reset its mesh budget. Changed mesh inputs/settings begin a different scope. Slot metadata and decisions do not enter stage settings or artifact identity. Adoption retains the origin slot rather than manufacturing another submission.
- Resume reconstructs consumed mesh slots from the complete, unambiguous parent execution chain and recorded seed indices. Package 2 validates all members and uniqueness before selection; malformed/contradictory accounting refuses automatic retry. A slot rejected for candidate quality remains consumed across resume. Exhaustion cannot reset through repeated `--resume`; a deliberately new execution has a new budget.
- An explicit resume after a deterministic processing/configuration remedy may re-run the failed boundary with its original seed while adopting valid upstream work. This is a user-requested recovery, not an automatic candidate retry. Do not reuse failed outputs or count adopted successful work as a new generation call.
- The current 3D worker is a multi-stage subprocess. This package does not add a worker-internal partial-resume engine. If raw/prepared work succeeded but the remaining worker failed and Package 2 cannot adopt a complete mesh result, `--resume` must explain that limit and stop before resubmitting shape inference. Retain the partial artifacts; a deliberate fresh invocation is an explicit recomputation decision. Local downstream assembly failures with a complete mesh/material result must still resume without inference.
- When submission outcome is unknown, retain `prompt_id` if available and `outcome_unknown: true`. Do not automatically submit or silently requeue on resume. Report the service-resolution action; do not add prompt cancellation/polling recovery in this package.
- Recipe execution carries the child's failure record and blocks dependent children using existing recipe states. Independent children may continue under existing semantics. Recipes perform no additional generation retry. Existing prop recipe execution generates concept candidates and waits for human approval; this package does not add automatic model approval to recipe resume.

### Worker transport and stage attribution

Extend `ComfyUIError` with optional explicit `category`, `operation`, and safe evidence while preserving its existing string/constructor compatibility. Tag errors at HTTP/upload/preflight/submit/history/download raise sites. Generic node execution errors and timeouts are non-retryable `inference`; missing nodes/model choices are `configuration`; connection failures are `environment`. Retain prompt IDs and output descriptors, not credentials or private endpoint URLs in failure evidence.

Both generation workers accept optional `--failure-report PATH`. Backend wrappers choose a fresh UUID-named report in the candidate directory for each subprocess invocation. On handled failure the worker atomically writes protocol version 1 and the structured failure; on success it writes no failure report. The wrapper validates every required field and category/stage before raising `StageFailure`. Missing report, invalid JSON, unknown version, contradictory fields, or an abrupt/nonzero process exit becomes `unknown`, not a retryable guess. Reports are retained; old reports from prior invocations are not read. Preserve current successful subprocess return behavior and ordinary diagnostic output.

The 3D worker records its exact leaf stage through `_journal_stage()` and the report. Cover uploads, preflight, and metadata acquisition outside current context managers with explicit operation attribution. The image worker leaves `stage` unset; the parent binds `concept_generation` or `material_generation`. Catch `KeyboardInterrupt` explicitly and re-raise after best-effort persistence; never catch arbitrary `BaseException`. Journal-write failures must remain visible and must not create success evidence or replace the original failure with a false retry classification.

### Dependencies and termination

On a terminal failure, append execution `blocked_stages` evidence with `name`, `attempt` (null if never allocated), `outcome` (`not_run` or `blocked`), `caused_by` (stage/stage_id/attempt/category), and `reason`. Use the current route's dependency graph; do not pretend absent worker stages ran. For a rejected candidate that will be retried, scope this evidence to that candidate's descendants. Keep runtime stage enums unchanged and preserve prior successes and unrelated candidates.

| Failed boundary | Descendants whose evidence is blocked/not-run, if required by this route |
| --- | --- |
| Concept | Conditioning, mesh, material/map acquisition, assembly, publication |
| Conditioning | Mesh, material/map acquisition, assembly, publication |
| Raw-shape workflow/acquisition | Mesh preparation, worker material inference/output acquisition, local materials, assembly, publication |
| Mesh preparation | Worker material inference/output acquisition, local materials, assembly, publication |
| Worker material inference/output acquisition | Local native-map retention or swatch generation/maps, assembly, publication |
| Swatch generation | Swatch map acquisition, assembly, publication |
| Local native-map retention or swatch maps | Assembly, publication |
| Assembly | Publication |
| Publication | None |

The labels above identify roles; records retain the existing actual stage name and exact handle. Publication remains gated by explicit user candidate approval and belongs to its own execution when invoked. Not-run evidence for publication is not a new publication attempt or permission to publish.

For a worker leaf failure, enclosing orchestration must not relabel all running stages as independent failures. Preserve already-succeeded raw/mesh stages; any unfinished enclosing aggregate may fail with the same leaf reference. Persist terminal execution/asset state once, without losing worker writes during parent reload/save.

On explicit recovery of an unresolved running record, record `interruption` with the observed fact “completion was not persisted,” detection time, and unknown original termination time/cause. Validate the complete execution collection before choosing it. Keep successful artifacts and Package 2 adoption behavior. A hard kill cannot guarantee a last-second write; the plan promises truthful recovery evidence, not crash-proof persistence.

## Review focus

1. A worker material/download failure must remain that leaf failure, not become stochastic mesh failure (Tasks 2–3).
2. Timeout after submission must not queue another prompt or claim cancellation (Tasks 2, 4).
3. Mixed validation diagnostics or malformed retry history must fail closed, even alongside one legitimate quality rejection (Tasks 1, 4).
4. Native PBR and swatch failures must preserve upstream work and spend identical retry policy, including interrupts (Tasks 3–4).
5. Resume must neither reset exhausted budgets nor adopt failed/ambiguous lineage; publication rollback and earlier approved assets must survive (Tasks 3–5).

## Tasks

### Task 1 — Failure vocabulary and explicit quality rejection

**Files:** create `slopforge/failures.py`, `tests/test_failure_classification.py`; modify `slopforge/validation.py`, `tests/test_slopforge.py`.

**Interfaces:** produces the four shared interfaces above and additive validation `failure_codes`; consumes existing validation reports. No journal mutation in this module.

- [ ] Add table-driven tests for every category, empty messages, unknown exceptions, JSON-safe evidence, and retry counters `0`, `-1`, `True`, null, used equal/above limit. Unknown/malformed failures return no retry.
- [ ] Add valid-inspection tests for each allowlisted topology threshold and mixed/legacy/invalid validation reports. This representative helper test must pass only after implementation:

```python
failure = failure_record(RuntimeError("unclassified worker exit"),
    stage="mesh_workflow_execution", attempt=1, operation="worker")
assert failure["category"] == "unknown"
assert should_retry(failure, used=1, limit=3) is False
assert candidate_quality_rejection({"status": "failed", "errors": ["broken"],
    "failure_codes": ["component_budget", "missing_output"]}) is False
```

- [ ] Run `.venv/bin/python -m pytest tests/test_failure_classification.py tests/test_slopforge.py -q`; confirm new assertions fail for missing interfaces/behavior, not fixture mistakes.
- [ ] Implement explicit categories, record validation, retry rule, and one validation code per existing error without changing validation thresholds or error strings. Emit dedicated non-quality codes for every other error; inspect every caller of `validate_model_outputs` before editing its result shape.
- [ ] Run the same command, inspect the full functions/callers, and commit `feat: define stage failure and candidate retry policy` after Codex review.

### Task 2 — Carry structured worker failures across the backend boundary

**Files:** modify `slopforge/backends/comfyui.py`, `processing/comfy_generate.py`, `processing/comfy_generate_3d.py`, `tests/test_comfyui_service.py`, `tests/test_comfy_generate.py`; create `tests/test_worker_failures.py`.

**Interfaces:** consumes `StageFailure` and `failure_record`; produces optional protocol-v1 worker reports and typed backend failures. Preserve `generate_image(...)`/`generate_model(...)` caller compatibility; only optional CLI transport flags are new.

- [ ] Add mocked tests for node/model preflight rejection, HTTP rejection, connection loss, execution error, history timeout with known prompt ID, upload/download error, malformed JSON, worker signal termination, and missing/stale/malformed/version-mismatched reports. Assert each performs at most one submission and never calls inference after preflight rejection.
- [ ] Add a worker-report fixture and fake subprocess that writes it to the fresh report path. Verify wrappers reject a preexisting unrelated report and return successful subprocess results unchanged. No running ComfyUI or Blender is needed.
- [ ] Run `.venv/bin/python -m pytest tests/test_comfyui_service.py tests/test_comfy_generate.py tests/test_worker_failures.py -q` and confirm the new assertions are red.
- [ ] Tag known client raise sites explicitly; add atomic worker reports and validated wrapper loading. Preserve uncaught diagnostics as `unknown`. Do not classify `CalledProcessError` from its stderr text. Keep local/remote HTTP behavior identical.
- [ ] Run the same tests; Codex reviews the complete client/worker boundaries and commits `feat: retain structured generation worker failures`.

### Task 3 — Persist truthful leaf failures, dependencies, and interruption recovery

**Files:** modify `slopforge/manifest.py`, `slopforge/candidates.py`, `slopforge/pipelines/model.py`, `processing/comfy_generate_3d.py`, `tests/test_manifest.py`, `tests/test_prop_lineage.py`; create `tests/test_prop_failures.py`.

**Interfaces:** add UUID stage IDs in `start_stage`; extend `finish_stage(..., error=None, *, failure=None)` additively; failed stages may retain validated failure metadata, successful stages must reject it. Extend `finish_execution(execution, status, *, failure=None)` similarly. Old callers continue working. `_execution_stage` gains optional exact `stage_id` lookup; `_lineage_finish` gains optional `stage_id` and finishes the actual started handle. Orchestration binds fallback stage names to Task 2 failures and persists `blocked_stages` evidence.

- [ ] Add manifest round-trip tests for failure metadata and rejection of contradictory success/failure records, duplicate IDs, malformed siblings, and ambiguous legacy name/attempt lookup. Test worker/local material stages sharing a name/attempt: only the explicitly referenced leaf may receive the failure; reuse must remain conservative. Start with this representative fixture:

```python
stage = start_stage(execution, "conditioning_preparation", 1, [], {}, {})
begin_stage(stage)
failure = failure_record(StageFailure("processing_validation", "invalid cutout",
    operation="validate_image", remedy="repair conditioning inputs"),
    stage=stage["name"], stage_id=stage["id"], attempt=1, operation="validate_image")
finish_stage(stage, "failed", error=failure["message"], failure=failure)
assert stage["status"] == "failed" and stage["failure"]["stage"] == stage["name"]
```

- [ ] Reuse `PropLineageTests` temporary-project/setup mocks for a boundary matrix: concept generation, conditioning preparation, raw acquisition, mesh preparation, material inference, final mesh/maps acquisition, swatch map processing, assembly inspection, and final publication. Assert exact leaf category/stage, validation/artifact retention, dependent evidence, save/reload survival, and zero dependent external calls.
- [ ] Add native/swatch `KeyboardInterrupt` cases and preflight-before-execution cases. Inject publication failure and prove existing outputs/approval rollback. Recover a persisted running stage on explicit resume with unknown actual stop time; retain historical succeeded stages.
- [ ] Run `.venv/bin/python -m pytest tests/test_manifest.py tests/test_prop_lineage.py tests/test_prop_failures.py -q`; confirm red assertions.
- [ ] Wire structured failures through `_lineage_finish`, `_journal_stage`, both material helpers, `approve`, `retexture`, `approve_texture`, and prop `generate_candidates`. Use one root leaf failure plus scoped descendant evidence. Persist candidates before propagating fatal errors. Never mark a validation-rejected stage succeeded.
- [ ] Move setup that can fail after execution creation inside a persisted failure boundary (including executable lookup and source-copy/setup). Pre-execution errors preserve existing asset state and set only `last_failure`. Preserve parent reload/save discipline and stage adoption settings.
- [ ] Run the same tests plus `.venv/bin/python -m pytest tests/test_prop_reuse.py tests/test_provenance_guardrails.py -q`; Codex reviews full touched functions/callers and commits `feat: persist prop failure and interruption evidence`.

### Task 4 — Replace broad retry loops with bounded candidate decisions

**Files:** modify `slopforge/pipelines/model.py`, `slopforge/candidates.py`, `tests/test_prop_failures.py`, `tests/test_prop_reuse.py`, `tests/test_prop_lineage.py`.

**Interfaces:** consumes Task 1 `should_retry`/quality predicate and Task 3 journal records; produces persisted `retry_decisions` and consistent terminal failures. Existing budgets and seed arrays remain the configuration API.

- [ ] Add mocked call-count cases: configuration/environment/inference/processing/unknown error at the first attempt with a three-slot budget must make exactly one generation call; topology rejection then success makes two calls with distinct recorded seeds; all three topology rejections make exactly three calls and report exhaustion.
- [ ] Add parity cases for native PBR and swatch routes. A map/assembly fault makes zero further mesh calls. A topology-only rejection skips remaining swatches on that mesh and advances once. Concept/retexture count remains a planned output count, not an extra backend retry multiplier.
- [ ] Add save/reload/resume cases for exhausted budgets, non-exhausted quality history, consumed seeds through parent executions, ambiguous/malformed siblings and duplicate accounting. Confirm no counter is inferred from the largest artifact attempt number. Legacy records without trustworthy accounting must stop automatic retries with a remedy.
- [ ] Add deterministic recovery and timeout cases: explicit local processing recovery adopts intact mesh/material artifacts, runs only stale/failed stages, and does not reset quality budget; `outcome_unknown` refuses silent submission on resume. A partial worker result that cannot be safely adopted must refuse resume before submitting shape inference and explain its limit. Verify all failed directories and inspection reports remain intact.
- [ ] Run `.venv/bin/python -m pytest tests/test_prop_failures.py tests/test_prop_reuse.py tests/test_prop_lineage.py -q`; confirm new policy tests are red.
- [ ] Refactor the existing `approve` mesh loop and swatch list comprehension into explicit bounded iteration. Advance only after validated `candidate_quality` and available next seed. Persist the decision before submission. Catching a generic error must not execute `continue`. Keep `retexture` and concept generation fail-fast rules scoped to props.
- [ ] Run the same tests and `make verify-provenance PYTHON=.venv/bin/python`; Codex audits full collection validation, uniqueness before filtering, counters, and call counts, then commits `fix: bound prop retries to candidate quality rejection`.

### Task 5 — Report the failure through recipes and CLI without retry multiplication

**Files:** modify `slopforge/recipes.py`, `slopforge/cli.py`, `tests/test_recipes.py`, `tests/test_slopforge.py`, `tests/test_prop_failures.py`.

**Interfaces:** existing CLI commands/options and recipe child statuses remain unchanged. Prop child stages gain an additive `failure` record copied from the atomic pipeline; existing `errors` strings remain available. No `should_retry` call belongs in recipes.

- [ ] Add CLI cases showing stage/category/message/remedy, nonzero exit on failure, and retained manifest evidence. Interruption remains the existing CLI interruption outcome rather than a normal success.
- [ ] Add a recipe fixture with a failing prop child, a dependent child, and an independent child. Assert exactly one atomic pipeline invocation for the failed child, the dependent remains blocked, independent work follows existing behavior, and previously valid approved children survive. Verify stale replacement is still not restored as approved.
- [ ] Run `.venv/bin/python -m pytest tests/test_recipes.py tests/test_slopforge.py tests/test_prop_failures.py -q`; confirm red reporting/call-count assertions.
- [ ] Carry structured records through `_execute` and existing CLI exception paths. On explicit recipe resume, rely on the atomic pipeline's Package 2/budget policy; do not wrap it in another automatic retry. Preserve failure evidence during state/artifact synchronization and reload.
- [ ] Run the same tests; Codex reviews restoration, dependency handling, output compatibility, and commits `feat: expose prop stage failures in recipe and CLI reporting`.

### Task 6 — Whole-package gate and evidence-backed documentation

**Files:** update `docs/ARCHITECTURE.md`, `docs/ASSET-OUTPUTS.md`, `docs/RECIPES.md`, `docs/AGENT-INTEGRATION.md`, `ROADMAP.md`, `CURRENT_STATE.md`; review all changed code/tests. Update issue #31/epic #26 only after verified integration.

- [ ] Review the entire branch against all decisions and five Review Focus cases. Verify no production changes to `earliest_stale_stage`, no generic scheduler, no new approval authority, and no new live/qualification claims.
- [ ] Run `.venv/bin/python -m pytest tests/test_failure_classification.py tests/test_worker_failures.py tests/test_prop_failures.py tests/test_prop_lineage.py tests/test_prop_reuse.py tests/test_recipes.py tests/test_manifest.py tests/test_comfyui_service.py tests/test_comfy_generate.py tests/test_slopforge.py -q`.
- [ ] Document actual failure fields, exact retry allowlist/budget accounting, deterministic explicit resume versus automatic candidate retry, uncertain remote submission handling, and native/swatch limits. Update Current state only from observed results; leave live/visual/Unity checks separately unverified.
- [ ] Run `make verify-provenance PYTHON=.venv/bin/python`, `make verify PYTHON=.venv/bin/python`, and `git diff --check main...HEAD`. Use the known-good unrestricted environment when sandbox restrictions prevent Blender/localhost fixtures; retain both results and all skips. No live inference is authorized by this plan.
- [ ] Codex/Luna performs the final independent review of the Qwen-written diff and actual outputs. Any Critical/Important finding blocks integration. Push/create a PR with exact verification evidence, wait for required remote checks, then integrate under the user's authorized repository workflow. Preserve useful commit history.
- [ ] After merge, link the PR and close #31 only if all package exit criteria below passed. Update #26/milestone without closing M0; mark Package 3 merged in Roadmap/Current state and name the next package. Return to clean synced `main`, prune the merged issue branch, and preserve no temporary review artifacts in public Git.

## Exit criteria and self-review

| Required outcome | Evidence owner |
| --- | --- |
| Stable category, earliest stage, failed invariant, identity/evidence and remedy | Tasks 1–3: category/worker/boundary matrix and manifest reload |
| Known deterministic faults consume no speculative retries | Tasks 2, 4: preflight and one-call cases |
| Only explicit candidate-quality rejection advances within budget | Tasks 1, 4: validation-code allowlist, mixed-failure rejection, call/seed counts |
| Resume preserves valid work and never resets quality exhaustion | Tasks 3–4: history/seed accounting and adoption regressions |
| Native/swatches and interruption retain truthful state | Tasks 3–4: parity, worker leaf and recovery fixtures |
| Dependents are blocked/not-run; recipe budgets do not multiply | Tasks 3, 5: route-scoped dependency evidence and recipe call count |
| Publication rollback and human approval boundaries survive | Tasks 3, 5: existing-output restoration and approval-state regressions |
| Complete offline gate plus independent review | Task 6; record unavailable/opt-in coverage separately |

This plan replaces message-based classification and recipe retries in the old draft with explicit boundary evidence and one retry owner. All new interfaces are defined above; failure/validation fields are additive and excluded from identity. Every Review Focus case has a named test task. Guardrails are merged, implementation is underway, and no qualification result is implied by this planning document.
