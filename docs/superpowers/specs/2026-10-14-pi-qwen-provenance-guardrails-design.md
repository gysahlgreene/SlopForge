# Pi/Qwen provenance guardrails design

## Purpose

Package 2 repeatedly exposed provenance mistakes that waste implementation and review time: malformed siblings are filtered away, incomplete dict-shaped provenance is accepted, identity is checked before uniqueness, contradictory lineage is accepted, and malformed state raises instead of failing closed. This tooling turns those lessons into repeatable checks and usable implementation guidance before Package 3.

The intended division of work is Codex/Luna for planning and independent review, with local Pi/Qwen doing most implementation writing. The guardrails should keep Qwen's tasks concrete and bounded, make required checks easy to run, and give it a clear stop-and-report path when the task or evidence is unclear or repeated attempts fail.

## Scope

1. Add `.agents/skills/slopforge-provenance/` with a concise skill covering provenance invariants, adversarial review, and implementation workflow. It will require the implementer to inspect the full target function and its callers, validate complete collections before selecting records, establish uniqueness before identity-based filtering, reject contradictory lineage, and fail closed without leaking malformed-state exceptions.
2. Add a short Pi/Qwen implementation task template in that skill. The template will ask Codex to provide a bounded objective, exact files/functions, invariants, first failing check, verification commands, and a concise completion report. It will direct Qwen to stop after repeated attempts without new evidence and report the last correct/first incorrect boundary rather than loop.
3. Add a reusable, table-driven adversarial mutation matrix under `tests/` for the provenance/reuse decision paths. It will exercise valid baselines and malformed siblings, incomplete records, duplicate identities, contradictory derivation links, and malformed container state. Invalid mutations must be rejected and must not raise; valid provenance must remain accepted.
4. Add a deliberately narrow AST-based audit script for the existing provenance decision boundaries. It will flag the known filter-before-validation / identity-before-uniqueness patterns, include focused fixture checks for its own detection behavior, and identify the function and source location. It is a targeted guard, not a general Python linter.
5. Add `make verify-provenance` to run the mutation checks and audit; include it in `make verify` so the guardrails run before implementation changes are considered complete.
6. Add a short link in root `AGENTS.md` telling agents working on provenance/reuse decisions to use the skill and run the dedicated check.

## Out of scope

- No Package 3 behavior or plan adoption.
- No production provenance or reuse behavior changes. If the new matrix exposes an existing defect, report it as a separate follow-up rather than expanding this tooling task.
- The known `earliest_stale_stage` malformed/ambiguous-record limitation remains tracked separately in issue #28; this task does not resolve it.
- No new dependencies, generalized validation framework, or broad repository linter.
- No live inference, visual qualification, or Unity checks.

## Design choices

Use existing Python tests and the repository's `make verify` path rather than adding a framework. Keep the adversarial matrix as a small shared test table with local mutations for the differing record shapes. Keep the source audit narrow and explicitly scoped to known decision functions so it does not become a speculative style checker. Make the Pi/Qwen guidance operational: each task should state the intended result, files and functions, non-negotiable invariants, exact checks, and stop/report conditions; Codex remains responsible for plan quality and independent review.

## Success criteria

- A single documented task format lets Codex hand local Qwen a bounded provenance change with exact invariants and checks.
- The adversarial matrix catches the known malformed, ambiguous, duplicate, and contradictory provenance cases and confirms valid cases still work.
- The audit fails on representative source snippets containing the known anti-patterns and passes the current compliant implementation.
- `make verify-provenance` and the repository's standard `make verify` execute the checks.
- Root agent instructions point contributors to the guardrails without duplicating the skill.
- Package 3 remains planned and untouched.

## Risks and limits

Static source checks can reliably catch only explicitly encoded patterns; they will not prove arbitrary Python control flow correct. The mutation matrix is the behavioral check and should remain authoritative. The target functions may change over time, so audit fixtures and function scope must be updated with intentional provenance-flow changes.
