# 3D workflow inventory

SlopForge stores API-format ComfyUI graphs in `workflows/`; a project override in `ai/workflows/` takes precedence. Workflows and model weights are external runtime requirements. `slopforge doctor` checks declared node classes and model choices against ComfyUI `/object_info`; it does not prove inference quality or validate the resulting geometry.

| Workflow | Capability | Models | Evidence and limits |
| --- | --- | --- | --- |
| `image_text2img_api.json` | Supporting concept and material images | Z-Image Turbo BF16, Qwen 3 4B encoder, `ae.safetensors` VAE | Live H100 inference passed. Text-only; not an image-to-3D workflow. |
| Built-in Hunyuan3D v2 graph (`processing/comfy_generate_3d.py`) | Image-to-3D GLB, followed by a surface-swatch material route | `hunyuan3d-dit-v2_fp16.safetensors` | Inline legacy graph with no graph file hash or requirements sidecar. |
| `trellis2_image_to_model_api.json` | Image-to-3D mesh-aware base color/metallic/roughness | TRELLIS.2 INT8 ConvRot, DINOv3 ViT-L, shape and texture VAEs | Conservative/Mac-oriented profile; API structure checked against H100, no recent INT8 inference run. |
| `trellis2_image_to_model_h100_api.json` | Image-to-3D mesh-aware PBR | TRELLIS.2 BF16, DINOv3 ViT-L, shape and texture VAEs | H100 profile; earlier runs reached 512³ and 1024³. Shape/material quality remains asset-dependent. |
| `trellis2_image_to_model_h100_final_api.json` | Higher-resolution image-to-3D mesh-aware PBR | Same BF16 model set | Graph is prepared and passes capability checks; no 1536³ inference is claimed. |
| `pixal3d_image_to_model_h100_api.json` | Camera-conditioned image-to-3D mesh-aware PBR | Pixal3D BF16, DINOv3+NAF, TRELLIS.2 shape and texture VAEs | H100 inference completed at 1536 cascade and 4096 texture size. Output quality remains asset-dependent; inspect geometry, texture coverage, and topology before use. |

The Z-Image graph uses ComfyUI core nodes. TRELLIS graphs use ComfyUI's TRELLIS.2 node set (`Trellis2*`, `VaeDecode*`, `BakeTextureFromVoxel`, `ApplyTextureToMesh`, `SaveGLB`, and related nodes). Pixal3D adds `Pixal3DConditioning` and uses ComfyUI's mesh remeshing and UV unwrap nodes. On 2026-10-04 the four TRELLIS API graph files passed `ComfyUIClient.validate_workflow()` against the live H100 `/object_info` response; Pixal3D ran successfully on the H100 on 2026-10-08.

The model and node versions installed in a ComfyUI service can differ from these workflows. Check upstream model and custom-node requirements before running a graph.

## Requirement sidecars

An API workflow `name.json` may have an adjacent `name.requirements.yaml` declaring its workflow ID/version, graph SHA-256, capabilities, required node classes and model filenames, sources/license references, input/output types, tested profiles, and estimated resource class. Unknown node revisions, model hashes, or license facts remain unknown. Doctor validates graph/sidecar consistency and reachable node/model-choice availability; it does not download or install dependencies.

Project overrides use the same convention: place `sample.requirements.yaml` next to `ai/workflows/sample.json`. Legacy overrides without sidecars continue to work and are reported as requirements unknown.

## Qualification levels

Availability checks and output qualification are separate. Use `declared`, `preflight_validated`, `inference_tested`, `technically_validated`, `visually_qualified`, and `production_default` for provider/workflow records. A preflight result does not imply successful inference or usable assets. Generated mesh shape, topology, material coverage, and animation suitability require their own evidence and human review.

## Resource and quality limits

Mesh repair, triangle budgeting, UV preparation, and PBR baking are configurable stages. Review the generated mesh, prepared surface, and material views; higher resolution does not guarantee better geometry or texture quality.

Model-provider capabilities do not guarantee manifold, watertight, riggable, or game-ready geometry. See [character rigging](CHARACTER-RIGGING.md) for the review requirements.

No workflow bundles weights. Weight terms are independent of SlopForge's MIT license. Check the selected model and custom-node terms before use; see [third-party notices](../THIRD_PARTY_NOTICES.md).

## Reproducibility

For file-backed generation, provenance records the selected workflow SHA-256, sidecar ID/version, model identifiers, and seed when available. A graph hash identifies workflow bytes, not custom-node revisions or model-weight bytes. The built-in Hunyuan3D fallback has no file hash or sidecar and is reported as requirements unknown.

Keep `COMFYUI_URL` and `SLOPFORGE_COMPUTE_PROFILE` independent: profiles select graphs, not hosts. See [ComfyUI setup](COMFYUI.md).
