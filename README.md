# SlopForge

**Turn an asset brief into a reviewed 3D game asset.**

SlopForge connects ComfyUI generation, Blender processing, human review, and Unity delivery. Run inference locally or on a remote GPU; keep your assets, approval decisions, and provenance in your own project.

[Get started](docs/INSTALL.md) · [Documentation](docs/README.md) · [Examples](docs/EXAMPLES.md)

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-ffdd00?style=for-the-badge&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/eoinmacd95f)

## See it working

| Humanoid test 1 | Prop test 2 |
| :---: | :---: |
| ![Humanoid test 1 walking in Unity](docs/media/character-qualification-2026-10/basalt-warden-unity-preview/Unity-Walk-Cycle.gif) | ![Prop test 2 imported into Unity](img/power-relay-unity.png) |
| **Humanoid test 1** — valid Unity Humanoid Avatar with a looping walk preview. Movement is demonstrated; arm deformation remains under review. [Evidence →](docs/media/character-qualification-2026-10/basalt-warden-unity-preview/README.md) | **Prop test 2** — mesh, materials, and Unity import demonstrated. Reconstruction defects remain visible. [Example commands →](docs/EXAMPLES.md) |

These are measured examples. Generation is stochastic: candidates must pass checks and human review, or the pipeline reports failure. A successful export alone does not make an asset game-ready.

The Unity preview uses the latest arm-fit candidate and a retargeted walk clip. Unity measured movement on all 49,886 imported vertices; this confirms playback, not deformation quality. [Idle screenshot](docs/media/character-qualification-2026-10/basalt-warden-unity-preview/Unity-Idle-GameView.png) · [Walk pose](docs/media/character-qualification-2026-10/basalt-warden-unity-preview/Unity-Walk-Side.png) · [Evidence and limits](docs/media/character-qualification-2026-10/basalt-warden-unity-preview/README.md).

## Materials and textures

| Brass key | Glazed jug | Supply crate | Power relay | Stone lantern |
| :---: | :---: | :---: | :---: | :---: |
| ![Brass key turntable](docs/media/material-showcase-2026-10/brass_key_turntable.gif) | ![Glazed jug turntable](docs/media/material-showcase-2026-10/ceramic_jug_turntable.gif) | ![Supply crate turntable](docs/media/material-showcase-2026-10/supply_crate_turntable.gif) | ![Power relay turntable](docs/media/material-showcase-2026-10/power_relay_v2_turntable.gif) | ![Stone lantern turntable](docs/media/material-showcase-2026-10/stone_lantern_v3_turntable.gif) |
| metal | glossy non-metal | wood + iron | ceramic + copper + graphite | granite + paper + wood |

Every 3D prop gets mesh-aware PBR materials generated with its geometry: base color,
roughness, metallic, a baked tangent-space normal map and, for declared glowing parts, an
emission map, all at 4096² on the H100 final profile. The brief says what each region is
made of; SlopForge writes that into the concept prompt and checks the generated maps against
it before review.

![Stone lantern: concept, base color, normal, roughness, metallic, emission and review renders](docs/media/material-showcase-2026-10/stone_lantern_v3.png)

```sh
slopforge --project ~/UnityProjects/MyGame generate prop stone_lantern "Weathered stone lantern" \
  --image-prompt "A squat carved stone lantern: upturned ribbed roof, square light box with opaque off-white rice-paper panels behind a dark wooden lattice, chunky square base; rough matte speckled granite; complete three-quarter view on a plain light-grey background." \
  --material "stone body=nonmetal: rough matte speckled granite" \
  --material "paper panels=emissive: opaque off-white rice paper" \
  --material "lattice=nonmetal: dark stained wood"
```

- **Material regions:** declare `nonmetal`, `metal` or `emissive[#rrggbb]` per region. A candidate whose metallic map contradicts an all-non-metal brief fails before review.
- **Reconstruction-ready concepts:** even lighting, matte non-metals, thick parts, and glowing parts drawn unlit so they reconstruct as solid surfaces.
- **Clean geometry:** raw shapes are remeshed on the GPU and baked against the full-detail mesh, so thin planks, handles and lattices survive.
- **Checks:** placeholder normal maps cannot be approved; map statistics, UV coverage and topology are recorded with every candidate.

These five are generation evidence from one run each, with no manual repair, rendered as lit turntables in Blender. The project owner rates them about 60% of the target prop quality; they have not been visually approved or imported into Unity. [How materials are made →](docs/MATERIALS.md) · [Showcase evidence and limits →](docs/media/material-showcase-2026-10/README.md)

## The workflow

```mermaid
flowchart LR
    Brief[Brief + style] --> Concept[Concept candidates]
    Concept --> Review[Human selection]
    Review --> Mesh[3D generation + checks]
    Mesh --> Materials[Material review]
    Materials --> Unity[Unity delivery]
    Mesh --> Rig[Character rigging]
    Rig --> Motion[Deformation review]
    Motion --> Playback[Animation + Unity validation]
```

- **Generate:** props, collectibles, architecture, and humanoid character candidates using configurable ComfyUI workflows.
- **Prepare:** inspect geometry, preserve sources, process meshes and PBR maps, and render review views in Blender.
- **Review:** compare candidates, approve explicitly, and retain failed attempts and processing evidence.
- **Coordinate:** resume recipes, reuse style/reference libraries, and select quality tiers with bounded candidate budgets.
- **Deliver:** export models/materials and prepare character animation tooling for Unity.

## Quick start

Requires **Python 3.10–3.14**, Blender, a compatible ComfyUI service, and an existing Unity project. Model weights and custom nodes are installed separately.

```sh
git clone https://github.com/gysahlgreene/SlopForge.git
cd SlopForge
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
slopforge init ~/UnityProjects/MyGame
slopforge --project ~/UnityProjects/MyGame doctor
```

[Installation](docs/INSTALL.md) covers dependencies. [ComfyUI configuration](docs/COMFYUI.md) covers local/remote inference and model/workflow compatibility.

### Generate a prop

```sh
slopforge --project ~/UnityProjects/MyGame generate prop stone_lantern \
  "Weathered stone lantern for a fantasy ruin" \
  --image-prompt "Squat carved stone lantern, broad square cap, opaque paper window panels, chunky base; matte granite; complete three-quarter view, isolated on a plain neutral background." \
  --material "body=nonmetal: matte granite" --material "panels=emissive: off-white paper"
slopforge --project ~/UnityProjects/MyGame candidates stone_lantern
slopforge --project ~/UnityProjects/MyGame approve stone_lantern 1
slopforge --project ~/UnityProjects/MyGame candidates stone_lantern
slopforge --project ~/UnityProjects/MyGame approve-texture stone_lantern 1
```

Inspect the concept, mesh views, materials, and validation report before each approval. For characters, continue through [readiness and rigging](docs/CHARACTER-RIGGING.md), then [animation validation](docs/CHARACTER-ANIMATIONS.md).

## What is qualified today?

| Area | Current evidence |
| --- | --- |
| Generation, candidate tracking, recipes, provenance | Implemented; offline tests and selected live GPU runs. Visual quality depends on the model and brief. |
| Material and texture generation | Five varied-material props generated from briefs on the H100 profile with declared-material checks and baked normal maps; one run each, visual approval pending. |
| Mesh/material preparation and Unity delivery | Demonstrated on selected props; geometry and material defects still require review. |
| Humanoid rigging | Humanoid test 1 has a valid Unity Humanoid Avatar and visible walk playback. Arm deformation and source topology still need review. A separate diagnostic rig has approved body deformation. |
| Third-party motion retargeting | Humanoid test 1 demonstrates looping idle/walk playback and measured skinned-mesh movement. Broader movement, deformation approval, and production qualification remain open. |
| Safe Unity replacement/reimport | Stable GUIDs and replacement validation remain open. |

Full finger animation is not available on the diagnostic humanoid rig. Reference-input plumbing exists, but the bundled concept graph is text-only. SlopForge does not assemble game scenes or ship sprites; the pipeline remains a qualified asset workflow rather than a game engine.

## Find your way around

Contributors: read [AGENTS.md](AGENTS.md), the [product contract](docs/PRODUCT_CONTRACT.md), [pipeline contract](docs/PIPELINE_CONTRACT.md), and [current state](CURRENT_STATE.md). Run `make verify` before declaring implementation complete.

| Directory | Purpose |
| --- | --- |
| `slopforge/` | CLI, asset lifecycle, recipes, providers, and Unity integration |
| `blender/` · `processing/` | Background mesh, rigging, and image helpers |
| `workflows/` · `templates/` | ComfyUI graphs, requirement declarations, and project defaults |
| `tests/` | Offline checks and opt-in Blender, Unity, and GPU integrations |
| `docs/` | User guides, contributor notes, and selected qualification examples |

[Contributing](CONTRIBUTING.md) · [Security and publishing](SECURITY.md) · [MIT license](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
