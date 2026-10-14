---
name: slopforge-provenance
description: Use when changing provenance, lineage, stage reuse, safe resume, or invalidation in SlopForge.
---

# SlopForge provenance changes

Use this workflow for changes to stage records, artifact identity, lineage, reuse,
resume, and invalidation.

## Before editing

- Read the whole target function and every caller that relies on its decision.
- State the record invariants and the exact malformed shapes that must fail closed.
- Add an adversarial mutation before changing behavior. Keep one valid baseline.

## Invariants

- Validate every collection member before filtering or selecting records. A malformed
  sibling must not disappear because another member matches.
- Prove identity uniqueness across the full relevant collection before selecting by
  artifact ID. Reject duplicate or missing identities.
- Check complete lineage for contradictions; do not accept a matching subset while
  ignoring additional parents or records.
- Malformed state must return a rejection with a useful reason, not leak an exception.
- Preserve the valid reuse/resume case while rejecting each invalid mutation.

## Implement and review

- Change the shared decision boundary, then inspect the whole function and all callers
  for the same failure mode.
- Run the focused mutation tests, then `make verify-provenance`.
- Review the complete diff and changed callers. Keep production semantics and evidence
  aligned with the contracts; report any out-of-scope defect separately.
- Codex/Luna owns planning and independent review. Local Pi/Qwen writes most bounded
  implementation code. Codex verifies the resulting diff and command output.
- After two attempts without materially new evidence, stop. Report the last correct
  and first incorrect boundary and the next check that would distinguish hypotheses.

Start Pi/Qwen implementation work from
[`templates/pi-qwen-implementation-task.md`](templates/pi-qwen-implementation-task.md).
