# Basalt Warden Unity movement preview — 2026-10-09

This is a new, separate playtest of the older textured `Basalt-Warden.glb` requested for Unity movement review. The editable Rigify source remains in Downloads; the project uses the standalone `Basalt-Warden-Unity-Humanoid-v3.fbx` export.

![Unity-retargeted walk cycle, viewed from the side](Unity-Walk-Cycle.gif)

[Idle game-view screenshot](Unity-Idle-GameView.png) · [Side walk pose](Unity-Walk-Side.png) · [Pose measurement report](Unity-Motion-Evidence.json)

Unity 6000.6.3f1 imported the export as a valid Humanoid Avatar. The export contains 160 deform bones and 99 weighted vertex groups. The preview Animator uses looping `HumanM@Idle02` and `HumanM@Walk01_Forward` clips, with the character driven by a CharacterController on a ground plane. A Unity `SkinnedMeshRenderer.BakeMesh` comparison between idle phase 0.20 and walk phase 0.25 measured a maximum vertex displacement of 0.3797 m and a mean displacement of 0.1048 m over the 49,886 Unity mesh vertices.

The GIF samples eight phases from the Unity-retargeted walk clip. Each phase was baked from the Unity skinned renderer and rendered from the review camera; it shows actual retargeted skin deformation, not an unrelated Blender animation. The idle PNG is a direct Game view capture. This proves that the clips play and move the mesh, not that their deformation is visually acceptable.

## Limits

This demonstrates one character and one movement pack. The selected idle animation puts the hands behind the back, making it unsuitable for inspecting neutral arm shape. Arm deformation still needs targeted review and weight refinement. The source review reports 265 non-manifold edges and two boundary edges, so this is not a production-cleared asset. Broader deformation tests remain open.
