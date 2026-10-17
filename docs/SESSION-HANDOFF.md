# Session handoff — repeatable character quality pipeline

> Read on return: [AGENTS](../AGENTS.md) → [contracts](PRODUCT_CONTRACT.md) / [roadmap](../ROADMAP.md) / [current state](../CURRENT_STATE.md). Inspect preserved worktrees. Review full dirty diff against the applicable plan/spec below. Then freshly verify before any claim. Baseline at audit start was `main` at `e56d188`.

## Remaining worktrees

| Worktree | Branch | HEAD | Ahead / Behind | Status |
| --- | --- | --- | --- | --- |
| `.` (repo root) | `main` | `e56d188` | — | baseline at audit start |
| sibling worktree `../SlopForge-character-quality` (or locate with `git worktree list`) | `codex/repeatable-character-quality-pipeline` | `97ed33f` | 6 ahead / 113 behind (graph counts) | dirty: 32 tracked + 9 untracked (41 entries); diff `1370 +/139 -` |
| `.worktrees/guided-character-to-unity` (in-repo) | `feat/guided-character-to-unity` | `3e42f89` | — | dirty — preserve |
| Pi/Qwen bridge worktree (branch `tools/codex-pi-qwen-bridge`; locate with `git worktree list`) | `tools/codex-pi-qwen-bridge` | `0fc63e5` | 3 ahead of main | clean, unique work — preserve |

Baseline at audit start: `main` at `e56d188`. This is documentation for the preserved state.

## M0 issue tracker (remaining)

- Open: **#26** only (M0 Core reliability epic).
- Packages 1–3: #30, #27, #31 closed; #28 closed.
- GitHub: no open PRs; only `main` exists on the remote.

## Bounded parallel track (not roadmap reordering)

User directed character quality as a bounded follow-up to M0. Separate issue tracks:
- **#14** — repeatable character pipeline
- **#40** — Aster-9 source geometry review

Do not change milestone order or claim qualification from this track.

## Remaining local branches

Four remaining local branches total: `main`, `codex/repeatable-character-quality-pipeline`, `feat/guided-character-to-unity`, `tools/codex-pi-qwen-bridge`.

## Aster status

Visual/material approval **pending** — no readiness, deformation, performance, or pipeline qualification. No new inference authorized.

## Plans / specs (read before diff review)

- `docs/superpowers/specs/2026-10-15-aster9-premium-character-design.md`
- `docs/superpowers/plans/2026-10-15-aster9-premium-character.md`
- `docs/superpowers/specs/2026-10-16-character-source-quality-design.md`
- `docs/superpowers/plans/2026-10-16-character-source-quality.md`

## Cleanup inventory

- **37 local branches removed total**
  - 36 whose tips were reachable from `main` (includes `codex/prototype-content-factory`)
  - 1 additional branch `quality/meaningful-improvements-2026-10-03` removed after `git cherry` confirmed its patch is already represented in `main`
- **7 stale remote branches** deleted — tips were ancestors of `main` and there were no open PRs; stale `origin` refs were pruned.
- **3 redundant worktrees removed:**
  - clean detached worktree at `.codex/worktrees/c59a/SlopForge`
  - clean merged branch `comfyui-remotebackends`
  - `.worktrees/prop-lineage-stage-state` — clean, merged
- Before removal, the prop-lineage worktree's SDD progress, briefs, review logs, and ignored plan were archived outside the repo at `~/.codex/archive/SlopForge/prop-lineage-stage-state-2026-10-10` (private local archive, not Git).

## Entry instructions

1. Read AGENTS, contracts, roadmap, and current state (`.`, `docs/`).
2. Inspect the preserved worktrees above (`git worktree list --verbose`); confirm they still match recorded states.
3. `cd ../SlopForge-character-quality && git diff HEAD` to review the full dirty diff; cross-reference against the applicable plan/spec from the list above.
4. Inspect and preserve the dirty worktree in place — do not rebase or modify it first. Run verification in place (`make verify`, or `make verify-live` with explicit authorization) and record results against the current state.
5. Inspect private artifacts only where they already exist; do not move or share them.
   The prop-lineage archive at `~/.codex/archive/SlopForge/prop-lineage-stage-state-2026-10-10` is outside the repo (private local archive, not Git).
6. Only after verification, decide whether a rebase onto `main` is needed.
7. **Do not** run inference, rigging, or approval workflows — each requires new user authorization. **Do not push** the unverified character-quality changes; the earlier conditional authorization for pushing applies only after they are verified and ready.

### Historical verification note (stale, needs fresh verification)

Last reported: 290 passed, 8 skipped, 49 subtests — historical and dirty. The dirty diff (`1370 +/139 -`) needs a fresh verification pass.
