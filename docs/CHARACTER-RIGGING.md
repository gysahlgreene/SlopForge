# 3D character rigging

Rigging is a separate character stage; prop cleanup does not create a deformable skeleton. New projects include a first-class `character` model type and the `character_3d_pack` recipe. It generates one full-body neutral A-pose concept, runs the selected 3D model workflow, and records a reviewable model on a character asset. Configure the rigging provider with `asset_pipeline.character_rigging_provider` (`blender_rigify` is the current provider).

```sh
slopforge --project ~/UnityProjects/MyGame recipe run character_3d_pack --name moon_scout
slopforge --project ~/UnityProjects/MyGame candidates moon_scout_character
slopforge --project ~/UnityProjects/MyGame approve moon_scout_character 1
slopforge --project ~/UnityProjects/MyGame approve-texture moon_scout_character 1
slopforge --project ~/UnityProjects/MyGame character rig moon_scout_character
```

Provider outputs can be recorded with `slopforge.character_rigging.record_rigging_result()` as typed artifacts on a `character` manifest asset. The result names an already approved source output, a project-relative FBX or GLB, optional PNG pose evidence, skeleton-name mapping, and provider provenance (`name`, `version`, `source`, and `license`). Registered rig and evidence artifacts remain candidates pending human review.

The recorder rejects paths outside the project, missing/empty exports, unapproved source artifacts, unsupported mesh formats, invalid evidence images, and incomplete provider license metadata. It records missing recommended pose evidence without pretending the rig passed deformation checks. Suggested evidence poses are T-pose, raised arms, crouch, leg lift, elbow bend, and shoulder rotation.

## Blender Rigify provider

`slopforge character rig <name> [--source-output model]` runs Blender's bundled Rigify add-on against a ready, approved GLB or FBX model artifact. It fits Blender's human metarig to the model bounds, welds coincident vertices, rejects meshes with open/non-manifold edges, generates automatic weights, renders six review poses, measures vertex displacement, and exports an FBX. Rig and pose artifacts are registered as pending review; the command never approves them.

The provider uses the installed Blender executable and its bundled code; no extra Python package or model weights are installed. The provider reports Blender/Rigify version and GPL-2.0-or-later provenance. Review the installed Blender distribution's notices for the exact bundled add-on terms. See [the provider audit](research/unirig-rigging-provider-audit.md) for why learned UniRig/SkinTokens providers remain uninstalled.

This is a fitting heuristic, not general-purpose automatic rigging. It expects an upright, mostly watertight humanoid whose proportions fit Blender's human metarig; bounds-based fitting cannot place joints reliably for arbitrary anatomy. Vertex welding can alter the mesh slightly. The synthetic Blender integration smoke verifies execution, weighting, export, and pose motion, but does not establish quality on generated SlopForge characters. Inspect the source, rig, and all six pose renders before approval; pose images and nonzero displacement do not establish acceptable deformations or Unity Humanoid compatibility.

The recipe reuses SlopForge's configurable image-to-3D model provider; it does not guarantee anatomical correctness, an animation-ready pose, or a closed manifold. Rigify remains a bounds-fitted humanoid heuristic and rejects open/non-manifold input instead of silently filling holes. Until a representative generated character completes the rigging path and passes deformation review, treat the result as experimental and do not approve it automatically. UniRig/SkinTokens remain optional-provider research because the upstream checkpoint license does not settle commercial training-data rights; see [the provider audit](research/unirig-rigging-provider-audit.md).

The H100 character smoke on 2026-10-04 produced a TRELLIS.2 BF16 scout mesh with 1,189 disconnected components and visible missing surfaces in the three-view review. It was kept unapproved and was not rigged. A Hunyuan3D comparison produced a more complete single-component mesh, but the production Rigify provider rejected both its GLB and prepared FBX with 4,168 open/non-manifold edges after welding. In a separate local diagnostic only, a disposable copy of the script bypassed that guard; Blender auto-weighted and exported the FBX and rendered all six poses. Visual review showed poor shoulder/elbow deformation, so that rig is not suitable for approval. The neutral-gray review renders do not verify texture coverage. Diagnostic files are under `project_hunyuan/rigify-nonmanifold-probe/` in the Downloads test directory. The user-provided ComfyUI-UniRig wrapper was audited but not installed: its isolated CUDA dependency set is unpinned and has not been verified on the live H100's PyTorch 2.14/CUDA 13 environment. The audit explains the compatibility and model-data-rights limits. Issue #14 remains open pending a representative character that passes rigging, deformation, and material review.
