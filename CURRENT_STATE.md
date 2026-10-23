# Current state

## Direction and evidence scope

Follow the [product contract and document precedence](docs/PRODUCT_CONTRACT.md),
[pipeline contract](docs/PIPELINE_CONTRACT.md),
[quality contract](docs/QUALITY_CONTRACT.md), and [roadmap](ROADMAP.md).
M0 core reliability was closed by the owner on 2026-10-21 ([exit record](docs/M0-EXIT-RECORD.md));
M1 Props reached Provisional for static props; on 2026-10-22 the owner moved the focus to M2 Modular environments,
now the active milestone ([epic #89](https://github.com/gysahlgreene/SlopForge/issues/89)). Historical
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
closed. The helper still has no production callers; it is kept as the planned resume building block.

M0 closed on 2026-10-21 with its epic, #26; packages 1–3 are closed.

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
| Unity prop delivery | Partially working; 28 of 30 protocol runs imported | Criteria v1–v5 (2026-10-20/21): fresh H100 runs imported through `unity-preview` into Unity 6000.6.3f1 / URP 17.6.0 with the Lit material assigned and a four-view batch render (latest: [v5](docs/media/props-provisional-2026-10-v5/README.md), 6 of 6); B2 in v2 and v4 stopped before Unity. Publication through `approve-texture` covers every M2-v3 kit module and every moorland model, and the opt-in Unity identity test (#74). Kit scenes are checked in Unity for grounding, colliders, static flags and seam gaps; Play mode is not run |
| Humanoid import and movement | Partially working; historical asset-specific evidence | [Humanoid test 1](docs/media/character-qualification-2026-10/basalt-warden-unity-preview/README.md): valid Avatar and walk movement; arm deformation under review, topology defects; not production-cleared |
| Body-deformation benchmark | Partially working; historical asset-specific review | [Diagnostic benchmark](docs/media/character-qualification-2026-10/basalt-corrected-humanoid/README.md): reviewed delivered body rig and Unity motion; source visual quality rejected; separate final-tier source pending review, not covered by rig approval |
| Fine detail/material fidelity and general rig recovery | Known unreliable | Recovery and benchmark reports retain visual defects; prior humanoid test 3's recovered rig remains rejected as recorded before this task; it is not promoted by these contracts |
| Cross-brief/category repeatability | Provisional (static props, `h100`/`final`, commit `221c8d1`, Unity 6000.6.3f1 / URP 17.6.0 import) | [Criterion v5](docs/media/props-provisional-2026-10-v5/QUALIFICATION-RECORD.md): all six runs (three briefs × two) pass every stage and owner-accepted threshold, including the colour check; earlier criteria v1–v4 and their failures are kept. Two runs per brief cannot measure a failure rate; Qualified is out of scope |
| Modular environment kits | Provisional (stone ruin, timber house and sci-fi corridor kits, `h100`/`final`, commit `5ceac3b`, Unity 6000.6.3f1 / URP 17.6.0 assembled scenes) | [Criterion M2-v3](docs/media/kits-provisional-2026-10-v3/README.md): all six runs (three kits × two) pass every owner-accepted criterion, from size, pivot, stretch, corner shape and joints to concept fit, colour, budgets, the matching stone material and the Unity scene checks; M2-v1 and M2-v2 and their failures are kept. The stone kit's material step changed after `5ceac3b` (#101) and has no protocol run. The owner reviewed the look on 2026-10-23 ("nowhere near as good as the props"); not approved. S2's pillar is near-black against its grey concept, a failure no check catches yet. Play mode, lightmapping and LODs are unchecked; two runs per kit cannot measure a failure rate |
| Standalone structures | Experimental; generated at real size, one run each | [Real-size evidence](docs/media/structures-real-size-2026-10/README.md): well, shrine and bunker passed their first mesh attempts with concept-fit and colour checks (2026-10-22); not visually approved; no part limit declared |
| Scenes and natural environments | Experimental; one live run | `foliage`, `tiling_material`, `vegetation` and `scene-render`; the owner approved the [prototype](docs/media/natural-showcase-2026-10/README.md), and the recipe rebuilt it from a blank project ([live run](docs/media/natural-live-2026-10/README.md)). Rendering only: no Play mode, frame rate or memory check |
| Mechanical and creature/Generic runtime quality | Unverified | Rig tooling is a capability; representative visual, performance, deformation and runtime evidence is still required |
| Complete readiness/qualification claims | Props and modular kits: thresholds declared; other categories blocked | The owner declared prop thresholds on 2026-10-21 (parts, UV area, emitter, metallic, colour, runtime budget); the pipeline enforces parts and colour. Modular kits have the owner-accepted M2 criteria (#94, [M2-v3 record](docs/media/kits-provisional-2026-10-v3/QUALIFICATION-RECORD.md)). Other categories still lack declared requirements; `ready` and `qualified` runtime labels do not imply readiness |

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
Do not change milestone order or claim qualification. The
[historical session handoff](docs/SESSION-HANDOFF.md) records its 2026-10-18 worktrees.

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
  or every category's visual/deformation gates. The provisional protocol has since
  run for props (v1–v5) and kits (M2-v1–v3) under declared criteria.

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

Props criterion v3 runs (2026-10-21, commit `ee61783`; [evidence](docs/media/props-provisional-2026-10-v3/README.md)). Criterion v3 is v2 with the conditioning exit fix.
- **Fix:** `prepare_3d_input.py` and `prepare_views.py` skip ONNX Runtime teardown with `os._exit(0)` after success. The crash happened in 2 of 64 runs before the fix and in 0 of 96 after. A stand-in `rembg` that aborts at exit guards it in `tests/test_rembg_exit.py`.
- **Result:** all six runs pass every stage and every owner-accepted threshold on the first mesh attempt, each as one part, through Unity URP import.
- **Status:** at most Provisional for "static props, `h100`/`final`, `ee61783`, Unity 6000.6.3f1 / URP 17.6.0 import", pending the owner's visual review of these runs.
- **Gaps:**
  - B2's glaze came out teal against a cobalt concept, and no threshold measures base-color fidelity;
  - jug ribbing in Unity;
  - pale crate wood;
  - publication, Play mode, scene scale, other profiles, and repeatability beyond two runs per brief are unchecked.

Owner review of v3 and the colour check (2026-10-21; private evidence):
- **Review:** the owner rated all three v3 props better than v2 and said colour accuracy against the concept is important.
- **Where the drift comes from:** the delivered base colour is the TRELLIS.2 output byte for byte. On B2's concept, four `cfg 1` seeds kept the hue within dH* 4.6, against 9.9 (teal) on the protocol's seed.
- **Texture `cfg 3` rejected:** it did not keep hue closer, and it changed lightness by up to 20 (jugs darker, crates brighter).
- **Change:** new projects' `prop` type compares the base colour's median CIELAB chromaticity with the concept's. dH* above 4 (`colour_hue_shift`) or less than 0.6 of the concept's saturation (`colour_desaturated`) fails the candidate and retries the next seed. Near-grey concepts are skipped. The owner accepted the thresholds.
- **Calibration on earlier runs:** the check fails the v3 teal jug and the v2 navy jug, and passes the v1 and v3 B1 jugs and both v3 crates.
- **Not covered:**
  - the crates' systematically pale wood (passes; a retry would not fix it);
  - colour drift in a small part (only the dominant colour is compared);
  - lightness.
- **Status:** not yet run under a protocol, and the v3 status claim stays pending until a criterion v4 run includes the check.

Props criterion v4 runs and the corrected colour check (2026-10-21, commit `0465073`; [evidence](docs/media/props-provisional-2026-10-v4/README.md)). Status **Experimental**.
- **Result:** five of six pass. B2 failed the colour check (`colour_desaturated`) on all three mesh attempts.
- **The check was measuring the wrong surfaces.** It used the whole atlas, including hidden insides and bases. That failed B2's cobalt first candidate (atlas saturation 0.42; 0.83 from the concept's side) and passed B1's visibly teal glaze (atlas dH* 3.9; 6.3 from the concept's side).
- **Fix:** the check now renders the base colour from the concept's fitted view (fit at least 0.8, no UV pass). When no view fits, it checks hue on the atlas and records a warning that saturation was not checked. Failure messages name their codes.
- **Re-measured from the concept's side:**
  - the v3 teal jug (10.5) and the v2 navy jug (6.1) still fail;
  - B2's three v4 candidates pass (0.83, 0.63, 0.66);
  - the v3 crate passes.
- **Next:** this is tested under [criterion v5](docs/media/props-provisional-2026-10-v5/QUALIFICATION-RECORD.md).

Props criterion v5 runs (2026-10-21, commit `221c8d1`; [evidence](docs/media/props-provisional-2026-10-v5/README.md)).
- **Result:** all six runs pass every stage and every owner-accepted threshold, including the colour check measured from the concept's side (dH* 0.7–3.7, saturation 0.76–1.32; lanterns grey and unchecked). None needed a colour retry. Both jugs are cobalt.
- **C1:** the H100 login hold ended and ComfyUI restarted, which lost C1's queued mesh job. The agent interrupted the waiting CLI, and the record's one permitted `approve --resume` finished it.
- **Status:** **Provisional** for that scope. On 2026-10-21 the owner rated the v5 runs better than v3 and closed M0.
- **Gaps:**
  - pale crate wood;
  - a crate top reconstructed closed;
  - jug ribbing;
  - lost ComfyUI jobs are not detected;
  - downloads are not retried.

M0 exit record (2026-10-21): [docs/M0-EXIT-RECORD.md](docs/M0-EXIT-RECORD.md) maps each M0 exit item to evidence and gaps and proposes closing M0 for static props on `h100`/`final`. The owner decides. `make verify-live` on 2026-10-21 passed (3 tests, 9 subtests, 70 s).

Glass and transparent parts (2026-10-22, issue #44; private evidence).
- **What reconstructs:** on the H100, a potion bottle drawn as clear glass with liquid reconstructed as shards with no cork, while "a solid smooth green surface, nothing visible through it" came out whole. A brass lantern's clear globe came out as a pale opaque shell with either wording.
- **Change:**
  - A `glass[#rrggbb]` material class with a solid-surface concept rule.
  - The material stage finds glass by the tint's hue at any lightness, or as the pale region for clear glass, and sets alpha 0.35, roughness 0.05 and metallic 0. No glass found fails as the retryable `glass_missing`.
  - Blender moves glass faces onto a `<name>_Glass` material, and the review renders show them see-through.
  - Unity gets a second, transparent URP Lit material for those faces (owner decision: two materials for glass props). A single transparent material cannot keep depth writes: URP's Lit setup turns them off.
  - The owner-accepted UV-area threshold is now enforced for props (`min_uv_area: 0.2`, retryable `uv_area_budget`). A shattered bottle had passed every check with UV area 0.025.
- **Tests:**
  - unit tests for the class, the masks, the candidate, the retry and the Unity script;
  - a real-Blender face-split test;
  - an opt-in Unity test (URP 17.6.0) in which the glass material is transparent (queue 3000) and the main one opaque.
- **Live:**
  - The brass lantern's globe was found on 4.8% of the map, and its 1,584 glass faces read as frosted see-through glass in Unity.
  - A bottle's first seed retried on the five-part limit; the second was found as 44% glass by colour distance and looked blotchy.
  - With the hue rule, another bottle found 98% glass, but its mesh was shattered. That case now fails on UV area.
- **Authoring:** describe glass in the image prompt by its solid look. An extra reconstruction rule did not change concept translucency.
- **A bottle with that wording:** seeds 1 and 2 reconstructed whole (UV area 0.65 and 0.61) but failed `colour_desaturated` (0.587 and 0.554 of the concept's saturation). Seed 3 was shattered (UV area 0.021). It passed only because that test project predates `min_uv_area`: existing projects keep their asset types, so add `min_uv_area: 0.2` to `ai/asset_types/prop.yaml` by hand.
- **Status:** glass parts in an opaque prop (the lantern) work end to end. Whole-glass objects are not reliable: some seeds shatter (a new project now retries them), and the bottle's colour sits at the saturation limit.

Prop coverage exploration (2026-10-22; [evidence](docs/media/props-coverage-2026-10/README.md)). One run each of a fully metal pot, a sci-fi canister, an organic tree stump and a glass-part lantern.
- **Passed:** the pot, canister and lantern, each on its first mesh attempt and through Unity.
- **Stump:** failed every seed on UV area (0.017–0.044), although its meshes were whole. Bark and moss unwrapped into about 10,600 islands, and 12-texel padding used most of the map.
- **Change:** UV islands are now padded by 4 texels and re-packed concave. The stump went 0.044 → 0.19, a crate 0.30 → 0.55 and a jug 0.54 → 0.65, with unchanged stretch.
- **Shattered-mesh check replaced:** with that padding, UV area no longer separated shattered bottles (0.11–0.12) from whole stumps (0.10–0.19), so props now retry on a concept silhouette fit under 0.8 (`concept_fit`; shattered 0.71–0.75, whole 0.86–0.99) instead of UV area. The owner accepted 0.8 on 2026-10-22.
- **Re-run:** with these changes the stump passed on its first seed (fit 0.95) and imported into Unity.
- **Open:**
  - TRELLIS copied the canister's front strip onto its unseen sides as darker blue panels (#63). The declared strip itself was found (0.67%) and glows in Unity;
  - every stump concept's trunk was taller than wide against the brief (followed up by the shape guide below);
  - lantern globes are drawn see-through despite the solid wording.

Concept proportions and the shape guide (2026-10-22, issue #65; [evidence](docs/media/concept-proportion-2026-10/README.md)).
- **Cause:** the concept model's prior for a tree stump outweighs the brief. On fixed seeds no wording made the
  trunk wider than tall: the brief as written, a square canvas, a stated ratio, "cut low", "very thick" and "a wide,
  low drum" gave 0–2 of 6 each. The original 12 concepts measured near square only because the roots and mushrooms
  widen the outline; their trunks measured 1.27–2.06 against 1.19 for an as-tall-as-wide cylinder.
- **Change:** `generate --shape-guide cylinder|box:<height/width>`.
  - It renders a depth guide of that envelope with Blender (`blender/shape_guide.py`), on the canvas `--aspect`
    sets.
  - It routes the concept through `workflows.guided_image`: the installed Z-Image ControlNet Union graph the
    character concepts use, now set on the h100 profiles.
  - The strength is 0.65. The guide's hash and strength join the concept identity.
  - The guide is rendered without dither or metadata, so a repeated request gives the same bytes.
  - It is opt-in, for props only.
- **Evidence (H100, fixed seeds):**
  - At 0.65, 6 of 6 trunks were wider than tall on the test seeds, and 6 of 6 on fresh seeds, with the roots,
    moss and mushrooms kept.
  - At 0.5, 2 of 6. At 0.8, 6 of 6, but the roots were lost.
  - A pot kept its handles, lid knob and feet under a guide. A crate kept its open top and straps but turned to the
    guide's angle.
- **Live run:** through the CLI, `--shape-guide cylinder:0.5` gave six squat concepts, two with mushrooms on the
  top. The approved one passed on the first mesh attempt (fit 0.92) and imported into Unity. Its mesh measures
  whole h/w 0.55 and trunk 0.79, against 1.01 and 1.67 for the unguided coverage stump.
- **Tests:**
  - the guide's routing, reference, slot and identity;
  - an actionable error without `guided_image`;
  - refusal for character concepts;
  - CLI parsing and refusal for image types;
  - opt-in Blender tests (skipped without Blender) of the guide's proportion, background and byte stability.
- **Not verified:**
  - more than one brief in depth;
  - more than one guided run to Unity;
  - visual approval.
  The moss came out yellower on the mesh than in the concept, which is the known gap that small-part colour is not
  checked.

Lost ComfyUI jobs and download retries (2026-10-21, issue #76).
- **Change:** `wait_for_completion` asks `/queue` straight after a dropped connection recovers, and otherwise every 30 s. A job that is neither queued, running nor in history (read again, to cover a job that finishes in between) stops as an `environment` failure marked `remote_lost` and `remote_terminal`, so `--resume` can queue it again. `download_output` retries transport failures up to five times with backoff, and does not retry HTTP errors.
- **Tests:** unit tests cover a lost job after a restart, a job that finishes between the two checks, periodic checks of a waiting job, `/queue` parsing, a retried download and a 404 that is not retried.
- **Live check (H100):** a pending job deleted through ComfyUI's queue API was reported lost in 2.3 s, while a running job checked every 2 s completed normally.
- **Not verified live:** an actual service restart, and a dropped download.
- **Follow-up (2026-10-22):** four glass-experiment runs lost finished outputs when the login hold expired and ComfyUI restarted during their downloads, because five retries lasted only 15 s. Downloads now retry a dropped connection for up to 2 minutes, with backoff capped at 30 s; a test checks that the window outlasts 60 s and ends by 120 s.

Kit module pivots and real-scale inspection (2026-10-22, M2).
- **Problem:**
  - Every model's origin was its bounds centre, and Unity keeps the FBX origin as the pivot. Measured in Unity, a
    3 m wall placed at the origin ran from −1.5 m to +1.5 m, so placed at ground level it sank halfway into it.
  - Inspection flagged every module sized in metres as "larger than the normalised scale".
  - A module's declared `target_size` did not join its assembly-stage settings, so a changed size could reuse an
    old model.
- **Change:**
  - Kit `pivot` rules (`bottom_center`, the new `top_center`, `center`) reach Blender, which places the FBX origin
    there.
  - The size and pivot join the assembly-stage settings, only when declared, so prop identities are unchanged.
  - Sized modules are inspected at real scale.
  - Inspection records `footprint_quadrants`, from which a corner's open side can be read. On the baseline stone
    corner the open quadrant measured 0.0 and the others 0.69–0.90.
- **Tests:**
  - pivot validation, including `top_center`;
  - the pivot and real-scale flags reach Blender;
  - `recipe run` gives each module its pivot;
  - `environment-check` checks a `top_center` pivot;
  - an opt-in Blender test: a sized L gets its origin at its bottom or top centre, no scale warning, and one
    empty footprint quadrant.
- **Not verified live:** a kit regenerated with pivots and imported into Unity. That comes with the scene builder.

Kit layouts assembled in Unity (2026-10-22, M2; [evidence](docs/media/kit-scene-2026-10/README.md)).
- **Change:**
  - Recipes can declare `layouts`: placements of 3D modules in metres on Unity's axes. A rotation is in quarter
    turns, or `auto` for a corner.
  - `environment-scene <run> <layout>` makes each published module a prefab: an identity root, a mesh collider and
    static flags.
  - It places the layout in a saved scene and renders four views.
  - It checks in Unity that each module stands at its placement height for its pivot, has a collider, is static,
    and leaves no seam gap wider than `snap_tolerance`. An `auto` corner is turned so the open side read from its
    mesh faces the layout's centre.
  - `init` installs a `stone_ruin_kit` recipe with `courtyard` and `corner_joint` layouts.
- **Live:**
  - The recipe ran from a fresh URP project on the H100. All five modules were published, `environment-check`
    passed, and the 25-instance courtyard built with no errors.
  - The corner auto-turned 90°.
  - The run found that a top-pivot floor stood its own thickness too high: the prefab kept the FBX root's
    translation. That is fixed, and the opt-in Unity test now covers a top-pivot module.
- **Tests:**
  - layout validation;
  - placement resolution, which refuses unpublished modules;
  - the CLI writes the report and records the artifact;
  - an opt-in Unity test (`SLOPFORGE_RUN_UNITY_IMPORT=1`) covering grounding, a top-pivot module, a 0.2 m seam
    gap and a corner turned inward.
- **Not verified:**
  - visual approval;
  - matching module appearance (sandy columns, grey walls, invented blotchy wall backs);
  - declared module thickness (wall 0.74 m, doorway 0.82 m, corner arms about 1 m);
  - the doorway, squeezed 45%;
  - Play mode, lightmapping, and more than one run.

Shared kit material and corner footprint check (2026-10-22, M2; [evidence](docs/media/kit-material-2026-10/README.md)).
- **Owner decision:** one shared material per kit, so modules match.
- **Change:**
  - `kit_constraints.material: {source: <texture child>, tile_size: <m>}`.
  - In each declared module's material stage, the approved texture is made seamless. The base colour is re-baked
    as the swatch (box-projected in metres) × baked ambient occlusion × 60% of the module's own relative
    brightness. The module keeps its normal, roughness and metallic maps.
  - An unapproved kit texture stops approval before mesh inference. The swatch hash and tile size join the
    assembly-stage settings.
  - Uncovered atlas texels take the mean colour, which stops mip bleeding.
  - `footprint: corner` modules fail as the retryable `module_footprint` code when the emptiest footprint quarter is
    above 0.15, and `environment-check` fails a published one.
  - The shipped `stone_ruin_kit` has a `stone` texture child, the material and a corner footprint.
- **Live:**
  - *First run:* found black mip patches (the bake left about 60% of each atlas black) and a corner that rebuilt as
    a solid block (0.86 in every quarter). Both are fixed. The new check failed that corner on its real data.
  - *Final fresh run:* every module passed on its first attempt, with no black texels. The courtyard (25 instances)
    and corner joint built with no errors in matching granite.
- **Tests:**
  - the seamless wrap;
  - the kit texture preflight, in a unit test and in an approval that stops before mesh inference;
  - recipe validation, and that only declared modules get the material;
  - the backend flags;
  - the retryable code and environment-check for corners;
  - an opt-in Blender test: swatch hue, the module's own brightness kept, and no black texels.
- **Not verified:**
  - the corner retry live;
  - visual approval, Play mode and lightmapping;
  - more than two runs of one kit.
  Module thickness is still undeclared, so the corner joint steps out.

Recipe resume kept regenerating architecture modules (2026-10-22, M2).
- **Cause:** concept generation started an execution record (lineage) only for the `prop` type. The model
  pipeline already built identity inputs for every 3D type, but they were dropped. On `recipe resume`, every
  `architecture` child's reuse check failed with "candidate execution identity is unknown". The resume then
  generated new concepts for modules already approved for 3D. This is what the 2026-10-18 stone ruin kit's
  resume did, against `docs/ENVIRONMENT-KITS.md`.
- **Change:** concepts get lineage whenever the pipeline supplies identity inputs, which it does for every 3D
  type.
- **Regression test:** a recipe with an architecture child and a prop child runs through the real concept
  pipeline, with only the image backend faked. Resume generates nothing new and reuses both. Before the fix it
  regenerated the architecture child's six concepts.
- **Not verified live:** a kit resume on the H100.

Kit joints: declared wall thickness and corner arm thickness (2026-10-22, issue #90).
- **Cause:** thickness was a free axis, so it followed each concept. Generated stone walls measured 0.74–0.88 m and
  corner arms 0.98–1.16 m, and in `corner_joint` the corner stepped out past the walls.
- **Change:**
  - Walls and doorways declare their thickness through `target_size`, as `[3, 0.75, 3]`.
  - A corner declares `arm_thickness`. Blender finds its open side and measures each arm away from the joint. It
    then rescales piecewise across the arms only, so the outer bounds stay exact.
  - Inspection records `arm_thickness`, and `environment-check` compares it with the declared value.
  - The stone kit's layouts put walls inside the cell edges with their outer faces on them, like the corner's arms.
    The courtyard is now closed by four auto-turned corners.
- **Live (fresh run, H100):**
  - corner arms measured 1.09 and 1.12 m, set to 0.75 and re-measured at 0.750 and 0.749;
  - the walls and doorway came out at exactly 0.75 m;
  - `environment-check` passed, and both scenes built with no errors or seam gaps. The corner joint is flush.
- **Tests:**
  - recipe validation and the flags reaching Blender;
  - `environment-check` for arm thickness;
  - an opt-in Blender test: an L with 1.2 m arms comes out with 0.75 m arms inside an unchanged 3 × 3 × 3 m box.

Kit module stretch limit and recipe child aspect (2026-10-22, issue #91).
- **Cause:** sizing a module to its declared size stretches it when its concept's proportions differ.
  - One doorway stretched 1.45 to 3 × 3 m.
  - Square-canvas stone corners came out taller than their arms are long and stretched 1.40.
- **Change:**
  - Blender records `axis_stretch` over the axes that shape the module's face. A declared thin axis is left out, so
    a wall's thickness doesn't count: 1.36 over all axes, 1.19 over its face.
  - `max_stretch` (kit-wide or per module) fails a module past it as `module_stretch`. This is not retryable: another
    mesh seed from the same concept would stretch again, so approval stops and asks for a concept closer to the
    module's shape. `environment-check` applies the limit too.
  - Recipe children can declare `aspect`. It is applied at generation and again on resume, so the identity
    matches.
  - The stone kit's corner uses `landscape` and the kit sets `max_stretch: 1.3`, which the owner accepted for M2.
- **Evidence:**
  - *Fixed seeds:* square-canvas corners measured h/w 1.01–1.17; on landscape all six were about cube-proportioned
    (0.70–0.88).
  - *Live fresh run:* stretch was floor 1.00, wall 1.10, doorway 1.25, corner 1.03 and column 1.00, all within 1.3.
- **Tests:**
  - the stretch rule is not retryable, and is copied and checked;
  - a child aspect sets the canvas and survives resume;
  - an opt-in Blender test: a 1 × 0.9 face sized to 3 × 3 reports 1.11.

Kit budgets (2026-10-22, issue #93; [evidence](docs/media/kit-budgets-2026-10/README.md)).
- **Change:** module rules can declare `face_budget`, used on the GPU, in Blender and in the stage identities, and
  `texture_size`, which resizes the maps. `environment-check` reports each module's faces and map texels, and the
  kit's totals.
- **Owner decision:** after a close-up comparison, the owner accepted floor 15k faces, walls, doorway and corner
  40k, column 20k, and all maps at 2048². The stone kit declares them.
- **Live:** a fresh stone kit at these budgets built its scenes with no check errors. Totals were 100,177 faces
  and 83.9M map texels, against about 230k faces and 335M texels before.
- **Tests:**
  - budget validation;
  - the asset override and the map resize;
  - kit totals.
- **Not verified:** the comparison used Blender's decimation at one distance.

Standalone structures at real size, with concept checks (2026-10-22, issue #92; [evidence](docs/media/structures-real-size-2026-10/README.md)).
- **Change:**
  - `generate --target-size=x,y,z` gives any 3D asset a real size in metres, with `-` keeping an axis in
    proportion. Such an asset stands on a bottom-centre pivot.
  - `architecture` gets the owner-accepted prop limits for concept fit (0.8) and colour. Every 2026-10-22
    structure and kit module fitted at 0.92–0.97.
- **Live:** the well, shrine and bunker came out at exactly their declared 3.2, 3.5 and 3.0 m heights on
  bottom-centre pivots, and passed concept fit (0.93–0.98) and the colour check on their first attempts.
- **Tests:**
  - CLI parsing, refusal for image types, and the size and pivot recorded on the asset;
  - the architecture limits match the prop ones.
- **Not verified:** a part limit for structures (#94). The bunker invented a second door, has a white patch, and
  its small hazard stripes faded unchecked.

Kit protocol criterion M2-v1 closed with no status (2026-10-23; [evidence](docs/media/kits-provisional-2026-10/README.md)).
- **Runs:** six at commit `d3d6c31`, two each of the stone, timber and sci-fi kits.
  - K1 (stone) passed every criterion.
  - T1 failed on corner arms (0.351/0.335 m against 0.4 m), a code bug.
  - S1 stopped at the sci-fi wall's 1.49 stretch.
  - K2, T2 and S2 lost a concept job that waited more than 600 s in the shared GPU queue. ComfyUI's history shows
    all three succeeded after 2–13 s of execution.
- **Fixes, each with a regression test:**
  - the corner arm rescale reads the bounds after bottom-centring;
  - queue time no longer counts toward a ComfyUI job's timeout (bounded at 3 h);
  - a stretch stop states its own remedy once;
  - the stone kit checks at the record's 0.05 m;
  - a kit material can declare roughness (stone 0.75), after K1's floor came out at 0.22 beside walls at 0.67;
  - the sci-fi wall renders on a portrait canvas.
- **Sci-fi wall test:** on S1's six seeds, through the h100 `final` shape stage, square-canvas walls reconstructed
  1.27–1.64 times wider than tall (one within 1.3) and portrait ones 1.15–1.28 (all six). S1's own wall reproduced
  its run value of 1.49. Concept outlines did not predict mesh proportions.
- **Next:** criterion [M2-v2](docs/media/kits-provisional-2026-10-v2/QUALIFICATION-RECORD.md) reruns all six.
- **Not verified:** the kit roughness and the arm fix in a live kit run; the owner's visual review. The timber
  kit's outer wall faces come out as bare timber, with its plaster only on the inside, and its finish (0.50–0.59) is
  as generated.

Kit protocol criterion M2-v2: five of six runs pass, so not Provisional (2026-10-23; [evidence](docs/media/kits-provisional-2026-10-v2/README.md)).
- **Runs:** six at commit `5c17d4d`, all built and rendered in Unity.
  - K1, K2, T1, S1 and S2 pass every criterion.
  - T2 fails Joints: its timber corner reconstructed as a wedge, and its arms measured 0.27 m against 0.4 m.
- **Live checks of the M2-v1 fixes:**
  - no concept job timed out;
  - T1's corner arms measure 0.400 m;
  - the sci-fi walls stretch 1.15 and 1.24;
  - every stone module's roughness averages 0.75.
- **Fixes, with regression tests:**
  - **Wedge corners:** inspection records each arm's taper. Published L corners measured 1.00–1.01 and the wedge
    1.72–1.82. Above 1.25 a corner fails as the retryable `module_taper`. The limit is agent-set.
  - **Health check:** the mesh worker retries it for 2 minutes. One timeout had cost T2 an attempt.
  - **Timber corner view:** the corner brief asks for a high angle that shows the arms' tops. On T2's six seeds
    through the shape stage, eye-level concepts gave no usable L, and high-angle ones gave three.
- **Next:** criterion [M2-v3](docs/media/kits-provisional-2026-10-v3/QUALIFICATION-RECORD.md) reruns all six.
- **Not verified:** the owner's visual review. The walls' invented outsides differ from their fronts, and the
  sci-fi corners are whiter than its walls.

Kit protocol criterion M2-v3: all six runs pass, so modular kits are Provisional (2026-10-23; [evidence](docs/media/kits-provisional-2026-10-v3/README.md)).
- **Scope:** the stone ruin, timber house and sci-fi corridor kits; `h100`/`final`; commit `5ceac3b`; Unity
  6000.6.3f1 / URP 17.6.0.
- **Runs:** two per kit. Each was built from a fresh blank Unity project through `environment-scene`, and every
  owner-accepted criterion passed. One intervention was used, a permitted fresh selection for K2's corner after a
  stretch stop.
- **Live checks of the M2-v2 fixes:**
  - both timber corners, from high-angle concepts, came out clean Ls with 0.400 m arms and a taper of 1.02–1.04;
  - six solid-block corner seeds were retried;
  - no job timed out or was lost.
- **Not verified:**
  - the wedge check in a live run (none occurred; it is tested on T2's M2-v2 mesh);
  - the owner's visual review (invented wall outsides, T2's streaked plaster, sci-fi corners whiter than its walls);
  - Play mode, lightmapping and LODs;
  - a failure rate.

Kit look after owner review (2026-10-23; [evidence](docs/media/kits-hue-match-2026-10/README.md)).
- **Owner review:** the Provisional kits are "nowhere near as good as the props".
- **Measured:**
  - kit modules carry 130–340 px/m of texture, against 640–1,050 for props;
  - TRELLIS rebuilds flat architecture as lumpy relief, and wall backs are invented;
  - the stone swatch bake flattened the stone to grey.
- **Hybrid prototype, rejected:** exact Blender geometry with a generated tiling material (about 1,000 px/m).
  Beside the TRELLIS modules in Unity, the owner preferred the reconstruction's form.
- **Change, the owner's choice:** a stone module keeps its own generated colours. The kit texture shifts only its
  average CIELAB tint, so lightness and variation stay; the matte finish stays too. The swatch bake, its tile
  size and the Blender `--kit-material` path are removed.
- **Tests:** hue-match and recipe tests; `make verify`.
- **Not verified:**
  - a protocol run with this stage, since M2-v3's Provisional status is for commit `5ceac3b`;
  - texture density beyond 2048²;
  - invented wall backs.

Natural environments and scenes (2026-10-23; [guide](docs/NATURAL-ENVIRONMENTS.md),
[prototype evidence](docs/media/natural-showcase-2026-10/README.md),
[live run](docs/media/natural-live-2026-10/README.md)). Experimental.
- **Built:** `foliage` and `tiling_material` image types, `vegetation` (procedural trees and shrubs from approved
  bark and foliage), and `scene-render`, which assembles a recipe's `scene` block in Unity with probe-volume GI and
  renders stills and a flythrough. `moorland_ruin` ships the prototype the owner approved ("this is perfect").
- **Live run from a blank project** (`h100`/`final`, all 30 children made by the recipe, concepts selected by the
  agent):
  - the first render was 360 flat-colour frames: frames had no field of view. Fixed, with a test.
  - three regressions against the prototype, each traced:
    - the cliff came out mostly black: TRELLIS's own texture, and no check covers lightness;
    - the arch rendered side-on: its size was declared by height only, so its facing was the reconstruction's;
    - the camp floor had dark insets: the agent chose a concept with a broken diamond centre.
  - **Interventions:** fresh selections for the cliff and the floor; the arch now declares its width and turns 90.
  - **Final render** at `d29fb05`: 85 s, 140 objects, 2.0 million blades, a 33 s bake, six stills and 360 frames,
    no errors. Against the prototype it matches except for seeded placement (the grove still differs).
- **Change:** `scene-render` reads the scene block from the project's recipe file, so a layout change needs no
  regeneration; the report records the source and hash.
- **Found:** TRELLIS sometimes textures a mesh mostly black on the concept's side. The cliff and S2's M2-v3 pillar
  are cases. Three lightness measures over 125 published models did not separate the failures from accepted
  timber modules, so there is no check yet. Next: label those views by eye and calibrate.
- **Tests:** `tests/test_scene.py` (frame field of view; recipe-file scene source and its validation).
- **Not verified:** Play mode, frame rate and memory; a second live run; the owner's review of the live footage.

Repository audit (2026-10-23): a review of code changed since the 2026-10-20 review (kits, the ComfyUI backend,
natural environments, scenes) and of every public doc. The 2026-10-20 review's 20 findings were all confirmed fixed.
- **Code fixes**, each with a regression test:
  - `scene-render` builds in `<run>.partial` and replaces `<run>` only on success; the replaced render moves to
    `<run>.previous`. It used to delete the last render before Unity ran.
  - A tree is reused only while its species, height, seed and bark and foliage hashes match.
  - The scene script destroys each shot's textures (about 2 GB leaked over 366 shots).
  - Approving a foliage or tiling image restores the published files and record if processing fails, and
    re-measures the processed image.
  - Kits reject pivot `origin` at recipe validation (Blender rejected it after the GPU work).
  - `vegetation` validates its name; a surface job that saves nothing raises a named error; `environment-scene`
    uses the project's output root.
  - Both scene builders share one corner auto-turn; only kits refuse a corner without a nearly empty quadrant.
    Merging the rule into scenes first failed the moorland render on its weathered ruin corner.
- **Docs:** stale and contradictory claims corrected across the README, roadmap, current state and guides (M0
  status, 28 of 30 prop runs in Unity, publication coverage, the kits' status after #101, S2's black pillar, the
  live run, owner reviews, closed issues); the docs index lists the current evidence and marks superseded pages;
  the session handoff is marked historical; the README's structure table shows the real-size structures and the
  live run's ruin pieces.
- **Verified:** `make verify`. In Unity 6000.6.3f1 on copies of the M2-v3 K2 project and the moorland live run:
  `environment-scene` turned K2's four corners exactly as the original run, and a stills-only `scene-render`
  reused all ten trees, swapped in, kept the previous render, and matched the live run's stills pixel for pixel.
- **Not verified:** a full flythrough after the texture fix (the stills path is the same code); a failed foliage
  re-approval against a live ComfyUI.
- **Left as is:** the kit and prop four-view renders look alike but differ by design (sizes, a top view, lighting).
