# 3D character rigging

**Current references:** [Humanoid test 1](media/character-qualification-2026-10/basalt-warden-unity-preview/README.md) demonstrates Unity walk playback; arm deformation and source topology remain under review. The [diagnostic humanoid benchmark](media/character-qualification-2026-10/basalt-corrected-humanoid/README.md) has approved body deformation and evaluated animation. Rigging providers remain experimental; broad deformation and production qualification are outstanding.

## Animation-readiness gate

### Source geometry review gate

Before approving structural readiness for a new rig, compare the retained mesh with the approved front, left, and rear design images. The source review is a separate human geometry decision. Blender's `front`, `side`, `rear`, and `three_quarter` renders are evidence of the candidate; they do not replace the three approved concepts. If the generation route used one image, the report records `single_image`; the review process does not turn it into multi-view conditioning.

Capture at least one concept crop and one close-up rendered from the retained Blender candidate for every concept-critical region. Review in neutral lighting and decide whether the modeled forms match the concepts before material appearance review. The selected model, approved concepts, four model renders, inspection report, every linked texture map, and close-up pairs are hashed. Missing or corrupt evidence leaves the report incomplete and cannot be approved.

```sh
slopforge --project ~/UnityProjects/MyGame character source-review moon_scout_character \
  --concept-view front=ai/references/moon_scout/front.png \
  --concept-view left=ai/references/moon_scout/left.png \
  --concept-view rear=ai/references/moon_scout/rear.png \
  --critical-region helmet \
  --concept-crop helmet=ai/references/moon_scout/helmet_detail.png \
  --model-closeup helmet=Assets/Art/Generated/Characters/moon_scout_character/Previews/helmet_closeup.png
slopforge --project ~/UnityProjects/MyGame review
slopforge --project ~/UnityProjects/MyGame character classify-source moon_scout_character <review-id> \
  --finding <finding-id>=intentional
slopforge --project ~/UnityProjects/MyGame character approve-source moon_scout_character <review-id> --confirm
```

Repeat `--critical-region`, `--concept-crop`, and `--model-closeup` for each region. The close-up must be a retained render of the same source model, not a material image. The report starts with component and topology findings marked `unclassified`; classify each as `intentional`, `repairable`, or `unresolved`. Reclassification is appended to manifest history. `repairable` and `unresolved` findings block rigging until the geometry is repaired and reviewed in a new evidence package. A disconnected component is not automatically debris; diagnostic positions and bounds are evidence for human classification, not proof or automatic repair.

Approval is tied to the full reviewed SHA-256 set. Changing the source model, concepts, preview, inspection report, close-ups, conditioning image, or material map makes that decision stale. Create a new review after changes. Source approval does not approve material appearance, alter asset readiness, clear topology findings, or establish deformation, performance, Unity playback, or pipeline qualification. Model and node identity, dependency versions, and license terms remain `unknown` when the retained provenance does not establish them.

The readiness report records structural measurements separately. It can be run before visual approval, but its approval cannot authorize rigging without a current approved source review. The source review also does not replace the explicit readiness approval shown below.

Run deterministic mesh inspection after approving a character model and before requesting a rig:

```sh
slopforge --project ~/UnityProjects/MyGame character readiness moon_scout_character
slopforge --project ~/UnityProjects/MyGame inspect moon_scout_character
slopforge --project ~/UnityProjects/MyGame character approve-source moon_scout_character <review-id> --confirm
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

Rigging is a separate character stage; prop cleanup does not create a deformable skeleton. New projects include a first-class `character` model type and the `character_3d_pack` recipe. It generates one full-body neutral A-pose concept, runs the selected 3D model workflow, and records a reviewable model on a character asset. When the compute profile sets `workflows.character_image` (the H100 profiles do), concepts are conditioned on the OpenPose skeleton named by the character type's `pose_control` (`workflows/inputs/character_a_pose_openpose.png`: arms 45° down, hands clear of the hips). Prompt text alone did not hold the pose: an unconditioned stylized-hero brief gave hands on hips on both seeds tried, and a realistic brief arms about 20° out. With the skeleton both came out in the skeleton's A-pose. A stocky dwarf brief ignored it at every strength tried (0.65–1.6) and with stocky or T-pose skeletons, though its fists stayed clear of the belt. The skeleton's hash is part of the concept's conditioning identity. Configure `asset_pipeline.character_rigging_provider` as `blender_rigify` or `skintokens`. SkinTokens runs from a separately configured Python environment, checkout, and checkpoint; `character provider-setup skintokens` applies only the pinned, hash-checked compatibility edit to that checkout.

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

With `blender_rigify` selected, `slopforge character rig <name> [--source-output model]` runs Blender's bundled Rigify add-on against a ready, approved GLB or FBX model artifact:

1. **Skeleton.** It uses Rigify's basic human metarig (spine, neck, head, arms, hands, legs, feet), without the full face rig and finger chains whose many small bones fell outside generated heads and hands.
2. **Joint placement.** Joints come from the mesh itself, assuming an upright A-pose facing −Y: horizontal slices find the gap between the legs (crotch), the arms beside the torso (arm clusters), and the torso centre line; elbows, wrists, knees and ankles are snapped to the local limb centroid so bones lie inside the body. When the arms cannot be separated from the torso (arms touching the body), it falls back to scaling the metarig to the mesh bounds and says so in the report.
3. **Weights.** Bone heat runs on a watertight voxel proxy, trying finer to coarser voxel sizes until every proxy vertex is weighted; the weights are transferred to the real mesh by nearest-surface interpolation. Raw generated meshes are open, multi-shell surfaces on which bone heat finds no solution, and a too-fine proxy keeps their inner shells as separate hollow layers.
4. **Clean-up.** Weights are capped to the influence limit and remapped to body deform bones. Forearm and hand weight is kept only on vertices connected to the arm along the surface within a limb radius, so clothing beside a hanging hand does not follow it. Faces that fuse a hand or forearm to the thigh, pelvis or spine (common where A-pose hands touch the body) are deleted and counted in the report.
5. **Evidence.** It renders six review poses from a three-quarter view with key, fill and rim light (rest, raised arms, crouch, forward leg lift, forward elbow bend, shoulder rotation), measures vertex displacement and exports an FBX with deform bones only. The report maps Unity Humanoid bones to those exported `DEF-` bones.

Rig and pose artifacts are registered as pending review; the command never approves them.

### Mesh preparation for characters

Character asset types require a closed (manifold) mesh. Raw image-to-3D characters are open, multi-shell surfaces, so mesh preparation runs `--local-repair`: it deletes components hidden inside the body (inner duplicate shells), then removes only the faces around non-manifold edges and pinched vertices and refills every hole, widening the area around holes that will not close. The rest of the surface is untouched. A full voxel remesh is used only if local repair fails, because it melts faces, pockets and folds into clay.

### Motion-capture preview

`blender/retarget_mocap.py` retargets a BVH or FBX clip onto the rig's `DEF-` skeleton (the bones exported to Unity) or a SkinTokens rig's Unity Humanoid bones, choosing the CMU mapping that matches the rig. Limb bones follow their source bone's world-space rotation from the actor's rest pose; feet and toes follow it from the actor's average foot orientation during that side's stance, because skeletons put the toe joint at different points (CMU at the ball of the foot, SkinTokens further forward and lower) and copying the ankle-to-toe direction held generated feet 12–40° toe-up and folded their boots; torso, neck, head and end bones follow it from the actor's average posture over one stride, because the BVH zero pose is a synthetic straight-spined T-pose and the actor's habitual posture (CMU 08_01: neck about 9° forward) made characters' heads jut. Mocap rest poses (usually T-pose) differ from generated A-pose characters, so limb bones (upper arm, forearm, thigh, shin) are first swung onto the source bone's rest direction, measured joint to joint because file bone tails are guesses. Torso, neck, clavicle and end bones are not swung: skeletons place those joints differently (CMU's clavicle rises 22° from mid-chest, a SkinTokens clavicle falls about 30° from the neck), and copying that direction made characters shrug through the walk; the clip is turned to face the character, scaled to its hip height, optionally kept in place, and one gait cycle (left foot plant to plant) is recorded for looping. Hands follow the forearms because mocap wrist data is noisy. `blender/render_turntable.py <walk.blend> <frames> --animate` plays that cycle at capture speed on a lit turntable with the lowest foot planted. After baking, three corrections keep the motion readable on generated bodies. The actor is turned to face along its own hip travel over the stride, not its rest facing (CMU 07_02 walks about 30° off it, which twisted the legs against the pelvis). Each arm swings outward by a constant angle when the actor's hang angle would drive the forearm and hand through the character's own hips or holsters (16–21° on the slimmer style characters, 4–7° on the dwarf; `arm_clearance_offset_degrees`). Each leg swings outward slightly when a foot would reach the midline (`stance_widening_degrees`), keeping the foot's world orientation. Humanoid finger chains get a relaxed curl (`relaxed_finger_bones`), because mocap wrists and fingers are not retargeted.

For walk previews use the [CMU Graphics Lab Motion Capture Database](http://mocap.cs.cmu.edu/) clip **07_02**. Clips were compared on one detected stride: a natural walk straightens both knees in stance and bends the elbows moderately. 07_01–07_03 were the only candidates whose knees both reach 0°; 07_02 has a 1.13 s stride, elbows 5–45° and a slight forward lean. 08_01, used earlier, never straightens the right knee (15°), bends the elbows up to 66° and leans back; 16_15, 35_01, 35_02 and 39_01 keep the knees bent 7–18°, and 02_01 has no detectable stride; CMU states the data is free for all uses and may be included in commercial products but not resold directly. Clips are downloaded into the ignored `private/` directory, not committed.

The provider uses the installed Blender executable and its bundled code; no extra Python package or model weights are installed. The provider reports Blender/Rigify version and GPL-2.0-or-later provenance. Review the installed Blender distribution's notices for the exact bundled add-on terms.

This is a landmark heuristic for upright A-pose humanoids, not general-purpose automatic rigging: unusual anatomy, props or capes, crossed or touching limbs, and non-humanoid characters need review or another provider. Deleting fused contact faces leaves small openings where hands touched the body. Inspect the source, rig and all six pose renders before approval; pose images and nonzero displacement do not establish acceptable deformations or Unity Humanoid compatibility.

SkinTokens is also available as an opt-in provider. It uses a separately configured runtime and checkpoint and remains experimental. To run SkinTokens on a GPU host, set `tools.skintokens_host` to an SSH host (key-based, non-interactive) and give `skintokens_python`, `skintokens_checkout` and `skintokens_checkpoint` as absolute paths on that host, typically in the GPU compute profile together with `character_rigging_provider: skintokens`. Preflight, `character provider-setup skintokens` and the seeded launcher then run there from the same audited `slopforge/skintokens_runtime.py`, streamed to the host's SkinTokens Python; the source is uploaded to a temporary directory, and the output and log come back to the project (`ai/logs/skintokens/`). The launcher drops HTTP proxy variables, because `demo.py` talks to a local Blender helper over HTTP and a host proxy intercepted it. SkinTokens decodes with sampling, so runs differ; the provider passes `--use_postprocess`, which masks predicted weights by voxel reachability from each joint. Without it, one of two runs on the same realistic character weighted about 1,000 trouser vertices to a fingertip (dominant bone 0.59 body-heights away), and the legs tore in the walk; two postprocessed runs had no such vertex. The post-processor then removes weights that jump across the skeleton: a patch of vertices led by one bone whose every mesh neighbour is led by a bone more than five steps away takes its neighbours' weights, and each vertex drops influences more than five bones from its dominant one (`relabelled_isolated_vertices`, `pruned_distant_influences`). Hands hanging against a holster or belt otherwise tied those parts to a fingertip, and they tore into long spikes when the arms lifted. With `--use_transfer`, SkinTokens keeps the source surface and UVs; `blender/skintokens_character.py` then reuses the source material as-is (`material_transfer: reused_source_material`) and only falls back to a selected-to-active rebake when UVs differ, because the rebake missed rays on folds and pockets and left dark dots. Each output still needs source review, deformation review, and the intended engine import check; provider completion and structural measurements do not qualify a rig.

Character readiness checks flag models with excessive connected components, boundary edges, or non-manifold geometry for review. These checks do not repair geometry or prove good skinning, deformation, or texture coverage.
