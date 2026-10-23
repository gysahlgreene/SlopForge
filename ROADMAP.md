# Roadmap

Follow the [product contract and document precedence](docs/PRODUCT_CONTRACT.md),
[pipeline contract](docs/PIPELINE_CONTRACT.md), and
[quality contract](docs/QUALITY_CONTRACT.md). Milestones are evidence gates, not
code inventories. This ordering replaces the earlier humanoid-preview-first sequence.

| Milestone | Status | Exit evidence |
| --- | --- | --- |
| M0 Core reliability | Closed by the owner on 2026-10-21; [exit record](docs/M0-EXIT-RECORD.md) with its gaps | The concrete core exit evidence below, with requirements/enforcement gaps visible |
| M1 Props | Provisional for static props on `h100`/`final` ([v5](docs/media/props-provisional-2026-10-v5/README.md)); the owner moved the focus to M2 on 2026-10-22, and #63 and #65 remain open; known limits in the M0 exit record | Representative static prop production through separate visual, structural, technical, style, performance and Unity gates under declared criteria |
| M2 Modular environments | Active since 2026-10-22 ([epic #89](https://github.com/gysahlgreene/SlopForge/issues/89)): **Provisional** for modular kits on `h100`/`final` (2026-10-23, criterion [M2-v3](docs/media/kits-provisional-2026-10-v3/README.md)): the stone ruin, timber house and sci-fi corridor kits, two runs each, pass the owner-accepted M2 criteria (#94) through assembled Unity scenes; the owner's visual review is pending | Reviewed modules assemble at declared scale/pivots, meet connection/repetition needs and project budgets, and work together in Unity |
| M3 Weapons/mechanical assets | After environments | Reviewed shapes/materials, moving-part hierarchy/pivots and functional motion where required, with project/runtime checks |
| M4 Humanoids | After mechanical assets; historical asset-specific checks plus three automatically rigged generated characters (deformation unapproved, no Unity evidence for them) | Representative source acceptance, rig readiness, deformation, compatible animation and Unity playback under declared criteria |
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
| Package 2 — safe resume, invalidation, and evidence-backed reuse | Reuse only valid lineage-backed artifacts and restart at the earliest stale stage; depends on Package 1 | Merged in [PR #32](https://github.com/gysahlgreene/SlopForge/pull/32); [issue #27](https://github.com/gysahlgreene/SlopForge/issues/27) is closed |
| Before Package 3 — Pi/Qwen provenance guardrails | Add adversarial provenance checks and implementation guidance before Package 3 starts | Merged in [PR #34](https://github.com/gysahlgreene/SlopForge/pull/34) (`5e3b544`); [issue #29](https://github.com/gysahlgreene/SlopForge/issues/29) closed |
| Package 3 — failure classification and bounded retries | Classify stage failures and retry only explicitly stochastic candidate failures; depends on Packages 1–2 and the guardrail tooling | Merged in [PR #36](https://github.com/gysahlgreene/SlopForge/pull/36) (`1886bc3`); plan merged in [PR #35](https://github.com/gysahlgreene/SlopForge/pull/35); [issue #31](https://github.com/gysahlgreene/SlopForge/issues/31) closed |

Malformed/ambiguous `earliest_stale_stage` records now fail closed in
[PR #38](https://github.com/gysahlgreene/SlopForge/pull/38) (`f63239a`), closing
[issue #28](https://github.com/gysahlgreene/SlopForge/issues/28). The helper still
has no production callers. M0 remains active until all core exit evidence below is met.

The owner closed M0 on 2026-10-21 on the [M0 exit evidence record](docs/M0-EXIT-RECORD.md), which maps each item below to
its evidence and gaps for static props on `h100`/`final`.

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

## Active character quality work (bounded parallel follow-up)

User-directed follow-up to M0; does not reorder milestones or claim qualification.
See [SESSION-HANDOFF](docs/SESSION-HANDOFF.md) for branch status, dirty diff scope,
and resumption instructions.

Early humanoid smoke tests are permitted only as bounded architectural checks when
needed to test core boundaries (such as rig handoff or engine delivery). Record the
question, scope, evidence, and stopping point. They do not reorder milestones,
establish character qualification, or authorize extended character quality work.
Later work otherwise needs an active-gate dependency or explicit user direction.
[Current state](CURRENT_STATE.md) records progress and outstanding evidence.
