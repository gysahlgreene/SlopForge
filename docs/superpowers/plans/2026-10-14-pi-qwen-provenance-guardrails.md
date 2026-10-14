# Pi/Qwen Provenance Guardrails Implementation Plan

> **For agentic workers:** Use local Pi/Qwen for most implementation writing, with Codex planning, reviewing, and verifying each bounded task. The user prohibited subagents. Confirm the available `pi` CLI is using local Qwen before writing; do not silently switch to another model. Use the skill and task template created here for Qwen-written code.

**Goal:** Add repeatable provenance mutation checks and narrow anti-pattern detection, plus concise Pi/Qwen guidance that prevents known provenance mistakes and unproductive retry loops.

**Architecture:** A focused unittest module will hold a reusable mutation table against the existing shared `stage_reuse_decision` contract. A standard-library AST audit will check changed provenance decision functions for malformed-member filtering and identity selection before an explicit uniqueness check. A skill, task template, Make target, and one root instruction pointer make the guardrails easy for local Qwen and Codex to use.

**Tech Stack:** Python standard library (`ast`, `subprocess`, `unittest`), existing pytest runner, GNU Make, Markdown.

**Spec:** `docs/superpowers/specs/2026-10-14-pi-qwen-provenance-guardrails-design.md`

## Global Constraints

- Do not implement Package 3 or adopt its draft plan.
- Do not change production provenance/reuse behavior; report a discovered production defect as a separate follow-up.
- Keep issue #28's `earliest_stale_stage` limitation out of scope.
- Add no dependencies, generalized validation framework, or broad repository linter.
- Keep Codex responsible for plan and independent review; local Pi/Qwen does most bounded implementation writing.
- Keep live inference, visual qualification, and Unity checks out of this work.

## Review Focus

- Malformed siblings must not disappear during filtering: test a valid output plus a `None` sibling and require rejection.
- Incomplete dict-shaped provenance must fail closed: omit a required artifact field and require rejection without an exception.
- Duplicate identities must be detected before reuse is accepted: duplicate an output ID and require rejection.
- Contradictory lineage must be rejected: add an unrelated derivation parent and require rejection.
- Invalid container shape must not raise: set the output collection to `None` and require rejection.

---

### Task 1: Add the reusable provenance mutation matrix

**Files:**
- Create: `tests/test_provenance_guardrails.py`
- Read: `slopforge/pipelines/reuse.py:stage_reuse_decision`

**Interfaces:**
- Consumes: `stage_reuse_decision(project_root, stage, *, inputs, settings)`.
- Produces: one table-driven regression test that checks invalid mutations reject and the valid baseline remains reusable.

- [ ] **Step 1: Add a fixture and mutation table**

Create a temporary root and one real output file. Build a valid `concept_generation` stage with attempt `1`, succeeded status, no inputs, empty settings, and one `image.concept` output whose path/hash match that file. Define these mutators in `MUTATIONS`: append `None` to outputs; remove `sha256` from the output; append a second output with the same ID; append an unrelated `derived_from` parent; replace outputs with `None`.

```python
MUTATIONS = (
    ("malformed sibling", lambda stage: stage["outputs"].append(None)),
    ("incomplete output", lambda stage: stage["outputs"][0].pop("sha256")),
    ("duplicate output ID", lambda stage: stage["outputs"].append(dict(stage["outputs"][0]))),
    ("contradictory lineage", lambda stage: stage["outputs"][0]["derived_from"].append(
        {"artifact_id": "foreign", "sha256": "f" * 64})),
    ("malformed output collection", lambda stage: stage.update(outputs=None)),
)
```

For each subtest, deep-copy the valid stage, apply one mutation, call `stage_reuse_decision`, and assert `reusable` is false. Call the function directly so any leaked exception fails the test. Add a separate valid-baseline assertion.

- [ ] **Step 2: Run the focused test**

Run: `.venv/bin/python -m pytest tests/test_provenance_guardrails.py -q`

Expected: the valid baseline passes; every mutation is rejected without raising.

- [ ] **Step 3: Run the existing reuse regressions**

Run: `.venv/bin/python -m pytest tests/test_prop_reuse.py tests/test_recipes.py -q`

Expected: existing reuse and publication lineage behavior remains green.

- [ ] **Step 4: Commit the test matrix**

```bash
git add tests/test_provenance_guardrails.py
git commit -m "test: add provenance mutation matrix"
```

### Task 2: Build and test the narrow provenance anti-pattern audit

**Files:**
- Create: `scripts/check_provenance_antipatterns.py`
- Modify: `tests/test_provenance_guardrails.py`

**Interfaces:**
- Produces: `inspect_source(source: str, filename: str) -> list[str]` and a CLI that returns nonzero when a changed provenance decision function contains a detected anti-pattern.
- The CLI checks only changed Python files under `slopforge/`, then only functions whose names contain `reuse`, `provenance`, or `lineage`. On a feature branch it compares the working tree with `main` when that ref exists; on `main` it compares with `HEAD^`; in detached CI checkouts without `main` it compares with `HEAD^` (the PR merge commit's base parent). A clean/no-source-change run succeeds with a concise message.

- [ ] **Step 1: Add failing audit fixture tests**

Add tests for `inspect_source` using small inline functions. One fixture filters a provenance list with `if isinstance(record, dict)` and then checks `record.get("id")`; it must report malformed-member filtering. Another selects records by `id` before any collection-wide uniqueness check; it must report identity-before-uniqueness. A valid fixture first validates all members, builds an ID list, rejects `len(set(ids)) != len(ids)`, and only then selects by ID; it must return no findings.

```python
def test_audit_flags_identity_filter_before_uniqueness():
    source = """\
def candidate_reuse_decision(records, wanted):
    matches = [record for record in records if record.get('id') == wanted]
    return matches
"""
    self.assertTrue(any("uniqueness" in finding for finding in inspect_source(source, "fixture.py")))
```

- [ ] **Step 2: Run the fixture tests to verify RED**

Run: `.venv/bin/python -m pytest tests/test_provenance_guardrails.py -q`

Expected: import fails because `scripts.check_provenance_antipatterns` does not exist yet.

- [ ] **Step 3: Implement the standard-library AST audit**

Parse the source with `ast.parse`. Inspect only target decision functions. Report function name and line for (a) a comprehension predicate that drops non-dict provenance members while filtering by identity/status, and (b) identity-selection comprehensions that occur before the function has performed a collection-wide uniqueness check for that collection. Keep the detector conservative: no dynamic execution and no new dependencies. Implement `inspect_source` so fixture tests exercise the same function used by the CLI.

Resolve the comparison base from the current branch as described above. Use `git diff --name-only <base> -- slopforge` so both committed branch changes and current working-tree edits are included. Parse changed source files and report each finding as `path:function:line: reason`. A source file that changed but has no target decision function needs no audit. Exit `1` for findings and `0` otherwise.

- [ ] **Step 4: Run focused tests and CLI**

Run: `.venv/bin/python -m pytest tests/test_provenance_guardrails.py -q`

Expected: all audit fixtures and the mutation matrix pass.

Run: `.venv/bin/python scripts/check_provenance_antipatterns.py`

Expected: exit `0`; this tooling branch does not change production decision functions.

- [ ] **Step 5: Commit the audit**

```bash
git add scripts/check_provenance_antipatterns.py tests/test_provenance_guardrails.py
git commit -m "test: audit provenance decision patterns"
```

### Task 3: Add Pi/Qwen workflow guidance and verification integration

**Files:**
- Create: `.agents/skills/slopforge-provenance/SKILL.md`
- Create: `.agents/skills/slopforge-provenance/templates/pi-qwen-implementation-task.md`
- Modify: `AGENTS.md`
- Modify: `Makefile`

**Interfaces:**
- Produces: a model-invoked skill with a concise description; a reusable task template; `make verify-provenance`; and an `AGENTS.md` pointer for provenance/reuse changes.

- [ ] **Step 1: Write the bounded Pi/Qwen task template**

The template must have fields for: outcome; exact files/functions; inspected callers; invariants; first failing check and command; implementation steps; full-function closure review; verification commands; and a completion report with changed files, results, and remaining uncertainty. State the division of labor directly: Codex/Luna writes and reviews the plan; local Pi/Qwen writes most implementation; Codex independently reviews the resulting diff and evidence. If two attempts produce no materially new evidence, stop and report the last correct and first incorrect boundary plus the next discriminating check.

- [ ] **Step 2: Write the skill and link it from root instructions**

Use frontmatter `name: slopforge-provenance` and a model-invoked description that triggers for changes to provenance, lineage, stage reuse, resume, or invalidation. Keep the skill focused on the whole-function closure pass, validating complete collections before filtering, uniqueness before identity-based selection, exact lineage consistency, fail-closed errors, adversarial mutation tests, and `make verify-provenance`. Add one short `AGENTS.md` line pointing to the skill when editing these decision paths.

- [ ] **Step 3: Add the dedicated Make target**

Add `verify-provenance` to `.PHONY` and define:

```make
verify-provenance:
	$(PYTHON) -m pytest -q tests/test_provenance_guardrails.py
	$(PYTHON) scripts/check_provenance_antipatterns.py
```

Make `verify` depend on `verify-provenance`, preserving its existing compile, full pytest, docs, and whitespace checks.

- [ ] **Step 4: Run focused checks and documentation checks**

Run: `make verify-provenance PYTHON=.venv/bin/python`

Expected: mutation tests and the audit pass.

Run: `.venv/bin/python scripts/check-docs.py && git diff --check`

Expected: documentation links/metadata and whitespace checks pass.

- [ ] **Step 5: Run full repository verification**

Run: `make verify PYTHON=.venv/bin/python`

Expected: compile, full pytest, docs checks, provenance checks, and whitespace check pass; live inference remains skipped.

- [ ] **Step 6: Commit guidance and integration**

```bash
git add .agents/skills/slopforge-provenance/SKILL.md .agents/skills/slopforge-provenance/templates/pi-qwen-implementation-task.md AGENTS.md Makefile
git commit -m "chore: add Pi/Qwen provenance guardrails"
```

### Task 4: Review the whole branch and prepare the issue update

**Files:**
- Review: all branch changes
- Update after verification: issue #29

- [ ] **Step 1: Review the branch against the spec**

Inspect `git diff main...HEAD`, `git diff --check`, all changed source/tests/docs, and confirm no Package 3 plan or production behavior changed. Check the 5 failure classes in the Review Focus section against the test matrix and audit fixtures.

- [ ] **Step 2: Run verification after the final review**

Run: `make verify PYTHON=.venv/bin/python`

Expected: the complete repository gate passes. Do not merge if it fails.

- [ ] **Step 3: Update issue #29 only after verified completion**

Record the merged branch/PR and checks in issue #29, state that the guardrails precede Package 3, and leave issue #31 planned/not started. Do not update issue #28 or mark M0 complete.

## Self-review

- **Spec coverage:** The skill/template and AGENTS pointer are Task 3; mutation matrix is Task 1; AST audit and its fixtures are Task 2; `make verify-provenance` and full verify are Task 3; Package 3 and issue #28 boundaries are explicit throughout.
- **Placeholder scan:** No TODO/TBD steps. Every command, primary file, test behavior, and commit is specified.
- **Type consistency:** `inspect_source(source, filename) -> list[str]` is the only helper API used by both tests and CLI. The CLI reads repository files and returns a conventional process exit status.
- **Review focus:** Malformed sibling, incomplete record, duplicate identity, contradictory lineage, and malformed container are all tested by the Task 1 mutation table. Audit fixture tests cover ordering rules.
