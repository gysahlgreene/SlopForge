# 3D workflow inventory

SlopForge stores API-format ComfyUI graphs in `workflows/`; a project override in `ai/workflows/` takes precedence. Workflows and model weights are external runtime requirements. `slopforge doctor` checks declared node classes and model choices against ComfyUI `/object_info`; it does not prove inference quality or validate the resulting geometry.

| Workflow | Capability | Models | Evidence and limits |
| --- | --- | --- | --- |
| `image_text2img_api.json` | Supporting concept and material images | Z-Image Turbo BF16, Qwen 3 4B encoder, `ae.safetensors` VAE | Live H100 inference passed. Text-only; not an image-to-3D workflow. |
| Built-in Hunyuan3D v2 graph (`processing/comfy_generate_3d.py`) | Image-to-3D GLB, followed by a surface-swatch material route | `hunyuan3d-dit-v2_fp16.safetensors` | Inline legacy graph with no graph file hash or requirements sidecar. |
| `trellis2_image_to_model_api.json` | Image-to-3D mesh-aware base color/metallic/roughness | TRELLIS.2 INT8 ConvRot, DINOv3 ViT-L, shape and texture VAEs | Conservative/Mac-oriented profile; API structure checked against H100, no recent INT8 inference run. |
| `trellis2_image_to_model_h100_api.json` | Image-to-3D mesh-aware PBR, with the full-detail shape saved for Blender's normal bake | TRELLIS.2 BF16, DINOv3 ViT-L, shape and texture VAEs | The `h100` profile's model graph. At the `final` tier it runs a 1536 shape upsample with 4096² maps ([quality tiers](QUALITY-TIERS.md)); every prop (v1–v5) and kit (M2-v1–v3) protocol run used it. Shape/material quality remains asset-dependent. |
| `trellis2_image_to_model_h100_final_api.json` | Higher-resolution image-to-3D mesh-aware PBR | Same BF16 model set | Graph is prepared and passes capability checks; no 1536³ inference is claimed. |
| `pixal3d_image_to_model_h100_api.json` | Camera-conditioned image-to-3D mesh-aware PBR | Pixal3D BF16, DINOv3+NAF, TRELLIS.2 shape and texture VAEs | H100 inference completed at 1536 cascade and 4096 texture size. Output quality remains asset-dependent; inspect geometry, texture coverage, and topology before use. |
| `trellis2_image_to_model_h100_character_api.json` | Image-to-3D for characters on the `h100` profiles (`character_model`) | Same BF16 model set | Used by the character style runs ([character styles](media/character-styles-2026-10/README.md)); experimental. |
| `image_character_pose_api.json` | Pose-conditioned character concepts from the A-pose OpenPose image in `workflows/inputs/` | Z-Image Turbo with a pose ControlNet | Used for every character concept on the `h100` profiles. |
| `image_seamless_inpaint_api.json` | Repaints a tiling material's seam cross (`seams: repaint`) | Z-Image Turbo, as the concept graph | Opt-in; `cut` seams are the default ([natural environments](NATURAL-ENVIRONMENTS.md)). |
| `image_upscale_esrgan_api.json` | Upscales a tiling material to 2048² | RealESRGAN x4plus | Used by every `tiling_material` approval; mixed 35% with a wrap-aware Lanczos resize. |
| `image_views_qwen_edit_api.json` | Front, side and back views of an approved concept for multi-view conditioning (`workflows.views`) | Qwen-Image-Edit-2511 fp8mixed, Qwen2.5-VL-7B fp8, Qwen VAE, fal multiple-angles LoRA | Experimental. Live H100 inference on two props (2026-10-20); see [multi-view conditioning](#multi-view-conditioning-props). |
| `pixal3d_multiview_image_to_model_h100_api.json` | Four-view image-to-3D mesh-aware PBR (`h100_multiview` props) | Pixal3D multi-view BF16, DINOv3+NAF, TRELLIS.2 shape and texture VAEs | Experimental. Same structure as the H100 TRELLIS.2 prop graph (GPU UDF remesh 384, Blender UVs and normal bake); live H100 inference on two props (2026-10-20). |

**Model graphs need the cut-out.** Every model graph crops to its input's transparency and removes no background,
so pass the concept cut-out (`slopforge.surface.make_cutout`), as the pipeline does. Given an opaque concept, the
graphs rebuilt the backdrop as a card or box around the object (2026-10-24,
[weapon graph comparison](media/weapon-graph-2026-10/README.md)), so `processing/comfy_generate_3d.py` refuses an
image without an alpha channel before inference.

The Z-Image graph uses ComfyUI core nodes. TRELLIS graphs use ComfyUI's TRELLIS.2 node set (`Trellis2*`, `VaeDecode*`, `BakeTextureFromVoxel`, `ApplyTextureToMesh`, `SaveGLB`, and related nodes). Pixal3D adds `Pixal3DConditioning` and uses ComfyUI's mesh remeshing and UV unwrap nodes. On 2026-10-04 the four TRELLIS API graph files passed `ComfyUIClient.validate_workflow()` against the live H100 `/object_info` response; Pixal3D ran successfully on the H100 on 2026-10-08.

The model and node versions installed in a ComfyUI service can differ from these workflows. Check upstream model and custom-node requirements before running a graph.

## Multi-view conditioning (props)

Single-image conditioning guesses the sides a concept does not show. The opt-in `h100_multiview` compute
profile instead conditions Pixal3D on four generated views of the approved concept. A model graph opts in by
naming `LoadImage` nodes `view_front`, `view_left`, `view_back` and `view_right` (Pixal3D's slots: left is the
object's own left); `approve` then requires `workflows.views`, a `view_front` node and at least one opposite
pair (front and back, or left and right, so the views' agreement can be measured), and stops before any stage
if one is missing.

1. `conditioning_preparation` generates an eye-level front from the concept, then the other slots from that
   front with the concept prompt appended, so unseen sides follow the brief (prompts in
   `slopforge/pipelines/model.py`, `VIEW_PROMPTS`).
2. `processing/prepare_views.py` cuts the views out, brings them to one object height and one scale, and
   measures how far each opposite pair's silhouettes mirror each other. A set below 0.9 for either pair is
   regenerated with the next seeds, up to three sets. If none agrees, approval stops before mesh inference with
   a `candidate_quality` failure; every set stays under `views_<execution>/attempt_<n>` and the stage
   provenance lists each set's seed and overlap (`view_attempts`).
3. The mesh stage uploads the framed views to the `view_<slot>` nodes and records their hashes among the
   workflow's uploaded inputs.

Raw and framed views are `image.view_raw.<slot>` and `image.view.<slot>` outputs of `conditioning_preparation`,
derived from the approved concept like the cutout. The views workflow hash, prompts, seed, threshold and attempt
budget are part of the stage settings, so changing any of them, or altering a view file, regenerates the views
and the mesh on resume; an unchanged resume reuses them. Graphs without view nodes, including the character
graphs, keep single-image conditioning and their previous stage identity.

On 2026-10-20 the showcase power relay lost its copied back details but gained an invented vent, and no crate
view set passed the check; see the [multi-view report](media/multiview-props-2026-10/README.md). The route stays
experimental and is not a default profile.

## Requirement sidecars

An API workflow `name.json` may have an adjacent `name.requirements.yaml` declaring its workflow ID/version, graph SHA-256, capabilities, required node classes and model filenames, sources/license references, input/output types, tested profiles, and estimated resource class. Unknown node revisions, model hashes, or license facts remain unknown. Doctor validates graph/sidecar consistency and reachable node/model-choice availability; it does not download or install dependencies.

Project overrides use the same convention: place `sample.requirements.yaml` next to `ai/workflows/sample.json`. Legacy overrides without sidecars continue to work and are reported as requirements unknown.

## Qualification levels

Availability checks and output qualification are separate. Use `declared`, `preflight_validated`, `inference_tested`, `technically_validated`, `visually_qualified`, and `production_default` for provider/workflow records. A preflight result does not imply successful inference or usable assets. Generated mesh shape, topology, material coverage, and animation suitability require their own evidence and human review.

## Resource and quality limits

Mesh repair, triangle budgeting, UV preparation, and PBR baking are configurable stages. Review the generated mesh, prepared surface, and material views; higher resolution does not guarantee better geometry or texture quality.

Model-provider capabilities do not guarantee manifold, watertight, riggable, or game-ready geometry. See [character rigging](CHARACTER-RIGGING.md) for the review requirements.

Character source review is an offline evidence step over retained artifacts. Supply approved project-relative front, left, and rear concepts, at least one concept crop and Blender-rendered model close-up per critical region, and the selected model's existing four-view previews, inspection report, and linked maps. Run `slopforge character source-review`, inspect the generated review board, classify each component/topology finding, then approve or reject the exact review. A single-image conditioning reference is recorded as single-image and cannot stand in for missing design views. Topology diagnostics include component bounds, world-space defect positions, and source vertex indices; they support human investigation and do not infer that disconnected geometry is debris or repair it. Missing/corrupt evidence remains incomplete; an input hash change makes prior approval stale. Unknown model, node, dependency, and licensing facts remain `unknown`. Source geometry approval, structural readiness, material appearance, deformation, engine playback, and pipeline qualification remain separate gates.

No workflow bundles weights. Weight terms are independent of SlopForge's MIT license. Check the selected model and custom-node terms before use; see [third-party notices](../THIRD_PARTY_NOTICES.md).

## Reproducibility

For file-backed generation, provenance records the selected workflow SHA-256, sidecar ID/version, model identifiers, and seed when available. A graph hash identifies workflow bytes, not custom-node revisions or model-weight bytes. The built-in Hunyuan3D fallback has no file hash or sidecar and is reported as requirements unknown.

Keep `COMFYUI_URL` and `SLOPFORGE_COMPUTE_PROFILE` independent: profiles select graphs, not hosts. See [ComfyUI setup](COMFYUI.md).
