# Pipeline contract

Follow the [product contract and document precedence](PRODUCT_CONTRACT.md).
Read with the peer [quality contract](QUALITY_CONTRACT.md). These are required
invariants; record enforcement gaps in [Current state](../CURRENT_STATE.md).

## Requirements and stage boundaries

Resolve the brief, category, project context, explicit overrides, and target
profile before claiming readiness. Retain effective requirements and their sources.
Missing requirements remain unknown; explicit project defaults are allowed.
Processing settings may enable a preview without establishing project acceptance.
A structural pass, export, or preview is a capability result, not asset approval
or readiness against unchecked requirements.

| Stage | Required inputs | Retained outputs and validation boundary |
| --- | --- | --- |
| Brief/context | Semantic brief, category, project style/references and requirements | Effective brief, prompt, defaults/overrides, target profile and unresolved requirements; unknown acceptance gates are visible |
| Concept | Resolved context and workflow configuration | Readable candidates, asset/candidate/generation identity, provenance, rejection and explicit selection |
| Conditioning | Selected concept and route-specific preparation | Source and actual conditioning image; explicit foreground-mask polarity; crop preserves subject and colors |
| Geometry | Conditioning, workflow and seed | Parseable nonempty GLB, raw source, metadata and link to the selected concept; preserve failed attempts |
| Mesh/UV preparation | Current raw mesh and recorded processing settings | Prepared mesh, usable UVs, finite geometry, triangle/topology/scale measures; repairs checked against declared requirements; preserve closed geometry |
| Material inference/bake | Current mesh/UVs and generation-specific texture field or explicit swatch route | Required readable PBR maps with checked dimensions, identity and mesh correspondence; actual conditioning and generation metadata |
| Blender assembly | Current mesh and maps | Resolved image/node references, preserved UVs, inspection report, front/side/rear/three-quarter review renders |
| Asset review/approval | Structural results, requirements and visual evidence | Separate gate outcomes and explicit decision tied to exact candidate/artifacts; rejection retains evidence; invalid outputs never promoted |
| Rigging, when required | Approved model/materials, rig requirements and readiness report | Bones, weights, bind/rest transforms, source rig and exports, deformation evidence and explicit review; failed recovery remains unapproved |
| Animation, when required | Reviewed rig, licensed compatible source and motion requirements | Retargeted clips, compatibility/root-motion checks, separate deformation and playback evidence |
| Unity delivery | Approved exports/maps and declared Unity/render-pipeline requirements | Import and material-reference results, Avatar when required, runtime/Play evidence for intended use; playback when animation is required |

## Provenance, review, and resuming

Each stage must identify its inputs, outputs, asset/candidate/generation, configuration,
validation, decisions, and dependencies. Retain prompts, references, seeds, effective
settings, graph hashes, workflow versions, model identities, environment/backend
versions and interventions. Unknown or unavailable versions/hashes must be recorded
as unknown, not inferred from a filename or a requirement declaration. Hashes
identify artifacts; graph hashes alone do not pin installed nodes or weights.
Keep large diagnostics and private machine details outside public Git.

Separate structural validation, visual/material/style review, deformation review,
and engine checks. Preserve the human authority defined by the product contract.
An approval applies to its recorded asset, scope, and artifacts; it does not qualify
a workflow. Changing an input, processing result, or requirement invalidates affected
downstream evidence and decisions while preserving their history.

Resume from retained artifacts whose identity, dependencies, and checks remain valid.
Record completed, failed, blocked, unknown, and not-run stages distinctly in evidence;
do not silently rerun successes, reuse stale approvals, or discard failed candidates.
These are evidence requirements, not new runtime enum values.

## Failure reporting and recovery

Identify the earliest failed stage, relevant identity, failed invariant, evidence,
and actionable remedy; mark dependent stages as not run or blocked. Preflight
configuration, paths, nodes, models, and invalid graph connections before expensive
inference. Configuration errors must not consume speculative generation retries.

A necessary manual repair must become supported processing or an explicit documented
user action. Do not bypass approvals or loosen validation to make a case pass.
Preserve the failing case, compare a known baseline, and change one relevant variable
at a time. Follow the root-cause and two-attempt policy in [AGENTS.md](../AGENTS.md).

Uniform or dark maps can be intentional. Check identity and loading structurally,
then appearance against the brief/concept. The transparency-mask regression is
caught by graph validation and crop preservation, not universal brightness limits.

## Verification and architectural boundaries

`make verify` runs syntax, fixture/unit/CLI, public-documentation, and whitespace
checks. Installed Blender enables deterministic fixtures; report unavailable and
opt-in coverage. `make verify-live` explicitly opts into service preflight and real
2D/3D inference with Blender. Neither replaces human review or Unity playback.

Regression protection tests invariants rather than exact generative images. Reuse
existing manifest, candidate, material, readiness, and Blender fixtures. Mask checks
live in `tests/test_comfyui_service.py`, `tests/test_workflow_requirements.py`, and
`scripts/check_comfy_mask_polarity.py`; the last uses ComfyUI's Python and actual nodes.

[Architecture](ARCHITECTURE.md) is the implementation-boundary reference:
`slopforge/` owns orchestration/state; `slopforge/backends/`, `processing/`, and
`workflows/` own ComfyUI integration; `blender/` owns mesh/material processing;
`templates/` owns installation scaffolding. Put early-detectable failures in existing
preflight or `doctor`, preserving these boundaries.
