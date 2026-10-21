# Documentation

Start with the user guides for installation, asset generation, review, and Unity delivery. Examples and qualification reports show what the current pipeline can produce and where human review is still needed.

Product direction and document precedence live in the [product contract](PRODUCT_CONTRACT.md).
The [pipeline contract](PIPELINE_CONTRACT.md) and [quality contract](QUALITY_CONTRACT.md)
define required behavior and evidence; [current state](../CURRENT_STATE.md) records gaps.

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
- [Materials and textures](MATERIALS.md): declared material regions, PBR maps, normal bake, emission and checks
- [Candidate review board](REVIEW-BOARD.md) and [quality tiers](QUALITY-TIERS.md)
- [Recipes](RECIPES.md) and [environment kits](ENVIRONMENT-KITS.md)
- [Character readiness and rigging](CHARACTER-RIGGING.md)
- [Character animation libraries](CHARACTER-ANIMATIONS.md)
- [Unity delivery](UNITY.md)

## Examples and qualification evidence

- [Character styles](media/character-styles-2026-10/README.md): four generated characters in four art styles, rigged automatically and walking, with how they were made and limits.
- [Structure showcase](media/structure-showcase-2026-10/README.md): six generated structures and a real-scale modular stone kit, with turntables, maps, conditions and limits.
- [Props provisional evidence](media/props-provisional-2026-10/README.md): three briefs, two independent H100 runs each, through Unity URP import, under a declared qualification record (criterion v1; owner rated better than the baseline). Later criteria: [v2](media/props-provisional-2026-10-v2/README.md) (5 of 6), [v3](media/props-provisional-2026-10-v3/README.md) (6 of 6), [v4](media/props-provisional-2026-10-v4/README.md) (5 of 6, colour check corrected) and [v5](media/props-provisional-2026-10-v5/README.md) (6 of 6, colour check on; Provisional).
- [M0 exit evidence record](M0-EXIT-RECORD.md): each M0 exit item with its evidence and gaps; M0 closed by the owner on 2026-10-21.
- [Concept adherence](media/concept-adherence-2026-10/README.md): fixed-seed concept tests of what makes concepts follow a brief (part sentences, `--aspect`, camera wording); the jug's profile view is unsolved.
- [Material showcase](media/material-showcase-2026-10/README.md): five props of different materials generated from briefs, with maps, renders, conditions and limits.
- [Texture mask recovery](media/texture-mask-recovery-2026-10/README.md): controlled failure, correction, fresh case and repeat; remaining appearance limitations.
- [Humanoid test 1](media/character-qualification-2026-10/basalt-warden-unity-preview/README.md): Unity walk playback, motion measurements, and current rig limitations.
- [Diagnostic humanoid benchmark](media/character-qualification-2026-10/basalt-corrected-humanoid/README.md): reviewed body deformation, valid Humanoid Avatar, and animation evidence.

## Reliability planning

- [Core 3D pipeline implementation audit](CORE-PIPELINE-AUDIT.md): evidence-backed M0 gaps and ordered implementation packages.

## For contributors

- [Session handoff](SESSION-HANDOFF.md): active worktree status, branch scope, and
  exact instructions for resuming work in a new session. Read before any implementation.
- [Product contract](PRODUCT_CONTRACT.md), [pipeline contract](PIPELINE_CONTRACT.md), [quality contract](QUALITY_CONTRACT.md), [roadmap](../ROADMAP.md), and [current state](../CURRENT_STATE.md)
- [Architecture](ARCHITECTURE.md), [asset outputs](ASSET-OUTPUTS.md), and [agent integration](AGENT-INTEGRATION.md)
- [Contributing and verification](../CONTRIBUTING.md)

Personal working notes and generated experiments belong under `private/` or `scratch/`. Git ignores those paths; keep public guides and a few compact, relevant examples under `docs/`.
