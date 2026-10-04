# ComfyUI workflow inventory

SlopForge stores API-format workflow graphs in `workflows/`; a project override in `ai/workflows/` takes precedence. These files are executable dependencies: ComfyUI core/custom-node versions and model files must match the graph. `slopforge doctor` checks the selected graph's node classes and model choices against the configured server's `/object_info`, but does not prove generation, validate tensor shapes, or check weight licenses/checksums.

| Workflow | Capability and outputs | Model files | Profile / evidence |
| --- | --- | --- | --- |
| `image_text2img_api.json` | Text-to-image; 1024×1024 latent; PNG | Z-Image Turbo BF16 diffusion, Qwen 3 4B text encoder, `ae.safetensors` VAE | Default graph; core ComfyUI nodes. Live H100 image inference and output retrieval passed in the recipe smoke. |
| Built-in Hunyuan3D v2 graph (`processing/comfy_generate_3d.py`) | Image-to-3D geometry; GLB, followed by SlopForge's surface-swatch material path | Comfy-Org Hunyuan3D 2.0 checkpoint (`hunyuan3d-dit-v2_fp16.safetensors`) | Legacy/default route only when no `workflows.model` is selected. Assembled in Python rather than stored as API JSON; consequently it has no file hash. |
| `trellis2_image_to_model_api.json` | Image-to-3D with mesh-aware base color/metallic/roughness; GLB and map PNGs | TRELLIS.2 INT8 ConvRot, DINOv3 ViT-L, shape and texture VAEs | Conservative/Mac-oriented profile. API structure is checked against H100; no current-task INT8 generation run. |
| `trellis2_image_to_model_h100_api.json` | Image-to-3D with mesh-aware PBR; shape target 1024; GLB and map PNGs | TRELLIS.2 BF16, DINOv3 ViT-L, shape and texture VAEs | H100 profile. Previous live runs reached 512³ and 1024³; quality remains asset-dependent. |
| `trellis2_image_to_model_h100_final_api.json` | Image-to-3D with mesh-aware PBR; shape target 1536; GLB and map PNGs | Same BF16 set as H100 profile | H100 final profile is prepared and its graph passes API capability checks; no 1536³ inference claimed. |

The Z-Image graph uses ComfyUI core nodes. The three TRELLIS graphs use ComfyUI's TRELLIS.2 node set (`Trellis2*`, `VaeDecode*`, `BakeTextureFromVoxel`, `ApplyTextureToMesh`, `SaveGLB`, and related nodes). Their full class lists are discovered from the graph rather than duplicated here. On 2026-10-04 all four graphs passed `ComfyUIClient.validate_workflow()` against the live H100 `/object_info` response.

## Resource and quality limits

The TRELLIS.2 upstream project documents Linux/NVIDIA support, a 24 GB VRAM floor, H100/A100 testing, and 512³–1536³ output resolutions. That is a provider capability statement, not a guarantee of watertight, manifold, riggable, or game-ready geometry. Upstream explicitly supports open and non-manifold surfaces. SlopForge's 2026-10-04 H100 character experiment failed mesh QA (1,189 components and 15,402 boundary/non-manifold edges) and stayed unapproved. The #14 rigging integration therefore remains open.

No workflow bundles model weights. Model code/weight terms are independent of the SlopForge license; check the exact upstream artifact before use. The Hunyuan3D 2.1 license restriction for EU/UK/South Korea applies to that provider component and is recorded in [provider source verification](research/provider-source-verification-2026-10.md). The available Hunyuan-based legacy path is not the default H100 workflow.

## Reproducibility

New image- and file-backed model-generation metadata records the SHA-256 of the selected workflow file alongside its workflow name, model identifiers and seed. The generated Hunyuan3D fallback graph has no file hash. A graph hash identifies workflow bytes, not installed custom-node revisions or model weight bytes. Those remain environment dependencies and are not captured automatically. A future workflow registry should add pinned node/model requirements and artifact checksums only when it can validate their sources reliably.

Compute profiles select graphs; they do not select the host. Keep `COMFYUI_URL` and `SLOPFORGE_COMPUTE_PROFILE` independently configurable. See [ComfyUI setup](COMFYUI.md) for server setup, model locations and opt-in integration commands.
