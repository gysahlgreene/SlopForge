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

## Implementation divergences found in the documentation review

These are follow-up gaps, not implementation changes in this task.

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
- **Backend provenance:** [generation metadata](processing/comfy_generate_3d.py),
  lines 319–329, records graph/sidecar identity, seeds and model names, not installed
  custom-node revisions or verified weight identities for each run. The generated
  legacy Hunyuan graph has no file hash or sidecar.
  [Provenance projection](slopforge/provenance.py) also omits some retained metadata
  (such as mesh preparation and actual conditioning paths) from generator records.
  [Architecture](docs/ARCHITECTURE.md) and [ComfyUI](docs/COMFYUI.md) describe these limits.
- **Resume and invalidation:** [recipe resume](slopforge/recipes.py)
  (`resume_recipe`) skips completed/approved stages using persisted state; a general
  dependency/requirement/hash-based invalidation guarantee is not established.
  The model approval path also starts new processing attempts rather than providing
  universal resumability at every expensive substage.
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

## Verification during this documentation task

Checks performed on 2026-10-10 for this documentation-only change:

- `.venv/bin/python scripts/check-docs.py`: passed (local links and private metadata).
- `git diff --check`: passed.
- `make verify PYTHON=.venv/bin/python`: passed; 237 tests and 49 subtests passed,
  6 skipped, 3 existing Pillow deprecation warnings. Compile, documentation and
  whitespace checks also passed; available deterministic Blender fixtures ran.
- Skips: opt-in Blender animation retarget, live ComfyUI 2D and 3D inference,
  real Rigify smoke, external SkinTokens runtime, and live workflow preflight.
- Initial plain `python scripts/check-docs.py` was unavailable because `python`
  was not on PATH; system `python3` lacked Pillow. Plain `make verify` failed
  collection with 20 import errors in that interpreter. Using the existing project
  virtual environment, as documented in Contributing, resolved the environment
  mismatch without dependency or runtime changes.
- The six contracts/state/agent documents were reviewed together and compared with
  configuration, manifests, pipeline code, operational guides and public evidence;
  an independent read-only review found no substantive contradictions.

No live inference, new asset generation, visual approval, deformation review, or
Unity playback was performed. No product functionality, schema, workflow settings,
dependencies, or runtime statuses changed. Existing regression fixtures and public
checks provide protection for this documentation change; no new runtime tests were
needed. Historical `make verify` / `make verify-live` results in the recovery and
benchmark reports remain historical, not reruns or expanded qualification claims.
