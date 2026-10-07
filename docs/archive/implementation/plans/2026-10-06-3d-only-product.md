# 3D-only product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans implement plan task-by-task. Steps use checkbox (`- [ ]`) syntax tracking. **Goal:** Remove SlopForge's shipped 2D output lanes and generic prototype planner while keeping a focused 3D asset, character, and Unity pipeline. **Architecture:** Retire 2D-only commands, modules, templates, tests, and user docs. Preserve shared image/reference generation only for 3D concept and material inputs, shared recipe orchestration, and all current 3D/rigging changes. **Tech Stack:** Python CLI, YAML project templates, pytest suite (not run during this pass), Markdown docs, ComfyUI workflow JSON. **Spec:** `docs/archive/implementation/specs/2026-10-06-3d-only-product-design.md`

## Global Constraints

- Preserve all pre-existing working-tree changes and user data.
- Do not delete research reports, sprite benchmark evidence, generated evidence, or existing initialized project data.
- Preserve local/remote HTTP ComfyUI, reference libraries, provenance, approval/review, quality tiers, resumable recipes, Blender/Unity 3D routes, and current character work.
- Do not run tests during this pass; use CLI/static checks only.
- Do not touch `main` or push.

## Review Focus

- Project initialization must still ship `concept` and `texture` inputs plus 3D types and 3D recipes.
- Parser command discovery must no longer advertise prototype, sprite, UI, VFX, or tileset commands.
- Shared image candidate support must remain available for concept/material inputs.
- Recipe resume and environment validation must remain available after prototype planner deletion.
- Unity skeletal animation and character rigging commands must remain registered and dispatchable.

## File Map

- `slopforge/cli.py`: remove retired imports, parsers, command-name routing, and dispatch blocks.
- `slopforge/initializer.py`: stop creating prototype/2D directories; continue copying remaining 3D taxonomy and recipe templates.
- `slopforge/`: delete prototype planner, placeholder primitive route, and 2D-only pack/import modules; keep shared HTML review, recipes, image pipeline, and 3D Unity modules.
- `templates/asset_types/`, `templates/recipes/`, `workflows/`: delete shipped types/recipes/workflows that only support retired output lanes; retain concept/material and 3D graphs.
- `tests/`: delete tests exclusive to removed modules; update shared fixtures/expectations that refer to deleted starter types.
- `README.md`, active product docs, `pyproject.toml`: remove 2D product claims, document the 3D workflow and remaining evidence limits, and update the package description. Glob-based package data will then include only retained files.
- `docs/research/` and `docs/media/`: preserve as historical research/evidence.

### Task 1: Remove non-3D CLI surface

**Files:** `slopforge/cli.py`, `slopforge/taxonomy.py`, `slopforge/recipes.py`

- [x] Remove imports for `prototypes`, `spritepack`, sprite/UI import settings, VFX prefabs, tilesets, Unity tile helpers, and the placeholder primitive registration route.
- [x] Remove parser blocks and `COMMANDS`/`parse_args` dispatch entries for `spritepack`, `tilepack`, `tile-unity`, `ui-meta`, and `prototype`.
- [x] Remove the corresponding `_run` branches and native-pipeline support; retain `recipe`, `environment-check`, `animation`, and `character` routes.
- [x] Search `slopforge/cli.py` for every retired command symbol and confirm none remain.

### Task 2: Retire modules, templates, and tests for removed lanes

**Files to delete:**

- `slopforge/prototypes.py`, `slopforge/spritepack.py`, `slopforge/tileset.py`, `slopforge/ui.py`, `slopforge/unity_tiles.py`, `slopforge/unity_ui.py`, `slopforge/unity_vfx.py`.
- `templates/asset_types/{decal,icon,portrait,sprite_sheet,tile_sheet,ui,vfx_sheet}.yaml`.
- `templates/recipes/{character_sprite_pack,starter_icons,starter_tileset_pack,starter_ui_pack,starter_vfx_pack}.yaml`.
- `workflows/wan22_ti2v_reference_api.json`, `workflows/wan22_ti2v_reference_api.requirements.yaml`, `workflows/wan_animate_reference_api.json`, `workflows/wan_animate_reference_api.requirements.yaml`, `workflows/wan_animate_sprite_api.json`, and `workflows/wan_animate_sprite_api.requirements.yaml`.
- `tests/test_prototypes.py`, `tests/test_spritepack.py`, `tests/test_tile_packs.py`, `tests/test_tilesets.py`, `tests/test_ui_packs.py`, `tests/test_unity_tiles.py`, `tests/test_unity_ui.py`, `tests/test_unity_vfx.py`, `tests/test_vfx_packs.py`.
- `tests/test_recipe_h100.py`, which exercises only the retired `starter_icons` recipe.
- Product guides dedicated to the removed lanes: `docs/PROTOTYPES.md`, `docs/SPRITE-PACKS.md`, `docs/TILESET-PACKS.md`, and `docs/VFX-PACKS.md`.

- [x] Confirm exact filenames before deleting; do not remove 3D workflows, character animation tooling, `docs/research/**`, or `docs/media/**`.
- [x] Update `initializer.py` to stop creating `ai/prototypes` and the `Icons`, `UI`, `Portraits`, `Decals`, `Tilesets/Spritesheets`, `VisualEffects/Spritesheets`, and `Characters/Spritesheets` Unity output folders. Retain `ai/animation_libraries`, which is used by skeletal 3D animation.
- [x] Remove 2D-only output folders from `templates/project.yaml` if present; retain `Concepts`, `Textures`, `Props`, `Models`, and `Characters`.
- [x] Update shared tests and fixtures from retired output types to `concept` or `prop` only where the test exercises shared behavior; do not delete shared tests for image inputs, recipes, review, provenance, or quality tiers.

### Task 3: Rewrite the product surface around 3D

**Files:** `README.md`, `docs/ARCHITECTURE.md`, `docs/ASSET-OUTPUTS.md`, `docs/EXAMPLES.md`, `docs/DEMO.md`, `docs/RECIPES.md`, `docs/UNITY.md`, `docs/COMFYUI.md`, `docs/WORKFLOWS.md`, `docs/QUALITY-TIERS.md`, `docs/STYLE-SYSTEM.md`, `docs/INSTALL.md`, `docs/SETUP.md`, `docs/CAPABILITY-ROADMAP-2026.md`, `docs/archive/release-audit-2026-10-04.md`, `pyproject.toml`

- [x] Rewrite README opening/capability table and examples so the primary flow is concept/reference → 3D generation → mesh cleanup/readiness → character rigging/deformation review → Unity import.
- [x] Keep a clear caveat that current generated meshes and rigs are not production-qualified until visual deformation and Unity playback pass.
- [x] Remove product links and claims for sprite/UI/VFX/tileset/prototype lanes while retaining links to historical ecosystem research.
- [x] Replace `starter_icons` walkthroughs with retained character/environment 3D recipes; update reference examples from icon categories to approved concept references.
- [x] Remove UI import guidance from `docs/UNITY.md` and Wan video workflow instructions from active ComfyUI/workflow docs; preserve qualification and benchmark material as historical evidence.
- [x] Update the active capability roadmap to rank mesh readiness, character rig/deformation, and Unity playback as the core sequence. Append the specialization decision to the audit without rewriting its historical findings.
- [x] Update architecture and typed-output examples to show concept, model, cleaned/rigged model, materials, and skeletal animation artifacts only.
- [x] Remove stale 2D/template claims from install and setup docs; update package-description metadata to call SlopForge a focused 3D game asset pipeline.
- [x] Keep existing Unity environment and material documentation that supports 3D outputs.

### Task 4: Verify the reduced surface without running tests

- [x] Run `.venv/bin/python -m slopforge.cli --help` and confirm it shows only the retained command groups.
- [x] Run parser help for `generate`, `recipe`, `character`, and `animation` to confirm key 3D routes remain.
- [x] Run `rg` across `slopforge`, `templates`, and active product docs for retired module imports, command names, and shipped starter recipe names; resolve product-code references while leaving research/history untouched.
- [x] Inspect `git status --short --branch` and the final diff to confirm all pre-existing 3D work remains and only approved 2D product files/docs/tests are removed or edited.
- [x] Do not run `pytest` or live ComfyUI/Blender/Unity workflows in this pass.
