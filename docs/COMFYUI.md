# ComfyUI backends

SlopForge treats ComfyUI as an inference service. The same HTTP API client handles local and networked ComfyUI; changing the service URL does not change the generation pipeline.

## Model input masks

`LoadImage` outputs a transparency mask (`1 - alpha`), while `ImageCropToMask`
requires foreground (`alpha`). Model graphs must explicitly insert `InvertMask`
between them. Automatic polarity guessing erased narrow characters and caused
near-black textures; preflight now rejects that connection. Bundled model runs
retain the actual `conditioning.png` and reference it in generation metadata.
Inspect it before debugging downstream materials. Existing project graph overrides
take precedence: update an unchanged override and its requirements sidecar from
the bundled pair, or correct custom graph wiring and provenance explicitly.
See [the regression evidence](media/texture-mask-recovery-2026-10/README.md).

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
export COMFYUI_URL=http://<comfyui-host>:8188
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

ComfyUI's HTTP API handles health and node discovery, image and mesh uploads, prompt submission, history polling, and output downloads. A history poll that fails to reach the service (connection reset, timeout) is retried with backoff (doubling from the poll interval, at most 30 s) until the job's deadline, because the remote job keeps running; only a failure that persists to the deadline stops the worker with an unknown remote outcome. A job reported as completed returns at once, and the worker then reports a missing image or GLB. `/view` serves generated GLB and other binary files as well as images. Blender and SlopForge processing remain on the machine running SlopForge. No SSH setup or local `COMFYUI_HOME` is needed.

The image workflow runner can bind approved reference files to configured graph inputs and return image results. Reference images can guide 3D concepts and material inputs when the selected workflow supports those inputs. Conditioning is an execution capability; it does not guarantee visual consistency or a usable 3D model.

`COMFYUI_HOME` and `asset_pipeline.tools.comfy_home` are optional legacy/local-install hints shown by doctor; generation does not read ComfyUI's filesystem. Workflow sidecars declare node and model requirements; doctor checks graph consistency locally and model-choice availability through ComfyUI's `/object_info` API. The API does not expose installed node revisions or model weight hashes, so those remain unverified. See the [workflow inventory](WORKFLOWS.md) for the sidecar format and current declarations.

## Previous local-install assumptions

Before the service refactor, the 2D and 3D scripts each implemented their own HTTP prompt, history, and output-image handling. The 3D script also defaulted `COMFYUI_HOME` to `~/ComfyUI`, copied source images and Blender-prepared GLBs into that installation's `input/`, and copied generated GLBs and maps from its `output/`. Thus a remote URL alone was insufficient for 3D generation, and the local filesystem paths had to match the ComfyUI machine. The workflows named models expected under that installation's `models/`; SlopForge did not read model files directly. The refactor removed these filesystem dependencies from generation and moved shared service operations into `ComfyUIClient`.

## Choose an independent compute profile

Quality tiers such as `draft`, `normal`, and `final` are selected independently of the compute profile and service URL. A tier can set candidate budgets and workflow node inputs by workflow basename. See [QUALITY-TIERS.md](QUALITY-TIERS.md) for configuration and precedence.

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
        model: pixal3d_image_to_model_h100_api.json
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

The bundled TRELLIS profiles use `trellis_2_int8_convrot.safetensors` at 1024-class shape and 2048 textures for Mac-compatible inference, and `trellis_2_bf16.safetensors` for H100 workflows. The `h100_final` profile uses Pixal3D's camera-conditioned 1536 cascade with 4096 PBR maps; the saved SlopForge graph uses native UDF remeshing and a 60,000-triangle target. This profile was run on the H100 and visually reviewed on a clothed humanoid; it is the strongest tested route so far, while fine facial detail and clean rigging still need improvement. See [quality tiers](QUALITY-TIERS.md). A profile can point to project workflow overrides in `ai/workflows/`. Profile entries may override workflows, model budgets, or model-specific tools; they cannot override `comfy_url`, `comfy_backend`, or `comfy_home`.

## Models and workflows

The exact bundled API graphs, input/output capabilities, profile selection, H100 evidence, and remaining provenance limits are listed in the [workflow inventory](WORKFLOWS.md). New inference metadata includes the selected graph's content SHA-256; model weight and custom-node revisions are not currently pinned.

The bundled Z-Image Turbo API workflow references these model names and destinations:

| ComfyUI destination | File | Source |
| --- | --- | --- |
| `models/text_encoders/` | `qwen_3_4b.safetensors` | [Comfy-Org Z-Image Turbo](https://huggingface.co/Comfy-Org/z_image_turbo/tree/main/split_files/text_encoders) |
| `models/diffusion_models/` | `z_image_turbo_bf16.safetensors` | [Comfy-Org Z-Image Turbo](https://huggingface.co/Comfy-Org/z_image_turbo/tree/main/split_files/diffusion_models) |
| `models/vae/` | `ae.safetensors` | [Comfy-Org Z-Image Turbo](https://huggingface.co/Comfy-Org/z_image_turbo/tree/main/split_files/vae) |

The legacy Hunyuan3D v2 graph is assembled by `processing/comfy_generate_3d.py` when no model workflow is selected. It requests `hunyuan3d-dit-v2_fp16.safetensors` in `models/checkpoints/`; its source is [Comfy-Org Hunyuan3D](https://huggingface.co/Comfy-Org/hunyuan3D_2.0_repackaged/tree/main/split_files). It is not one of the checked-in API JSON workflows.

TRELLIS.2 profiles use the models from [Comfy-Org TRELLIS.2](https://huggingface.co/Comfy-Org/TRELLIS.2/tree/main): `diffusion_models/trellis_2_int8_convrot.safetensors` or `diffusion_models/trellis_2_bf16.safetensors`, `clip_vision/dino_v3_vit_l.safetensors`, and both `vae/trellis_2_{shape,texture}_vae_bf16.safetensors`. Check upstream terms and model availability before downloading.

H100 profiles generate character concepts with `image_character_pose_api.json` (`workflows.character_image`): the Z-Image graph above plus `models/model_patches/Z-Image-Turbo-Fun-Controlnet-Union-2.1-2602-8steps.safetensors` from [alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1](https://huggingface.co/alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1) (Apache-2.0; the sidecar records its SHA-256). It needs ComfyUI's `ModelPatchLoader` and `ZImageFunControlnet` nodes (present in 0.37.0).

The H100 final Pixal3D graph uses `diffusion_models/pixal3d_bf16.safetensors`, `clip_vision/dino_v3_L_naf_fp32.safetensors`, and the TRELLIS.2 shape and texture VAEs. The Pixal3D and DINO files are from [Comfy-Org/Pixal3D](https://huggingface.co/Comfy-Org/Pixal3D/tree/main); the workflow sidecar records verified SHA-256 hashes for all four installed files.

The opt-in `h100_multiview` profile (props) adds two graphs. `pixal3d_multiview_image_to_model_h100_api.json` uses `diffusion_models/pixal3d_multiview_bf16.safetensors` from [Comfy-Org/Pixal3D](https://huggingface.co/Comfy-Org/Pixal3D/tree/main) with the same DINO and VAE files, and ComfyUI's `Pixal3DMultiViewConditioning` (present in 0.37.0, commit `8d534945`). `image_views_qwen_edit_api.json` (`workflows.views`) generates the views with `diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors` from [Comfy-Org/Qwen-Image-Edit_ComfyUI](https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI), `text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors` and `vae/qwen_image_vae.safetensors` from [Comfy-Org/Qwen-Image_ComfyUI](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI), and `loras/qwen-image-edit-2511-multiple-angles-lora.safetensors` from [fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA](https://huggingface.co/fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA), all Apache-2.0. The two sidecars record the SHA-256 of every file as downloaded and checked on 2026-10-20. Doctor checks LoRA choices like other model files.

Project workflows in `ai/workflows/` override bundled workflow files. Put an optional `name.requirements.yaml` next to `name.json`; legacy overrides without sidecars continue to work and doctor reports their requirements as unknown. Workflow node classes and selectable model values are checked against the configured ComfyUI before queuing. `slopforge doctor` reports the URL, detected backend, selected compute profile, service health, ComfyUI version/device, sidecar consistency, workflow node availability, model-choice availability, and unverified dependency revisions/hashes for each configured workflow, including `character_model`. Image generation downloads only saved results (`type: output`); preview-node images (`type: temp`) are ignored. The doctor preflight does not submit a prompt or test file transfer; it remains read-only.

Reference conditioning uses `asset_pipeline.conditioning.workflow_inputs` to map each slot's image and optional strength to node IDs and input names in the selected image workflow. Approved references are uploaded through the same HTTP client for local and remote services. See [STYLE-SYSTEM.md](STYLE-SYSTEM.md) for configuration and CLI selection.

The bundled text-to-image graph remains text-only. It creates supporting concept images and does not qualify the 3D generation route.

## Integration checks

Normal unit tests use mocked HTTP and need no running ComfyUI:

```sh
python -m pytest
```

The opt-in workflow capability check validates every bundled workflow against the server's `/object_info` without submitting inference:

```sh
SLOPFORGE_COMFYUI_PREFLIGHT=1 \
COMFYUI_URL=http://127.0.0.1:8188 \
python -m pytest tests/test_workflow_preflight_live.py -q
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

Troubleshooting: run `doctor`; confirm the URL is reachable from the SlopForge machine; inspect missing node/model choices in doctor or ComfyUI's response; ensure custom nodes and weights are installed on the ComfyUI machine; and inspect the generated candidate and logs. If ComfyUI runs as a systemd user service and the account has lingering disabled (`loginctl show-user <user> -p Linger` reports `no`), the service stops when the last login session on that host closes; SlopForge then reports `ComfyUI is not reachable … Connection refused` and classifies the stage failure as `environment` without spending a generation retry. Keep a login session open for the length of a run (one that runs a command, for example `ssh <host> 'sleep 14400'`; an `ssh -N` connection registers no login session and the service still stops), or ask the host's administrator to enable lingering, then continue with `approve <name> <n> --resume`. On Linux, if Triton cannot compile and reports missing `Python.h`, install Python development headers matching the Python version used to run ComfyUI. `COMFYUI_HOME` should not be set to a remote path.
