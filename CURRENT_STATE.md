# Current state

## Direction and evidence scope

Follow the [product contract and document precedence](docs/PRODUCT_CONTRACT.md),
[pipeline contract](docs/PIPELINE_CONTRACT.md),
[quality contract](docs/QUALITY_CONTRACT.md), and [roadmap](ROADMAP.md).
M0 core reliability is active; props are the next category gate. Historical
humanoid work is bounded evidence, not the next production milestone.

## M0 package tracking

Package 1 (execution lineage, stage state, and provenance foundation) is merged
in [PR #25](https://github.com/gysahlgreene/SlopForge/pull/25); its tracking issue
[#30](https://github.com/gysahlgreene/SlopForge/issues/30) is closed. Package 2
(safe resume, invalidation, and evidence-backed reuse) is merged in [PR #32](https://github.com/gysahlgreene/SlopForge/pull/32),
merge commit `405cc38`; tracking issue [#27](https://github.com/gysahlgreene/SlopForge/issues/27)
is closed. Its deterministic offline verification passed as recorded below.

The Pi/Qwen provenance guardrails merged in
[PR #34](https://github.com/gysahlgreene/SlopForge/pull/34), commit `5e3b544`;
[issue #29](https://github.com/gysahlgreene/SlopForge/issues/29) is closed.
That prerequisite is satisfied; local Pi/Qwen is the implementation engine, with
Codex/Luna retaining the independent quality gate. Package 3 (failure
classification and bounded retries) merged in
[PR #36](https://github.com/gysahlgreene/SlopForge/pull/36) (`1886bc3`); its plan
merged in [PR #35](https://github.com/gysahlgreene/SlopForge/pull/35) (`460dc2f`),
and issue #31 is closed. The malformed/ambiguous `earliest_stale_stage` helper
was hardened in [PR #38](https://github.com/gysahlgreene/SlopForge/pull/38)
(`f63239a`); [issue #28](https://github.com/gysahlgreene/SlopForge/issues/28) is
closed. The helper still has no production callers. M0 is not complete.

The only open M0 issue is #26; packages 1–3 are closed.

Contracts describe intended behavior. The inventory below separates recorded
historical evidence, current implementation inspection, and checks performed during
this documentation task. Code existence does not establish production readiness.
No broad category/workflow/profile is claimed Qualified here.

## Capability inventory

| Capability | State | Evidence and limits |
| --- | --- | --- |
| Prop execution lineage and safe reuse | Implemented; deterministic offline verification passed; one prior live boundary is not rechecked | v4 manifest records content-addressed prop stage outputs. A worker defect was fixed so `mesh_workflow_execution` remains running until the orchestrator records its final `mesh.glb`; another fix passes the stage-handle context through native material completion. Regression tests and `make verify-provenance` pass. A pre-fix local M0 resume run requeued shape/texture because the prior mesh stage had no `mesh.glb`; post-fix live reuse was not rerun, so that behavior remains unverified. Exact backend weight/node revisions may remain unknown, and publication outputs are not a resume cache. No workflow qualification claim |
| Offline verification baseline | Verified working for tested coverage | Canonical checks and this task's results below; opt-in/live gates remain separate |
| Package 3 failure handling | Merged; deterministic offline verification passed | Structured failure records, bounded topology-budget mesh retries, resume accounting, and unknown remote-outcome stop are merged in PR #36. See the [Package 3 plan](docs/superpowers/plans/2026-10-14-failure-classification-retries.md) and verification record below. No live inference, visual, Unity runtime, or qualification claim |
| Texture-mask failure recovery | Verified working for the recorded failure class | [Recovery report](docs/media/texture-mask-recovery-2026-10/README.md): wrong transparency/foreground polarity, explicit inversion in four graphs, static/queue preflight, native loader/crop checks for narrow/broad/RGB inputs |
| Corrected material generation and Blender delivery | Partially working | Recovery report retains failed input/seed, a fresh humanoid and a repeat through colored 4096² maps, resolved textures, FBX and four-view renders; atlases vary; surface blotches, face/detail defects and three fresh-model components remain |
| Unity prop delivery | Partially working; six-run import evidence | 2026-10-20: six fresh runs of three briefs imported through `unity-preview` into Unity 6000.6.3f1 / URP 17.6.0 with the Lit material assigned and a four-view batch render ([evidence](docs/media/props-provisional-2026-10/README.md)); no `approve-texture` publication, Play-mode or in-scene check. Earlier: The source lantern passed configured structural checks and imported into Unity 6000.6.3f1 / URP 17.6.0 with stable GUID/importer settings. Three private Blender refinement probes found opaque window faces, a neutral 1×1 normal map, and strongly mottled body material; a localized core/glass edit did not resolve the visual gap and was not promoted. Repair likely requires substantial body/window reconstruction. Material/visual approval is pending; the refined FBX was not imported into Unity, and no Play-mode or category qualification record exists |
| Humanoid import and movement | Partially working; historical asset-specific evidence | [Humanoid test 1](docs/media/character-qualification-2026-10/basalt-warden-unity-preview/README.md): valid Avatar and walk movement; arm deformation under review, topology defects; not production-cleared |
| Body-deformation benchmark | Partially working; historical asset-specific review | [Diagnostic benchmark](docs/media/character-qualification-2026-10/basalt-corrected-humanoid/README.md): reviewed delivered body rig and Unity motion; source visual quality rejected; separate final-tier source pending review, not covered by rig approval |
| Fine detail/material fidelity and general rig recovery | Known unreliable | Recovery and benchmark reports retain visual defects; prior humanoid test 3's recovered rig remains rejected as recorded before this task; it is not promoted by these contracts |
| Cross-brief/category repeatability | Experimental (props, `h100`/`final`, commit `4d3ea32`) | [Qualification record v1](docs/media/props-provisional-2026-10/QUALIFICATION-RECORD.md) and six runs: crate and jug passed every technical criterion in both runs, but by the record's concept criteria A1 (no straps) and both jug runs (no three-quarter view) are concept-stage failures, so only A2 passes every stage; both lantern runs missed the declared emissive region, so the set is not Provisional. Visual approval pending; no failure rate; no other categories |
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

## Active character quality work (bounded parallel follow-up)

On 2026-10-16, the Aster-9 geometry-only review confirmed that material maps do
not supply the missing modeled suit forms, while existing topology totals do not
locate individual defects. Opened [issue #40](https://github.com/gysahlgreene/SlopForge/issues/40),
related to [character pipeline issue #14](https://github.com/gysahlgreene/SlopForge/issues/14),
with a proposed source-review and approval gate. The design and implementation
plan are in `docs/superpowers/specs/2026-10-16-character-source-quality-design.md`
and `docs/superpowers/plans/2026-10-16-character-source-quality.md`.

This is a separate user-directed bounded track, not a roadmap reordering.
Do not change milestone order or claim qualification. See
[SESSION-HANDOFF](docs/SESSION-HANDOFF.md) for branch status, dirty diff scope,
and verified resumption instructions.

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
  relocation is unsupported. Package 3 failure classification and bounded
  retries are merged; they do not provide a generic workflow scheduler.
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

On 2026-10-13, the remaining Package 2 provenance findings were fixed. The prop child
reuse decision validates every execution record's `id`, `status`, `identity_inputs`,
and `stages` fields before candidate execution matching; valid unrelated records do
not affect identity selection, and duplicate candidate IDs remain ambiguous. The
swatch material producer now writes a basecolor artifact, and reuse requires the full
producer map set: `texture.basecolor`, `texture.normal`, `texture.roughness`,
`texture.metallic`, `texture.metallic_gloss`, and `texture.emission`.

Earlier Package 2 provenance regressions covered malformed publication and
processed-mesh records, selected execution stage records, and adoption collection
validation. These checks and their history remain part of the offline coverage.

The Package 2 focused suite passed: 220 tests and 14 subtests across
`test_prop_reuse.py`, `test_prop_lineage.py`, `test_mesh_pbr.py`, `test_recipes.py`,
and `test_manifest.py`. Unrestricted `make verify PYTHON=.venv/bin/python` passed:
435 tests, 61 subtests, 6 opt-in skips, and 3 existing Pillow deprecation warnings;
compile, documentation, metadata, and whitespace checks passed. The restricted run
hit Blender 5.1 subprocess SIGSEGVs and loopback bind permission denial; the
unrestricted rerun passed. This verifies offline structural decisions only; it does
not establish inference quality, appearance, readiness qualification, or Unity
runtime behavior.

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

## Package 3 verification

On 2026-10-15, independent review found malformed topology metrics could pass
validation or raise; the fix rejects booleans, non-finite/negative counts, and
oversized integers with `metric_invalid`, with four regression tests. The synced
branch's unrestricted `make verify PYTHON=.venv/bin/python` passed: 589 tests,
76 subtests, 6 opt-in skips, and 3 existing Pillow deprecation warnings.
Documentation and whitespace checks passed. The sandbox-restricted run produced
9 environment failures (Blender 5.1 subprocess SIGSEGVs and loopback bind denial);
the unrestricted rerun passed. PR #36 merged as `1886bc3`; GitHub's required
second-person approval was bypassed by the repository owner after independent
review and passing checks.

These results verify offline behavior only. Package 3 is merged. Live ComfyUI
inference, Unity runtime, visual/material review, and asset or pipeline
qualification were not performed. M0 remains incomplete.

## Texture/material quality track (bounded; no qualification claim)

Opened issues [#41](https://github.com/gysahlgreene/SlopForge/issues/41) (placeholder normal),
[#42](https://github.com/gysahlgreene/SlopForge/issues/42) (pixel-level map inspection),
[#43](https://github.com/gysahlgreene/SlopForge/issues/43) (blotch/variance diagnosis) and
[#44](https://github.com/gysahlgreene/SlopForge/issues/44) (glass/emissive). Part of #41 is implemented:
`approve-texture` rejects a 1×1 placeholder normal unless waived (`make verify`: 618 passed, 6 skipped).
`measure_material_maps` now records per-map near-black fraction, distinct colors and dimensions in each native candidate's validation, as warnings only (thresholds undeclared). Blender inspection also reports `uv_area_sum` (overlaps counted twice) and `uv_loop_outside_unit_fraction`, and candidates carry `normal_source`, shown on the review board (checked against a real Blender plane fixture; #41 and the measurement part of #42 are implemented offline, not checked on a live candidate). Not verified: a live candidate, whether a real normal bake improves appearance, and #42–#44.

H100 diagnosis ladder (2026-10-18, private evidence, one input/seed): `h100_final` resolution gave finer texture than 1024/2048; same-seed H100 repeats were byte-identical; the native normal bake now ships in `h100_final` (live preflight passed; one generated candidate inspected). Metallic: same ComfyUI code on both hosts; the H100 decodes a brass key as fully metallic (correct) but also the glossy stone lantern (model misprediction), while Mac MPS output was ≈0 for every asset (suspected MPS channel loss, unverified on a metal asset). Validation warns on ≥90% fully metallic maps. No visual approval or qualification claim.

Brief-declared materials (2026-10-18, one private H100 run): a fresh project generated the stone lantern from a brief with `--material` declarations; the candidate had no false metal, a real baked normal map and fine-grained stone. The glowing window panels reconstructed as empty cavities, so no emissive surface exists (#44 open). Visual approval and Unity import were not performed.

Material showcase (2026-10-18, commit `01ff304`, H100 profile, final tier): five props — brass key, glazed jug, supply crate, power relay, stone lantern — generated from briefs through `generate`/`approve` with no manual repair; [evidence and limits](docs/media/material-showcase-2026-10/README.md). Shared fixes found on the way: concept prompts always carry reconstruction rules and declared materials; GPU UDF remesh at 384 replaces Blender's voxel repair (which erased thin parts); preview cameras handle flat and wide props; a project lock prevents concurrent commands from erasing manifest records. Remaining: one run per prop (no repeatability claim), no visual approval or Unity import, multiple small components on some props, guessed hidden sides, and emitter detection on dark-baked albedo (#44).

Declared emitters (2026-10-20, H100 `final`, private evidence): both lantern runs of the props protocol had `emissive_fraction` 0. Two defects were found and fixed, each with a regression test. (1) Detection: TRELLIS.2 baked the paper panels pale and near-neutral, but at a seed-dependent level (flat ~200 or ~253, mottled ~167), and the fixed 225 cut-off missed the lower ones; pale emitters are now found at 150 and 1.3× the map's median, which finds all seven pale reconstructions on record. (2) Unity: the URP material never glowed, because URP's validation drops `_EMISSION` from a material whose GI flags say `EmissiveIsBlack`; the builder now marks it `BakedEmissive` and the import fails if the keyword is still off. Fresh brief-C runs: one on the first cut-off attempt (190) had 0 (replayed with the final rule, 0.9% with a few dark panes); C2 on the final rule found the panels (0.65%) and glows in the Unity preview after the keyword fix, unevenly across panes; C3 on the final code had 0 because that seed rebuilt the windows as slats with thin warm slivers of paper. So the stage works when the panels reconstruct pale and neutral, but the lantern brief is not reliable: 1 of 2 runs on the final code glowed, and all 30 concepts showed the panels lit against the prompt. No visual approval. Follow-up below.

Declared emitters, concept and retry (2026-10-20, H100 `final`, private evidence): instead of a third cut-off, the first incorrect artifact was traced to the concept. Concept generation is deterministic per seed (C3's concept reproduced bit for bit), so the emissive rule was varied alone on fixed seeds: the old rule ("shown switched off ..., not glowing; its glow is added later") drew 12 of 12 lantern concepts lit; describing only the unlit look ("a solid opaque surface with a dull matte finish in its own flat daytime colour") drew 9 of 12 unlit, and kept the relay's declared amber lens amber and solid. Z-Image Turbo runs at CFG 1 with a zeroed negative, so a negative prompt is not available. With the same mesh seed, an unlit concept never baked a smaller panel than its lit twin (5 pairs; C3's concept and seed 0 → 0.7% with the unlit concept). A seed that still bakes no panel now fails the material candidate with `emitter_missing`, a retryable quality code (before, a material failure stopped after 1 of 3 attempts as non-retryable, and a missing emitter only warned). Regression tests cover the rule wording, the failure and its retry, and a report whose code contradicts its measurement. Three fresh brief-C runs on this code (merged locally with #56 for `unity-preview`; criterion v1 selection): 5, 6 and 6 of 6 concepts unlit; each found the panels on the first mesh attempt (2.48%, 4.75%, 0.77% of the map), and every visible pane glows in the Blender renders and all four Unity URP views. Not verified live: the retry path (no run needed it) and a pale-bodied emitter. Limits: about a quarter of concepts are still drawn partly lit and concept selection does not check it; the disconnected-component warnings (2 to 43) are unrelated and open. Approach 3 (projecting the emitter from the concept) was not needed; it would need the three-quarter camera pose and leaves hidden windows unlit. No owner visual approval; the props protocol runs are not re-run.

Owner review (2026-10-18): the five-prop showcase is about 60% of the target prop quality. Lit turntables (`blender/render_turntable.py`, `scripts/turntable_gif.py`) are published with the [showcase evidence](docs/media/material-showcase-2026-10/README.md). Largest remaining gaps: guessed hidden sides, small detached components, emitter detection on dark-baked albedo, and no repeatability or Unity evidence for the set.

Structures (2026-10-18): six standalone `architecture` assets (stone well, market stall, stone shrine, watchtower, ruined arch, sci-fi bunker) generated from briefs on the H100 profile, and a five-module `stone_ruin_kit` whose modules now keep declared real sizes (`target_size`, mesh preparation `--target-size`); floor, wall, doorway, corner and column pass `validate_environment_kit` on their material-candidate measurements. The formal `environment-check` stays pending until `approve-texture` (needs Unity). The kit corner reconstructed as a closed block; wall/doorway concepts needed ~20% horizontal squeeze. [Evidence](docs/media/structure-showcase-2026-10/README.md). No visual approval or Unity import.

Characters (2026-10-18): the Rigify provider now places joints from mesh cross-sections on the basic human metarig, solves bone heat on an adaptive watertight voxel proxy, restricts forearm/hand weight to surface-connected arm vertices, cuts fused hand–thigh faces, renders three-quarter lit FK evidence and maps Unity Humanoid bones to exported `DEF-` bones. Characters keep Blender voxel repair after the GPU UDF remesh (`--require-manifold`); concepts ask for a gap between hands and thighs. Three new characters (ranger, mechanic, knight) rigged and walked as procedural test-cycle turntables; on fixed FK poses the share of edges stretched past 1.5× fell about 1.5–3× (raised arms ~3%, barely changed). (Superseded by the 2026-10-19 rounds below; that evidence was removed.) No source/readiness/deformation approval, no Unity import for these three. The opt-in `test_rigify_blender_integration` fails on `main` before this change because it lacks an approved source review.

Characters (2026-10-19, private evidence; owner rejected the 2026-10-18 round): four art styles (realistic, stylized hero, anime, hand-painted) regenerated on the H100 final tier, rigged with SkinTokens on the H100 and walked with the CMU 08_01 clip. Fixes, each with a regression test: H100 normal maps are baked in Blender (MikkTSpace) from the full-detail remesh, removing the white speckle of ComfyUI's Lengyel-tangent bake; SkinTokens runs with `--use_postprocess` (one of two runs without it tied about 1,000 trouser vertices to a fingertip); the post-processor reuses the source maps when UVs match (no dark ray-miss dots) and removes weights that jump more than five bones; retargeting swings only limbs onto the actor's rest directions, so torso and clavicles keep the character's build (no shrug or flipped hips). Observed on these four: clean walk turntables and level T-poses without spikes. Limits: faces are soft (the head is about 150 px of the conditioning image); the dwarf's concept keeps its arms almost against the body in all four candidates despite the prompt, so its armpit armour webs when the arms reach horizontal; SkinTokens runs here were launched by hand over SSH (the provider still runs SkinTokens locally only); one run per character, no source/deformation approval, no Unity import.

Characters, second round (2026-10-19, private evidence): the same four briefs regenerated through the CLI on the H100 profile with pose-conditioned concepts (Z-Image Fun ControlNet, OpenPose A-pose skeleton), front concept projection onto base color, SkinTokens through the provider's new SSH path (`tools.skintokens_host`; preflight, audited setup and seeded inference ran on the H100), and the CMU walk with the stride now measured on the clip's ankle. Observed: realistic, hero and anime concepts follow the skeleton (an unconditioned hero brief had given hands on hips); the dwarf brief ignores pose control at every strength and skeleton tried. Rigs needed far less weight cleanup (realistic 3 pruned influences, against 3,268 the round before), T-poses are spike-free, and all four walk on the same 63–189 stride. Projection sharpened eyes, brows and beards on three characters and was skipped on the dwarf (proportions 7.8% off). Limits: close-ups show projected features a few concept pixels off the sculpted forms; the candidates' base colors predate the final visibility smoothing tweak (commit `1b64859`); rigging gates (source review, readiness, deformation approval) were not run, so SkinTokens was invoked through the provider function rather than `character rig`; one run per character, no Unity import.

Characters, third round (2026-10-19, private evidence, after owner review of walks and model quality): walks retargeted from CMU 07_02 with heading alignment, arm clearance from the rig's own mesh, stance widening, stance-referenced feet and relaxed hands (a natural walk on all four; a regression test for each correction). Models regenerated with the character mesh graph (512 QEF remesh, QEM crease-preserving decimation): crisper edges and hardware in clay renders; one realistic seed came out turned sideways and the new `concept_silhouette` gate is in place for that case. Not verified: whether owners judge the new models non-lumpy; the dwarf's projection is still skipped (8%); one run per character.

Owner review (2026-10-19/20): rigging and walks are much better; model quality, especially faces, is about half of a shippable game character. An open head pass (refined waist-up crop grafted onto the body) helped only the realistic character and was not wired in. A template/kit route (MakeHuman base, library garments, licence gating) gave cleaner but plainer characters and was judged out of scope for SlopForge, so it was removed (recoverable from history at `a2e0fcb`). The third round is published as experimental evidence: [character styles](docs/media/character-styles-2026-10/README.md).

Prop pipeline audit fixes (2026-10-20, offline): a whole-repo audit found five persistence and accounting defects on the prop path, each now covered by a regression test that failed before its fix. (1) The swatch bake overwrote its own input maps, so `metallic_gloss` kept the flat-tile layout while the other maps used the UV layout, and map-stage hashes stopped matching; tiles are now kept separately and `metallic_gloss` is packed after the bake. (2) `approve-texture` updated the manifest after its rollback window, and crashed there once concepts had been regenerated; lineage now runs inside the rollback, and the regenerated case stops before any file changes. (3) The approved concept's `approval` flag was written to a detached copy and never saved. (4) A resumed run counted only the prior run's mesh attempts, recorded a contradictory retry decision, and blocked every later resume. (5) Failed material candidates were dropped when approval failed, and their folders were reused. A native-material Blender failure is also now attributed to `material_assembly_export`. Verified: `make verify`, `make verify-provenance`, and one real-Blender swatch candidate (cube fixture, real `make_pbr_maps`, image inference mocked): baked 2048² maps, `metallic_gloss` equal to a repack of the baked maps, all map and assembly hashes matching. Not verified: a live swatch candidate, its visual result, or Unity import.

CLI, recipe and backend audit fixes (2026-10-20, offline): `recipe resume` marked every completed 3D child that had a `generation_prompt` (all ten in `starter_environment_kit`) or `materials:` as stale, because generation recorded the raw prompt while the resume check expected reconstruction rules and material regions; both now use one prompt builder, so recipe concepts also get the rules. Guided `make` crashed at material approval (missing `allow_placeholder_normal`). A single failed `/history` poll ended a remote job's worker with an unknown outcome; transport failures are now retried with backoff until the deadline, and a completed job with no outputs returns at once. Non-editable installs lacked the character pose image; a test now checks every runtime data file is in `data-files` (wheel built before/after: 0 → 1 pose image). `--project=PATH` and a bare `slopforge` no longer fall into the old three-argument parser, `doctor` honours `SLOPFORGE_PROJECT_ROOT`, and a commented-out config section keeps its defaults instead of crashing. Verified offline with regression tests and `make verify`; not verified against a live remote ComfyUI blip.

Character and Blender audit fixes (2026-10-20, offline and local Blender 5.1.0): SkinTokens rigs now carry a `unity_humanoid_mapping` built from the post-processor's Unity bone names (before, `animation unity-setup --rig-type humanoid` refused every SkinTokens rig), and a failed post-process reports the Blender report's errors instead of `CalledProcessError`. The remote SkinTokens cleanup accepts only a validated `mktemp` path. `retarget_character_animation.py` used `Action.fcurves`, which Blender 5.1 no longer has; its fallback now uses `Action.is_empty` (real-Blender regression test). `transforms_applied` checked `rotation_euler`, which stays zero for glTF imports; it now decomposes the world matrix, and a 90°-rotated GLB fixture reports `False`. The opt-in `test_rigify_blender_integration` now approves a source review first and passes (`SLOPFORGE_RUN_BLENDER_RIGIFY=1`), as does the opt-in retarget smoke (`SLOPFORGE_RUN_BLENDER_ANIMATION=1`). Not verified: a real SkinTokens rig through Unity Humanoid import.

Repository cleanup (2026-10-20): removed code and files with no callers or references: `tests/f1_tests.py`/`f2_tests.py` (never collected by pytest; copies of existing tests), `scripts/doctor.sh`/`init-project.sh`, the unwired head-pass experiment `blender/graft_head.py` and its test (recoverable from `f63d8cd`), four unused helpers, dead `next_attempt` assignments, and 13 unreferenced images in `img/`. Four modules now use `provenance.file_sha256` instead of their own copies, and `model.py`'s SHA-256 shape checks use `reuse._valid_sha256`; a retry decision with an upper-case scope hash now fails closed (mutation test added). `reuse.earliest_stale_stage` still has no production caller and is kept as the planned resume building block named in the roadmap. Verified with `make verify` and `make verify-provenance`.

Smaller audit fixes (2026-10-20, offline and local Blender 5.1.0), each with a regression test that failed before its fix: character normalization sized the remesh voxel per part, so every part got the whole face budget (a quarter-size part had as many faces as the body); it now uses one voxel size from the combined bounds, bakes at the source texture size instead of a fixed 256², records an empty material slot as `null` instead of crashing, and its Blender call exits non-zero on a script error. An interrupted image or character-concept run lost its earlier candidates because only prop runs saved after each one. A recipe prop child with a variation but no requested prompt crashed the reuse check instead of being judged not reusable. `approve --resume` left a prior execution `running` forever when the process had died between stages; it is now finished as an `interruption`. `generate` for a 3D type took its concept count from `model_candidates`; it now uses `image_candidates` like recipes and [quality tiers](docs/QUALITY-TIERS.md). Swatch emission keywords matched substrings (`led` in `sealed`). Image generation could download a preview (`temp`) image instead of the saved output. A missing configured `asset_python`/`SLOPFORGE_PYTHON` silently fell back to SlopForge's own interpreter; it now stops with an error. `doctor` crashed on a SkinTokens preflight exception (now a warning) and skipped the `character_model` workflow. Topology diagnostics scanned every vertex for each open edge (6,000 open triangles: 32.7 s, now 0.15 s with a KD-tree). A skipped front concept projection left no trace in validation; it is now a warning. Verified with `make verify` and `make verify-provenance`. Not verified: a real multi-part character through normalization, a live image run with a preview node, or the visual effect of the shared voxel size on small parts.

Props provisional evidence protocol (2026-10-20, H100 live, private outputs): after the audit fixes reached `main` (PR #55), [qualification record v1](docs/media/props-provisional-2026-10/QUALIFICATION-RECORD.md) was committed before any run. It declares:

- three showcase briefs (supply crate, glazed jug, stone lantern) and the Unity 6000.6.3f1 / URP 17.6.0 PC/console profile on `h100`/`final`;
- what counts as independent: a fresh project and fresh CLI seeds per run;
- the pass/fail criteria, permitted interventions, and unchecked gates.

A new `unity-preview` command imports a material candidate into Unity, assigns the Lit material and saves a four-view URP render, without the approval that `approve-texture` records. It has two unit tests and was checked against real Unity.

All six runs reached the Unity import with no edits to generated assets ([evidence](docs/media/props-provisional-2026-10/README.md)).

- **Structural.** All six pass validation: at most 30,000 triangles, UVs in 0–1, no degenerate faces. They have 3–25 detached components, reported as warnings.
- **Technical.** All six have 4096² maps and a Blender normal bake, with no false-metal error. Both lantern runs found no emissive region, which fails the record's declared-material criterion, so the set is **Experimental**. Post-merge review: by the record's concept criteria A1, B1 and B2 are also concept-stage failures, so 1 of 6 runs (A2) passes every stage (issue #65).
- **Environment.** One environment failure (H100 ComfyUI stopped when the host's last login session closed; Linger is off) stopped C2 with no retry spent. It resumed once with `--resume`; the remedy is in [ComfyUI](docs/COMFYUI.md).
- **Metallic values.** The jug, declared non-metal, had metallic means of 0.30 and 0.48 when measured during the runs (not recorded in `runs.json`; issue #61). The baseline jug measured 0.41–0.59, so this was already true. The mismatch gate counts only fully metallic texels.
- **Concepts.** All twelve crate concepts are wider than tall, against the brief. All twelve lantern concepts show lit panels, against the prompt.
- **Not done.** No visual approval: the owner reviews against the 60% baseline. No publication, Play mode, performance budget or failure rate.
- **M0.** The six-run exit item has now run. M0 stays active until the owner reviews it and the remaining exit evidence is judged.

Multi-view conditioning for props (2026-10-20, experimental; [report](docs/media/multiview-props-2026-10/README.md)): a model graph with `view_front/left/back/right` inputs makes `conditioning_preparation` generate those views from the approved concept (`workflows.views`, Qwen-Image-Edit-2511 with a multiple-angles LoRA, concept prompt appended for unseen sides), frame them at one scale and regenerate a set whose opposite silhouettes mirror each other less than 0.9 (up to three sets; all kept). Views are hashed `image.view*` outputs derived from the approved concept and inputs of the mesh stage; the new `h100_multiview` profile feeds them to Pixal3D's multi-view conditioning (`pixal3d_multiview_bf16`, installed on the H100 with the Qwen files after user approval, SHA-256 verified). Regression tests cover view binding and hashes, framing, the silhouette check, retries, the stop before mesh inference, resume reuse, invalidation by a changed views workflow or tampered view, and unchanged single-view identity. Live on the 2026-10-18 showcase concepts: the relay's back lost the copied disc and lens and the candidate passed validation as one component without warnings (baseline: 9 components), but its accepted back view invented a vent that was modelled and the plate colour faded; every crate view set was rejected (closed top, three-quarter angles), so approval stopped before mesh inference. Before the check and brief prompts, a first live pass gave the relay an invented back mechanism and the crate a distorted shape. Not verified: repeatability, other props, visual approval, Unity import; the profile is not a default. Native mesh-texturing workflows rebuild material assembly on resume (local, no inference), which predates this change.

Prepared-mesh workflow binding (2026-10-20, offline): the 3D worker bound the prepared mesh's content hash into the material-stage effective workflow only for a `LoadMesh` node, but every bundled TRELLIS.2 graph loads it with `Load3DAdvanced`. Live runs therefore recorded no `prepared_mesh.model_file` entry in `effective_bindings.uploaded_inputs`, and the material-stage `workflow_effective_sha256` hashed the ComfyUI upload name instead of the mesh content. The binding now follows the uploaded name whatever the loader class; a regression test built on the bundled H100 graph's `prepared_mesh` node failed before the fix. Effect on existing manifests: material-stage and sidecar effective hashes recorded before this change differ from new ones for the same inputs and lack the prepared-mesh binding; shape-stage hashes are unchanged. No reuse or resume decision reads the effective hash or bindings (stage reuse compares settings and input artifact hashes, and the material stage's inputs already carry the prepared mesh's content hash), so reuse and resume behavior is unchanged and old records need no migration. Verified with `make verify` and `make verify-provenance`. Not verified: a live run.

Post-merge review fixes (2026-10-20, offline): a review of #56–#58 after they merged found two emitter defects and an evidence over-count. (1) A pale undeclared-colour emitter covering most of the map was never found, because 1.3 times the map's median (the paper itself) exceeded 255; the cut-off is now capped at 225. (2) One found emitter hid another missing one, because the check used the union of all declared emitters; `emissive_fraction` is now the smallest declared emitter's share, so a missing one fails `emitter_missing`. (3) A failed `unity-preview` left its copied FBX and maps under `Assets/`; they are now removed. (4) The props evidence counted A1, B1 and B2 as passes; by the record's own concept criteria they fail at the concept stage, and the report and the entries above are corrected. Also documented: a large pale non-emitter part can glow when an undeclared-colour emitter is declared, and an approved recipe child that declares an emitter is regenerated once on its next `recipe resume`, because #58 changed the emitter rule text in its prompt. Each code fix has a regression test that failed before it; verified with `make verify`. Not verified: a live run.

Concept adherence (2026-10-20, H100, fixed seeds, [evidence](docs/media/concept-adherence-2026-10/README.md); issue #65): the six-run protocol failed mostly at the concept stage, so concept properties were tested one variable at a time on six fixed seeds. For the crate brief, the share of concepts taller than wide went from 0/6 (brief as written, square canvas) to 6/6 with the view and proportion stated first on a portrait canvas, and straps went from 0/6 to 6/6 once they had their own sentence with form and count. New `generate --aspect portrait|landscape|square` sets the concept canvas for 3D assets. It is applied like a quality tier's node input, so the concept identity records it, and it is refused for character concepts, whose pose skeleton fixes the canvas. A fresh-seed CLI run gave 3 of 3 portrait concepts taller than wide with straps. Prompt-authoring guidance is in docs/AGENT-INTEGRATION.md and the project AGENTS template. Not solved: the jug stayed in profile under every wording tried, and a camera sentence can change a design (it closed the open crate). No mesh was generated from the test concepts, and the qualification record's briefs are unchanged (re-authoring them is a protocol change for the owner). Also found: an `ssh -N` connection does not register a login session on the H100, so ComfyUI still stops; hold a login with a remote command (docs/COMFYUI.md).

Emitter preflight (2026-10-20, H100 `h100`/final, one brief, private evidence; issue #62): before any mesh inference, `approve` now applies the emitter rule to the approved concept's cutout, flattened onto black so the removed backdrop cannot pass as a pale emitter. It stops with a `configuration` failure (`emitter_preflight`) when a declared emitter is not visible there. Live, on the showcase power relay brief (`lens=emissive#e0a030`):
- Concept 2 drew the lens dark brown-amber. Its approval stopped in 7.6 s with no H100 job; before this change it would have run three final-tier mesh attempts.
- Concept 1 shows the lens at the declared colour and passed the check, but all three mesh seeds baked the lens dark rust-brown (about RGB 80, 32, 11), with `emitter_missing` each time and no asset delivered.

So the colour-only miss on the bake is systematic for this brief, as #62 suspected; the preflight cannot catch it, because the concept is correct. Matching on hue alone would also light the copper caps, which bake to a similar orange family. The follow-up is to locate the emitter in the concept, where matching works, and project that mask onto the mesh, as `blender/project_concept.py` already projects concepts for characters. Not verified: undeclared-colour (pale) emitters through the live preflight, and briefs other than the relay.

Concept-registered emitters (2026-10-21, issue #62; private evidence): the relay's amber lens baked dark rust, dark grey-brown or olive across seeds, so colour matching on the bake missed it on every seed. Each declared emitter is now also found in the approved concept and carried onto the texture:
- `blender/concept_view.py` fits the view to the concept silhouette (overlaps 0.969–0.975 on the relay bakes) and renders base-colour and float UV passes.
- `slopforge/emitters.py` keeps the largest matching blob, grows it along the declared hue (so copper glints are dropped), maps it onto the render through the silhouettes' bounding boxes, and marks the texels shown there.
- `derive_emission` lets either source mark a texel.

Results:
- **Offline:** on the three earlier bakes the mapped lens outline sat on the lens each time.
- **Live,** H100 h100/final, the same concept that previously failed `emitter_missing` on all three seeds: the first mesh attempt produced a valid candidate (`emissive_fraction` 0.0006 from projection, no retry). That seed rebuilt the lens as a protruding tan boss, and the glow sits on it.
- **Regression test:** a real-Blender test shows colour matching alone missing a dark-baked disc while the projection finds it and lands on its texels.

`scipy` is now a declared dependency; rembg already installed it.

Not verified: pale undeclared-colour emitters through the projection on a live run, briefs other than the relay, and the visual result. The earlier, unregistered projection prototypes are recorded on #62.

Pale emitters and the concept projection (2026-10-21, live lantern on H100 h100/final, protocol brief C, private evidence): the first mesh attempt passed (`emissive_fraction` 0.021; fit 50°/5°, overlap 0.953). Projecting the pale panels, though, marked mostly granite: projected texels averaged mid-grey (117, 113, 112), and only 10% of them were paper found by the colour rule (204, 196, 188), because the pale rule on the concept also takes stone highlights. Only emitters declared with a colour are now projected; pale emitters use the colour rule on the bake, which found this lantern's panels (0.017 of the map).

Declared non-metal metallic (2026-10-20, H100 `h100`/`final`, private outputs): the glazed jug declares jug, stopper and twine non-metal. Its metallic map averaged 0.30 and 0.48 in the props evidence runs, 0.38–0.60 on the glaze. The `material_mismatch` gate counted only fully metallic texels (≥230) and needed half of them, so partial metal passed. A controlled re-render of one fresh jug, changing only the metallic map, showed the generator's map darkening the glaze from median RGB 10,62,101 to 4,38,67. The native material stage now writes a zero metallic map when the brief declares materials and none is `metal`. This follows the emission rule in [Materials](docs/MATERIALS.md): declarations decide the map. Mixed and undeclared briefs keep the generator's map. The raw map stays in `native_material/`, candidates record `metallic_source`, validation records the metallic `mean` and `generator_mean`, and the now unreachable gate is removed. Regression tests cover zeroing at partial and full metal, a mixed brief and an undeclared brief keeping the map, and no metallic warning on a zeroed map. Fresh runs from commit `1cf90ee`:

- **Jugs.** Two fresh runs both gave a zero metallic map (generator means 0.47 and 0.22). Both imported through `unity-preview` with a four-view URP render.
- **Crate.** One fresh run kept its generator map (mean 0.04). Its metallic texels sit on grey iron (median base color 76,79,79), not the wood (127,103,75), and it also imported through `unity-preview`.
- **Warning.** At `1cf90ee` the zero map added a spurious "single constant color" warning, so the jug candidates were `passed_with_warnings`. It is fixed with a test; outputs are unchanged.
- **Not covered.** The glaze base color is still decoded darker than the concept (median 29,46,75 against 39,59,104 on run B1), and one new jug's handle came out teal. A brief that also declares metal keeps any false metal on its glossy non-metal regions. The `nonmetal` concept rule still asks for matte surfaces with no polished highlights, against glossy-glaze briefs. No visual approval: the owner reviews.

Hidden components on props (2026-10-21, issue #64; private evidence): the 3–25 "detached components" reported on the six protocol props were all hidden inside the main body.
- **Evidence:** rendering each prop from eight directions, from the sides, above and below, with and without every non-main component changed no pixel on any prop, while those components held 7–39% of the triangles (11,672 of 29,892 on lantern C1).
- **Change:** `prepare_model.py` now runs the existing enclosed-component removal on every mesh preparation, not only with `--local-repair` (characters). It runs before UV unwrapping, so hidden parts also stop taking texture-atlas space.
- **Live check** (H100 h100/final, the protocol crate brief): 3,128 hidden vertices removed; the candidate was one component with 23,719 faces, passed validation with no warnings, and its previews are intact.
- **Tests:** the Blender regression test now covers the prop path (`--no-voxel-repair`) as well as `--local-repair`.

Not done: the GPU graph still decimates to the face budget before the hidden parts are removed, so the freed share is not yet spent on visible detail. Components outside the main surface are still only reported.

GPU removal of hidden components, rejected (2026-10-21, H100 h100/final; private evidence): the remesh option `sign_mode.drop_enclosed_components` was A/B tested against the committed graph on fixed seeds, comparing eight-view silhouettes.
- **Crate and lantern:** silhouettes matched (IoU ≥ 0.998) and the delivered mesh had 25–27% more faces (23,552 → 29,806; 18,064 → 22,584). The lantern still had 3,614 hidden vertices left for Blender to remove.
- **Jug:** silhouette IoU fell to 0.82–0.91, because the option deleted the handle and the stopper.
- **Decision:** the option stays off in every graph. Hidden parts are still removed in Blender after decimation. As with `drop_inverted_components` on characters, the GPU component filters delete visible parts on some shapes.

The budget gap, measured (2026-10-21, the same three meshes, offline plus one H100 run each; private evidence). Distances are mean distance from the visible detail remesh to the delivered mesh, as a share of the bounding-box diagonal.
- **Blender decimation from the detail remesh:** Blender removed the hidden parts first, then decimated to the budget. Faces went from 23,552/18,064/29,470 to about 28,500, and distance fell 2.7–7.7× (crate 1.9e-4 → 2.5e-5). It cost 11–26 s more Blender time and raised non-manifold edges from 1–78 to 150–530.
- **GPU QEM placement:** the character graph's decimation inputs gave 10–44% lower distance than the current midpoint placement.
- **What it looks like:** smooth-shaded without normal maps, the GPU route flattens crate plank seams and rivets. With the baked normal map, as delivered, the routes look nearly the same at whole-object framing.
- **Decision:** neither change is adopted. The lost budget mostly costs silhouette precision at close range. Revisit if close-up views, LODs or collision need the geometry.

Unity asset identity (2026-10-21, issue #24): publication already replaced files in place, kept `.meta` files and reused an existing material, but nothing recorded or checked the identity.
- **Change:** after each import, Unity reports for the FBX, the material and each map its GUID, importer type and a hash of its importer settings, plus the GUID of each texture the material references. SlopForge adds file hashes and records the report as `unity_import` under the asset's logical ID. Approval stops and restores the previous files if the material references other textures or if republishing changed a GUID at the same path.
- **Live check** (Unity 6000.6.3f1, URP 17.6.0, opt-in `SLOPFORGE_RUN_UNITY_IMPORT=1`): replacing the FBX and maps kept every GUID and the material's texture references. Reimporting unchanged sources gave the same report, `.meta` bytes and file list. A new name gave all-new GUIDs and left the original's `.meta` files unchanged. A prefab saved from the imported model resolved, after republishing, to the replaced mesh (twice as wide) and the same material.
- **Negative controls:** a `.meta` with an edited GUID was reported and refused. A deleted `.meta` got its old GUID back from this machine's `Library/` cache, so the delete case is only exercised on a fresh checkout.
- **Tests:** unit tests cover the report, the material reference check, the recorded `unity_import` and the refused republish with rollback.
- **Not covered:** scene references (prefab only), meshes whose object names change between versions, and Unity's own asset-database consistency check.

Owner review and props criterion v2 (2026-10-21):
- **Review:** the owner rated all three v1 protocol props better than the 60% baseline. No percentage or asset approval was given.
- **Decisions:**
  - side-on concepts are acceptable for round props when every named part is visible;
  - the protocol briefs are rewritten with the authoring guidance;
  - the proposed thresholds are accepted.
- **Recorded in:** [criterion v2](docs/media/props-provisional-2026-10-v2/QUALIFICATION-RECORD.md), committed before its runs.
- **Pipeline change:** new projects' `prop` type allows at most five separate parts (`max_components: 5`). More fails as the retryable `component_budget`. The six most recent post-fix meshes (crate, jug and lantern, two each) were all one part.
- **Thresholds checked in the record only:** UV area at least 0.20; the lantern's declared emitter at least 0.5% of the map (a valid relay lens measured 0.06%, so this is not a pipeline-wide minimum); mean metallic at most 0.05 on briefs that declare no metal.

Props criterion v2 runs (2026-10-21, commit `ca15b1c`, H100 `final`, Unity 6000.6.3f1 / URP 17.6.0; [evidence](docs/media/props-provisional-2026-10-v2/README.md)). Status **Experimental**.
- **Five of six pass every stage and threshold.** Each passed on its first mesh attempt with no warning, as a single part, and imported into Unity. Both crates are taller than wide with their straps, the lantern panels glow (2.9% and 3.1%), and the declared non-metal jug and lanterns have zero metallic maps.
- **B2 failed in conditioning:** `prepare_3d_input.py` wrote its outputs, then died with SIGABRT (`recursive_mutex lock failed`) at interpreter exit. Its outputs are byte-identical to clean re-runs. It was not resumed, because it is not an environment failure under the record.
- **Owner review:** all three props rated better than the v1 runs.
- **Still visible:** the jug glaze is darker than the concept, faint ribbing shows on the jug in Unity, and the crate wood is pale.
