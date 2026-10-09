# Documentation

Start with the user guides for installation, asset generation, review, and Unity delivery. Examples and qualification reports show what the current pipeline can produce and where human review is still needed.

## Get started

| Guide | Use it for |
| --- | --- |
| [Installation](INSTALL.md) | Python, Blender, ComfyUI, and Unity dependencies |
| [Setup](SETUP.md) | Project initialization, defaults, and overrides |
| [Examples](EXAMPLES.md) | Props, character candidates, variations, and environment recipes |
| [ComfyUI](COMFYUI.md) | Local/remote service configuration and compatible models |
| [Workflow inventory](WORKFLOWS.md) | Bundled graphs, requirements, and licensing pointers |

## Create and review assets

- [Style packs](STYLE-SYSTEM.md) and [reference libraries](REFERENCE-LIBRARIES.md)
- [Candidate review board](REVIEW-BOARD.md) and [quality tiers](QUALITY-TIERS.md)
- [Recipes](RECIPES.md) and [environment kits](ENVIRONMENT-KITS.md)
- [Character readiness and rigging](CHARACTER-RIGGING.md)
- [Character animation libraries](CHARACTER-ANIMATIONS.md)
- [Unity delivery](UNITY.md)

## Examples and qualification evidence

- [Basalt Warden](media/character-qualification-2026-10/basalt-corrected-humanoid/README.md): reviewed deformation, valid Humanoid Avatar, and animation evidence.
- [Basalt Warden Unity movement preview](media/character-qualification-2026-10/basalt-warden-unity-preview/README.md): Unity playback screenshots, clip evidence, and current rig limitations.

## For contributors

- [Architecture](ARCHITECTURE.md), [asset outputs](ASSET-OUTPUTS.md), and [agent integration](AGENT-INTEGRATION.md)
- [Contributing and verification](../CONTRIBUTING.md)

Personal working notes and generated experiments belong under `private/` or `scratch/`. Git ignores those paths; keep public guides and a few compact, relevant examples under `docs/`.
