# Roadmap

Follow the [product contract and document precedence](docs/PRODUCT_CONTRACT.md),
[pipeline contract](docs/PIPELINE_CONTRACT.md), and
[quality contract](docs/QUALITY_CONTRACT.md). Milestones are evidence gates, not
code inventories. This ordering replaces the earlier humanoid-preview-first sequence.

| Milestone | Status | Exit evidence |
| --- | --- | --- |
| M0 Core reliability | Active; existing implementation and bounded recovery evidence | The concrete core exit evidence below, with requirements/enforcement gaps visible |
| M1 Props | Next category gate; examples exist, repeatability unestablished | Representative static prop production through separate visual, structural, technical, style, performance and Unity gates under declared criteria |
| M2 Modular environments | After props; recipes/kit support exists | Reviewed modules assemble at declared scale/pivots, meet connection/repetition needs and project budgets, and work together in Unity |
| M3 Weapons/mechanical assets | After environments | Reviewed shapes/materials, moving-part hierarchy/pivots and functional motion where required, with project/runtime checks |
| M4 Humanoids | After mechanical assets; historical asset-specific checks exist | Representative source acceptance, rig readiness, deformation, compatible animation and Unity playback under declared criteria |
| M5 Creatures/Generic rigs | After humanoids | Category-appropriate skeletons, deformation, animation compatibility and Generic runtime playback under declared criteria |
| M6 Broader automation | After category reliability | Reduced intervention across evidenced stages while preserving provenance, recovery, requirements and human review authority |

## Active core exit evidence

### M0 package sequence

These implementation packages build the reliability evidence needed by M0; none
by itself completes the milestone. Operational issue tracking is under the
[M0 Core reliability epic](https://github.com/gysahlgreene/SlopForge/issues/26)
and [M0 milestone](https://github.com/gysahlgreene/SlopForge/milestone/1).

| Package | Objective and dependency | Status |
| --- | --- | --- |
| Package 1 — execution lineage, stage state, and provenance foundation | Persist prop execution identity, artifact lineage, and stage outcomes; prerequisite for Package 2 | Merged in [PR #25](https://github.com/gysahlgreene/SlopForge/pull/25); [issue #30](https://github.com/gysahlgreene/SlopForge/issues/30) is closed |
| Package 2 — safe resume, invalidation, and evidence-backed reuse | Reuse only valid lineage-backed artifacts and restart at the earliest stale stage; depends on Package 1 | Implemented and verified; [PR #32](https://github.com/gysahlgreene/SlopForge/pull/32) has passing checks and awaits the required formal approval; [issue #27](https://github.com/gysahlgreene/SlopForge/issues/27) remains open until merge |
| Before Package 3 — Pi/Qwen provenance guardrails | Add adversarial provenance checks and implementation guidance before Package 3 starts | Planned prerequisite; [issue #29](https://github.com/gysahlgreene/SlopForge/issues/29) |
| Package 3 — failure classification and bounded retries | Classify stage failures and retry only explicitly stochastic candidate failures; depends on Packages 1–2 and the guardrail tooling | Planned, not started; its existing draft is reference material until Codex/Luna adopts a final plan; [issue #31](https://github.com/gysahlgreene/SlopForge/issues/31) |

The known non-blocking `earliest_stale_stage` malformed/ambiguous-record follow-up
is [issue #28](https://github.com/gysahlgreene/SlopForge/issues/28); that helper has
no production callers. M0 remains active until all core exit evidence below is met.

Before closing M0, retain a compact evidence record demonstrating:

- A documented clean starting state: project configuration, dependencies, workflow
  and environment versions, requirements/defaults, and actionable preflight failures.
- Brief → concept/selection → conditioning → geometry → mesh/UV → materials →
  multi-view review → explicit approval → Unity import/preview on a declared profile,
  with stage identities, provenance, and retained artifacts.
- Controlled failures stop dependent work; rejected candidates survive; resume reuses
  valid stages and invalidates affected downstream results after changes. Necessary
  interventions are supported steps or documented actions.
- The original texture-mask failure and fresh representative inputs remain covered
  by practical regression protection; structural and appearance results are distinct.
- Three representative briefs with two independent runs each as the quality contract's
  provisional initial evidence protocol, recording all failures, interventions,
  versions, and unchecked gates. Six runs alone do not establish Qualified status.
- `make verify` passes with skips reported; explicitly authorized live checks and
  human/Unity evidence cover the claimed end-to-end scope. Any remaining gaps limit
  the exit claim rather than disappearing behind passing offline tests.

Core scope is production plumbing and review/recovery reliability. Props establish
the first category quality claim. Do not close core with undefined acceptance gates
or claim category qualification from a core smoke test.

Early humanoid smoke tests are permitted only as bounded architectural checks when
needed to test core boundaries (such as rig handoff or engine delivery). Record the
question, scope, evidence, and stopping point. They do not reorder milestones,
establish character qualification, or authorize extended character quality work.
Later work otherwise needs an active-gate dependency or explicit user direction.
[Current state](CURRENT_STATE.md) records progress and outstanding evidence.
