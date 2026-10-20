# Props provisional evidence: qualification record

Criterion version 1, declared on 2026-10-20 before any run. This record defines the
[quality contract](../../QUALITY_CONTRACT.md)'s provisional initial evidence protocol
(three briefs, two independent runs each) for the M0 exit and the first M1 props evidence.
Results are in the [evidence report](README.md). Six runs cannot make anything Qualified.

## Scope and target profile

- **Category:** `prop`. Static, single mesh, one PBR material atlas, no rig.
- **Target profile:** Unity 6000.6.3f1 with URP 17.6.0, PC/console. Intended use is a
  static scene prop seen at close range. This is the project owner's declared M0 profile.
- **Explicit project defaults:** the template's `prop_faces: 30000` triangle budget and the
  final tier's 4096² maps. No runtime budget is declared (draw calls, texture memory,
  LOD, collision), so the performance gate stays unknown.
- **Pipeline:** compute profile `h100` with quality tier `final`, the same configuration as
  the [material showcase](../material-showcase-2026-10/README.md):
  - concept workflow `image_text2img_api` v1
  - model workflow `trellis2_image_to_model_h100_api` v6 (1536 shape, UDF remesh 384,
    4096² maps and normal bake)
  - tier defaults of six concepts, three mesh attempts and three material candidates
- **Environment:** ComfyUI 0.37.0 on one H100 80 GB, Blender 5.1.0, Python 3.14.7, and
  Unity 6000.6.3f1 batch mode on macOS arm64. The SlopForge commit is recorded per run.
  Model weight hashes and custom-node revisions are not exposed and stay unknown.

## Visual baseline

The 2026-10-18 [material showcase](../material-showcase-2026-10/README.md), which the
owner rated at about 60% of the target prop quality. Each brief below is used verbatim
from that showcase, so the runs can be compared side by side with it.

## Representative briefs

| Brief | Why it is representative |
| --- | --- |
| A. `supply_crate` | Hard surface that mixes metal and non-metal, with thin straps and rivets |
| B. `ceramic_jug` | Curved glossy non-metal with a thin handle and small attached parts |
| C. `stone_lantern` | Rough stone, an open lattice, and a declared emissive region |

These three do not cover fully metallic props, sci-fi hard surface, organic shapes, or
transparent glass.

**A.** `generate prop supply_crate "Wooden supply crate"`
- `--image-prompt`: "One sturdy medieval wooden supply crate, slightly taller than wide:
  weathered oak planks with clear wood grain and small knots, reinforced by dark
  wrought-iron corner brackets and straps with round rivet heads. Complete object, front
  three-quarter view, isolated on a plain light-grey background."
- `--material "planks=nonmetal: weathered oak with visible grain"`
- `--material "brackets=metal: dark wrought iron with rivets"`

**B.** `generate prop ceramic_jug "Glazed ceramic jug"`
- `--image-prompt`: "One rustic glazed ceramic jug with a round belly, short neck, side
  handle and a cork stopper: deep cobalt-blue glossy glaze that thins to warm brown clay
  at the rim and base, a natural tan cork stopper, a strip of rough twine wrapped around
  the handle. Complete object, front three-quarter view, isolated on a plain light-grey
  background."
- `--material "jug=nonmetal: glossy cobalt glaze over brown clay"`
- `--material "stopper=nonmetal: natural cork"`
- `--material "twine=nonmetal: rough natural twine"`

**C.** `generate prop stone_lantern "Weathered stone lantern for a fantasy ruin"`
- `--image-prompt`: "A squat carved Japanese-style stone lantern for a fantasy ruin:
  four-sided upturned roof with radial ribs and a round finial, a square light box whose
  four windows are filled flush with solid opaque off-white rice-paper panels behind a
  simple dark wooden lattice, the lantern unlit in daylight, a chamfered middle tier and
  a chunky square base. Rough matte grey granite with fine black-and-white speckle and
  small chips, no polish. Complete object, front three-quarter view, isolated on a plain
  light-grey background."
- `--material "stone body=nonmetal: rough matte speckled grey granite"`
- `--material "paper panels=emissive: opaque off-white rice paper"`
- `--material "lattice=nonmetal: dark stained wood"`

## Independent runs

A run is one fresh execution of a brief:
- It starts from a new copy of the URP blank Unity project followed by `slopforge init`,
  in its own Git-ignored folder.
- It shares no manifest, candidate, or stage output with any other run.
- The CLI draws fresh seeds. No seed is passed and no artifact is replayed.

Both runs of a brief use the same brief text and configuration. The order is A1, B1, C1,
then A2, B2, C2. The ComfyUI service, its loaded weights and the local tools are shared
conditions. ComfyUI caches only nodes whose inputs are identical; seeded nodes differ.

## Procedure per run

1. `slopforge init <project>` in a fresh project copy.
2. `generate` with the brief above and tier defaults.
3. **Concept selection.** The agent selects one concept and records its reason.
   - Criteria, in order:
     1. the whole single object is in frame on a plain background;
     2. every part the brief names is present;
     3. the declared materials are visually distinct;
     4. the view is three-quarter.
   - Among concepts that meet all four, the clearest silhouette wins, with the lowest
     number breaking ties.
   - If no concept meets them, the run is recorded as a concept-stage failure. The
     closest concept is still selected so that later stages produce diagnostic evidence,
     and the run stays failed.
   - The CLI calls this `approve <name> <n>` and writes `approval` on the concept. That
     is agent selection for evaluation, not the owner's appearance approval.
4. `approve <name> <n>` runs conditioning, geometry, mesh/UV preparation and material
   candidates, with Blender front, side, rear and three-quarter review renders.
5. A lit turntable of the Unity-previewed candidate is rendered with
   `blender/render_turntable.py`.
6. `unity-preview <name> <m>` runs on the lowest-numbered valid material candidate,
   chosen by number, not by appearance. It copies that candidate into
   `CandidatePreviews/`, imports it into Unity, assigns a URP Lit material, and saves a
   four-view URP render. It does not approve or publish the candidate.

## Success and failure criteria

A run succeeds technically only if every stage below passes with no intervention beyond
the permitted list:

| Stage | Pass condition |
| --- | --- |
| Concept | `generate` exits 0; six readable concepts; one meets the selection criteria |
| Conditioning | Cutout and 3D input image produced; the pipeline's crop and mask checks pass |
| Geometry | Parseable, non-empty GLB within the three-attempt budget |
| Mesh/UV | Pipeline validation passes: finite bounds, UVs present, at most 30,000 exported triangles |
| Materials | At least one candidate with status `candidate`; a baked normal map (not `neutral_placeholder`); 4096² maps; no declared-material mismatch |
| Multi-view review | Four Blender review renders and a turntable exist |
| Unity | `unity-preview` exits 0 (FBX imported; Lit material assigned with base, normal and metallic-gloss maps); the four-view URP render exists |

The following are recorded but are not pass/fail, because no threshold is declared:
- connected components
- emissive, metallic and near-black map fractions
- UV area and outside-unit fractions
- bounds and scale
- elapsed time

**A run fails when** a stage errors, a check fails, the attempt budget runs out, or a
non-permitted intervention would be needed. Failed runs are kept and are not replaced by
another run.

**Environment failures.** An environment failure (service unreachable, network drop,
Unity licence) or an interruption may be resumed once with `approve --resume`, and this
is recorded. A shared defect stops the protocol for diagnosis under
[AGENTS.md](../../../AGENTS.md); it is not retried until it passes.

## Interventions

**Permitted:**
- agent concept selection under the criteria above
- `unity-preview`
- `approve --resume` after an environment failure or interruption
- read-only turntable rendering

**Not permitted:**
- editing prompts between runs
- choosing seeds
- count overrides
- `--force`
- `--allow-placeholder-normal`
- editing generated meshes or maps
- `approve-texture` (it publishes and records an approval)
- rerunning to replace a failure
- code changes during the protocol (a needed change ends it, and the protocol restarts
  under a new criterion version)

## Review authority and unchecked gates

**Review authority.** Structural, technical and Unity results are machine checks run by
the agent. Visual, material and style acceptance belongs to the project owner. The agent
records observations only. A comparison with the 60% baseline is the owner's call.

**Gates left unchecked** (unchecked is not a pass):
- owner visual, material and style approval
- asset approval and publication (`approve-texture`)
- performance against runtime budgets
- collision and LOD
- scale and pivot against a game scene
- Play mode and in-scene lighting (the Unity render is an editor batch render)
- style consistency across a project's assets
- fidelity of unseen sides beyond what the review renders show
- other compute profiles and tiers

## Status this evidence can support

- **Provisional, at most,** for "static props, `h100`/`final`, the recorded commit, Unity
  6000.6.3f1 / URP 17.6.0 import". That requires all six runs to pass the technical
  criteria. The visual result stays pending until the owner reviews it.
- **Experimental** otherwise.
- **Qualified is out of scope.** Performance thresholds, visual acceptance criteria and
  runtime requirements are not declared.
