# Quality contract

Follow the [product contract and document precedence](PRODUCT_CONTRACT.md).
Read with the peer [pipeline contract](PIPELINE_CONTRACT.md). This contract defines
acceptance and qualification criteria; [quality tiers](QUALITY-TIERS.md) configure
generation settings and budgets, not approval or evidence status.

## Asset acceptance

Acceptance is relative to a recorded brief, category, workflow version, and project
target profile. Declare applicable requirements, thresholds, review method, and
review authority before evaluating success. A target profile states the intended
Unity environment, rendering, use, and technical/performance constraints; do not
invent platforms or budgets. Explicit project defaults are allowed. Missing
requirements or undefined acceptance thresholds remain unknown and prevent claims
of readiness or qualification for the affected scope. A non-applicable gate needs
a recorded reason; an unchecked gate is not a pass.

| Dimension | Required assessment |
| --- | --- |
| Visual | Silhouette, proportions, recognizable detail, material placement/coverage, defects, and fidelity to brief/concept from multiple views |
| Structural | Usable geometry, topology, connected components, finite bounds, UVs and mesh/map identity; constraints depend on intended category/use |
| Technical | Scale, orientation, transforms, pivots, file formats, texture channels/dimensions, references, required collision/LOD data, and compatible import settings |
| Style | Project style and references, consistency with related assets, and explicit deviations |
| Performance | Project-declared geometry, textures, materials, rig/animation and runtime budgets under stated measurement conditions |
| Deformation | For rigged assets: weights, bind/rest pose, articulation under representative motions, and human review of defects; smaller pose ranges do not qualify a failing rig |
| Runtime | Unity import, material/render compatibility, intended scene use, and playback/root-motion/Avatar checks where applicable |

Keep structural, visual/material/style, deformation, and runtime results separate.
Passing tests or exporting a file cannot establish appearance, rig quality, or
engine behavior. Approval records the exact candidate/artifacts, requirements,
reviewer/authority, decision, evidence, remaining limits, and unchecked gates.
A scoped approval must not be presented as complete game readiness.

## Pipeline evidence status

Asset approval and pipeline qualification are independent. An approved asset proves
its reviewed gates; a qualified workflow still requires review of each new asset.
The following are evidence-backed documentation statuses, not runtime schema changes.
Every status claim names its category, workflow version/hash, target profile,
tested conditions, evidence, and limits.

| Status | Meaning |
| --- | --- |
| Experimental | Capability is being explored; available tests/results and failures are recorded, with no reliability claim |
| Provisional | Repeated evidence supports a bounded scope, but declared qualification criteria are not yet met; interventions and unchecked gates remain explicit |
| Qualified | Evidence satisfies all declared qualification criteria for the stated scope, including applicable review/runtime gates and acceptable failure/recovery behavior |

No run count automatically confers Qualified status. Missing requirements or
undefined thresholds prevent that claim. Declare representative inputs, independence,
success/failure criteria, permitted interventions, recovery expectations, and required
gates in a qualification record. Changes to workflow, environment, requirements,
or scope require assessing whether existing evidence still applies. Criteria may
evolve here without changing the product definition; record the criterion version
and reassess affected claims rather than retroactively treating old evidence as new.

## Provisional initial evidence protocol

Start with three representative briefs for the stated category/profile and two
independent runs of each. This six-run protocol is explicitly provisional initial
evidence, not a sufficient qualification rule. Define independence (including seed
and fresh execution conditions) in the record; replaying one successful candidate
is useful regression evidence but not a second independent production run.

Record every success and failure, selected/rejected candidates, seeds, inputs,
versions, effective settings, interventions and their reasons, stage outcomes,
review decisions, elapsed/resource measurements when available, and unchecked gates.
Retain failed artifacts and provenance. Summarize asset results separately from
repeatability and report uncertainty. Further evidence must satisfy declared
qualification criteria, rather than merely increasing the count of successes.

Historical mask recovery or Unity character demonstrations retain their original
scope; they do not establish broader prop or character qualification. See
[Current state](../CURRENT_STATE.md) for evidence and implementation divergences.
