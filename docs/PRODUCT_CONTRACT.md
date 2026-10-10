# Product contract

SlopForge is a project-aware pipeline for producing reviewed 3D assets for Unity.
It connects stochastic generation to deterministic engineering, retaining enough
inputs, decisions, and evidence for a fresh developer to reproduce the documented
process. One impressive asset does not establish pipeline reliability.

## Authority and precedence

User instructions take precedence. Repository direction follows this order:
Product contract → Pipeline and Quality contracts → Roadmap → Current state →
architecture and implementation documentation → incidental implementation.
[Pipeline](PIPELINE_CONTRACT.md) and [Quality](QUALITY_CONTRACT.md) are peer
contracts: expose and reconcile contradictions between them rather than silently
choosing one. Tests check contracts; existing code does not redefine them.
[AGENTS.md](../AGENTS.md) governs working behavior without independently defining
product direction. Changes to product scope, priorities, review authority, or
milestone order require explicit user direction.

## Users, priorities, and scope

Intended users are Unity developers and small teams, including artists and agents
working with them, who need consistent assets in an existing game's context.
The production unit is an asset in a project, not an isolated prompt result.

Priorities, in order: pipeline reliability; reproducibility and observability;
correct asset structure; project/style consistency; asset quality; performance;
convenience; new features. Improving a lower priority must preserve higher ones.
Keep the user workflow simple and expose decisions and useful failures.

Scope includes props, modular environments, weapons and mechanical assets,
humanoids, creatures and Generic rigs, with models, textures, materials, rigging,
animation, review, and Unity delivery as applicable. Category expansion follows
[the roadmap](../ROADMAP.md), not the mere availability of implementation.
Supporting 2D concepts, references, masks, conditioning images, surface swatches,
and review renders remain internal production artifacts for 3D assets.

Non-goals are a standalone 2D asset product, a general engine-independent content
platform, building whole games, replacing artistic judgment, and promising
universally game-ready output from a prompt. No target platform or performance
budget is universal; each project's declared target profile supplies those needs.

## Project inheritance and human authority

An asset inherits project style, references, scale conventions, technical and
performance requirements, and delivery expectations. Asset-specific overrides
must be explicit and retained with the effective requirements. Missing requirements
remain unknown. Explicit project defaults are permitted when recorded as defaults;
a toolkit processing fallback is not evidence of a project's acceptance threshold.
Unknown requirements may permit processing or preview, but prevent a claim of
readiness against those requirements.

Automate progressively as stages become observable and reliable: preparation,
validation, recovery, and delivery should reduce repeated manual work. Automation
must preserve review gates and human authority over appearance, style, deformation,
and final acceptance. Agents may propose, inspect, and operate stages; approval
requires the user's decision or explicit delegated authority for a stated scope.

## Production process and correctness

Brief and project context → concept candidates and selection → conditioning →
geometry → mesh/UV preparation → materials → multi-view review → asset approval
→ Unity delivery and runtime checks. Rigged assets also require readiness,
rigging, deformation review, animation compatibility, and engine playback checks.
Keep mesh-aware materials and surface-swatch routes explicit.

Generative appearance varies. Deterministic engineering must still select the
correct inputs/workflow, retain identity and provenance, match meshes and maps,
validate processing, preserve review states, and report stage-specific failures.
Equivalent valid inputs and configuration must follow the same documented process;
exact pixels or meshes across hardware/software versions are not guaranteed.
Preserve valid stages on resume and failed candidates for diagnosis.

These are requirements, not claims of current qualification. The
[pipeline contract](PIPELINE_CONTRACT.md) defines stage invariants; the
[quality contract](QUALITY_CONTRACT.md) defines acceptance and qualification;
[current state](../CURRENT_STATE.md) records evidence and enforcement gaps.
