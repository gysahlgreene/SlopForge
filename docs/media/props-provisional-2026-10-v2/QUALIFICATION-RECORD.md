# Props provisional evidence: qualification record, criterion v2

Criterion version 2, declared on 2026-10-21 before any v2 run. It replaces
[criterion v1](../props-provisional-2026-10/QUALIFICATION-RECORD.md) for new runs. The v1
runs and their results stay as they are. Results for v2 are in the [evidence report](README.md).
Six runs cannot make anything Qualified.

## What changed from v1, and who decided

The project owner made these decisions on 2026-10-21, after reviewing the v1 runs:

- **Visual review of v1:** all three v1 props (crate, jug, lantern) were rated better than the
  2026-10-18 baseline, which was rated about 60% of target. No percentage was given.
- **Round props:** a side-on concept is acceptable for a rotationally symmetric prop, such as
  the jug, as long as every named part is visible. Concept criterion 4 changes to match.
- **Briefs:** they are rewritten with the authoring guidance in
  [Agent integration](../../AGENT-INTEGRATION.md). They are no longer word for word the same as
  the baseline's.
- **Thresholds:** the proposed pass/fail numbers were accepted as listed below.

The pipeline is the current code, not v1's commit `4d3ea32`. The commit is recorded per run. Changes
since v1 that these runs exercise:
- declared emitters are found and retried (#57, #58, #70);
- the emitter preflight runs before mesh work (#69);
- declared non-metal props get a zero metallic map (#71);
- hidden inner parts are removed from props (#72);
- the Unity import record (#74);
- a five-part limit on props, from this record.

## Scope and target profile

- **Category:** `prop`. Static, single mesh, one PBR material atlas, no rig.
- **Target profile:** Unity 6000.6.3f1 with URP 17.6.0, PC/console. Intended use is a static
  scene prop seen at close range.
- **Declared runtime budget:**
  - at most 30,000 exported triangles;
  - one material, so one draw call per instance;
  - 4096² maps: base color, normal, metallic-gloss and emission;
  - no LOD and no collision required.

  Texture memory follows from the maps. It is recorded, not limited.
- **Pipeline:** compute profile `h100` with quality tier `final`, the same as v1:
  - concept workflow `image_text2img_api` v1;
  - model workflow `trellis2_image_to_model_h100_api` v6;
  - six concepts, three mesh attempts and three material candidates.
- **Environment:** ComfyUI 0.37.0 on one H100 80 GB, Blender 5.1.0, Python 3.14.7, and Unity
  6000.6.3f1 batch mode on macOS arm64. Model weight hashes and custom-node revisions are not
  exposed and stay unknown.

## Representative briefs (v2)

The same three objects and material declarations as v1. Only the image prompts change, and the
crate also gets a portrait canvas.

**A.** `generate prop supply_crate "Wooden supply crate" --aspect portrait`
- `--image-prompt`: "Front three-quarter view of one sturdy medieval wooden supply crate that is
  taller than it is wide, about one and a quarter times as tall as it is wide. Weathered oak
  planks with clear wood grain and small knots. Dark wrought-iron corner brackets on every corner
  and two horizontal iron straps around the body, all with round rivet heads. Complete object,
  isolated on a plain light-grey background."
- `--material "planks=nonmetal: weathered oak with visible grain"`
- `--material "brackets=metal: dark wrought iron with rivets"`

**B.** `generate prop ceramic_jug "Glazed ceramic jug" --aspect portrait`
- `--image-prompt`: "Front three-quarter view of one rustic glazed ceramic jug that is taller
  than it is wide. A round belly and a short neck. One side handle in a thick loop, with a strip
  of rough twine wrapped around the handle. A natural tan cork stopper in the neck. Deep
  cobalt-blue glossy glaze that thins to warm brown clay at the rim and base. Complete object,
  isolated on a plain light-grey background."
- `--material "jug=nonmetal: glossy cobalt glaze over brown clay"`
- `--material "stopper=nonmetal: natural cork"`
- `--material "twine=nonmetal: rough natural twine"`

**C.** `generate prop stone_lantern "Weathered stone lantern for a fantasy ruin"` (square canvas)
- `--image-prompt`: "Front three-quarter view of one squat carved Japanese-style stone lantern
  for a fantasy ruin. A four-sided upturned roof with radial ribs and a round finial on top.
  Below the roof, a square light box with one window on each of its four sides; each window is
  filled flush with a solid opaque off-white rice-paper panel behind a simple dark wooden
  lattice. A chamfered middle tier. A chunky square base. Rough matte grey granite with fine
  black-and-white speckle and small chips, no polish. Seen in daylight. Complete object,
  isolated on a plain light-grey background."
- `--material "stone body=nonmetal: rough matte speckled grey granite"`
- `--material "paper panels=emissive: opaque off-white rice paper"`
- `--material "lattice=nonmetal: dark stained wood"`

**Authoring check.** This check is not part of the protocol, and its concepts are not reused.
Each new wording was generated once, with six concepts, before this record was committed:
- **Crate:** the wording was tested in [concept adherence](../concept-adherence-2026-10/README.md).
  It came out taller than wide in 6 of 6 concepts, with straps in 6 of 6.
- **Jug:**
  - All six concepts show the cork, a handle and twine, side-on.
  - One concept drew two handles.
- **Lantern on a portrait canvas, with "taller than it is wide":** it came out as a tall pedestal
  lantern, with some light boxes hexagonal. That goes against "squat", so the lantern keeps the
  square canvas.
- **Lantern on the square canvas:** squat, with four-sided boxes and panels unlit in 6 of 6.

## Independent runs and procedure

Same as v1:
- a fresh copy of the URP blank project plus `slopforge init` for each run;
- fresh seeds;
- run order A1, B1, C1, A2, B2, C2;
- the steps `generate`, agent concept selection, `approve`, turntable, then `unity-preview` on
  the lowest-numbered valid material candidate.

**Concept selection criteria, in order:**
1. the whole single object is in frame on a plain background;
2. every part the brief names is present, in the stated count;
3. the declared materials are visually distinct;
4. the view is three-quarter. For a rotationally symmetric prop (here the jug), a side-on view
   also passes when every named part is visible.

Among concepts that meet all four, the clearest silhouette wins, with the lowest number breaking
ties. If none meets them, the run is a concept-stage failure. The closest concept is still
selected for diagnostic evidence, and the run stays failed.

## Success and failure criteria

A run succeeds technically only if every stage passes with no intervention beyond the permitted
list. The v1 stage conditions all still apply, unchanged:
- Concept, conditioning and geometry.
- **Mesh/UV:** finite bounds, UVs present, at most 30,000 triangles.
- **Materials:** a candidate, a baked normal map, 4096² maps, and no declared-material mismatch.
- **Review renders.**
- **Unity:** `unity-preview` exits 0, the Lit material is assigned, and the URP render exists.

New pass/fail thresholds (owner-accepted):

| Measure | Pass condition | Where it is checked |
| --- | --- | --- |
| Separate mesh parts after hidden-part removal | at most 5 | Pipeline (`max_components: 5` on the `prop` type); more fails as `component_budget` and the next seed is tried |
| UV area used (`uv_area_sum`) | at least 0.20 | This record |
| Declared emitter coverage (brief C) | at least 0.5% of the map | This record. The pipeline only requires that some region is found, because valid small emitters are smaller (a relay lens measured 0.06%) |
| Mean metallic on a brief that declares no metal (B, C) | at most 0.05 | This record, measured on the delivered map |
| Triangles, materials, map size | the declared runtime budget above | Pipeline and this record |

Recorded, but not pass/fail:
- non-manifold and boundary edges (props are not deformed);
- bounds and scale;
- elapsed time;
- near-black and fully-metallic map fractions.

Failures, environment failures (one `approve --resume`), and kept failed runs are handled as in
v1.

## Interventions

The permitted and not-permitted lists are as in v1. In particular:
- no prompt edits between runs;
- no seed choice;
- no `--force`;
- no `approve-texture`;
- no code change during the protocol. A needed change ends the protocol, which then restarts
  under a new criterion version.

## Review authority, unchecked gates, and status

As in v1:
- **Review:** structural, technical and Unity results are agent machine checks. Visual,
  material and style acceptance is the owner's.
- **Unchecked gates:**
  - owner approval of these runs;
  - publication;
  - Play mode and in-scene lighting;
  - scale and pivot in a game scene;
  - style consistency;
  - unseen sides beyond the review renders;
  - other profiles.
- **Provisional, at most,** for "static props, `h100`/`final`, the recorded commit, Unity
  6000.6.3f1 / URP 17.6.0 import". That needs all six runs to pass every technical criterion
  above and the owner's visual review.
- **Experimental** otherwise.
- **Qualified is out of scope.**
