# 3D character rigging

Rigging is a separate character stage; prop cleanup does not create a deformable skeleton. Provider outputs can be recorded with `slopforge.character_rigging.record_rigging_result()` as typed artifacts on a `character` manifest asset. The result names an already approved source output, a project-relative FBX or GLB, optional PNG pose evidence, skeleton-name mapping, and provider provenance (`name`, `version`, `source`, and `license`). Registered rig and evidence artifacts remain candidates pending human review.

The recorder rejects paths outside the project, missing/empty exports, unapproved source artifacts, unsupported mesh formats, invalid evidence images, and incomplete provider license metadata. It records missing recommended pose evidence without pretending the rig passed deformation checks. Suggested evidence poses are T-pose, raised arms, crouch, leg lift, elbow bend, and shoulder rotation.

## Provider status

No automatic rigging provider is currently installed or invoked by SlopForge. The result contract is the boundary for an eventual provider adapter; it is not an inference backend. UniRig and its successor SkinTokens were audited in [the provider report](research/unirig-rigging-provider-audit.md). Both publish MIT code/checkpoint metadata, but the reviewed sources do not establish commercial rights for all training data or reliable deformation on arbitrary generated characters. SkinTokens also has a separate CUDA/Blender-heavy runtime. Do not treat either as a production default until rights, environment isolation, and a real representative-character smoke test are resolved.

The provider audit is research documentation only; no third-party rigging software or model weights were added. A recorded rig must be reviewed in a DCC/game-engine workflow before approval. Structural file checks and the presence of pose images do not establish acceptable skinning or Unity Humanoid compatibility.
