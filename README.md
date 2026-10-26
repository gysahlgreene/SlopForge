<div align="center">

# SlopForge

**Written brief in, reviewed 3D game asset out, in your Unity project.**

![A camera flies over a golden-hour moorland in Unity: over groves of oak, birch and pine and a winding gravel path, through the arch of a broken stone chapel to a small camp of props, then past heather to a granite tor](docs/media/natural-live-2026-10/flythrough.webp)

<sub>Every rock, ruin, prop, tree, flower and ground surface here was generated from a brief and assembled by one recipe, with no manual repair.</sub>

[![Verify](https://img.shields.io/github/actions/workflow/status/gysahlgreene/SlopForge/ci.yml?branch=main&label=verify&style=flat-square)](https://github.com/gysahlgreene/SlopForge/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/python-3.10%E2%80%933.14-3776ab?style=flat-square)](docs/INSTALL.md)
[![MIT license](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Buy Me A Coffee](https://img.shields.io/badge/buy%20me%20a%20coffee-ffdd00?style=flat-square&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/eoinmacd95f)

[Quick start](#quick-start) · [Documentation](docs/README.md) · [Examples](docs/EXAMPLES.md)

</div>

## Props

<p align="center"><img src="docs/media/props-lineup-2026-10/props_lineup.gif" width="820" alt="Seven generated props turning on a dark stage: a stone lantern, a glazed jug, a mossy tree stump, a supply crate, a cast-iron pot, a sci-fi fuel canister and a brass lantern"></p>

| Supply crate | Glazed jug | Stone lantern | Brass lantern |
| :---: | :---: | :---: | :---: |
| <img src="docs/media/props-provisional-2026-10-v5/A1_supply_crate_turntable.gif" width="190" alt="Supply crate"> | <img src="docs/media/props-provisional-2026-10-v5/B1_ceramic_jug_turntable.gif" width="190" alt="Glazed jug"> | <img src="docs/media/props-provisional-2026-10-v5/C1_stone_lantern_turntable.gif" width="190" alt="Stone lantern"> | <img src="docs/media/props-coverage-2026-10/G1_brass_lantern_turntable.gif" width="190" alt="Brass lantern"> |
| **Cast-iron pot** | **Fuel canister** | **Tree stump** | **Supply crate, run 2** |
| <img src="docs/media/props-coverage-2026-10/D1_iron_pot_turntable.gif" width="190" alt="Cast-iron pot"> | <img src="docs/media/props-coverage-2026-10/E1_fuel_canister_turntable.gif" width="190" alt="Sci-fi fuel canister"> | <img src="docs/media/props-coverage-2026-10/F2_tree_stump_turntable.gif" width="190" alt="Mossy tree stump"> | <img src="docs/media/props-provisional-2026-10-v5/A2_supply_crate_turntable.gif" width="190" alt="Supply crate, second run"> |

![Brass lantern: the selected concept, four Blender review views, and four Unity URP renders](docs/media/props-coverage-2026-10/G1_brass_lantern.png)

<sub>Concept → Blender review → Unity URP, for every prop. [Evidence →](docs/media/props-provisional-2026-10-v5/README.md)</sub>

## Weapons and moving parts

| Slide and trigger | Hinged lid |
| :---: | :---: |
| <img src="docs/media/moving-parts-2026-10/pistol_moving_parts.gif" width="400" alt="A black pistol with rosewood grips: the trigger pulls back, the slide racks back and returns, the trigger releases"> | <img src="docs/media/moving-parts-2026-10/chest_lid.gif" width="400" alt="A domed wooden chest with iron bands: the lid opens 100 degrees on its back edge onto a plank interior, then closes"> |

| Pistol | Longsword | Crossbow |
| :---: | :---: | :---: |
| <img src="docs/media/weapon-pipeline-2026-10/pistol_turntable.gif" width="260" alt="Generated pistol turning"> | <img src="docs/media/weapon-pipeline-2026-10/longsword_turntable.gif" width="260" alt="Generated longsword turning"> | <img src="docs/media/weapon-pipeline-2026-10/crossbow_turntable.gif" width="260" alt="Generated crossbow turning"> |

<sub>Moving parts publish as a Unity prefab: colliders, a Rigidbody, sockets and an Animator, checked in Play mode. [Evidence →](docs/media/moving-parts-2026-10/README.md) · [Weapons →](docs/media/weapon-pipeline-2026-10/README.md)</sub>

## Structures and environments

![A stone ruin courtyard, a timber house room and a sci-fi corridor room, each assembled in Unity from five generated modules](docs/media/kits-provisional-2026-10-v3/kits_lineup.jpg)

| Stone well | Stone shrine | Sci-fi bunker |
| :---: | :---: | :---: |
| <img src="docs/media/structures-real-size-2026-10/stone_well_turntable.gif" width="260" alt="Stone well with a shingled roof, winch and bucket, turning"> | <img src="docs/media/structures-real-size-2026-10/stone_shrine_turntable.gif" width="260" alt="Pale stone shrine with a pediment, two columns and a bronze basin, turning"> | <img src="docs/media/structures-real-size-2026-10/scifi_bunker_turntable.gif" width="260" alt="Concrete sci-fi bunker with a hazard-striped steel door and roof vents, turning"> |
| **Ruined arch** | **Broken window wall** | **Weathered corner** |
| <img src="docs/media/natural-live-2026-10/ruin_arch_turntable.gif" width="260" alt="Mossy granite archway with moulded piers, turning"> | <img src="docs/media/natural-live-2026-10/ruin_window_turntable.gif" width="260" alt="Stepped broken granite wall with an arched window, turning"> | <img src="docs/media/natural-live-2026-10/ruin_corner_turntable.gif" width="260" alt="Weathered L-shaped granite wall corner with moss, turning"> |

<sub>Modular kits snap together on a 3 m grid in Unity; structures are generated at real size. [Kit evidence →](docs/media/kits-provisional-2026-10-v3/README.md) · [Structures →](docs/media/structures-real-size-2026-10/README.md)</sub>

## Scenes

| Inside the chapel | Through the arch | Below the tor |
| :---: | :---: | :---: |
| <img src="docs/media/natural-live-2026-10/camp.jpg" width="280" alt="Inside the broken chapel: flagstones, a crate, a lantern and a pot by the north wall"> | <img src="docs/media/natural-live-2026-10/arch.jpg" width="280" alt="The chapel's freestanding arch with columns and fallen drums in tall grass"> | <img src="docs/media/natural-live-2026-10/tor.jpg" width="280" alt="Heather on a grassy knoll below a granite tor of cliff chunks"> |

<sub>One recipe of 30 briefs builds, lights and renders the whole moorland in Unity. [How →](docs/media/natural-live-2026-10/README.md)</sub>

## Characters

| Realistic | Stylized hero | Anime | Hand-painted |
| :---: | :---: | :---: | :---: |
| <img src="docs/media/character-styles-2026-10/realistic_walk.gif" width="190" alt="Realistic mercenary walking"> | <img src="docs/media/character-styles-2026-10/hero_walk.gif" width="190" alt="Stylized hero walking"> | <img src="docs/media/character-styles-2026-10/anime_walk.gif" width="190" alt="Anime adventurer walking"> | <img src="docs/media/character-styles-2026-10/painted_walk.gif" width="190" alt="Hand-painted dwarf walking"> |

<sub>Generated, rigged automatically and walking on motion capture. [Evidence →](docs/media/character-styles-2026-10/README.md)</sub>

## Materials

![Stone lantern: concept, base color, normal, roughness, metallic, emission and review renders](docs/media/material-showcase-2026-10/stone_lantern_v3.png)

<sub>Base colour, normal, roughness, metallic and emission up to 4096², generated with the mesh. [How →](docs/MATERIALS.md)</sub>

## Status

| | Status | |
| --- | --- | --- |
| Props | **Provisional** | [evidence](docs/media/props-provisional-2026-10-v5/README.md) |
| Modular kits and structures | **Provisional** | [evidence](docs/media/kits-provisional-2026-10-v3/README.md) |
| Weapons and moving parts | Experimental | [evidence](docs/media/moving-parts-2026-10/README.md) |
| Scenes | Experimental | [evidence](docs/media/natural-live-2026-10/README.md) |
| Characters | Experimental | [evidence](docs/media/character-styles-2026-10/README.md) |

Every asset passes automated checks and your approval before it is published. Provisional means two independent runs
of three briefs passed every check; nothing is Qualified yet. [What each status means →](docs/QUALITY_CONTRACT.md)

## Quick start

You need Python 3.10–3.14, Blender, a ComfyUI service (local or remote GPU) and a Unity project.

```sh
git clone https://github.com/gysahlgreene/SlopForge.git && cd SlopForge
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
slopforge init ~/UnityProjects/MyGame
slopforge --project ~/UnityProjects/MyGame doctor

slopforge --project ~/UnityProjects/MyGame generate prop brass_lantern "Brass hurricane lantern" \
  --material "frame=metal: aged brass" --material "globe=glass: clear glass"
slopforge --project ~/UnityProjects/MyGame approve brass_lantern 1          # pick a concept
slopforge --project ~/UnityProjects/MyGame approve-texture brass_lantern 1  # publish to Unity
```

[Installation](docs/INSTALL.md) · [ComfyUI setup](docs/COMFYUI.md) · [Writing briefs](docs/AGENT-INTEGRATION.md#mesh-aware-materials) · [More examples](docs/EXAMPLES.md)

## Contributing

Read [AGENTS.md](AGENTS.md), the [product](docs/PRODUCT_CONTRACT.md) and [pipeline](docs/PIPELINE_CONTRACT.md) contracts and
[current state](CURRENT_STATE.md), and run `make verify`. [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) ·
[MIT license](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
