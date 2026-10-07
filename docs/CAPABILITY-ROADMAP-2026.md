# 3D game-asset roadmap (2026-10)

SlopForge now focuses on one outcome: coherent 3D game assets that can be reviewed, processed, and imported into Unity. Concept/material images remain supporting inputs. Sprite, UI, VFX, tileset, and generic prototype-planner work is outside the product scope. Historical experiments are separated under `docs/archive/`, with compact evidence under `docs/media/`; they are not active lanes.

The current pipeline has substantial orchestration and processing infrastructure, but generated visual quality is still the blocker. “Implemented” below describes a software stage, not production-quality AI output.

## Current capability

| Stage | State | Evidence and limitation |
| --- | --- | --- |
| Concept and material inputs | **LIVE VERIFIED, quality unqualified** | Text-to-image inference, references, provenance, and image validation work. The bundled graph is text-only; a successful image call does not prove the concept matches the intended art direction. |
| 3D generation | **LIVE VERIFIED, visually mixed** | Hunyuan3D and TRELLIS.2 routes produce model/material outputs. Mesh holes, disconnected parts, UV or texture defects remain possible. |
| Mesh processing | **STRUCTURALLY VERIFIED** | Blender cleanup, normalization, measurements, multi-view previews, and material export exist. Structural checks do not establish a good-looking model. |
| Character readiness | **STRUCTURALLY VERIFIED** | Reports inspect topology, components, transforms, scale, normals, and required conditions before rigging. They do not prove anatomy or deformation. |
| Automatic rigging | **EXPERIMENTAL** | Rigify and an opt-in isolated SkinTokens provider are available. Basalt now has user-approved body deformation and valid Unity Humanoid diagnostic-animation evaluation. Full input/material qualification, visible Unity footage, and repeatability across future candidates remain open. |
| Skeletal animation and retargeting | **STRUCTURALLY VERIFIED / ENGINE PARTIAL** | Animation library, explicit bone mapping, Blender retargeting, and Unity setup exist. A generated Basalt rig evaluates a procedural diagnostic clip. Known-good third-party motion retargeting remains unqualified. |
| Unity delivery | **ENGINE VERIFIED for selected stages only** | Model/material and synthetic-rig imports have prior checks. Basalt has a valid Humanoid Avatar and Animator-evaluated diagnostic animation; visible Unity playback capture and production motion remain outstanding. |
| Review, provenance, resumability | **STRUCTURALLY VERIFIED** | Typed outputs, candidate approval, reference libraries, quality tiers, recipe dependencies, stage state, and workflow provenance are part of the core product. Human visual approval remains mandatory. |

## Product priorities

1. **#14 — qualify the character input contract and end-to-end rigging.** Split the work into mesh cleanup/readiness, material preservation, rigging/skinning, deformation evidence, and export. Compare providers only on a normalized, readiness-passing textured character. Basalt provides the first reviewed body-deformation and Humanoid-evaluation benchmark. Complete remaining input/material and visible playback evidence before closing the issue.
2. **#15 — qualify skeletal animation and retargeting.** Use known-good source clips, explicit bone maps/rest-pose checks, and Unity playback. Do not report an animation as valid from export or import status alone.
3. **3D visual consistency — make connected assets share a visual language.** Improve reference-conditioned concepts and generation prompts against a small authored asset/style set. Review the resulting models together in a neutral scene before expanding pack breadth.
4. **3D delivery — make regeneration/reimport safe and repeatable.** Record stable asset identity, processing evidence, material assignments, scale/orientation, and Unity import settings. Prioritize this only after the current model contract is stable.
5. **Fresh-idea acceptance run.** After the first four gates, create a small 3D environment/character set from an editable plan and deliver it into Unity with provenance and human review.

The product no longer pursues #9 sprite generation or #16 generic natural-language prototype orchestration. Recipe-based 3D asset sets remain supported. Reference-conditioning interfaces remain useful for 3D, but the Wan image-to-video qualification is historical evidence and does not qualify the 3D reference route.

## Platform priorities

| System | Priority | Reason |
| --- | --- | --- |
| Typed assets, provenance, approval, recipe resume | **KEEP** | These are SlopForge's strongest coordination features; they prevent generated output from becoming an untracked file pile. |
| Local/remote ComfyUI over HTTP | **KEEP** | Service location stays independent from compute profile. No SSH file coupling is needed. |
| Provider isolation | **KEEP** | Keep experimental rigging/model dependencies out of the core environment. |
| Mesh/material/deformation evidence | **HARDEN** | Current failures are quality and readiness failures; show them clearly and prevent bad assets from appearing approved. |
| Stable identity and deterministic Unity reimport | **ADD AFTER MESH CONTRACT** | Avoid duplicate imports and overwriting unrelated Unity assets during regeneration. |
| Contact sheets and turntable review | **SOON** | Contact sheets, multi-view stills and an eight-second diagnostic animation exist; extend those helpers as needed. |
| Generic provider SDK, distributed scheduler, audio, sprite/UI/VFX/tileset lanes | **OUT OF SCOPE** | They do not address the current 3D quality and delivery bottlenecks. |

## Validation standard

- **Structural:** file, topology, component, UV, material, scale, and transform checks.
- **Visual:** inspect neutral-lighting front/side/rear/turntable views and compare related assets together.
- **Deformation:** inspect neutral/A-pose, arms overhead, shoulder rotation, elbow bends, crouch, leg lift, and knee bend.
- **Engine:** verify Unity import settings, materials, scale/orientation, skeleton/bind poses, replacement behavior, and visible animation playback.
- **Human approval:** required after visual/deformation review. Unit tests do not qualify AI output.

See the [implementation audit](archive/release-audit-2026-10-04.md), [3D workflow inventory](WORKFLOWS.md), [character rigging evidence](CHARACTER-RIGGING.md), and [named-source ecosystem research](research/ecosystem-capability-audit.md).
