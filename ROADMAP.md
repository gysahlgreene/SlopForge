# Roadmap

Milestones represent qualification gates, not the existence of implementation.
Existing rigging and animation code does not establish repeatability for new assets.
Milestone order and product scope change only with explicit user direction.

| Milestone | Status | Exit evidence |
| --- | --- | --- |
| M0 Foundation and verification | Existing; verification structure being established | Configuration, manifest, CLI, requirements and fixture checks run through `make verify` |
| M1 Concepts and review | Existing; qualification continues | Readable, attributable candidates and preserved selection/rejection/resume states |
| M2 Geometry and mesh preparation | Existing; qualification continues | Retained source, valid exports, budgets, topology and UV checks across representative inputs |
| M3 Reliable materials | Mask regression verified; broader qualification continues | Failed input, fresh input and repeat verified through maps, Blender assembly and review renders; permanent regression protection |
| M4 Unity preview | Next delivery gate | A newly generated reviewed humanoid imports with resolved materials and visibly walks on Play; compact evidence |
| M5 Model and texture quality | After the preview gate | Reviewed gains in face/detail/material quality without breaking qualified processing |
| M6 Broader rig/animation qualification | Existing support; expansion deferred | Representative deformation and animation cases pass separate structural, visual and engine checks |

Work on the active failure first. Later milestone work is justified only when it
is a dependency of the active gate or explicitly requested. Record adjacent ideas
in issues; keep implementation focused.
