# Product contract

SlopForge provides a project-aware, repeatable pipeline for producing reviewed,
game-ready assets with generative models and deterministic processing tools.
The objective is a reliable production process, not a single impressive asset.

## Priorities

In order: pipeline reliability; reproducibility and observability; correct asset
structure; project/style consistency; asset quality; performance; convenience;
new features. A change must preserve higher priorities when improving lower ones.
Keep the user workflow simple and expose review decisions rather than internal
implementation details.

## Core workflow

Brief and project style → explicit prompt → concept candidates → concept review
→ geometry → mesh preparation and UVs → materials → multi-view review → approval
→ Unity delivery. Characters additionally require readiness, rig deformation
review, animation compatibility, and engine playback qualification.

Every stage has explicit inputs, retained outputs, provenance, and validation.
Preserve successful stages when resuming; retain failed candidates for diagnosis.
Make invalid states visible and stop before promoting them or running dependent
stages. Keep 2D, 3D, and surface-swatch routes explicit.

## Quality and correctness

Generative appearance varies. That does not excuse broken deterministic processing.
Required pipeline behavior includes correct input/workflow selection, readable
outputs, asset and generation identity, matching mesh/material maps, completed
processing, explicit review states, and stage-specific failures with useful remedies.
Human review remains necessary for appearance and deformation.

Equivalent valid inputs and configuration must execute the same documented
process. Record seeds, workflow hashes, model/environment versions where available,
and intermediate artifacts. Exact pixels and meshes across hardware versions are
not a reproducibility guarantee.

These are product requirements, not a claim that every stage is already qualified.
[Current state](../CURRENT_STATE.md) records verification and outstanding work.
Agents implement this contract; changes to product priorities, scope, review gates,
or milestone order require explicit user direction.
