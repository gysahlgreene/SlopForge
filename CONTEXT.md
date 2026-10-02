# SlopForge Asset Creation

This context defines the creative and review terms shared by agents, users, and SlopForge while creating game assets.

## Language

### Request and concept

**Asset brief**:
A concise statement of the requested asset and its intended use.
_Avoid_: Prompt, generation text

**Generation prompt**:
The visual instructions an agent writes for an image-generation model, informed by the asset brief and project art direction.
_Avoid_: Description, semantic description

**Concept candidate**:
A generated image proposing the asset's appearance before 3D processing.
_Avoid_: Texture candidate, final asset

**Concept selection**:
The user's choice of a concept candidate to continue into 3D processing.
_Avoid_: Approval, final approval

### Mesh appearance and review

**Concept detail**:
A design feature in the selected concept, such as a screen, panel, or light. The mesh should carry it as geometry or a deliberately authored decal; the generated base material does not copy the full concept image.
_Avoid_: Surface material

**Surface material**:
The generated color and surface texture projected over the mesh and baked into its UV map.
_Avoid_: Concept detail, texture map

**Texture candidate**:
A proposed material treatment applied to the generated mesh for visual review.
_Avoid_: Concept candidate, texture source

**Mesh preview**:
A rendered view of a texture candidate on the mesh, used to assess material scale, coverage, seams, and how the mesh geometry carries the design.
_Avoid_: Concept image, final asset

**Final approval**:
The user's decision that a reviewed mesh preview is ready to export into the Unity project.
_Avoid_: Concept selection
