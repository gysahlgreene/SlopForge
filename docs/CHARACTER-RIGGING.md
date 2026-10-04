# 3D character rigging

Rigging is a separate character stage; prop cleanup does not create a deformable skeleton. Provider outputs can be recorded with `slopforge.character_rigging.record_rigging_result()` as typed artifacts on a `character` manifest asset. The result names an already approved source output, a project-relative FBX or GLB, optional PNG pose evidence, skeleton-name mapping, and provider provenance (`name`, `version`, `source`, and `license`). Registered rig and evidence artifacts remain candidates pending human review.

The recorder rejects paths outside the project, missing/empty exports, unapproved source artifacts, unsupported mesh formats, invalid evidence images, and incomplete provider license metadata. It records missing recommended pose evidence without pretending the rig passed deformation checks. Suggested evidence poses are T-pose, raised arms, crouch, leg lift, elbow bend, and shoulder rotation.

## Blender Rigify provider

`slopforge character rig <name> [--source-output model]` runs Blender's bundled Rigify add-on against a ready, approved GLB or FBX model artifact. It fits Blender's human metarig to the model bounds, welds coincident vertices, rejects meshes with open/non-manifold edges, generates automatic weights, renders six review poses, measures vertex displacement, and exports an FBX. Rig and pose artifacts are registered as pending review; the command never approves them.

The provider uses the installed Blender executable and its bundled code; no extra Python package or model weights are installed. The provider reports Blender/Rigify version and GPL-2.0-or-later provenance. Review the installed Blender distribution's notices for the exact bundled add-on terms. See [the provider audit](research/unirig-rigging-provider-audit.md) for why learned UniRig/SkinTokens providers remain uninstalled.

This is a fitting heuristic, not general-purpose automatic rigging. It expects an upright, mostly watertight humanoid whose proportions fit Blender's human metarig; bounds-based fitting cannot place joints reliably for arbitrary anatomy. Vertex welding can alter the mesh slightly. The synthetic Blender integration smoke verifies execution, weighting, export, and pose motion, but does not establish quality on generated SlopForge characters. Inspect the source, rig, and all six pose renders before approval; pose images and nonzero displacement do not establish acceptable deformations or Unity Humanoid compatibility.

Issue #14 remains partial: SlopForge still lacks a dedicated 3D identity/model-generation recipe and representative generated-character validation. Rigify does not generate the character model.
