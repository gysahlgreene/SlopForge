# Pi/Qwen implementation task

- **Outcome:** What should be true when this task is complete?
- **Exact files and functions:** Where should the change happen?
- **Inspected callers:** Which callers and dependencies were read?
- **Invariants:** What must remain true, including malformed-input behavior?
- **First failing check:** What test or check will fail before implementation, and its exact command?
- **Implementation steps:** What is the smallest change that satisfies the check?
- **Whole-function closure pass:** Re-read the full changed function and all callers. Check malformed siblings, incomplete records, duplicate identity, contradictory lineage, and fail-closed errors where applicable.
- **Verification commands:** Which focused checks and repository gate must pass?
- **Completion report:** List changed files, exact command results, and remaining uncertainty.

Codex/Luna writes and reviews the plan. Local Pi/Qwen writes most implementation code. Codex independently reviews the diff and verification evidence. If two attempts add no materially new evidence, stop and report the last correct and first incorrect boundary plus the next discriminating check.
