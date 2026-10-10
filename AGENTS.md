# Working on SlopForge

## Objective

Build a repeatable pipeline for models, textures, materials, rigging, animation,
and engine delivery. A fresh session or developer must be able to reproduce
qualified results using the repository, without knowledge from an earlier chat.
One successful asset is evidence for that asset, not proof of pipeline reliability.

Before substantial work, read [Product contract](docs/PRODUCT_CONTRACT.md),
[Pipeline contract](docs/PIPELINE_CONTRACT.md),
[Quality contract](docs/QUALITY_CONTRACT.md), [Roadmap](ROADMAP.md), and
[Current state](CURRENT_STATE.md). Follow the product contract's document precedence;
expose and reconcile contradictions between peer contracts. AGENTS governs working
behavior, not independent product direction. User instructions take precedence.
Work on the active milestone; later work requires a dependency of its gate or
explicit user direction. Tests/validation check contracts; implementation must
satisfy them. Update current state with verified evidence and visible gaps.

Before changing a generation or delivery stage, read its existing implementation
and relevant guidance in [the documentation index](docs/README.md). For generation
settings and environment requirements, consult [Quality tiers](docs/QUALITY-TIERS.md),
[ComfyUI](docs/COMFYUI.md), [Workflows](docs/WORKFLOWS.md), and
[Agent integration](docs/AGENT-INTEGRATION.md). Preserve the boundaries in
[Architecture](docs/ARCHITECTURE.md). Follow [Contributing](CONTRIBUTING.md) for
changes and public evidence.

## Turn discoveries into durable fixes

When a pitfall, environment quirk, ordering requirement, fragile step, or failure
mode appears:

1. Preserve the failing inputs, seed, configuration, intermediate outputs, and
   relevant environment versions. Read existing notes and compare a qualified
   baseline before changing the approach.
2. Identify the root cause with a controlled reproduction. Change one relevant
   variable at a time; distinguish observations from hypotheses.
3. Fix the shared pipeline and every affected caller. Encode required knowledge
   in the appropriate scripts, configuration, validation, prompts, or tooling.
   Turn required manual repairs into supported pipeline steps.
4. Add a focused regression check and early validation where possible. Invalid
   prerequisites or outputs must stop with an actionable error before expensive
   downstream work or approval. Preserve failed candidates and provenance.
5. Update the relevant guide with the cause, remedy, prerequisites, and verified
   limits. Document any necessary step that cannot be automated. Keep private
   machine details and large diagnostic artifacts outside public Git.
6. Verify from the documented starting state through the affected downstream
   stages. Recheck the original failing case and fresh representative inputs.
   Record what passed and what remains unverified.

Repeated commands, similar retries without new evidence, recurring assumptions,
manual output repairs, or reliance on chat-only knowledge trigger a stop and
root-cause reassessment. Improve the repository before resuming production;
an unresolved diagnosis must leave a reproducible case and clear next check.

After two attempts without materially new evidence, stop implementation changes.
Record known facts, assumptions, what each attempt tested, and its results.
Identify the last correct and first incorrect artifacts, then instrument their
boundary. Each further attempt must eliminate a hypothesis or add evidence.

## Qualification

Keep structural validation, visual material review, deformation review, and
engine playback checks separate. Passing tests or reducing review pose ranges
does not qualify an asset's appearance or rig. Preserve review gates; publish
success evidence only for stages actually checked. State asset-specific results
and pipeline repeatability separately, with the tested conditions and limits.
Use Experimental, Provisional, and Qualified only with the scope and evidence
required by the quality contract. The three-brief/two-independent-run protocol is
provisional initial evidence; six runs do not automatically qualify a pipeline.
Unknown requirements and undefined thresholds prevent the affected readiness claim.

Run `make verify` before declaring implementation complete. Use `make verify-live`
for explicitly authorized inference checks; expose unavailable or skipped coverage.
Improve verification when it misses a discovered failure. For substantial
completion reports, state goal, root cause, changes, regression protection,
verification evidence, and remaining uncertainty. Preserve architectural boundaries
from the architecture guide and keep personal diagnostics outside public Git.
