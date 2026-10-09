# Pipeline contract

Read with [Product contract](PRODUCT_CONTRACT.md). These are required invariants;
passing a structural check does not approve visual quality. Record enforcement
gaps in [Current state](../CURRENT_STATE.md).

| Stage | Required inputs | Required outputs and checks |
| --- | --- | --- |
| Concept | Brief, style, taxonomy, workflow configuration | Readable candidate images; asset/generation identity and provenance in the manifest; explicit selection |
| Conditioning | Selected concept and route-specific background/alpha preparation | Retained source and actual conditioning image; foreground mask polarity is explicit; crop preserves subject and colors |
| Geometry | Selected concept's conditioning, recorded workflow and seed | Parseable GLB with nonempty geometry; raw source retained; generation linked to the selected concept |
| Mesh/UV preparation | Current raw mesh and configured triangle budget | Valid mesh within budget; finite coordinates; UVs present and usable; preserve closed geometry; validate repairs and topology against asset requirements |
| Material inference/bake | Current mesh, UVs, generation-specific texture field | Readable required PBR maps with valid dimensions; maps belong to this generation and mesh; retained actual conditioning and generation metadata |
| Blender assembly | Current mesh and its maps | Images load; material nodes reference the expected files; UVs preserved; inspection succeeds; front/side/rear review renders exist |
| Approval | Structurally qualified candidate and review evidence | Explicit approval links the selected candidate and its artifacts; rejection preserves evidence; invalid candidates never become approved outputs |
| Rigging | Approved model/materials and readiness report | Required bones and usable weights; deformation evidence and explicit review; failed weighting recovery remains unqualified until demonstrated correct |
| Animation | Reviewed rig, licensed compatible animation source | Valid retargeted clips, rest/bind transforms and root motion; separate deformation and playback checks |
| Unity delivery | Approved exports, maps, supported render pipeline | Successful import; resolved material references; valid Avatar when required; preview visibly animates on Play when requested |

## Failure reporting and recovery

Identify the earliest failed stage, its asset/candidate/generation, failed invariant,
relevant evidence, and actionable remedy. Mark dependent stages as not run.
Preflight configuration, paths, nodes, models, and known invalid graph connections
before expensive inference. Configuration errors are not candidate-quality failures
and must not consume a sequence of speculative generation retries.

Resume from retained valid artifacts. A manual output repair that is necessary for
success must become a supported processing step or an explicit documented user
action. Do not bypass approvals or loosen validation to make a case pass.

Uniform maps can be intentional; brightness or variation alone is not a universal
quality gate. Validate map identity and loading structurally, and inspect appearance
against the selected concept. The transparency-mask regression is caught by graph
validation and a crop-preservation check, not by rejecting all dark assets.

## Verification and architectural boundaries

`make verify` runs syntax checks, fixtures/unit/CLI tests, public documentation
checks, and whitespace checks. Installed Blender enables the existing deterministic
Blender fixtures; skip reasons identify unavailable coverage. `make verify-live`
explicitly opts into service preflight and real 2D/3D inference with Blender.
Neither command substitutes for visual/deformation review or actual Unity playback.

Regression fixtures assert invariants rather than an exact generative image.
Reuse the existing manifest, candidate, material, readiness, and Blender fixtures.
The mask regression lives in `tests/test_comfyui_service.py`,
`tests/test_workflow_requirements.py`, and `scripts/check_comfy_mask_polarity.py`.
The last check runs with ComfyUI's own Python and actual image-loading/crop nodes.

Keep orchestration and state in `slopforge/`; ComfyUI integration in
`slopforge/backends/`, `processing/`, and `workflows/`; mesh/material processing in
`blender/`; installation scaffolding in `templates/`. Preserve these boundaries
when fixing failures. Add early-detectable runtime failures to existing preflight
or `doctor` checks rather than inventing a parallel approval system.
