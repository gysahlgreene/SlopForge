# Character animation libraries

Reusable source clips live in `ai/animation_libraries/<name>.yaml`. Each clip records an ID, an animation category (`idle`, `walk`, `run`, `jump`, `attack`, `hurt`, `death`, or `interact`), a project-relative FBX/GLB, loop and root-motion settings, and an optional source-to-target bone-name map. Retargeting requires an explicit map with unique target names.

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

The command consumes only approved artifacts. `--rig-type humanoid` asks Unity to create a Humanoid Avatar and fails if Unity cannot produce a valid one. Generic is supported; Humanoid has fixture validation and generated Basalt Avatar/diagnostic-animation evaluation. Third-party motion on generated characters remains unqualified. Unity owns `.meta` files; generated controller and prefab remain pending SlopForge review. `SLOPFORGE_RUN_BLENDER_ANIMATION=1` runs the actual Blender FBX retarget smoke; adding `SLOPFORGE_RUN_UNITY_ANIMATION=1` also runs the Unity Generic import/controller/prefab smoke. These integrations are opt-in; normal tests do not require Blender, Unity, or ComfyUI.

Unity 6000.6.3f1 was exercised against a synthetic Blender Rigify humanoid fixture with a matching animated FBX. SlopForge's explicit bone map produced a valid Humanoid Avatar, imported the clip, and created a controller and prefab. This verifies engine plumbing on a fixture only; Basalt now has user-approved body deformation, a valid Humanoid Avatar and evaluated procedural motion, but has not completed an approved-library retarget plus captured visible Unity playback. See the [reviewed benchmark](media/character-qualification-2026-10/basalt-corrected-humanoid/README.md). The Rigify bounds-fitting provider still expects watertight upright human-like geometry and is not general-purpose. Issue #15 remains open until retargeting and playback are demonstrated on an acceptable generated character.
