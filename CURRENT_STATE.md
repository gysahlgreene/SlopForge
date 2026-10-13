# Current state

## Direction and evidence scope

Follow the [product contract and document precedence](docs/PRODUCT_CONTRACT.md),
[pipeline contract](docs/PIPELINE_CONTRACT.md),
[quality contract](docs/QUALITY_CONTRACT.md), and [roadmap](ROADMAP.md).
M0 core reliability is active; props are the next category gate. Historical
humanoid work is bounded evidence, not the next production milestone.

Contracts describe intended behavior. The inventory below separates recorded
historical evidence, current implementation inspection, and checks performed during
this documentation task. Code existence does not establish production readiness.
No broad category/workflow/profile is claimed Qualified here.

## Capability inventory

| Capability | State | Evidence and limits |
| --- | --- | --- |
| Prop execution lineage and safe reuse | Implemented; deterministic offline Package 2 verification passed | v4 manifest records content-addressed prop stage outputs. Approval resume, recipe prop-child reuse, and `retexture` processed-mesh reuse check stage inputs/settings, artifact lineage, and hashes; stale decisions preserve prior stage history. Exact backend weight/node revisions may remain unknown, and publication outputs are not a resume cache. No live inference or visual qualification claim |
| Offline verification baseline | Verified working for tested coverage | Canonical checks and this task's results below; opt-in/live gates remain separate |
| Texture-mask failure recovery | Verified working for the recorded failure class | [Recovery report](docs/media/texture-mask-recovery-2026-10/README.md): wrong transparency/foreground polarity, explicit inversion in four graphs, static/queue preflight, native loader/crop checks for narrow/broad/RGB inputs |
| Corrected material generation and Blender delivery | Partially working | Recovery report retains failed input/seed, a fresh humanoid and a repeat through colored 4096² maps, resolved textures, FBX and four-view renders; atlases vary; surface blotches, face/detail defects and three fresh-model components remain |
| Unity prop delivery | Partially working; asset-specific historical example | [Public example](README.md) and [commands](docs/EXAMPLES.md) show prop mesh/material import; visible reconstruction defects remain; no representative prop qualification record |
| Humanoid import and movement | Partially working; historical asset-specific evidence | [Humanoid test 1](docs/media/character-qualification-2026-10/basalt-warden-unity-preview/README.md): valid Avatar and walk movement; arm deformation under review, topology defects; not production-cleared |
| Body-deformation benchmark | Partially working; historical asset-specific review | [Diagnostic benchmark](docs/media/character-qualification-2026-10/basalt-corrected-humanoid/README.md): reviewed delivered body rig and Unity motion; source visual quality rejected; separate final-tier source pending review, not covered by rig approval |
| Fine detail/material fidelity and general rig recovery | Known unreliable | Recovery and benchmark reports retain visual defects; prior humanoid test 3's recovered rig remains rejected as recorded before this task; it is not promoted by these contracts |
| Cross-brief/category repeatability | Unverified | No declared-criteria record covering the provisional three-brief/two-independent-run protocol or broader qualification was established in this task |
| Modular environment, mechanical and creature/Generic runtime quality | Unverified | Recipes, kits and rig tooling are capabilities; representative visual, performance, deformation and runtime evidence is still required |
| Complete readiness/qualification claims | Blocked by missing acceptance/enforcement evidence | Project requirements and thresholds must be declared and applicable gates checked; gaps below prevent inferring readiness from `ready` or `qualified` runtime labels |

The recovery report historically described qualification of a failure class. Under
the quality contract this is bounded regression/recovery evidence, not a complete
category qualification record. Older Unity measurements establish only the stated
asset and checked gates. None of these examples satisfies the independent-run
protocol by itself.

The guided workflow remains development work in the registered
`feat/guided-character-to-unity` worktree, confirmed by `git worktree list` during
this task. Preserve it; its existence is not integration or qualification evidence.

## Remaining gaps after Package 1

These gaps remain outside Package 1 or require separate evidence.

- **Qualification vocabulary:** [model pipeline](slopforge/pipelines/model.py),
  lines 414 and 423, calls an individual mesh attempt `qualified` when it has a
  structurally viable material candidate. Line 250 uses the term in an error too.
  This is not the quality contract's category/workflow/profile Qualified status.
- **Project requirements and readiness:** [configuration](slopforge/config.py)
  (`DEFAULTS`, `load_project`) and [project template](templates/project.yaml)
  provide processing defaults, tiers and budgets without a complete acceptance
  profile. [Model validation](slopforge/validation.py) checks files, mesh measures
  and optional topology limits, not all visual/style/performance/runtime requirements.
  [Material approval](slopforge/pipelines/model.py), line 297, sets `ready` after
  publication/Unity material creation, without evidence of all project/runtime gates.
- **Backend provenance limits:** generation sidecars and mesh stage records now retain
  source/effective graph identity, effective bindings, content hashes, and backend
  facts surfaced by the existing health boundary. Exact model weights and custom-node
  revisions remain unavailable unless ComfyUI exposes trustworthy revisions; the
  synthesized Hunyuan graph has no source file hash. Live provider-version coverage
  was not exercised during Package 1 implementation.
- **Resume and invalidation limits:** prop approval resume now reuses compatible
  lineage-backed work and restarts at the earliest stale prop boundary. Recipe
  resume applies this check only to prop/model children; other recipe handlers keep
  their existing behavior. Missing/unknown provenance remains conservative, and
  relocation is unsupported. Broad failure classification and retry policy remain
  Package 3 work; this implementation does not provide a generic workflow scheduler.
- **Evidence terminology in operational guides:** [workflow levels](docs/WORKFLOWS.md)
  use provider capability labels such as `visually_qualified` and `production_default`;
  [agent integration](docs/AGENT-INTEGRATION.md) calls repair resolution 120 qualified.
  These bounded labels/settings must not be read as the quality contract's Qualified
  category status. [Setup](docs/SETUP.md), sections 4 and the approval description,
  still center Hunyuan/swatch instructions while the current template selects TRELLIS.
  Reconcile operational wording in a separate implementation/documentation follow-up.
- **Evidence coverage:** offline fixtures and historical examples do not establish
  cross-brief consistency, declared performance thresholds, fresh Unity playback,
  or every category's visual/deformation gates. The new provisional protocol has
  not been run here; six runs would still require declared qualification criteria.

## Verification during Package 1 implementation

Checks performed on 2026-10-10 for Package 1 implementation:

- `make verify` using the repository's existing virtual-environment interpreter: passed;
  263 tests and 49 subtests passed, 6 skipped, with 3 existing Pillow deprecation
  warnings. Compile, documentation, metadata and whitespace checks passed; available
  deterministic Blender fixtures ran.
- Package 1 lineage, manifest, provenance, mesh-PBR, texture-publication and ComfyUI
  focused suite: 62 passed and 6 subtests passed.
- Skips: opt-in Blender animation retarget, live ComfyUI 2D and 3D inference,
  real Rigify smoke, external SkinTokens runtime, and live workflow preflight.
- No live inference, new asset generation, visual approval, deformation review, or
  Unity playback was performed. These results establish deterministic offline
  Package 1 state and persistence behavior only; they do not qualify output quality,
  readiness, reuse, invalidation, or automatic resume. Historical `make verify` /
  `make verify-live` results in the recovery and benchmark reports remain historical.

## Prop reuse policy evidence

Task 1 of Package 2 adds a fixed-stage policy, not an integrated resume workflow.
On 2026-10-10, `.venv/bin/python -m pytest tests/test_prop_reuse.py
tests/test_manifest.py -q` passed with 21 tests and 5 subtests. Coverage includes
content integrity, output identity, Package 1 output-specific lineage subsets,
unknown stage rejection, and append-only decisions. `make verify
PYTHON=.venv/bin/python` passed with 273 tests, 6 opt-in skips, 3 existing Pillow
deprecation warnings, and 52 subtests. Documentation and whitespace checks passed.
No caller integration, automatic resume, live inference, visual review, or Unity
playback was exercised; these results do not establish asset readiness or pipeline
qualification.

## Safe resume and invalidation evidence

On 2026-10-10, `make verify PYTHON=.venv/bin/python` passed after Package 2 changes:
306 tests and 58 subtests passed, 6 opt-in checks skipped, and 3 existing Pillow
deprecation warnings were reported. Compile, documentation, metadata, and whitespace
checks passed. The focused package suite passed 91 tests and 11 subtests. Deterministic
coverage includes identical reuse, concept/geometry/material/processing invalidation,
missing and hash-mismatched artifacts, interruption and failed-stage resume, recipe
reload decisions, `retexture` lineage, unknown legacy provenance, duplicate filenames
with different content, style/conditioning validation, worker stage integrity checks,
and stale recipe child handling. The initial canonical run exposed an outdated test
expectation for a processed mesh with no recorded lineage; it was changed to require
recomputation and passed on rerun.

These checks establish deterministic control flow and manifest persistence only.
The opt-in Blender/live ComfyUI/provider checks remained skipped. No inference quality,
appearance, qualification, readiness, or Unity runtime claim is established.

### Remaining Package 2 provenance review

On 2026-10-13, focused regressions confirmed that malformed authoritative members
invalidate publication readiness and processed-mesh reuse. The Package 2 focused
suite passed: 155 tests and 11 subtests. `make verify PYTHON=.venv/bin/python` passed
on an unrestricted rerun; the sandboxed run had unrelated Blender 5.1 subprocess
segfaults and a loopback bind permission failure. Six opt-in checks remained skipped.
This verifies offline structural decisions only; it does not establish inference
quality, appearance, readiness qualification, or Unity runtime behavior.

The earlier follow-up validated selected publication and processed-mesh provenance
collections; it did not establish that every execution and stage sibling was valid.
Reuse now validates all execution IDs before resolving candidate identity, rejects
malformed execution stage collections, validates every stage record in the selected
execution, and validates every stage record in an adoption collection before matching.
Output contracts are explicit for reusable stages whose producers and consumers
require them: conditioning preparation, mesh workflow execution, material
generation, material map acquisition, and material assembly export. Material
generation accepts its swatch plus metadata route or the base color, normal,
roughness, and metallic outputs recorded by a textured mesh worker. Other recorded
worker outputs remain optional where the producer/consumer path permits absence.

Recipe artifact synchronization validates each artifact record before indexing;
malformed records invalidate current readiness before synchronization. Resume removes
unusable malformed records from the active artifact map, proceeds through stale
regeneration, and retains valid prior outputs as superseded history.

The Package 2 focused suite passed: 211 tests and 14 subtests across
`test_prop_reuse.py`, `test_prop_lineage.py`, `test_mesh_pbr.py`, `test_recipes.py`,
and `test_manifest.py`. Unrestricted `make verify PYTHON=.venv/bin/python` passed:
426 tests, 61 subtests, 6 opt-in skips, and 3 existing Pillow deprecation warnings;
compile, documentation metadata/link, and whitespace checks passed. The restricted
run had 9 failures caused by Blender 5.1 subprocess SIGSEGVs and loopback bind
permission denial; the unrestricted rerun passed. No live inference, visual review,
readiness qualification, deformation review, or Unity runtime checks were performed.
