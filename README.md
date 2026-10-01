# SlopForge

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10--3.14-3776ab?style=for-the-badge&logo=python" />
  <img alt="License" src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" />
  <img alt="Slop" src="https://img.shields.io/badge/slop-forged%20locally-7c3aed?style=for-the-badge" />
  <img alt="Art direction" src="https://img.shields.io/badge/art%20direction-YAML-6b7280?style=for-the-badge" />
  <img alt="PBR" src="https://img.shields.io/badge/PBR-vibes%20based-fb8c00?style=for-the-badge" />
  <img alt="Human approval" src="https://img.shields.io/badge/human%20approval-required-ff6b6b?style=for-the-badge" />
</p>

SlopForge is a local-first tool that uses ComfyUI and Blender to generate 2D art and 3D props from descriptions and project style settings, then exports approved assets into a Unity project.

```text
semantic description
→ project art direction
→ ComfyUI concept candidates
→ background isolation
→ 2D approval or Hunyuan3D
→ Blender cleanup, UVs, scale, and PBR
→ Unity-ready PNG or FBX
```

## What can SlopForge make?

- 2D icons and props
- Inventory UI assets and item art
- Stylized environmental props
- 3D generated props with Blender cleanup and FBX export
- Generate candidates, review them, and approve assets for export

## Quick start

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
slopforge --help
slopforge init ~/UnityProjects/MyGame
```

For first-time setup on macOS, use `PYTHON_BIN=python3.12 ./scripts/install-macos.sh` and follow [docs/SETUP.md](docs/SETUP.md) for the route-specific dependencies.

Run commands from the project root to discover `ai/project.yaml`, or pass the project explicitly:

```sh
slopforge --project ~/UnityProjects/MyGame generate icon health_potion \
  "Health potion inventory icon"
```

## Create a 2D asset

Generation creates reviewable candidates under the project's `ai/assets/candidates/`. Approve one to copy it to the configured Unity output directory:

```sh
slopforge --project ~/UnityProjects/MyGame generate icon health_potion \
  "Health potion inventory icon"
slopforge --project ~/UnityProjects/MyGame candidates health_potion
slopforge --project ~/UnityProjects/MyGame approve health_potion 2
```

## Create a 3D asset

```sh
slopforge --project ~/UnityProjects/MyGame generate prop alien_terminal \
  "Wall-mounted terminal controlling sealed doors"
slopforge --project ~/UnityProjects/MyGame candidates alien_terminal
slopforge --project ~/UnityProjects/MyGame approve alien_terminal 2
```

## Example projects and workflows

See [docs/EXAMPLES.md](docs/EXAMPLES.md) for practical examples of:

- inventory icon generation
- environmental props
- style-pack switching
- candidate review and approval loops
- Unity import and iteration workflows

## Architecture

- `slopforge/`: the Python package for the project-aware CLI, config, taxonomy, style prompts, manifest, candidate handling, validation, and pipelines.
- `processing/`: ComfyUI API calls, 3D input preparation, and PBR maps.
- `blender/`: GLB-to-Blend/FBX processing and Blender-based model inspection.
- `workflows/`: bundled ComfyUI API graph defaults.
- `templates/`: project initialization files, taxonomy, and optional agent instructions.
- `examples/`: sample style data.

Workflow precedence is project override first (`ai/workflows/<configured path>`), then the toolkit's bundled `workflows/`. Set a filename in project configuration to make that override easy to manage.

## Requirements

- Python 3.10–3.14 and the packages declared by `pyproject.toml`.
- ComfyUI and image models for generated 2D assets.
- Blender, Hunyuan3D nodes/model, and the CPU ONNX backend from `rembg[cpu]` for 3D assets.
- An existing Unity project (`Assets/` directory) as the output target.

Only Python and SlopForge are needed for prompts/configuration and the Unity-native `primitive` route. See [docs/SETUP.md](docs/SETUP.md) for installation, model locations, agent setup, and route-specific dependencies.

## Agent integration

Agents can invoke the same command manually. Optional generic Continue rules are in `templates/continue/`. They tell an agent to inspect the manifest and existing assets, use Unity geometry for simple references, and work inside the SlopForge project structure.

## Configuration and diagnostics

Use `slopforge --project PATH styles`, `assets`, `inspect NAME`, `doctor`, and `prompt TYPE DESCRIPTION`. `slopforge doctor` is diagnostic and does not install or modify anything. Project paths are configured with `ai/project.yaml` and environment overrides such as `COMFYUI_URL`, `COMFYUI_HOME`, `BLENDER_BIN`, and others.

## Current limitations

- Reference images are organized and recorded but are not used as visual conditioning.
- The PBR maps are a heuristic/generated v1 approach, not physically accurate scans.
- Hunyuan3D and Blender results depend on local models, nodes, and hardware; the 3D pipeline remains experimental.
- Model weights are not included. Known source links and expected ComfyUI destinations are documented, but availability and model terms should be checked upstream.
- SlopForge is MIT licensed. Separately installed model weights and ComfyUI custom nodes have their own terms; see `THIRD_PARTY_NOTICES.md`.
