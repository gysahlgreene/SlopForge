<div align="center">

# SlopForge

**Turn an asset brief into a reviewed 3D game asset.**

![A camera flies over a golden-hour moorland in Unity: over groves of oak, birch and pine and a winding gravel path, through the arch of a broken stone chapel to a small camp of props, then past heather to a granite tor](docs/media/natural-live-2026-10/flythrough.webp)

<sub>Every rock, ruin, prop, tree, flower and ground surface in this Unity scene was generated from a written brief and assembled by one recipe, with no manual repair. [How it was made →](#scenes-and-natural-environments)</sub>

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
| [Structures and environments](#structures-and-environments) — buildings, ruins, modular kits | **Provisional** for modular kits on the H100 `final` tier: three kits, two independent runs each, passed every check through an assembled Unity scene. Standalone structures are generated at real size. Not yet Qualified | Stone, timber and sci-fi rooms assembled in Unity; three real-size structures and three ruin pieces as lit turntables |
| [Scenes and natural environments](#scenes-and-natural-environments) — terrain, rocks, trees, ground cover, assembled showcases | **Experimental**: one moorland scene, approved by the owner, built from briefs and rendered in Unity with a flythrough; now a recipe and `scene-render`, rebuilt live from a fresh project | The flythrough above; six stills |
| Weapons and mechanical assets, creatures | Planned on the [roadmap](ROADMAP.md) | — |

Every 3D asset type shares the same [materials and textures](#materials-and-textures) stage. Generation is stochastic: candidates must pass checks and human review, or the pipeline reports failure. A successful export alone does not make an asset game-ready.

## Props

![Seven generated props turning on a dark stage: a stone lantern, a glazed jug, a mossy tree stump, a supply crate, a cast-iron pot, a sci-fi fuel canister and a brass lantern](docs/media/props-lineup-2026-10/props_lineup.gif)

**Three briefs, two independent runs each** (2026-10-21):

| Supply crate | Glazed jug | Stone lantern |
| :---: | :---: | :---: |
| <img src="docs/media/props-provisional-2026-10-v5/A1_supply_crate_turntable.gif" width="240" alt="Supply crate, run 1"> | <img src="docs/media/props-provisional-2026-10-v5/B1_ceramic_jug_turntable.gif" width="240" alt="Glazed jug, run 1"> | <img src="docs/media/props-provisional-2026-10-v5/C1_stone_lantern_turntable.gif" width="240" alt="Stone lantern, run 1"> |
| <img src="docs/media/props-provisional-2026-10-v5/A2_supply_crate_turntable.gif" width="240" alt="Supply crate, run 2"> | <img src="docs/media/props-provisional-2026-10-v5/B2_ceramic_jug_turntable.gif" width="240" alt="Glazed jug, run 2"> | <img src="docs/media/props-provisional-2026-10-v5/C2_stone_lantern_turntable.gif" width="240" alt="Stone lantern, run 2"> |
| <sub>oak planks + wrought iron</sub> | <sub>cobalt glaze + cork + twine</sub> | <sub>granite + glowing paper + wood</sub> |

**Four more kinds of prop, one run each** (2026-10-22):

| Cast-iron pot | Sci-fi fuel canister | Mossy tree stump | Brass lantern |
| :---: | :---: | :---: | :---: |
| <img src="docs/media/props-coverage-2026-10/D1_iron_pot_turntable.gif" width="180" alt="Cast-iron pot"> | <img src="docs/media/props-coverage-2026-10/E1_fuel_canister_turntable.gif" width="180" alt="Sci-fi fuel canister"> | <img src="docs/media/props-coverage-2026-10/F2_tree_stump_turntable.gif" width="180" alt="Mossy tree stump"> | <img src="docs/media/props-coverage-2026-10/G1_brass_lantern_turntable.gif" width="180" alt="Brass lantern"> |
| <sub>all cast iron</sub> | <sub>paint + steel + glow strip</sub> | <sub>bark + moss + mushrooms</sub> | <sub>brass + glass globe</sub> |

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
- **Wording does not always hold proportions.** Every stump's trunk came out taller than wide whatever the wording. An opt-in shape guide fixed it in 12 of 12 concepts and one run through Unity ([evidence](docs/media/concept-proportion-2026-10/README.md), [#65](https://github.com/gysahlgreene/SlopForge/issues/65)).
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

Each character is generated from a brief (a pose-conditioned concept, then TRELLIS.2 on an H100), rigged automatically with SkinTokens, and retargeted to a motion-capture walk with no manual repair. The rigging and walk improved through owner review but are not approved; the models are not yet game quality: forms are lumpy, faces soft and fingers fused, the limits of current open single-image 3D generation. Experimental and unapproved. [How they were made, evidence and limits →](docs/media/character-styles-2026-10/README.md)

Unity playback is shown separately: an earlier test character has a valid Unity Humanoid Avatar and plays a retargeted walk ([Unity evidence →](docs/media/character-qualification-2026-10/basalt-warden-unity-preview/README.md) · [diagnostic rig benchmark →](docs/media/character-qualification-2026-10/basalt-corrected-humanoid/README.md)).

Characters continue through [readiness and rigging](docs/CHARACTER-RIGGING.md), then [animation validation](docs/CHARACTER-ANIMATIONS.md).

## Structures and environments

**Three modular kits, assembled in Unity** (2026-10-23). Every module is generated from a written brief at its real
size, checked, published to Unity as a prefab, and placed by the kit's layout. There is no manual repair:

![A stone ruin courtyard, a timber house room and a sci-fi corridor room, each assembled in Unity from five generated modules](docs/media/kits-provisional-2026-10-v3/kits_lineup.jpg)

| Kit | Modules | One look across the kit | Protocol runs |
| --- | --- | --- | --- |
| `stone_ruin_kit` | floor, wall, doorway, corner, column | one stone texture sets every module's tint and finish | 2 of 2 passed |
| `timber_house_kit` | floor, wall, window, doorway, corner | dark oak beams and lime plaster, declared per module | 2 of 2 passed |
| `scifi_corridor_kit` | floor, wall, doorway, corner, pillar | painted panels, steel and a cyan light strip | 2 of 2 passed |

All six runs passed every owner-accepted check, so modular kits on this tier are **Provisional**:
- **The pieces fit:**
  - every module is within 5 cm of its declared size and pivot on a 3 m grid;
  - corner arms are as thick as the walls, so joints run flush;
  - Unity finds no seam gap wider than 1 mm.
- **The pieces keep their shape:** no module is stretched more than 1.3 times to reach its size. A corner that
  reconstructs as a solid block or a wedge is rejected, and the next seed is tried.
- **The pieces match their concepts:** concept fit is at least 0.89, and colour stays within the accepted limits
  (hue and saturation; the check for textures turned dark came after these runs).
- **Ready for a scene:** each piece is a prefab with a mesh collider and static flags. Floors use 15k faces, walls
  and corners 40k, columns 20k, and every map is 2048².

Unity checks the assembly; it isn't judged by eye.

```sh
slopforge --project ~/UnityProjects/MyGame recipe run timber_house_kit --name house
slopforge --project ~/UnityProjects/MyGame approve house_wall 1          # then each module in turn
slopforge --project ~/UnityProjects/MyGame approve-texture house_wall 1
slopforge --project ~/UnityProjects/MyGame environment-check house
slopforge --project ~/UnityProjects/MyGame environment-scene house room
```

For the stone kit, approve its `stone` texture first: every module takes its tint and finish from it, and keeps its own generated colours and weathering.

**What the evidence supports:**
- Two independent runs of each kit passed every check on the H100 `final` tier through Unity 6000.6.3f1 / URP
  17.6.0. That makes the kits Provisional.
- Two runs per kit cannot measure a failure rate, so nothing is Qualified.
- The status is for commit `5ceac3b`. The stone kit's material step has since changed: modules now keep their own
  colours with the kit's tint matched (#101). No protocol run covers that yet.
- The owner reviewed the scenes on 2026-10-23 and judged them well below the props. They are not approved.

**Known limits:**
- **Unseen wall backs are invented:** the timber walls' outsides are bare wood, the sci-fi walls' outsides dark.
- **Some texture blemishes remain:** streaked plaster, gouges and green patches in some runs.
- **The sci-fi corners are whiter than its walls,** because that kit has no shared material.
- **S2's pillar is near-black** where its concept is grey metal: TRELLIS sometimes textures a mesh mostly black.
  The [dark-texture check](docs/media/dark-texture-check-2026-10/README.md) now rejects such a texture; these runs
  predate it.
- **Not covered:** Unity is checked in editor batch renders, with no Play mode, lightmaps or LODs.

[Protocol evidence →](docs/media/kits-provisional-2026-10-v3/README.md) · [Earlier rounds: v1](docs/media/kits-provisional-2026-10/README.md), [v2](docs/media/kits-provisional-2026-10-v2/README.md) · [Environment kits guide →](docs/ENVIRONMENT-KITS.md) · [M2 epic →](https://github.com/gysahlgreene/SlopForge/issues/89)

**Standalone structures** use the `architecture` asset type, with the same brief-declared materials as props. They are
generated at real size with `generate --target-size`, and get the same concept-fit and colour checks as props:

| Stone well, 3.2 m tall | Stone shrine, 3.5 m tall | Sci-fi bunker, 3.0 m tall |
| :---: | :---: | :---: |
| <img src="docs/media/structures-real-size-2026-10/stone_well_turntable.gif" width="240" alt="Stone well with a shingled roof, winch and bucket, turning"> | <img src="docs/media/structures-real-size-2026-10/stone_shrine_turntable.gif" width="240" alt="Pale stone shrine with a pediment, two columns and a bronze basin, turning"> | <img src="docs/media/structures-real-size-2026-10/scifi_bunker_turntable.gif" width="240" alt="Concrete sci-fi bunker with a hazard-striped steel door and roof vents, turning"> |
| **Ruined arch, 3.6 m tall** | **Broken window wall, 3 m long** | **Weathered corner, 3 m across** |
| <img src="docs/media/natural-live-2026-10/ruin_arch_turntable.gif" width="240" alt="Mossy granite archway with moulded piers, turning"> | <img src="docs/media/natural-live-2026-10/ruin_window_turntable.gif" width="240" alt="Stepped broken granite wall with an arched window, turning"> | <img src="docs/media/natural-live-2026-10/ruin_corner_turntable.gif" width="240" alt="Weathered L-shaped granite wall corner with moss, turning"> |

The top row is one real-size run each (2026-10-22), and each passed on its first mesh attempt. The bunker's white patch
and invented second door are single-image limits. The bottom row is ruin pieces from the
[live moorland run](docs/media/natural-live-2026-10/README.md) (2026-10-23). None of them is visually approved yet.
[Real-size evidence →](docs/media/structures-real-size-2026-10/README.md) · [The first structure run →](docs/media/structure-showcase-2026-10/README.md)

## Scenes and natural environments

**A whole scene from briefs** (2026-10-23). The flythrough at the top is one Unity scene that SlopForge built from
one recipe, in a blank project:
- **Rocks:** boulders, outcrops and a granite tor of cliff chunks.
- **A broken stone chapel:** jagged walls, a window, a weathered corner, a freestanding arch, columns, fallen drums
  and cracked flagstones.
- **A camp of props:** a crate, a jug, a stone lantern, a pot, a stump and a brass lantern, from the briefs of the
  prop protocol and coverage runs, each generated once by the recipe.
- **Ground:** meadow, forest floor, gravel and granite tiling materials, with 2 million grass blades coloured from
  the meadow.
- **Plants:** heather and wildflower cards, and oak, birch and pine trees built from generated bark and leaf
  cut-outs.

| Inside the chapel | Through the arch | Below the tor |
| :---: | :---: | :---: |
| <img src="docs/media/natural-live-2026-10/camp.jpg" width="280" alt="Inside the broken chapel: flagstones, a crate, a lantern and a pot by the north wall"> | <img src="docs/media/natural-live-2026-10/arch.jpg" width="280" alt="The chapel's freestanding arch with columns and fallen drums in tall grass"> | <img src="docs/media/natural-live-2026-10/tor.jpg" width="280" alt="Heather on a grassy knoll below a granite tor of cliff chunks"> |

```sh
slopforge --project ~/UnityProjects/MyGame recipe run moorland_ruin --name moor
slopforge --project ~/UnityProjects/MyGame approve moor_boulder 1      # each child in turn; 3D ones then approve-texture
slopforge --project ~/UnityProjects/MyGame scene-render moor
```

**How it works:**
- **The recipe:** [`moorland_ruin`](templates/recipes/moorland_ruin.yaml) carries the 30 briefs and a `scene` block:
  terrain rules, plants, scatter, structures, lighting and cameras.
- **Planning:** `scene-render` builds the trees and plans every placement in Python.
- **In Unity:** it builds and lights the scene, bakes global illumination from probe volumes with sky occlusion, and
  renders stills and the flythrough.

**What the evidence supports:**
- **Approved, then rebuilt:** the owner judged a prototype's look "perfect". The recipe then rebuilt the scene from
  a blank project, which is the footage shown. That run found three faults, now fixed, and the agent reselected two
  concepts, one of them for a mesh TRELLIS textured black. It is one run, and the owner has not reviewed it yet.
- **Not a game level:** this is a showcase render. Play mode, frame rate, LODs and wind are not checked, and 2 million
  mesh grass blades would be too heavy for a game.

[Live run evidence →](docs/media/natural-live-2026-10/README.md) · [The approved prototype →](docs/media/natural-showcase-2026-10/README.md) · [Natural environments guide →](docs/NATURAL-ENVIRONMENTS.md)

## Materials and textures

![Stone lantern: concept, base color, normal, roughness, metallic, emission and review renders](docs/media/material-showcase-2026-10/stone_lantern_v3.png)

<sub>The maps of a stone lantern from the 2026-10-18 showcase, made before the colour and metal checks below. The [Provisional prop runs](docs/media/props-provisional-2026-10-v5/README.md) show current output.</sub>

Every 3D asset gets mesh-aware PBR materials generated with its geometry: base color, roughness, metallic, a baked tangent-space normal map and, for declared glowing parts, an emission map, at 4096² on the H100 final profile (kit modules declare 2048²).

- **Material regions:** the brief declares `nonmetal`, `metal`, `emissive[#rrggbb]` or `glass[#rrggbb]` per region. Glass faces get a second, transparent URP material in Unity.
- **Reconstruction-ready concepts:** every 3D concept prompt asks for even lighting, matte non-metals, thick parts, and glowing or glass parts drawn as solid surfaces so they reconstruct whole.
- **Clean geometry:** raw shapes are remeshed on the GPU, and normals are baked against the full-detail mesh, so thin planks, handles and lattices survive. UV islands are padded by 4 texels and packed tightly.
- **Checks before review:** a candidate is rejected, and the next seed tried, when any of these fail:
  - it has more than five parts;
  - its silhouette does not fit the concept (this catches shattered meshes);
  - its colour drifts from the concept;
  - its texture turns dark where the concept is light ([calibration](docs/media/dark-texture-check-2026-10/README.md));
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

- **Generate:** props, collectibles, architecture, kit modules, foliage cut-outs, tiling ground and bark materials, and humanoid character candidates using configurable ComfyUI workflows; trees and shrubs with `vegetation`.
- **Prepare:** inspect geometry, preserve sources, process meshes and PBR maps, and render review views and turntables in Blender.
- **Review:** compare candidates, approve explicitly, and retain failed attempts and processing evidence.
- **Coordinate:** resume recipes, reuse style/reference libraries, and select quality tiers with bounded candidate budgets.
- **Deliver:** export models/materials, assemble kit layouts into Unity scenes, render whole scenes with `scene-render`, and prepare character animation tooling for Unity.

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
| Material and texture generation | Declared non-metal, metal, emissive and glass regions, with baked normal maps at 4096² by default (2048² for kit modules). Candidates are checked for part count, concept fit, colour against the concept, glowing and glass parts, and metal. The colour of small parts is not checked. |
| Structures and modular kits | **Provisional** for the stone ruin, timber house and sci-fi corridor kits on `h100`/`final`, commit `5ceac3b`, Unity 6000.6.3f1 / URP 17.6.0: two independent runs each passed every owner-accepted M2 criterion through an assembled Unity scene ([criterion M2-v3](docs/media/kits-provisional-2026-10-v3/README.md)). Not Qualified, and the owner judged the kits' look below the props'. The stone kit's material step changed after that commit (#101) and has no protocol run. Standalone structures are generated at real size, one run each. |
| Scenes and natural environments | **Experimental**: one owner-approved moorland scene (prototype); `scene-render` and the `moorland_ruin` recipe rebuilt it once from a blank project ([live run](docs/media/natural-live-2026-10/README.md)). Rendering only: no Play mode or performance check. |
| Mesh/material preparation and Unity delivery | 28 of the 30 protocol prop runs imported into Unity URP with materials assigned, rendered in editor batch mode (two stopped earlier). Every M2-v3 kit module and every moorland model was published with `approve-texture`; kit scenes are checked in Unity for grounding, colliders, static flags and seam gaps. Play mode is not run. |
| Humanoid rigging | Four generated characters in four art styles rig automatically with SkinTokens and walk on retargeted motion capture (natural stride, clean feet and shoulders); not approved, and model quality is well below target. Humanoid test 1 has a valid Unity Humanoid Avatar and visible walk playback. A separate diagnostic rig has approved body deformation. |
| Third-party motion retargeting | Humanoid test 1 demonstrates looping idle/walk playback and measured skinned-mesh movement. Broader movement, deformation approval, and production qualification remain open. |
| Safe Unity replacement/reimport | Implemented for props: republishing keeps GUIDs and texture references, and a prefab follows a republished mesh. If a GUID changes, approval stops and the previous files are restored. Checked by an opt-in live Unity test; a deleted `.meta` is only exercised on a fresh checkout. |

Full finger animation is not available on the diagnostic humanoid rig. Reference-input plumbing exists, but the bundled concept graph is text-only. SlopForge assembles showcase scenes for review, not game levels, and does not ship sprites; the pipeline remains a qualified asset workflow rather than a game engine.

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
