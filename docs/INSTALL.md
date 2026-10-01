# Installation

For the complete clean-Mac process, including ComfyUI models, Blender, Unity, and optional Continue setup, follow [SETUP.md](SETUP.md). This page covers the package and project steps only.

## From this checkout

Python 3.10–3.14 is supported. Install the package into a local virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
slopforge --help
slopforge doctor
```

On macOS, `scripts/install-macos.sh` creates `.venv`, upgrades pip, and installs the editable checkout. The console entry point is also suitable for `pipx install .`.

## Initialize a Unity project

The target must already have an `Assets/` directory. Initialization installs only project configuration, manifest, taxonomy, neutral style data, and generated-output folders. It does not copy the toolkit into the Unity project.

```sh
slopforge init ~/UnityProjects/MyGame
```

Existing managed files are not overwritten. Pass `--force` to replace configuration, taxonomy, and the default style explicitly. An existing asset manifest is always preserved, including candidate history and approvals. Back up customized configuration before using `--force`. The standalone toolkit can then target the project from any working directory:

```sh
slopforge --project ~/UnityProjects/MyGame generate icon example "Simple inventory icon"
```

Or `cd` into the project; root discovery walks upward until it finds `ai/project.yaml`.

## External tools

ComfyUI and Blender are separate installations. SlopForge does not install or bundle them or download their model weights. Configure project settings in `ai/project.yaml` or use `COMFYUI_URL`, `COMFYUI_HOME`, `BLENDER_BIN`, and `SLOPFORGE_PYTHON`. The doctor reports missing local dependencies and unreachable services without installing or modifying anything.

The default SlopForge installation declares `rembg[cpu]`, which installs the CPU ONNX Runtime backend required for background removal. The segmentation model is downloaded/cached by `rembg` only when first used, not during installation or `slopforge doctor`. On Apple Silicon, use a ComfyUI/PyTorch build compatible with the installed macOS and available MPS support. Memory and model compatibility depend on the selected workflows and checkpoints.
