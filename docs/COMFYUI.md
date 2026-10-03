# ComfyUI backends

SlopForge treats ComfyUI as an inference service. The same HTTP API client handles local and networked ComfyUI; changing the service URL does not change the generation pipeline.

## Choose where ComfyUI runs

Local ComfyUI is the default:

```sh
export COMFYUI_URL=http://127.0.0.1:8188
slopforge --project ~/UnityProjects/MyGame doctor
slopforge --project ~/UnityProjects/MyGame make
```

For a remote ComfyUI server, set its reachable HTTP URL:

```sh
export COMFYUI_URL=http://gpu-host.example:8188
slopforge --project ~/UnityProjects/MyGame doctor
slopforge --project ~/UnityProjects/MyGame make
```

The first tested remote example is the H100 host:

```sh
export COMFYUI_URL=http://100.108.220.4:8188
export SLOPFORGE_COMPUTE_PROFILE=h100
slopforge --project ~/UnityProjects/MyGame doctor
slopforge --project ~/UnityProjects/MyGame make
```

Switch back to the local Mac independently:

```sh
export COMFYUI_URL=http://127.0.0.1:8188
export SLOPFORGE_COMPUTE_PROFILE=mac
slopforge --project ~/UnityProjects/MyGame doctor
```

SlopForge detects loopback URLs as `local` and other hosts as `remote`. Override detection with `SLOPFORGE_COMFYUI_BACKEND=local|remote`, or set `asset_pipeline.tools.comfy_backend` to `auto`, `local`, or `remote`. Neither backend selection nor host name selects a model profile.

ComfyUI's HTTP API handles health and node discovery, image and mesh uploads, prompt submission, history polling, and output downloads. `/view` serves generated GLB and other binary files as well as images. Blender and SlopForge processing remain on the machine running SlopForge. No SSH setup or local `COMFYUI_HOME` is needed.

`COMFYUI_HOME` and `asset_pipeline.tools.comfy_home` are optional legacy/local-install hints shown by doctor; generation does not read ComfyUI's filesystem. Workflow model availability is checked through ComfyUI's `/object_info` API before prompts are queued.

## Previous local-install assumptions

Before the service refactor, the 2D and 3D scripts each implemented their own HTTP prompt, history, and output-image handling. The 3D script also defaulted `COMFYUI_HOME` to `~/ComfyUI`, copied source images and Blender-prepared GLBs into that installation's `input/`, and copied generated GLBs and maps from its `output/`. Thus a remote URL alone was insufficient for 3D generation, and the local filesystem paths had to match the ComfyUI machine. The workflows named models expected under that installation's `models/`; SlopForge did not read model files directly. The refactor removed these filesystem dependencies from generation and moved shared service operations into `ComfyUIClient`.

## Choose an independent compute profile

Profiles select workflow graphs, models, and their resolution/settings. Define the profiles in `ai/project.yaml`, then select one with `SLOPFORGE_COMPUTE_PROFILE` or `asset_pipeline.compute_profile`:

```yaml
asset_pipeline:
  compute_profile: mac
  compute_profiles:
    mac:
      workflows:
        model: trellis2_image_to_model_api.json
    h100:
      workflows:
        model: trellis2_image_to_model_h100_api.json
    h100_final:
      workflows:
        model: trellis2_image_to_model_h100_final_api.json
```

Then choose the inference service separately:

```sh
# Remote server and H100 quality profile
COMFYUI_URL=http://gpu-host.example:8188 SLOPFORGE_COMPUTE_PROFILE=h100 \
  slopforge --project ~/UnityProjects/MyGame doctor

# Local server and Mac-compatible profile
COMFYUI_URL=http://127.0.0.1:8188 SLOPFORGE_COMPUTE_PROFILE=mac \
  slopforge --project ~/UnityProjects/MyGame doctor
```

The bundled TRELLIS profiles use `trellis_2_int8_convrot.safetensors` at 1024-class shape and 2048 textures for Mac-compatible inference, `trellis_2_bf16.safetensors` at 1024/2048 for H100 drafts, and BF16 at 1536/4096 for H100 final output. A profile can point to project workflow overrides in `ai/workflows/`. Profile entries may override workflows, model budgets, or model-specific tools; they cannot override `comfy_url`, `comfy_backend`, or `comfy_home`.

## Models and workflows

The bundled Z-Image Turbo API workflow references these model names and destinations:

| ComfyUI destination | File | Source |
| --- | --- | --- |
| `models/text_encoders/` | `qwen_3_4b.safetensors` | [Comfy-Org Z-Image Turbo](https://huggingface.co/Comfy-Org/z_image_turbo/tree/main/split_files/text_encoders) |
| `models/diffusion_models/` | `z_image_turbo_bf16.safetensors` | [Comfy-Org Z-Image Turbo](https://huggingface.co/Comfy-Org/z_image_turbo/tree/main/split_files/diffusion_models) |
| `models/vae/` | `ae.safetensors` | [Comfy-Org Z-Image Turbo](https://huggingface.co/Comfy-Org/z_image_turbo/tree/main/split_files/vae) |

The bundled Hunyuan3D workflow requests `hunyuan3d-dit-v2_fp16.safetensors` in `models/checkpoints/`; its source is [Comfy-Org Hunyuan3D](https://huggingface.co/Comfy-Org/hunyuan3D_2.0_repackaged/tree/main/split_files).

TRELLIS.2 profiles use the models from [Comfy-Org TRELLIS.2](https://huggingface.co/Comfy-Org/TRELLIS.2/tree/main): `diffusion_models/trellis_2_int8_convrot.safetensors` or `diffusion_models/trellis_2_bf16.safetensors`, `clip_vision/dino_v3_vit_l.safetensors`, and both `vae/trellis_2_{shape,texture}_vae_bf16.safetensors`. Check upstream terms and model availability before downloading.

Project workflows in `ai/workflows/` override bundled workflow files. Workflow node classes and selectable model values are checked against the configured ComfyUI before queuing. `slopforge doctor` reports the URL, detected backend, selected compute profile, service health, ComfyUI version/device, workflow node availability, and configured workflow paths. It remains read-only.

## Integration checks

Normal unit tests use mocked HTTP and need no running ComfyUI:

```sh
python -m pytest
```

Opt-in integration tests require a reachable ComfyUI and the models for the selected workflow:

```sh
SLOPFORGE_COMFYUI_INTEGRATION=1 \
COMFYUI_URL=http://127.0.0.1:8188 \
python -m pytest tests/test_comfyui_integration.py
```

TRELLIS generation is separately gated because it is long-running and resource-intensive:

```sh
SLOPFORGE_COMFYUI_3D_INTEGRATION=1 \
SLOPFORGE_COMPUTE_PROFILE=h100 \
COMFYUI_URL=http://gpu-host.example:8188 \
python -m pytest tests/test_comfyui_integration.py
```

Troubleshooting: run `doctor`; confirm the URL is reachable from the SlopForge machine; inspect missing node/model choices in doctor or ComfyUI's response; ensure custom nodes and weights are installed on the ComfyUI machine; and inspect the generated candidate and logs. On Linux, if Triton cannot compile and reports missing `Python.h`, install Python development headers matching the Python version used to run ComfyUI. `COMFYUI_HOME` should not be set to a remote path.
