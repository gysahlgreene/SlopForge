# Mesh texturing fix: status and handoff

**Date:** 2 October 2026  
**Repository:** `<slopforge-checkout>`

**Test project:** `<workspace>/sloptest1`

**Git baseline:** `e81185f` — `can't stop the slop`

## Current outcome

**The mesh preview is substantially better, and the Unity material handoff now has a tested fix.** A real end-to-end run produces a charcoal relay with a turquoise front plate and copper couplings. Unity previously imported the FBX with all texture slots empty; SlopForge now creates a Unity PBR material and explicitly remaps it to the FBX during approval. The candidate remains unapproved. Attached surface artifacts and actual in-project visual review remain open.

The asset `prop:sloptest_power_relay_trellis` is at `awaiting_texture_approval`. Concept candidate 1 is approved; material candidate 3 is the new review candidate, but **no material is selected or approved**. Final asset outputs in the manifest remain empty. Candidate 3 is under `ai/assets/candidates/prop/sloptest_power_relay_trellis/material_03/` in the test project.

The user resumed implementation after asking for this document. The sections below record the original pause point and follow-up work, evidence, remaining gaps, and reproducibility details.

## Results since the pause

The direct `PaintMesh` probe was rendered. Its raw 6.65-million-face mesh showed a pale blue plate on a coherent but impractical mesh. A same-seed comparison on a prepared 28,197-face mesh showed substantial differences between direct vertex painting and UV baking. Removing `BakeTextureFromVoxel`'s optional high-resolution reference mesh did not materially change the baked result, so that projection is not a confirmed cause.

The high-to-low normal map was the main visible source of speckling. Rendering the same 1024-route mesh without its normal connection made it substantially smoother while retaining the material colors. The native workflow now omits that normal bake; SlopForge writes a flat tangent normal map, and the mesh uses smooth geometric normals.

The native workflow now adds TRELLIS.2's 512-to-1024 shape upsample pass with six sampling steps before texture generation. SlopForge's actual approval flow generated material candidate 3 from the transparent cutout:

- Appearance: charcoal housing, turquoise front plate, copper side couplings, pale accents.
- Validation after cleanup: **28,328 faces** under the 30,000-face budget; **8 disconnected components**, down from 94 (and 1,256 on candidate 2). The cleanup removed 86 detached single-triangle fragments. A small-component warning remains; several larger detached components were preserved because they may be intentional details.
- State: `awaiting_texture_approval`; candidate 3 is unselected and unapproved. Final asset outputs in the manifest remain empty.
- Preview files are in `ai/assets/candidates/prop/sloptest_power_relay_trellis/material_03/Previews/`.
- Mesh generation seed: `3621470973`.

This is a clear visual improvement, not a finished game asset. The side preview still shows attached reconstruction defects around the lower housing and support.

### Unity material handoff

A temporary Unity 6000.6.3f1 project imported the candidate FBX and revealed the actual failure: Unity created a renderer and Standard material, but the material's base color, normal, and metallic texture slots were empty. The FBX embedded image files, but Unity did not connect them to the imported material. This explains why a Blender preview could look textured while the Unity model did not.

Texture approval now builds a metallic/smoothness image (metallic in RGB, inverse roughness in alpha), creates a Unity Lit material with the generated base color, normal, metallic/smoothness, and emission maps, and writes an explicit FBX material remap. The Blender source maps remain separate. On the temporary Unity project, the remapped FBX imported with **26,168 vertices and 28,328 triangles**; Unity reported the base color, normal, and metallic/smoothness maps on its material. A Unity front render is saved at `ai/assets/candidates/prop/sloptest_power_relay_trellis/material_03/Previews/sloptest_power_relay_trellis_unity_front.png`.

The test project `<workspace>/sloptest1` is only an Assets/config fixture; it has no `ProjectSettings/ProjectVersion.txt`, so the real approval step cannot yet run against that directory. The Unity check used a separate temporary Unity project with the built-in Standard shader. Its render confirms the colored regions display on the mesh; it does not verify the user's project lighting or URP shader. The approval flow requires a valid Unity project and the Unity CLI. To check the complete path, I copied the test project data into a disposable Unity project, ran `approve-texture 3`, and confirmed it reached `ready`; the exported FBX and `.mat` passed a second Unity import and render.

The 1536 cascade was tested and stopped because its first MPS sampler step took over four minutes. On this Mac, the actual 1024 cutout run took about 12 minutes for six upsample steps and 12.5 minutes for the 12 texture steps, plus mesh processing. A white-background diagnostic was faster. The higher resolution improved material region separation, but the actual MPS route has substantial runtime cost.

The real CLI run also exposed a Python environment issue. `python_executable()` resolved `.venv/bin/python` through its symlink to the system interpreter, losing the virtual environment and failing to import Pillow. It now preserves the configured executable path; the actual approval flow then completed successfully.

## Target and original failure

The intended workflow is agent driven: an agent designs the asset, writes a specific creative prompt, reviews candidates, and checks the result on an actual mesh. The target example is a solid alien power relay with graphite housing, a turquoise ceramic front plate, copper side couplings, an amber lens, and ivory accents.

The concept image was good, but the Hunyuan geometry plus separately generated surface swatch produced arbitrary color blocks or blurry stripes over the mesh. Both original material attempts also exceeded the 30,000-face budget at 33,530 faces. A swatch supplies surface appearance without knowing which part of the object should receive each material; better prose alone does not establish that correspondence.

Original evidence, relative to the test project:

- Concept: `ai/assets/candidates/prop/sloptest_power_relay/candidate_01.png`
- Failed swatch previews: `ai/assets/candidates/prop/sloptest_power_relay/material_01/Previews/sloptest_power_relay_front.png` and the equivalent `material_02` path.

## Changes implemented

### Native mesh-aware material generation

Added `workflows/trellis2_image_to_model_api.json`, using ComfyUI's portable TRELLIS.2 implementation. It runs inference on this Mac through PyTorch MPS. The test project's `ai/project.yaml` selects it through `asset_pipeline.workflows.model`. Projects without that setting retain the Hunyuan/swatch route; the template exposes the native option as a comment.

The native route now performs these stages:

1. ComfyUI generates a 512-resolution shape, upsamples its latent to 1024, then decodes raw geometry from the approved concept.
2. Blender voxel-remeshes the dense output, reduces it to the configured budget, unwraps it, and exports a prepared GLB in the generator's coordinate frame.
3. ComfyUI reloads that mesh, generates learned material voxel fields, and bakes base color, metallic, and roughness into its UVs.
4. SlopForge copies those maps unchanged, preserves the UVs during Blender processing, exports FBX, and renders review previews.
5. The high-to-low normal bake is omitted because it introduced severe speckling on the remeshed geometry. A flat tangent normal map is used. The material remains a candidate until approved.

Blender preparation replaces ComfyUI's mesh reduction/unwrap stages because `DecimateMesh` encountered unsupported MPS integer `scatter_reduce_`, and CPU unwrapping of the dense raw mesh was prohibitively slow. The corrected raw geometry contains roughly 6.65 million triangles. Cleanup uses approximately 256 voxel cells along its largest extent, with repeated reduction checks and a minimum 2048 texture bake resolution.

Related behavior now implemented:

- Configured workflow and Blender executable pass through the backend to the generation driver.
- Driver requires generated base color, roughness, and metallic maps, waits for completed Comfy history, rejects node errors, and records workflow/model/seed provenance. It supplies a flat normal map because the remesh bake produced severe artifacts.
- Native candidates use `kind: mesh_pbr`; swatch candidates use `kind: surface_swatch`.
- Native material design follows the concept. Unsupported `--material-prompt` overrides are rejected before file changes; native swatch retexturing is rejected, and guided review omits that option.
- Forced regeneration preserves candidate records and appends candidate numbers, with supersession handling for older viable candidates.
- Doctor checks the configured native workflow and weights instead of requiring the unused Hunyuan checkpoint.
- Native emission is currently a zero map. Glass transmission is not generated.

### Confirmed Apple GPU precision defect

The first native output was shredded into horizontal strips even before reduction. A concrete defect was found in integer sorting on the installed PyTorch MPS backend: returned sorted values lost precision for voxel IDs above `2**24`, although sort indices were correct. This broke sparse neighbor lookup and material voxel sampling.

The actual hash-map reproduction missed **1,023 of 1,024 valid neighbors**. Replacing returned sort values with `argsort()` followed by gathering the original integer keys produced **zero misses**.

Local ComfyUI patches apply that change in:

- `<comfyui-install>/comfy/ldm/trellis2/flexgemm.py`
- `<comfyui-install>/comfy_extras/nodes_mesh_postprocess.py` — both affected sampling functions.

Reproducible patch: `scripts/comfy_mps_sort_fix.patch`. Regression check: `scripts/check_comfy_mps_sort.py`. The check passed on MPS for the actual hash map, nearest sampling, and trilinear sampling. Run it with:

```sh
<comfyui-install>/.venv/bin/python scripts/check_comfy_mps_sort.py <comfyui-install>
```

After patching and restarting ComfyUI, raw geometry was solid and recognizable. Evidence: `/tmp/slopforge_fixed_geometry/relay_front.png`. This confirms repaired surface coverage, not acceptable final asset quality.

### Corrections to the existing swatch route

- Previously only base color was projected into the mesh UV atlas; the other channels remained in source-swatch coordinates. All channels now follow the projection, with tangent normals baked from projected luminance bump.
- Texture loading reloads modified files instead of retaining cached pre-bake images.
- Heuristic map generation recognizes graphite/charcoal/matte and prioritizes the first material description.
- Connectivity inspection merges exactly coincident positions so UV/normal seams do not falsely count as separate physical components.

These correct pipeline defects. They do not solve assignment of different materials to semantic parts of the model.

## Earlier poor result: candidate 2

The actual approval CLI ran against real ComfyUI and Blender. The seed source was pinned to **1113241411** to resume cached inference after adding cleanup; generation and processing were not mocked.

| Item | Recorded result |
| --- | --- |
| Asset | `prop:sloptest_power_relay_trellis` |
| Material candidate | 2, `mesh_pbr`, unapproved |
| Validation | `passed_with_warnings` |
| Faces / budget | 27,366 / 30,000 |
| Vertices | 37,580 |
| Disconnected components | 1,256; tiny debris warning |
| UV layers / materials | 1 / 1; different colors share a texture atlas |
| Texture images | 5, none missing; emission is zero |
| PBR prompt ID | `0a440b5f-1df2-44e9-8c89-8bc9c7978961` |

The candidate's `generation.json` records shape prompt ID `cf8a38ab-8266-4eb0-a134-39d728e490ba`; an earlier diagnostic shape request was `3fc4267e-2c37-4578-8869-cf763a0a432f`. Use the saved generation record when tracing this candidate.

Candidate directory, relative to the test project:

```text
ai/assets/candidates/prop/sloptest_power_relay_trellis/material_02/
```

It contains `generation.json`, `validation.json`, the FBX, preview Blend file, `Materials/sloptest_power_relay_trellis_{basecolor,normal,roughness,metallic,emission}.png`, and front/side/rear renders under `Previews/`.

**Observed visual problems on candidate 2:** copper coupling colors were present, but the turquoise plate was largely absent. Geometry was rough/chipped with shading artifacts. Disabling the normal map removed much of the speckling, but this lower-resolution result still had weak material color separation.

Controls and logs:

- `/tmp/slopforge_native_albedo_control_2.png`
- `/tmp/slopforge_native_geometry_control_2.png`
- `/tmp/slopforge_native_pbr_control.py`
- `/tmp/slopforge_native_cli_run.log`
- `/tmp/slopforge_cleaned_mesh_check.log`

A glTF export emitted a mesh-validity warning. A subsequent Blender `mesh.validate(verbose=True)` returned `False`, meaning no repairs were performed by that check. That does not establish clean topology or good visual quality.

## Latest real run: candidate 3

The actual SlopForge approval flow ran with the updated workflow and flat normal map. It completed with ComfyUI, Blender, and the project virtual environment.

| Item | Result |
| --- | --- |
| Material candidate | 3, `mesh_pbr`, unapproved |
| Mesh seed | `3621470973` |
| Faces / budget | 28,328 / 30,000 after cleanup |
| Vertices | 26,000 in Blender; 26,168 after Unity FBX import |
| Disconnected components | 8 after removing 86 single-face islands; small-component warning remains |
| Status | `passed_with_warnings` |
| Asset status | `awaiting_texture_approval`; no candidate selected |
| Materials | base color, flat normal, roughness, metallic, packed metallic/smoothness, and zero emission |

The candidate is a visible improvement over candidate 2: its face plate reads turquoise, its side couplings read copper, and the front/side/rear renders are much smoother. The side still shows some reconstruction defects. Candidate files are under `ai/assets/candidates/prop/sloptest_power_relay_trellis/material_03/` in the test project.

The 1024 MPS run took about 12 minutes for the six shape upsample steps and 12.5 minutes for the 12 material steps, in addition to other stages. The 1536 test was stopped after its first step exceeded four minutes. The 1024 route improves color separation at a high runtime cost on this Mac.

## Diagnostics since the pause

A **PaintMesh → SaveGLB** probe completed using the corrected cached raw mesh and learned color voxels. It bypasses UV baking and uses CPU nearest-neighbor voxel coloring.

- Request: `09e345f8-10f8-4f7c-a3bc-3566154965bb`
- Output: `<comfyui-install>/output/slopforge/trellis_probe/painted_fixed_00001_.glb` — file existence confirmed at documentation time.
- Rendered front view: `/tmp/slopforge_vertex_probe/front.png`.

The direct-paint probe used a dense raw mesh and did not establish a usable export path. The same-seed direct-paint versus UV-bake comparison confirmed map differences; removing the reference mesh did not improve the render. The remaining exact cause of those map differences is unresolved.

Remaining work: inspect the residual attached geometry defects, run the approval flow against a real Unity project (the current test fixture is not one), and decide whether the 1024 route's visual improvement is worth its long MPS runtime.

## Verification already performed

| Evidence | Status and limit |
| --- | --- |
| Existing unit suite after initial backend changes | 40 tests passed at that stage |
| New native material tests | 2 passed |
| Expanded Blender material tests | 2 passed after correcting a fixture UV expectation |
| Current unit suite | 45 of 46 tests passed; the remaining Doctor test returns failure because `rembg`/`onnxruntime` are absent from the ComfyUI Python environment |
| Actual MPS regression | Passed |
| Doctor check | Earlier project Doctor run passed; this test environment lacks `rembg`/`onnxruntime`, causing one Doctor unit test to fail |
| End-to-end generation | Candidate 3 completed with validation warnings |
| Python compilation / workflow JSON / diff whitespace | Passed after the material handoff changes |
| Unity FBX/material import and render | Passed in temporary Unity `6000.6.3f1`; renderer has base color, normal, and metallic/smoothness maps on both candidate and approved FBX |
| Full `approve-texture` flow | Passed in a disposable Unity project copy; manifest reached `ready`, FBX/material/maps exist |
| Target project Unity approval | Not run; `<workspace>/sloptest1` lacks `ProjectSettings/ProjectVersion.txt` |

Latest suite output: `/tmp/slopforge-unit-tests-current.log`. Unity material assignment and render logs: `/tmp/slopforge_approved_import.log` and `/tmp/slopforge_approved_render.log`.

## Local state and reproducibility

At documentation time the repository has uncommitted edits to the generation driver, model pipeline, Blender processing/inspection, backends, CLI, Doctor, heuristic maps, templates, tests, and documentation. New workflow, MPS patch/check, Unity material builder, mesh cleanup, and native tests are untracked. These changes have not been committed or pushed as part of this fix.

External changes also matter:

- Test project `ai/project.yaml` selects TRELLIS.2; its manifest and generated artifacts have changed.
- Candidate 3's Blend, FBX, previews, validation record, manifest entry, and added metallic/smoothness map were updated by the single-face debris cleanup. It remains an unselected candidate.
- Local ComfyUI source contains the two patches above, outside this repository. A repo checkout alone does not install them; a ComfyUI update may overwrite them.
- Approximately 8 GB of Comfy-Org weights were downloaded into `<comfyui-install>/models/`: `diffusion_models/trellis_2_int8_convrot.safetensors`, `clip_vision/dino_v3_vit_l.safetensors`, and `vae/trellis_2_{shape,texture}_vae_bf16.safetensors`.
- ComfyUI was restarted with `PYTORCH_ENABLE_MPS_FALLBACK=1`; its launch log is `/tmp/slopforge_comfy_trellis.log`.
- Diagnostic `/tmp` files are local temporary evidence and may disappear.

README, `docs/AGENT-INTEGRATION.md`, CONTEXT, and agent/project templates have been updated. Some generalized swatch/heuristic descriptions in `docs/STYLE-SYSTEM.md` and `docs/EXAMPLES.md` still need reconciliation. This document records the candidate cleanup and Unity material remap work; real-project approval and scene-level visual review remain open.
