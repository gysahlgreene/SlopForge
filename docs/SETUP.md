# Setup from a clean Mac

SlopForge is the command-line coordinator for local game-asset slop generation. It does not install ComfyUI, Blender, Unity, Continue, model weights, or an LLM. Install only what the asset route needs:

| Route | Needed |
| --- | --- |
| Prompt, config, manifest, `primitive` | SlopForge Python environment; initialized Unity project for project commands |
| 2D images | Above + ComfyUI API + image workflow models |
| 3D models | 2D setup + `rembg[cpu]` ONNX backend + segmentation model on first use + Hunyuan3D model/nodes + Blender |
| Use/import in game | Unity project and Editor; the Editor is not needed to generate files |
| Agent automation | Optional Continue or another coding agent with terminal access and an LLM configured |

The LLM used by Continue and the image/3D models used by ComfyUI are separate. SlopForge itself calls neither an LLM provider nor Continue.

## 1. Install SlopForge

Install Python 3.12 (supported range is 3.10–3.14) from [python.org](https://www.python.org/downloads/macos/) or Homebrew (`brew install python@3.12`), then from this repository run:

```sh
PYTHON_BIN=python3.12 ./scripts/install-macos.sh
source .venv/bin/activate
slopforge --help
```

The installer creates `.venv` and installs SlopForge plus `numpy`, Pillow, PyYAML, and `rembg[cpu]`. Package installation needs network access. The CPU extra provides ONNX Runtime. `rembg` fetches/caches its segmentation model on first use; that model and ComfyUI weights are not bundled. The venv is for SlopForge only; keep it separate from ComfyUI's Python environment.

If `python3.12` is not on PATH, use the executable for another supported Python or set `PYTHON_BIN` to its path. `pipx install .` is also supported by the package entry point; use the checkout-based install above if you need this repository's bundled workflows and templates during development.

## 2. Initialize the game project

The target must be an existing Unity project with `Assets/`:

```sh
slopforge init "$HOME/UnityProjects/MyGame"
```

If you do not have a project yet, install Unity Hub and the Editor version your game needs from [Unity downloads](https://unity.com/download), then create/open a project once so `Assets/` exists. You can close the Editor while generating.

Initialization creates `ai/project.yaml`, a manifest, taxonomy and neutral style, plus `Assets/Art/Generated/`. It does not copy the engine, install Unity, edit scenes, or create `.meta` files. Existing managed files are preserved unless `--force` is given.

Run commands from anywhere with `--project`, or from the project tree so root discovery finds `ai/project.yaml`:

```sh
slopforge --project "$HOME/UnityProjects/MyGame" doctor
```

Edit `ai/project.yaml` and `ai/styles/default/style.yaml` before generation. Set `asset_pipeline.active_style` to switch to another pack. Project workflow files in `ai/workflows/` override bundled files with the same configured name.

## 3. Set up ComfyUI for 2D

Install ComfyUI using its [macOS download](https://www.comfy.org/download) or [Apple Silicon instructions](https://github.com/comfyanonymous/ComfyUI#apple-mac-silicon). Run its local API at `http://127.0.0.1:8188`; use a ComfyUI environment separate from SlopForge. SlopForge submits the bundled API workflow and downloads the resulting PNG through the API.

Download the three image models into the exact ComfyUI folders in [COMFYUI.md](COMFYUI.md). The URLs there were copied from local workflow metadata; check their availability and terms. Start ComfyUI, then confirm the URL with:

```sh
curl -fsS http://127.0.0.1:8188/system_stats >/dev/null && echo "ComfyUI API reachable"
slopforge --project "$HOME/UnityProjects/MyGame" doctor
```

Doctor checks reachability and the configured workflow file; it does not prove that every workflow node/model is loadable. If ComfyUI uses another URL, set `COMFYUI_URL` or `asset_pipeline.tools.comfy_url`.

Try a no-inference prompt first, then generate an image:

```sh
slopforge --project "$HOME/UnityProjects/MyGame" prompt icon "Small red healing potion"
slopforge --project "$HOME/UnityProjects/MyGame" generate icon healing_potion "Small red healing potion"
slopforge --project "$HOME/UnityProjects/MyGame" candidates healing_potion
slopforge --project "$HOME/UnityProjects/MyGame" approve healing_potion 1
```

## 4. Add Blender and Hunyuan3D for 3D

Install Blender from [blender.org](https://www.blender.org/download/). SlopForge runs Blender in background mode; it needs GLB import and FBX export support. It searches for `blender` on PATH and common macOS app paths. Otherwise set `BLENDER_BIN` or `asset_pipeline.tools.blender` to the executable inside your Blender installation.

The configured ComfyUI must expose the node classes used by the shipped Hunyuan3D API graph: `ImageOnlyCheckpointLoader`, `Hunyuan3Dv2Conditioning`, `EmptyLatentHunyuan3Dv2`, `VAEDecodeHunyuan3D`, `VoxelToMesh`, and `SaveGLB`, plus standard ComfyUI nodes. The source graph identifies these as ComfyUI core nodes; if yours lacks them, update ComfyUI using its official instructions. The 3D workflow is resource-intensive and experimental.

Download `hunyuan3d-dit-v2_fp16.safetensors` to:

```text
<COMFYUI_HOME>/models/checkpoints/hunyuan3d-dit-v2_fp16.safetensors
```

`COMFYUI_HOME` is the ComfyUI installation root (default `~/ComfyUI`); it is also where SlopForge expects the `input/` and `output/` directories for GLB transfer. The exact model URL and source notes are in [COMFYUI.md](COMFYUI.md).

Then generate and approve a prop:

```sh
slopforge --project "$HOME/UnityProjects/MyGame" generate prop stone_lantern "A small carved stone lantern"
slopforge --project "$HOME/UnityProjects/MyGame" candidates stone_lantern
slopforge --project "$HOME/UnityProjects/MyGame" approve stone_lantern 1
```

Approval runs background isolation, clean white-background preparation, Hunyuan3D, Blender cleanup/normalization/UVs, heuristic v1 PBR maps, `.blend` preview, and FBX export. The source GLB and intermediates remain in the project. Unity imports the outputs and owns their `.meta` files.

## 5. Optional Continue or another coding agent

Install Continue and configure its LLM/provider using [Continue's documentation](https://docs.continue.dev/). This is separate from ComfyUI and SlopForge. The LLM plans/calls tools, while ComfyUI generates images/models. Configure a local or hosted provider in Continue; there is no required model/provider and SlopForge does not read its credentials. The agent needs terminal access and permission to run the SlopForge executable.

`slopforge init` adds project instructions for Codex (`AGENTS.md`), Claude Code (`CLAUDE.md`), and Continue (`.continue/rules/`). Existing instruction files are left untouched. Start the agent with SlopForge's venv active, or call `<SlopForge checkout>/.venv/bin/slopforge` by full path. These instructions guide asset workflow; they do not configure model inference.

## Configuration and checks

Project settings live in `ai/project.yaml`. Environment overrides are:

| Variable | Purpose |
| --- | --- |
| `COMFYUI_URL` | ComfyUI API base URL; default `http://127.0.0.1:8188` |
| `COMFYUI_HOME` | ComfyUI root containing `input/`, `output/`, and `models/` |
| `BLENDER_BIN` | Blender executable |
| `SLOPFORGE_PYTHON` | Python used by helper scripts |
| `SLOPFORGE_PROJECT_ROOT` | Default project for asset commands; `doctor` discovers from the current directory or accepts `--project` |

Run `slopforge --project PATH doctor` for a read-only diagnostic. PASS means a local executable/file or service check succeeded; WARN means optional or external setup is absent. Doctor does not validate workflow node compatibility, perform inference, or modify the machine.

For errors, check in this order: `doctor`; ComfyUI is running at the configured URL; model files are in the listed folders; the project workflow override is compatible; Blender is executable; then inspect the failed candidate and manifest warning. See [Architecture](ARCHITECTURE.md), [Unity](UNITY.md), and [Agent integration](AGENT-INTEGRATION.md) for details.
