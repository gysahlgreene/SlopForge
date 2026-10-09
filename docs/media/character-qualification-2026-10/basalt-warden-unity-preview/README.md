# Humanoid test 1: Unity movement preview

![Humanoid test 1 walking in Unity](Unity-Walk-Cycle.gif)

[Idle screenshot](Unity-Idle-GameView.png) · [Walk pose](Unity-Walk-Side.png) · [Pose measurement report](Unity-Motion-Evidence.json)

Captured in Unity 6000.6.3f1 from the latest arm-fit candidate export. Unity imported it as a valid Humanoid Avatar. The preview uses looping idle and walk clips on a CharacterController over a ground plane; WASD and arrow keys drive movement, with root motion disabled. The GIF is a three-second, 20 fps excerpt from a direct Unity Game view recording, showing the character walking under player control.

A Unity `SkinnedMeshRenderer.BakeMesh` comparison between idle phase 0.20 and walk phase 0.25 measured 0.4052 m maximum and 0.1079 m mean displacement across all 49,886 Unity mesh vertices. This confirms that the retargeted walk moves the skinned mesh; it does not rate the deformation as good.

Arm deformation still needs visual review and refinement. The idle clip places the hands behind the back, so it is not a neutral arm-shape check. Source topology review found 265 non-manifold edges and two boundary edges. This is a movement preview, not a production-cleared character.
