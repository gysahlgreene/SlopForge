# ComfyUI setup

Install and start ComfyUI separately; see [SETUP.md](SETUP.md). Its local API is reachable by default at `http://127.0.0.1:8188`. Override the base URL with `COMFYUI_URL` or `asset_pipeline.tools.comfy_url`. `COMFYUI_HOME` or `asset_pipeline.tools.comfy_home` locates ComfyUI's `input/` and `output/` directories for the Hunyuan3D GLB transfer.

The bundled Z-Image Turbo API workflow references these model names and destinations:

| ComfyUI destination | File | URL recorded in local ComfyUI workflow metadata |
| --- | --- | --- |
| `models/text_encoders/` | `qwen_3_4b.safetensors` | https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors |
| `models/diffusion_models/` | `z_image_turbo_bf16.safetensors` | https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors |
| `models/vae/` | `ae.safetensors` | https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors |

The Hunyuan3D workflow requests `hunyuan3d-dit-v2_fp16.safetensors` in `models/checkpoints/`. Its URL was present in the local ComfyUI Hunyuan workflow metadata:

https://huggingface.co/Comfy-Org/hunyuan3D_2.0_repackaged/resolve/main/split_files/hunyuan3d-dit-v2_fp16.safetensors

These URLs are transcribed from workflows on the source machine; availability and model licenses have not been independently verified. Review upstream terms before downloading.

The image API graph is `workflows/image_text2img_api.json`. Hunyuan3D API workflow nodes are constructed by `processing/comfy_generate_3d.py`, which uses the configured checkpoint and records the returned seed and prompt ID. The graph expects `ImageOnlyCheckpointLoader`, `Hunyuan3Dv2Conditioning`, `EmptyLatentHunyuan3Dv2`, `VAEDecodeHunyuan3D`, `VoxelToMesh`, and `SaveGLB`; the exported source workflow identifies these as ComfyUI core nodes. A ComfyUI build without these classes cannot run the 3D step. The model workflow is experimental and can require substantial memory/compute. Reference images are not connected to the current image workflow; use `text_only` conditioning.
