# Character animation libraries

Reusable source clips live in `ai/animation_libraries/<name>.yaml`. Each clip records an ID, a prototype animation type (`idle`, `walk`, `run`, `jump`, `attack`, `hurt`, `death`, or `interact`), a project-relative FBX/GLB, loop and root-motion settings, and an optional source-to-target bone-name map. Retargeting requires an explicit map with unique target names.

Validate a library, then retarget an approved source clip to an approved character rig:

```sh
slopforge --project /path/to/unity-project animation validate base
slopforge --project /path/to/unity-project animation retarget base walk --character pilot
```

The Blender operation imports the animation armature and approved character FBX, copies mapped pose transforms, bakes the mapped motion, measures maximum mesh displacement across sampled frames, and exports a pending-review animation FBX. The source and target bone local axes must be compatible; bone names alone cannot correct different rest-pose axes, scale, or proportions. The displacement number is diagnostic evidence, not a quality score. Inspect the clip on the actual character before approval.

After approving the rig and desired retargeted clips, build Unity import settings, an `AnimatorController`, and a character prefab:

```sh
slopforge --project /path/to/unity-project animation unity-setup pilot --rig-type generic
```

The command consumes only approved artifacts. `--rig-type humanoid` asks Unity to create a Humanoid Avatar and fails if Unity cannot produce a valid one. Generic is the verified path. Unity owns `.meta` files; generated controller and prefab remain pending SlopForge review. `SLOPFORGE_RUN_BLENDER_ANIMATION=1` runs the actual Blender FBX retarget smoke; adding `SLOPFORGE_RUN_UNITY_ANIMATION=1` also runs the Unity Generic import/controller/prefab smoke. These integrations are opt-in; normal tests do not require Blender, Unity, or ComfyUI.

Unity 6000.6.3f1 was also exercised against the synthetic Blender Rigify export with a matching animated FBX. The export contains the Rigify hand transforms, but Unity's `CreateFromThisModel` import fails with `Required human bone 'RightHand' not found`; no AnimatorController or prefab is produced. This is a verified Humanoid limitation in the current Rigify path, not a successful Humanoid smoke. The Rigify bounds-fitting provider also expects a watertight upright human-like model; it is not a general character-generation system. Issue #15 remains open until Humanoid mapping/retargeting works with a representative rig and the #14 generated-character path is established.
