# Release-quality audit (2026-10-04)

Current branch: `codex/prototype-content-factory` at `5716d8e` before this research reconciliation. It is three commits ahead of origin; `main` was not changed. The research report is input and recommendation, not a product specification; selected claims and corrections are recorded in [the report's reconciliation addendum](../research/game-asset-pipeline-2026.md#2026-10-04-reconciliation-addendum).

GitHub inventory initially found issues #4–#20. This reconciliation added follow-ups #21 (live reference-conditioning qualification) and #22 (animation-readiness gate). PR #3 is merged to `main`; PRs #1 and #2 are closed unmerged. No repository tags were present during preflight. Earlier roadmap work on this branch remains intact.

## Baseline and verification

- macOS, Python 3.14.7, project `.venv`; declared range is Python 3.10–3.14.
- Offline suite on the current working tree (2026-10-04): `.venv/bin/python -m pytest -q` → **205 passed, 6 skipped, 3 warnings, 10 subtests**. The warnings are Pillow `Image.getdata()` deprecations in one test. `compileall` and `git diff --check` also passed. Blender 5.1 fixture coverage passed; no Unity or model inference was needed for #22.
- Static basics: `.venv/bin/python -m compileall -q slopforge processing blender tests` and `git diff --check` passed after audit edits.
- Live H100 recipe: `SLOPFORGE_RUN_H100=1 COMFYUI_URL=http://<comfyui-host>:8188 .venv/bin/python -m pytest tests/test_recipe_h100.py -q -s` → **1 passed**. The run generated two Z-Image PNGs through an H100 ComfyUI server and retrieved them over HTTP. It records workflow hashes. Visual inspection found that the “transparent background” prompts returned opaque white backgrounds.
- Live H100 API round trip: `SLOPFORGE_COMFYUI_INTEGRATION=1 COMFYUI_URL=http://<comfyui-host>:8188 .venv/bin/python -m pytest tests/test_comfyui_integration.py::test_live_comfyui_2d_generation_and_http_file_transfer -q -s` → **1 passed**. It uploaded an input PNG, retrieved it byte-for-byte, submitted an image workflow, polled history, and downloaded/decoded the generated PNG.
- H100 workflow preflight: the four pre-existing API workflows and the new Wan qualification graph pass node/model-choice checks against live `/object_info` on ComfyUI 0.37.0 / H100 80 GB. This check does not run each graph.
- Workflow sidecar live preflight: `SLOPFORGE_COMFYUI_PREFLIGHT=1 COMFYUI_URL=<configured ComfyUI URL> .venv/bin/python -m pytest tests/test_workflow_preflight_live.py -q` → **1 passed, 4 subtests** against the remote H100. This checked every bundled graph, declared nodes, and selectable model choices; it did not submit inference.
- Packaging: `pip wheel --no-deps .` succeeded; inspected wheel contains all four JSON workflows and four `.requirements.yaml` sidecars.
- Local ComfyUI: unavailable at `127.0.0.1:8188`; no local live inference is claimed.
- Blender 5.1.0 and Unity CLI 1.0.0-beta.11 are installed. Previous documented live checks used Blender headless and Unity 6000.6.3f1; see issue notes below. The Mac did not have a `blender` executable on PATH.
- H100 device had about 16.1 GB VRAM free at the time of audit (other workloads were running); no 1536³ inference was run.

## Closed-issue traceability

“Verified” means the implementation has matching tests and the documented acceptance work was exercised at least at its stated level. It does not mean every output is production quality.

| Issue | Implementation | Tests / actual evidence | Docs | Audit status / remaining limit |
| --- | --- | --- | --- | --- |
| #4 typed outputs | `slopforge/manifest.py` | `tests/test_manifest.py`; migration and backward-compatibility tests | `docs/ASSET-OUTPUTS.md` | **VERIFIED**; additive schema and legacy migration are covered. |
| #5 recipes | `slopforge/recipes.py` | `tests/test_recipes.py`, `tests/test_recipe_cli.py`; live H100 recipe smoke passed | `docs/RECIPES.md` | **VERIFIED** for resumable recipe execution, dependency ordering, and partial regeneration. |
| #6 reference conditioning | `slopforge/conditioning.py`, ComfyUI client binding | `tests/test_conditioning.py`; local HTTP-server tests cover upload/binding; #21 paired live Wan inference | `docs/STYLE-SYSTEM.md`, `docs/COMFYUI.md`, `docs/archive/reference-conditioning-2026-10.md` | **VERIFIED at its transport scope**; #21 separately qualifies one experimental image-to-video graph. |
| #7 review board | `slopforge/review.py` | `tests/test_review.py`, `tests/test_review_actions.py` | `docs/REVIEW-BOARD.md` | **VERIFIED** as static HTML; no browser automation or browser-side mutation. |
| #8 explore/promote | `slopforge/exploration.py`, candidate lifecycle | `tests/test_exploration.py`; mocked CLI flow covers explore → promote → approve | `docs/EXAMPLES.md` | **VERIFIED** for stored design variations/provenance; model diversity remains workflow-dependent. |
| #10 UI packs | `slopforge/ui.py`, `slopforge/unity_ui.py` | `tests/test_ui_packs.py`, `tests/test_unity_ui.py`; prior Unity 6 editor smoke documented | `docs/EXAMPLES.md`, `README.md`, `templates/recipes/starter_ui_pack.yaml` | **VERIFIED** for starter components/import metadata and optional prefab route; responsive complete HUD/menu is not included. |
| #11 VFX packs | recipe and `slopforge/unity_vfx.py` | `tests/test_vfx_packs.py`, `tests/test_unity_vfx.py`; prior Unity 6.6.3f1 smoke documented | `docs/VFX-PACKS.md` | **VERIFIED** for deterministic packaging and optional ParticleSystem output; motion/alpha quality is provider-dependent. |
| #12 environment kits | `slopforge/environment.py`, Blender inspection | `tests/test_environment_kits.py`; prior Blender 5.1 headless fixture smoke documented | `docs/ENVIRONMENT-KITS.md` | **VERIFIED** for recipe structure and measurements; demo-room assembly remains follow-up. |
| #13 tilesets | `slopforge/tileset.py`, `slopforge/unity_tiles.py` | `tests/test_tilesets.py`, `tests/test_tile_packs.py`, `tests/test_unity_tiles.py`; prior Unity 6.6.3f1 smoke documented | `docs/TILESET-PACKS.md` | **VERIFIED** for slicing, diagnostics, tile metadata, and optional Tile assets; RuleTile/Palette authoring remains unimplemented. |
| #17 reference libraries | `slopforge/libraries.py` | `tests/test_libraries.py`; stable resolution/hash/missing-entry cases | `docs/REFERENCE-LIBRARIES.md` | **VERIFIED**; external membership is referenced, not copied. |
| #18 quality tiers | `slopforge/quality.py`, `slopforge/config.py` | `tests/test_quality.py`; config precedence and host-independence coverage | `docs/QUALITY-TIERS.md` | **VERIFIED** for portable configured tiers; cost estimates are only shown when supplied. |
| #20 workflow requirements | `slopforge/workflow_requirements.py`, `slopforge/doctor.py`, generation provenance | `tests/test_workflow_requirements.py`, `tests/test_provenance.py`; all six bundled graphs pass live H100 node/model preflight, including background-removal checkpoint choices | `docs/WORKFLOWS.md`, `docs/COMFYUI.md`, `docs/ASSET-OUTPUTS.md` | **VERIFIED** for API JSON sidecars, stale/missing requirement checks, legacy diagnostics, and packaged sidecars. Inline Hunyuan remains explicitly unknown. |

## Open-roadmap traceability

| Issue | Evidence found | Status |
| --- | --- | --- |
| #9 2D identity/sprites | Identity-conditioned recipe and deterministic `spritepack` exist (`tests/test_character_recipe.py`, `tests/test_spritepack.py`, `docs/SPRITE-PACKS.md`). Wan 2.2 TI2V 5B and earlier I2V samples were nearly static. A separate 17-frame Wan Animate API run produced a readable short action; BiRefNet output had genuine alpha after mask inversion, but frames touched the canvas edge. An 81-frame attempt hit the H100 memory cgroup OOM and produced no output. No approved multi-action pack, stable anchor/crop, or Unity playback is verified. | **PARTIAL / OPEN** |
| #14 3D character/rigging | Provider-result contract, readiness gate, and Blender Rigify heuristic exist (`slopforge/character_rigging.py`, `slopforge/character_readiness.py`). SkinTokens completed isolated inference on the original invalid Hunyuan mesh and again on its topology-repaired copy. The second output has normalized weights (max four influences) and visibly better elbow/arm pose response than Rigify, but contains nine mesh components, no material, and an unskinned helper. The source remesh passed structural readiness; Rigify then completed but its pose sheet shows severe elbow/shoulder and limb deformation. The SkinTokens FBX imported in Unity 6000.6.3f1 as Generic with one skinned renderer, 28 bones, and 28 bind poses; no animation or playback was tested. A projection bake from the single-view concept tiled visibly and is not usable texture coverage. | **PARTIAL / OPEN** — promising deformation and import evidence, still no acceptable textured character, reproducible provider runtime, human review, or Unity animation validation. |
| #15 animation/Humanoid | Clip libraries and Blender retargeting are covered by unit and Blender fixtures. The fresh-project Unity path populates the Humanoid skeleton before applying the explicit Rigify map, preserves animation FBX hierarchy, and validates the saved prefab's controller and Avatar. Opt-in Blender 5.1 + Unity 6000.6.3f1 integration passed on a synthetic humanoid fixture. A separate SkinTokens candidate imported as Generic with 34 bones and bind poses; no clip/controller/playback was tested. | **PARTIAL / OPEN** — depends on #14; no acceptable generated character or visible Unity playback is qualified. |
| #16 prototype orchestration | Editable, fingerprinted, approval-gated seven-stage lunar refinery plan with 63 items, resumption, budgets, dependencies and child regeneration exists (`slopforge/prototypes.py`, `tests/test_prototypes.py`). It is recipe-driven and not concept-aware. | **PARTIAL / OPEN** |
| #21 visual-conditioning qualification | `workflows/wan22_ti2v_reference_api.json`; paired same-prompt/seed live H100 inference with approved reference and neutral image control; outputs and provenance saved. | **VERIFIED for this graph; experimental, not a production default** |
| #22 animation readiness | Blender mesh inspection now records components/topology, transforms, normals, bounds/scale, face budget, source artifact/hash, and a separate readiness decision. Rigging requires approved readiness; CLI inspection/approval and Blender fixtures are covered by the full suite. | **VERIFIED; gate does not prove deformation or Unity validity** |
| #19 epic | Checklist now tracks #20, #21, #9, #22, #14, #15 and #16 in dependency order. | **OPEN; roadmap reconciled** |

Original acceptance tests and implementation summaries are on the linked GitHub issues. They have not been silently rewritten as “done” where live evidence failed.

## Capability map

The expanded lifecycle map, system priorities, ComfyUI workflow-family coverage, provider decisions, and technical debt are in [Capability roadmap 2026](../CAPABILITY-ROADMAP-2026.md).

| Capability | State | Evidence / caveat |
| --- | --- | --- |
| Atomic 2D generation, candidate review, approval, provenance | Implemented | Live H100 image run passed; alpha request produced opaque RGB PNGs. |
| Typed multi-output manifests, recipes, resumability, quality tiers | Implemented | Offline suite and live H100 recipe test. |
| Static review board and explicit references/libraries | Implemented | Unit tests; review board is not an interactive app. Bundled image graph is text-only. |
| UI/VFX/environment/tile/character-sprite pack packaging | Implemented, provider-dependent | Deterministic packagers work. Generated motion/alpha quality has not been proven for sprites/VFX. |
| 3D props with material maps and Unity export | Experimental | Real outputs and Blender/Unity checks exist; mesh defects and material coverage still require visual review. |
| Automatic 3D character rigging | Experimental / blocked on quality | Rigify requires clean humanoid geometry; generated H100 meshes failed QA. |
| Unity Humanoid retargeting | Experimental / verified on fixture | Rigify synthetic fixture produced a valid Unity Humanoid Avatar, imported a Humanoid clip, and created a controller/prefab. No generated character or visible in-scene playback is qualified. |
| Concept-aware prototype content plan | Partial | Approval-gated recipe plan exists; concept-to-plan generation does not. |
| Audio generation, terrain/foliage/skybox/lighting, semantic asset search, scheduler/cache | Planned research only | No current implementation; not necessary to close an immediate correctness gap. |

## Confirmed gaps and proposed priority

1. **P0/P1 — #9 qualified sprite pipeline.** Acceptance requires distinct motion, stable identity, useful alpha and deterministic packaging, followed by visible Unity playback. The experimental Wan graph shows reference-image effect but does not qualify identity transfer or sprites.
2. **P1 — #14 provider bake-off**, now gated by the #22 readiness report/approval. Use a shared mesh corpus and isolated provider environments.
3. **P1 — #14/#15 generated-character qualification.** Keep generation, readiness, deformation, rig, Unity Avatar and clip playback as separate gates; the fixture path now works, but H100 character meshes have not passed.
4. **P1 — #16 concept-aware plan generation**, then #19 acceptance on a fresh idea-to-prototype-content run.

**#20, #21, and #22 are implemented on `codex/prototype-content-factory`.** #21 qualifies one reference-consuming workflow with paired visual evidence; this does not imply #6 was incorrectly closed because its written criteria covered transport, workflow input binding and provenance. Next is #9. Do not advance #14 by installing an unverified node stack into production ComfyUI.

## Scope and limitations of this audit

The H100 smoke proved one two-icon recipe path, HTTP output retrieval, and the paired reference-conditioning qualification. It did not test local ComfyUI, the full Wan sprite workflow, Unity interaction during this audit, or a fresh TRELLIS inference. Previous H100, Blender, and Unity evidence is explicitly marked above and in its issue documentation. No 1536³ run was performed. Model weights and the H100's ComfyUI environment were not modified.

## Product scope decision (2026-10-06)

SlopForge is now focused on 3D game assets, character rigging/animation, Blender processing, and Unity delivery. The previous status rows for sprites, UI, VFX, tilesets, and concept-aware prototype planning are historical audit evidence, not active product commitments. Their bundled generators, packagers, import commands, and starter recipes have been removed. Keep the negative sprite benchmark evidence and named-source ecosystem research for traceability.

- **#6 reference conditioning:** retain the generic reference-input plumbing for 3D concepts/materials. The Wan image-to-video qualification is not qualification evidence for image-to-3D conditioning.
- **#9 sprites:** closed as outside active product scope; sprite output and its shipped pipeline are removed.
- **#14 rigging:** highest-priority product gap. Separate mesh readiness/material preservation, rigging/skinning, deformation review, and Unity playback gates.
- **#15 animation:** keep the skeletal 3D route; qualify retargeting and real Unity playback before claiming generated-character animation works.
- **#16 prototype planner:** closed as outside active product scope; keep editable 3D recipe orchestration.
- **#19 epic:** rewritten around coherent, engine-ready 3D assets and the remaining qualification sequence.
- **#24 Unity reimport:** narrowed to stable replacement of textures/materials and 3D models; sequence after the #14 output contract.

## Implementation delta (2026-10-06)

The current branch now includes SkinTokens as an opt-in isolated rigging provider and exposes character normalization/approval stages through the CLI. This changes integration status, not qualification status: no generated character has passed readiness on the normalized textured mesh, reviewed deformation, and Unity animation playback gates. The dated provider experiments above remain historical evidence.
