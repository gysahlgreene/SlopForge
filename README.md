<div align="center">

# SlopForge

**Turn an asset brief into a reviewed 3D game asset.**

![Seven generated props turning on a dark stage: a stone lantern, a glazed jug, a mossy tree stump, a supply crate, a cast-iron pot, a sci-fi fuel canister and a brass lantern](docs/media/props-lineup-2026-10/props_lineup.gif)

<sub>Each prop was generated from a written brief on an H100 and imported into Unity, with no manual repair.</sub>

[![Verify](https://img.shields.io/github/actions/workflow/status/gysahlgreene/SlopForge/ci.yml?branch=main&label=verify&style=flat-square)](https://github.com/gysahlgreene/SlopForge/actions/workflows/ci.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/python-3.10%E2%80%933.14-3776ab?style=flat-square)](docs/INSTALL.md)
[![MIT license](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Buy Me A Coffee](https://img.shields.io/badge/buy%20me%20a%20coffee-ffdd00?style=flat-square&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/eoinmacd95f)

[Get started](docs/INSTALL.md) · [Documentation](docs/README.md) · [Examples](docs/EXAMPLES.md)

</div>

SlopForge connects ComfyUI generation, Blender processing, human review, and Unity delivery. Run inference locally or on a remote GPU, and keep your assets, approval decisions and provenance in your own project.

## What it makes

| Asset type | Status | Evidence |
| --- | --- | --- |
| [Props](#props) — pickups, furniture, containers, devices | **Provisional** on the H100 `final` tier: three briefs, two independent runs each, passed every check through Unity import. Not yet Qualified | Ten props as lit turntables, each with concept, Blender and Unity URP views |
| [Characters](#characters) — rigged humanoids | Generated in four art styles, rigged automatically and walking; experimental, well below shippable model quality | Four characters walking as lit turntables; one character with Unity Humanoid playback |
| [Structures and environments](#structures-and-environments) — buildings, ruins, modular kits | Standalone structures and real-scale kit modules generated end to end | Six structures and a modular stone-kit courtyard as lit turntables |
| Weapons and mechanical assets, creatures | Planned on the [roadmap](ROADMAP.md) | — |

Every 3D asset type shares the same [materials and textures](#materials-and-textures) stage. Generation is stochastic: candidates must pass checks and human review, or the pipeline reports failure. A successful export alone does not make an asset game-ready.

## Props

**Three briefs, two independent runs each** (2026-10-21):

| Supply crate | Glazed jug | Stone lantern |
| :---: | :---: | :---: |
| <img src="docs/media/props-provisional-2026-10-v5/A1_supply_crate_turntable.gif" width="240" alt="Supply crate, run 1"> | <img src="docs/media/props-provisional-2026-10-v5/B1_ceramic_jug_turntable.gif" width="240" alt="Glazed jug, run 1"> | <img src="docs/media/props-provisional-2026-10-v5/C1_stone_lantern_turntable.gif" width="240" alt="Stone lantern, run 1"> |
| <img src="docs/media/props-provisional-2026-10-v5/A2_supply_crate_turntable.gif" width="240" alt="Supply crate, run 2"> | <img src="docs/media/props-provisional-2026-10-v5/B2_ceramic_jug_turntable.gif" width="240" alt="Glazed jug, run 2"> | <img src="docs/media/props-provisional-2026-10-v5/C2_stone_lantern_turntable.gif" width="240" alt="Stone lantern, run 2"> |
| oak planks + wrought iron | cobalt glaze + cork + twine | granite + glowing paper + wood |

**Four more kinds of prop, one run each** (2026-10-22):

| Cast-iron pot | Sci-fi fuel canister | Mossy tree stump | Brass lantern |
| :---: | :---: | :---: | :---: |
| <img src="docs/media/props-coverage-2026-10/D1_iron_pot_turntable.gif" width="180" alt="Cast-iron pot"> | <img src="docs/media/props-coverage-2026-10/E1_fuel_canister_turntable.gif" width="180" alt="Sci-fi fuel canister"> | <img src="docs/media/props-coverage-2026-10/F2_tree_stump_turntable.gif" width="180" alt="Mossy tree stump"> | <img src="docs/media/props-coverage-2026-10/G1_brass_lantern_turntable.gif" width="180" alt="Brass lantern"> |
| all metal | paint + steel + glowing strip | bark + moss + mushrooms | brass + glass globe |

Each prop was generated on an H100 from a written brief through `generate` → `approve`, with no manual repair, then imported into a fresh Unity 6000.6.3f1 / URP 17.6.0 project. Every run is checked from the concept through to the engine:

![Brass lantern: the selected concept, four Blender review views, and four Unity URP renders](docs/media/props-coverage-2026-10/G1_brass_lantern.png)

*Brass lantern: the selected concept (left), Blender review views (top) and Unity URP renders (bottom). The globe is a second, transparent material.*

**What the evidence supports.** All six runs of the three protocol briefs passed every stage and every owner-accepted threshold:
- at most five parts, 30,000 triangles and one 4096² material;
- colour within the accepted limits of the concept's hue and saturation (grey concepts are not checked);
- the glowing parts found;
- no metal on non-metal briefs.

That makes static props on this tier **Provisional**. The owner reviewed the runs and rated them better than earlier rounds. Two runs per brief cannot measure a failure rate, so nothing is Qualified.

**Known limits:**
- **Unseen sides are invented.** The canister's front strip was copied onto its sides and back as darker panels ([#63](https://github.com/gysahlgreene/SlopForge/issues/63)).
- **Proportions are not followed.** All 12 stump concepts came out taller than wide, against the brief ([#65](https://github.com/gysahlgreene/SlopForge/issues/65)).
- **Some surfaces differ from the concept:**
  - crate wood comes out paler than its concept;
  - one crate's open top was rebuilt closed;
  - one jug shows ribbing in Unity.
- **Glass:** glass parts work, but an object made entirely of glass does not reconstruct reliably.
- **Not covered by the checks:** the colour of small parts. Unity is checked in editor batch renders, not in Play mode.

[Protocol evidence →](docs/media/props-provisional-2026-10-v5/README.md) · [New prop kinds →](docs/media/props-coverage-2026-10/README.md) · [Earlier showcase (2026-10-18) →](docs/media/material-showcase-2026-10/README.md)

The brass lantern above was made from this brief:

```sh
slopforge --project ~/UnityProjects/MyGame generate prop brass_lantern "Brass hurricane lantern" --aspect portrait \
  --image-prompt "Front three-quarter view of one brass hurricane lantern, taller than it is wide. A rounded glass globe in the middle, drawn as a solid smooth pale surface with a faint sheen, nothing visible through it. Brass wire guards around the globe. A ring handle on top. A round brass base. Complete object, isolated on a plain light-grey background." \
  --material "frame=metal: aged brass" --material "globe=glass: clear glass"
slopforge --project ~/UnityProjects/MyGame candidates brass_lantern
slopforge --project ~/UnityProjects/MyGame approve brass_lantern 1
slopforge --project ~/UnityProjects/MyGame approve-texture brass_lantern 1
```

Inspect the concept, mesh views, materials, and validation report before each approval. [Writing briefs that reconstruct well →](docs/AGENT-INTEGRATION.md#mesh-aware-materials) · [More prop examples →](docs/EXAMPLES.md)

## Characters

| Realistic | Stylized hero | Anime | Hand-painted |
| :---: | :---: | :---: | :---: |
| <img src="docs/media/character-styles-2026-10/realistic_walk.gif" width="180" alt="Realistic mercenary walking"> | <img src="docs/media/character-styles-2026-10/hero_walk.gif" width="180" alt="Stylized hero walking"> | <img src="docs/media/character-styles-2026-10/anime_walk.gif" width="180" alt="Anime adventurer walking"> | <img src="docs/media/character-styles-2026-10/painted_walk.gif" width="180" alt="Hand-painted dwarf walking"> |

Each character is generated from a brief (a pose-conditioned concept, then TRELLIS.2 on an H100), rigged automatically with SkinTokens, and retargeted to a motion-capture walk with no manual repair. The rigging and walk are solid; the models are not yet game quality: forms are lumpy, faces soft and fingers fused, the limits of current open single-image 3D generation. Experimental and unapproved. [How they were made, evidence and limits →](docs/media/character-styles-2026-10/README.md)

Unity playback is shown separately: an earlier test character has a valid Unity Humanoid Avatar and plays a retargeted walk ([Unity evidence →](docs/media/character-qualification-2026-10/basalt-warden-unity-preview/README.md) · [diagnostic rig benchmark →](docs/media/character-qualification-2026-10/basalt-corrected-humanoid/README.md)).

Characters continue through [readiness and rigging](docs/CHARACTER-RIGGING.md), then [animation validation](docs/CHARACTER-ANIMATIONS.md).

## Structures and environments

| Stone well | Market stall | Stone shrine |
| :---: | :---: | :---: |
| <img src="docs/media/structure-showcase-2026-10/stone_well_turntable.gif" width="240" alt="Stone well turntable"> | <img src="docs/media/structure-showcase-2026-10/market_stall_turntable.gif" width="240" alt="Market stall turntable"> | <img src="docs/media/structure-showcase-2026-10/stone_shrine_turntable.gif" width="240" alt="Stone shrine turntable"> |
| **Watchtower** | **Ruined arch** | **Sci-fi bunker** |
| <img src="docs/media/structure-showcase-2026-10/watchtower_turntable.gif" width="240" alt="Watchtower turntable"> | <img src="docs/media/structure-showcase-2026-10/ruined_arch_turntable.gif" width="240" alt="Ruined arch turntable"> | <img src="docs/media/structure-showcase-2026-10/scifi_bunker_turntable.gif" width="240" alt="Sci-fi bunker turntable"> |

Standalone structures use the `architecture` asset type with the same brief-declared materials as props. Modular kits are recipes whose modules declare real sizes, so pieces snap on a shared grid:

| Modular stone kit courtyard |
| :---: |
| <img src="docs/media/structure-showcase-2026-10/stone_ruin_kit_turntable.gif" width="360" alt="Stone ruin kit courtyard turntable"> |

The floor, wall, doorway and column modules come out at their declared 3 m sizes and pass the kit's grid and pivot rules; the courtyard is assembled from them in Blender as a demonstration. One run each, not yet visually approved or imported into Unity; the kit's corner module reconstructed incorrectly. [Structure evidence and limits →](docs/media/structure-showcase-2026-10/README.md) · [Environment kits →](docs/ENVIRONMENT-KITS.md)

## Materials and textures

![Stone lantern: concept, base color, normal, roughness, metallic, emission and review renders](docs/media/material-showcase-2026-10/stone_lantern_v3.png)

Every 3D asset gets mesh-aware PBR materials generated with its geometry: base color, roughness, metallic, a baked tangent-space normal map and, for declared glowing parts, an emission map, at 4096² on the H100 final profile.

- **Material regions:** the brief declares `nonmetal`, `metal`, `emissive[#rrggbb]` or `glass[#rrggbb]` per region. Glass faces get a second, transparent URP material in Unity.
- **Reconstruction-ready concepts:** every 3D concept prompt asks for even lighting, matte non-metals, thick parts, and glowing or glass parts drawn as solid surfaces so they reconstruct whole.
- **Clean geometry:** raw shapes are remeshed on the GPU, and normals are baked against the full-detail mesh, so thin planks, handles and lattices survive. UV islands are padded by 4 texels and packed tightly.
- **Checks before review:** a candidate is rejected, and the next seed tried, when any of these fail:
  - it has more than five parts;
  - its silhouette does not fit the concept (this catches shattered meshes);
  - its colour drifts from the concept;
  - a declared glowing or glass part is not found.

  A metallic map that contradicts an all-non-metal brief also fails before review. Placeholder normal maps cannot be approved.

[How materials are made →](docs/MATERIALS.md)

## How it works

```mermaid
flowchart LR
    Brief[Brief + style + materials] --> Concept[Concept candidates]
    Concept --> Review[Human selection]
    Review --> Mesh[3D generation + checks]
    Mesh --> Materials[PBR materials + review]
    Materials --> Unity[Unity delivery]
    Mesh --> Rig[Character rigging]
    Rig --> Motion[Deformation review]
    Motion --> Playback[Animation + Unity validation]
```

- **Generate:** props, collectibles, architecture, and humanoid character candidates using configurable ComfyUI workflows.
- **Prepare:** inspect geometry, preserve sources, process meshes and PBR maps, and render review views and turntables in Blender.
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

[Installation](docs/INSTALL.md) covers dependencies. [ComfyUI configuration](docs/COMFYUI.md) covers local/remote inference and model/workflow compatibility. Then follow the [props](#props) or [characters](#characters) example above.

## What is qualified today?

| Area | Current evidence |
| --- | --- |
| Generation, candidate tracking, recipes, provenance | Implemented; offline tests and selected live GPU runs. Visual quality depends on the model and brief. |
| Static props | **Provisional** for `h100`/`final`, commit `221c8d1`, Unity 6000.6.3f1 / URP 17.6.0 import. Three briefs × two independent runs passed every stage and owner-accepted threshold ([criterion v5](docs/media/props-provisional-2026-10-v5/QUALIFICATION-RECORD.md)). Four more prop kinds passed end to end in single exploratory runs; the stump passed only after a UV fix prompted by its failed first run. Not Qualified: six runs cannot measure a failure rate. |
| Material and texture generation | Declared non-metal, metal, emissive and glass regions, with baked normal maps at 4096². Candidates are checked for part count, concept fit, colour against the concept, glowing and glass parts, and metal. The colour of small parts is not checked. |
| Structures and modular kits | Six standalone structures and a five-module stone kit generated on the H100 profile; kit modules keep declared real sizes and pass grid/pivot rules on their measurements. One run each; visual approval, corner reconstruction and Unity evidence pending. |
| Mesh/material preparation and Unity delivery | 30 protocol prop runs imported into Unity URP with materials assigned, rendered in editor batch mode. Publication through `approve-texture` is shown on one live asset. Play mode and in-scene checks are not run. |
| Humanoid rigging | Four generated characters in four art styles rig automatically with SkinTokens and walk on retargeted motion capture (natural stride, clean feet and shoulders); not approved, and model quality is well below target. Humanoid test 1 has a valid Unity Humanoid Avatar and visible walk playback. A separate diagnostic rig has approved body deformation. |
| Third-party motion retargeting | Humanoid test 1 demonstrates looping idle/walk playback and measured skinned-mesh movement. Broader movement, deformation approval, and production qualification remain open. |
| Safe Unity replacement/reimport | Implemented for props: republishing keeps GUIDs and texture references, and a prefab follows a republished mesh. If a GUID changes, approval stops and the previous files are restored. Checked by an opt-in live Unity test; a deleted `.meta` is only exercised on a fresh checkout. |

Full finger animation is not available on the diagnostic humanoid rig. Reference-input plumbing exists, but the bundled concept graph is text-only. SlopForge does not assemble game scenes or ship sprites; the pipeline remains a qualified asset workflow rather than a game engine.

## Find your way around

Contributors: read [AGENTS.md](AGENTS.md), the [product contract](docs/PRODUCT_CONTRACT.md), [pipeline contract](docs/PIPELINE_CONTRACT.md), and [current state](CURRENT_STATE.md). Run `make verify` before declaring implementation complete.

| Directory | Purpose |
| --- | --- |
| `slopforge/` | CLI, asset lifecycle, recipes, providers, and Unity integration |
| `blender/` · `processing/` | Background mesh, rigging, turntable and image helpers |
| `workflows/` · `templates/` | ComfyUI graphs, requirement declarations, and project defaults |
| `tests/` | Offline checks and opt-in Blender, Unity, and GPU integrations |
| `docs/` | User guides, contributor notes, and selected qualification examples |

[Contributing](CONTRIBUTING.md) · [Security and publishing](SECURITY.md) · [MIT license](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
