# Character generation and auto-rigging practices

**Checked:** 2026-10-07. Primary-source research for SlopForge's generated humanoid characters. Vendor guidance is not an independent quality guarantee; recommendations below are identified as such.

## Why the current result fails

TRELLIS.2 is documented as image-to-3D generation for arbitrary assets with detailed PBR materials; its output path extracts a textured mesh/GLB. The project explicitly supports open surfaces and non-manifold geometry. That is useful for appearance, but neither the README nor paper promises a humanoid rest pose, animation-friendly topology, or a character skeleton. A beautiful static result is therefore not necessarily riggable. SlopForge's own H100 character audit records fragmented/non-manifold candidates and poor shoulder/elbow deformation after a separate rigging pass; see [provider-source-verification](provider-source-verification-2026-10.md) and [rigging-provider audit](unirig-rigging-provider-audit.md). This is the expected seam between a general image-to-3D generator and a downstream rigging model, not evidence that more GPU will fix it.

## What Meshy does differently

Meshy's documented workflow combines model-type detection, a rigging tool with manually placeable body markers (including symmetry), preview of binding/weights and pose switching, and direct animation presets. Its own troubleshooting guide identifies non-standard pose, dense or uneven topology, and abnormal proportions as causes of offset bones, weight penetration, and severe deformation; it recommends T/A-pose, remeshing, and standard proportions. The Animate guide specifically recommends generating in T-pose or A-pose. Its [Rigging API](https://docs.meshy.ai/en/api/rigging) says automated rigging works well only for standard bipeds with clear limb/body structure; it does not support untextured or unclear/non-humanoid inputs. URL uploads require textured GLB, the character facing +Z, and a supplied/estimated height; the task-ID path rejects meshes above 300,000 faces. Thus even Meshy's own service does not promise to rescue arbitrary sculpts. Sources: [Meshy rigging guide](https://docs.meshy.ai/en/webapp/guides/3d-model/rigging), [Meshy Animate guide](https://docs.meshy.ai/en/webapp/guides/animate), [Rigging API](https://docs.meshy.ai/en/api/rigging), [Animation API](https://docs.meshy.ai/en/api/animation).

The practical difference is a character-specific path with guided landmark placement and immediate motion feedback, rather than expecting an arbitrary textured object generator and an independent auto-rigger to agree on anatomy. This is an inference from the documented workflows, not a claim about Meshy's proprietary implementation.

## Input and acceptance practices

- **Generate for articulation.** Use a neutral, symmetric A-pose or T-pose with arms and legs clearly separated from the torso. Keep human proportions and visible head, body, arms, and legs. Defer extreme proportions, wings, tails, oversized hair/cloth, and props that obscure joints until the base character passes. Adobe explicitly lists neutral pose, humanoid shape, distinguishable body regions, symmetry, no extra scene objects, no gaps between body parts, and a centered character; it warns large appendages and clothing may fail. Source: [Adobe Mixamo FAQ](https://helpx.adobe.com/creative-cloud/faq/mixamo-faq.html).
- **Qualify the surface before rigging.** Reject holes, floating fragments, self-intersections/non-manifold regions, missing limb surfaces, and ambiguous or merged anatomy. Require a coherent body silhouette and inspect front, side, rear, and three-quarter views. The Meshy guide calls out excessive or uneven topology; the TRELLIS.2 docs show why closed/manifold geometry cannot be assumed. For production deformation, prefer even, animation-suitable topology around shoulders, elbows, hips, knees, and fingers; treat automated remeshing as a preparation step that needs visual reinspection because it can erase silhouette/detail.
- **Protect appearance while preparing geometry.** Keep the untouched textured source and make a separate rig-prep copy. Remesh/reduce only the copy, reproject or transfer texture/materials, and compare multi-view renders before rigging. This is a SlopForge recommendation inferred from the documented remesh/deformation risks and the project's high-detail preservation requirement.
- **Make bone placement reviewable.** Allow manual marker correction where the shoulders, wrists, elbows, groin, or knees are not confidently detected. Run simple raised-arm, T/A-pose, crouch, and leg-lift checks; inspect shoulder and hip intersections and hands/feet. A produced skeleton or successful weight bind is only a candidate, not an approval.
- **Validate in the target runtime.** Unity's character guide recommends modeling bipeds in T-pose, cleaning holes/vertices/hidden faces, and checking scale against its one-unit cube. A Humanoid needs at least 15 bones arranged like a human skeleton; confirm Avatar mapping and T-pose, then test animation playback and material/scale/orientation. Unity distinguishes Humanoid (Avatar mapping) from Generic rigs (arbitrary skeleton with a root node); successful FBX import alone does not establish a valid Humanoid rig. Sources: [Unity creating models for animation](https://docs.unity3d.com/Manual/UsingHumanoidChars.html), [Rig tab reference](https://docs.unity3d.com/Manual/FBXImporter-Rig.html).

## SlopForge recommendation

1. Keep TRELLIS.2 for general assets and textured character concepts, but add a **character-specific generation recipe** that explicitly requests a neutral symmetric A-pose, ordinary humanoid anatomy, visible joint landmarks, and unobstructed limbs. Generate a clean base body first; add bulky armor/props as separate meshes after the base has passed rig/deformation review when the look allows it.
2. Gate rigging on geometry/anatomy checks and a human multi-view review. Try a bounded set of candidates; failed checks remain unapproved with reasons. Preserve source and prep copies, provenance, reports, pose renders, and Unity evidence.
3. Run a small hosted Meshy API bake-off as the integrated benchmark against SlopForge's local SkinTokens/Blender path using the **same accepted source meshes**, not just a hand-picked best result. Record pass rate, marker edits, deformation defects, runtime, texture preservation, export and Unity Humanoid playback. If Meshy materially wins, decide whether its hosted rigging fits the project's cost, privacy, availability, and licensing needs; don't imitate an opaque service without measured evidence.
4. Evaluate open/local riggers only after mesh qualification. UniRig's paper describes skeleton prediction and skinning as difficult for diverse geometry; its authors warn inaccurate skeletons degrade skinning. SkinTokens/UniRig can be useful providers, but neither their papers nor repos establish robust deformation on SlopForge's generated characters. Keep structural checks and human deformation approval regardless of provider. Sources: [UniRig paper](https://arxiv.org/abs/2504.12451), [SkinTokens repository](https://github.com/VAST-AI-Research/SkinTokens).

## Source links

- [TRELLIS.2 official repository](https://github.com/microsoft/TRELLIS.2)
- [Meshy auto-rigging guide](https://docs.meshy.ai/en/webapp/guides/3d-model/rigging)
- [Meshy animation guide](https://docs.meshy.ai/en/webapp/guides/animate)
- [Meshy Rigging API](https://docs.meshy.ai/en/api/rigging)
- [Meshy Animation API](https://docs.meshy.ai/en/api/animation)
- [Adobe Mixamo FAQ](https://helpx.adobe.com/creative-cloud/faq/mixamo-faq.html)
- [Unity 6.6 Rig tab documentation](https://docs.unity3d.com/Manual/FBXImporter-Rig.html)
- [UniRig paper](https://arxiv.org/abs/2504.12451)
- [SkinTokens official repository](https://github.com/VAST-AI-Research/SkinTokens)
