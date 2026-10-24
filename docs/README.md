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
| [Character pipeline demo](DEMO.md) | A live walk-through of the character recipe from a fresh project |
| [ComfyUI](COMFYUI.md) | Local/remote service configuration and compatible models |
| [Workflow inventory](WORKFLOWS.md) | Bundled graphs, requirements, and licensing pointers |

## Create and review assets

- [Style packs](STYLE-SYSTEM.md) and [reference libraries](REFERENCE-LIBRARIES.md)
- [Materials and textures](MATERIALS.md): declared material regions, PBR maps, normal bake, emission and checks
- [Candidate review board](REVIEW-BOARD.md) and [quality tiers](QUALITY-TIERS.md)
- [Recipes](RECIPES.md) and [environment kits](ENVIRONMENT-KITS.md)
- [Weapon concepts](media/weapon-concepts-2026-10/README.md): side-profile concepts on the wide and landscape canvases
- [Weapon part masks](media/weapon-parts-2026-10/README.md): text detection against boxes on weapon concepts
- [Weapon mesh graphs](media/weapon-graph-2026-10/README.md): three mesh graphs on three weapon concepts, and orientation
- [Mesh reduction](media/mesh-reduction-2026-10/README.md): Blender reduces the full-detail shape instead of the graph's midpoint decimation
- [Weapons through the pipeline](media/weapon-pipeline-2026-10/README.md): a pistol, longsword and crossbow on TRELLIS.2 and Pixal3D, with the fixes they needed
- [Weapons](WEAPONS.md): the `weapon` type, its side-profile concepts and shape rule (M3, Experimental)
- [Natural environments](NATURAL-ENVIRONMENTS.md): rocks, tiling ground and bark, foliage cut-outs, trees and shrubs, and `scene-render`
- [Character readiness and rigging](CHARACTER-RIGGING.md)
- [Character animation libraries](CHARACTER-ANIMATIONS.md)
- [Unity delivery](UNITY.md)

## Examples and qualification evidence

- [Character styles](media/character-styles-2026-10/README.md): four generated characters in four art styles, rigged automatically and walking, with how they were made and limits.
- [Moorland scene, live run](media/natural-live-2026-10/README.md): the `moorland_ruin` recipe rebuilt from a blank project and rendered by `scene-render`, with its ruin pieces, interventions and limits. The owner-approved [prototype](media/natural-showcase-2026-10/README.md) came first.
- [Modular kits, criterion M2-v3](media/kits-provisional-2026-10-v3/README.md): three kits, two runs each, all passing; kits are Provisional. Earlier rounds: [M2-v1](media/kits-provisional-2026-10/README.md) and [M2-v2](media/kits-provisional-2026-10-v2/README.md).
- [Kit look after owner review](media/kits-hue-match-2026-10/README.md): the hybrid prototype the owner rejected, and modules keeping their own colours with the kit's tint matched.
- [Kit budgets](media/kit-budgets-2026-10/README.md): per-module face and texture budgets and kit totals.
- [Standalone structures at real size](media/structures-real-size-2026-10/README.md): a well, a shrine and a bunker generated at declared heights, with turntables.
- [Structure showcase](media/structure-showcase-2026-10/README.md) (earlier, 2026-10-18): the first six structures and stone kit, scaled to a 1 m largest side; superseded by the real-size runs and M2 kits.
- [Stone ruin kit in Unity](media/kit-scene-2026-10/README.md) (earlier): the first `environment-scene` courtyard and corner joint.
- [Shared kit material](media/kit-material-2026-10/README.md) (earlier, removed): the seamless swatch bake that #101 replaced, and the defects its live runs found.
- [Props lineup](media/props-lineup-2026-10/README.md): seven generated props turning together.
- [Multi-view conditioning](media/multiview-props-2026-10/README.md): experimental four-view Pixal3D conditioning for props.
- [Props provisional evidence](media/props-provisional-2026-10/README.md): three briefs, two independent H100 runs each, through Unity URP import, under a declared qualification record (criterion v1; owner rated better than the baseline). Later criteria: [v2](media/props-provisional-2026-10-v2/README.md) (5 of 6), [v3](media/props-provisional-2026-10-v3/README.md) (6 of 6), [v4](media/props-provisional-2026-10-v4/README.md) (5 of 6, colour check corrected) and [v5](media/props-provisional-2026-10-v5/README.md) (6 of 6, colour check on; Provisional).
- [Dark-texture check](media/dark-texture-check-2026-10/README.md): why TRELLIS sometimes textures a mesh black, and the `colour_darkened` check calibrated on 147 labelled views.
- [Prop coverage exploration](media/props-coverage-2026-10/README.md): one run each of a metal pot, a sci-fi canister, an organic stump and a glass-part lantern; found the UV padding and shattered-mesh fixes.
- [M0 exit evidence record](M0-EXIT-RECORD.md): each M0 exit item with its evidence and gaps; M0 closed by the owner on 2026-10-21.
- [Concept adherence](media/concept-adherence-2026-10/README.md): fixed-seed concept tests of what makes concepts follow a brief (part sentences, `--aspect`, camera wording); the jug's profile view is unsolved.
- [Concept proportions](media/concept-proportion-2026-10/README.md): no wording made a stump's trunk wider than tall; the opt-in `--shape-guide` depth guide did on 12 of 12 seeds.
- [Material showcase](media/material-showcase-2026-10/README.md): five props of different materials generated from briefs, with maps, renders, conditions and limits.
- [Texture mask recovery](media/texture-mask-recovery-2026-10/README.md): controlled failure, correction, fresh case and repeat; remaining appearance limitations.
- [Humanoid test 1](media/character-qualification-2026-10/basalt-warden-unity-preview/README.md): Unity walk playback, motion measurements, and current rig limitations.
- [Diagnostic humanoid benchmark](media/character-qualification-2026-10/basalt-corrected-humanoid/README.md): reviewed body deformation, valid Humanoid Avatar, and animation evidence.

## Reliability planning

- [Core 3D pipeline implementation audit](CORE-PIPELINE-AUDIT.md): evidence-backed M0 gaps and ordered implementation packages.

## For contributors

- [Session handoff](SESSION-HANDOFF.md): historical worktree and issue state from 2026-10-18; not kept current.
- [Product contract](PRODUCT_CONTRACT.md), [pipeline contract](PIPELINE_CONTRACT.md), [quality contract](QUALITY_CONTRACT.md), [roadmap](../ROADMAP.md), and [current state](../CURRENT_STATE.md)
- [Architecture](ARCHITECTURE.md), [asset outputs](ASSET-OUTPUTS.md), and [agent integration](AGENT-INTEGRATION.md)
- [Contributing and verification](../CONTRIBUTING.md)

Personal working notes and generated experiments belong under `private/` or `scratch/`. Git ignores those paths; keep public guides and a few compact, relevant examples under `docs/`.
