# 3D character rigging

**Current benchmark:** [Basalt Warden](media/character-qualification-2026-10/basalt-corrected-humanoid/README.md) has approved body deformation, a valid Unity Humanoid Avatar, and evaluated diagnostic animation. Rigging providers remain experimental; full material/input qualification and third-party motion validation are outstanding.

## Animation-readiness gate

Run deterministic mesh inspection after approving a character model and before requesting a rig:

```sh
slopforge --project ~/UnityProjects/MyGame character readiness moon_scout_character
slopforge --project ~/UnityProjects/MyGame inspect moon_scout_character
slopforge --project ~/UnityProjects/MyGame character approve-readiness moon_scout_character
slopforge --project ~/UnityProjects/MyGame character normalize moon_scout_character
slopforge --project ~/UnityProjects/MyGame character approve-normalization moon_scout_character
slopforge --project ~/UnityProjects/MyGame character readiness moon_scout_character --source-output normalized_model
slopforge --project ~/UnityProjects/MyGame character approve-readiness moon_scout_character
slopforge --project ~/UnityProjects/MyGame character rig moon_scout_character --source-output normalized_model
```

The report records topology, connected components, transforms, face normals, bounds, UV coverage, per-mesh material and linked-image-texture assignment, missing texture files, auxiliary objects, Blender-world axes/units, source artifact, and source SHA-256. Missing or invalid geometry, UV, material, texture, coordinate, or helper measurements fail closed. `pass` still requires explicit approval; `needs_review` requires human approval after reviewing the model's orientation, intended scale, rest pose, and helper objects; `fail` cannot be approved. Rigging is blocked until the report is accepted. The manifest keeps model generation, animation readiness, rigging, deformation, and Unity Avatar states separate. This gate checks mesh structure and scale; it does not establish anatomy, useful skin weights, acceptable deformation, or Unity Humanoid validity.

The reported dimensions are in Blender units; the report also records the Blender scene unit system and scale and converts dimensions to metres for the size check. Unspecified scene units require human scale review. The recorded Z-up and -Y-forward values describe Blender's world basis, not an automatic judgment that the character faces the intended direction. Review those values against the front/side/rear views before approving readiness. A linked image texture is evidence that a texture node exists, not proof of useful coverage or visual quality; inspect the actual material in neutral lighting. A structural pass or human readiness approval does not make the asset game-ready: deformation review and Unity validation remain separate gates.

Readiness is classified from the raw measurements on every run and starts pending review. Approval and the shared rigging/normalization gate also check those measurements against the current contract. Older reports that lack the required fields cannot authorize processing, even when their saved status says approved; rerun `character readiness` and review the new report before approving it.

Each inspection uses a fresh temporary report and verifies that source bytes stayed unchanged while Blender inspected them. Missing output or a changed source stops the run and preserves the previous report and approval instead of treating stale evidence as current.

Material counts use slots actually assigned to faces. An unused textured slot cannot cover faces assigned to an empty or invalid slot. Linked-image checks establish node-link presence; human review must still verify the active shader and visible texture coverage.

Normalization is a separate, reviewable stage. It welds/remeshes components, creates UVs, and bakes available source material channels; inspect its report and compare it with the source before approval. Run readiness again against `normalized_model` and approve that report before rigging with `--source-output normalized_model`. The original generated model remains intact. Remeshing and baking can reduce visual fidelity; normalization cannot invent missing detail or repair a bad character design.

Rigging is a separate character stage; prop cleanup does not create a deformable skeleton. New projects include a first-class `character` model type and the `character_3d_pack` recipe. It generates one full-body neutral A-pose concept, runs the selected 3D model workflow, and records a reviewable model on a character asset. Configure `asset_pipeline.character_rigging_provider` as `blender_rigify` or `skintokens`. SkinTokens runs from a separately configured Python environment, checkout, and checkpoint; `character provider-setup skintokens` applies only the pinned, hash-checked compatibility edit to that checkout.

```sh
slopforge --project ~/UnityProjects/MyGame recipe run character_3d_pack --name moon_scout
slopforge --project ~/UnityProjects/MyGame candidates moon_scout_character
slopforge --project ~/UnityProjects/MyGame approve moon_scout_character 1
slopforge --project ~/UnityProjects/MyGame approve-texture moon_scout_character 1
slopforge --project ~/UnityProjects/MyGame character rig moon_scout_character --source-output normalized_model
```

Provider outputs can be recorded with `slopforge.character_rigging.record_rigging_result()` as typed artifacts on a `character` manifest asset. The result names an already approved source output, a project-relative FBX or GLB, optional PNG pose evidence, skeleton-name mapping, and provider provenance (`name`, `version`, `source`, and `license`). Registered rig and evidence artifacts remain candidates pending human review.

The recorder rejects paths outside the project, missing/empty exports, unapproved source artifacts, unsupported mesh formats, invalid evidence images, and incomplete provider license metadata. It records missing recommended pose evidence without pretending the rig passed deformation checks. Suggested evidence poses are T-pose, raised arms, crouch, leg lift, elbow bend, and shoulder rotation.

## Blender Rigify provider

With `blender_rigify` selected, `slopforge character rig <name> [--source-output model]` runs Blender's bundled Rigify add-on against a ready, approved GLB or FBX model artifact. It fits Blender's human metarig to the model bounds, welds coincident vertices, reports boundary edges, rejects non-manifold edges, generates automatic weights, renders six review poses, measures vertex displacement, and exports an FBX. Boundary edges are open surface edges; readiness flags them for human review, but they are not treated as non-manifold edges by the Rigify guard. Rig and pose artifacts are registered as pending review; the command never approves them.

The provider uses the installed Blender executable and its bundled code; no extra Python package or model weights are installed. The provider reports Blender/Rigify version and GPL-2.0-or-later provenance. Review the installed Blender distribution's notices for the exact bundled add-on terms.

This is a fitting heuristic, not general-purpose automatic rigging. It expects an upright humanoid whose proportions fit Blender's human metarig; bounds-based fitting cannot place joints reliably for arbitrary anatomy. Vertex welding can alter the mesh slightly. The synthetic Blender integration smoke verifies execution, weighting, export, and pose motion, but does not establish quality on generated SlopForge characters. Inspect the source, rig, and all six pose renders before approval; pose images and nonzero displacement do not establish acceptable deformations or Unity Humanoid compatibility.

SkinTokens is also available as an opt-in provider. It uses a separately configured runtime and checkpoint and remains experimental. Each output still needs source review, deformation review, and the intended engine import check; provider completion and structural measurements do not qualify a rig.

Character readiness checks flag models with excessive connected components, boundary edges, or non-manifold geometry for review. These checks do not repair geometry or prove good skinning, deformation, or texture coverage.
