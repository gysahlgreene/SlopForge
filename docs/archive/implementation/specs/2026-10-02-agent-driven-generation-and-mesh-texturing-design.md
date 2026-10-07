# Agent-Driven Asset Generation and Mesh Texturing

## Status

Implemented locally. Unit and Blender integration checks cover prompt pass-through, candidate provenance, material baking, bounds-framed mesh views, and reuse of the saved mesh. A real ComfyUI and Blender material iteration was visually reviewed on `sloptest_relic`; Unity import and a separate in-game prop review remain outstanding.

## Intent

SlopForge is primarily operated by a coding agent working with the user. The agent supplies the creative judgment: it understands the request and project, writes specific prompts, reviews generated images and mesh previews, and iterates. SlopForge supplies reliable, inspectable generation and asset processing: it runs configured tools, preserves candidates and provenance, and exports approved files for Unity.

The workflow should improve two outcomes together:

1. Concept images should reflect the request with the quality of an agent-authored prompt, rather than a short description diluted by a fixed prompt template.
2. A generated prop's material should look coherent on the actual mesh. Review should expose UV stretching, misplaced features, and poor scale before the final Unity asset is approved.

The agent uses its host environment and model. SlopForge does not add an LLM, API key, or provider dependency.

## Current behavior and constraints

- `slopforge/style.py` expands a short description into a long, labeled prompt containing the style pack and taxonomy rules. The exact resulting prompt is recorded on candidates, but there is no direct way to submit an agent-authored final prompt unchanged.
- `processing/comfy_generate.py` assigns the positive prompt to the workflow's first `CLIPTextEncode`. The bundled workflow connects its negative input to `ConditioningZeroOut`, so the script's default negative prompt has no effect in that workflow.
- Model generation uses the selected concept to generate a GLB, then Blender joins and unwraps the mesh with Smart UV Project. A single square base-color image is assigned across the resulting UV atlas. This can stretch or scatter texture details across unrelated islands.
- The implementation builds material candidates from a generated surface image, projects that material across the mesh, bakes the result to the saved UV atlas, and renders front, side, and rear previews. It does not project concept art into the material. Normal maps derive from surface luminance; roughness, metallic, and emission remain prompt-guided heuristics.
- The existing model approval path runs the entire 3D pipeline and writes final outputs in one operation. It does not offer a mesh-level material review and texture-only iteration before final approval.
- Candidate records already capture seeds, prompts, styles, and available model/workflow metadata. The new flow should extend this record rather than introduce a separate provenance system.

## Proposed workflow

1. The agent reads the project's active style, asset type, existing assets, and the requested use. It asks the user only for missing creative choices that materially affect the result.
2. The agent writes a concrete image prompt for the configured model and keeps the user's semantic asset description separately. The prompt may include silhouette, composition, camera, materials, palette, lighting, and useful constraints. The agent uses the style pack as guidance rather than copying every field into the prompt.
3. SlopForge sends the supplied prompt unchanged in agent mode, records it with the semantic description and generation settings, and returns saved candidates. Existing prompt-building remains available for human users and callers that do not supply a prompt.
4. The agent inspects candidates visually, gives a concise comparison grounded in the brief, and proposes targeted prompt changes when another generation is useful. The user remains the final approver of the concept and final asset.
5. For a selected 3D concept, SlopForge generates and cleans the mesh once. It creates material candidates, applies them using mesh-aware object-space projection rather than stretching one image over unrelated UV islands, bakes the result to the existing UV atlas for ordinary Unity material use, and renders a review preview of the textured mesh.
6. The agent and user review that mesh preview. Texture iterations reuse the generated mesh and UVs; they do not rerun Hunyuan3D unless the concept or geometry changes. Only an approved result replaces final Unity outputs.

## Design decisions

### Agent owns creative prompt authoring

Add an explicit prompt input to image and model concept generation while retaining the semantic description as a separate required field. When supplied, the prompt is the exact positive text sent to ComfyUI. When omitted, current style-aware prompt construction remains the fallback. Candidate and manifest provenance store both values distinctly, together with the resolved workflow/model and seed where available.

This keeps creative prompt work with the agent already present in the workflow and makes prompt A/B comparisons possible. SlopForge remains responsible for safe paths, candidate validation, stage execution, and provenance. It does not silently rewrite an explicit prompt. Prompt inputs must be passed as data, not interpreted by a shell.

The bundled workflow's negative conditioning should be represented accurately in provenance and user-facing guidance. A future workflow may consume a negative prompt, but this design does not add a negative-prompt control until a configured graph actually uses it.

### Mesh-aware material application

Use a generated, surface-only material image as a repeating surface source. Apply it in Blender with object-space box projection so the texture scale follows the model and does not depend on arbitrary UV island placement. Bake the projected base color into the mesh's existing UV atlas so exported FBX materials remain usable in a standard Unity project without a custom shader.

Keep the material source, baked maps, and preview as candidate outputs until the user approves. Keep the current simple heuristic treatment for normal, roughness, metallic, and emission maps in the initial iteration; do not claim they are physically accurate. Provide a small per-asset tiling adjustment because object scale and intended material grain vary. Use a documented default and record any adjustment.

Object-space surface projection handles material coverage and scale. It does not guarantee exact transfer of semantic features such as a readable screen, logo, or front-panel arrangement from the concept view. The first implementation should render the real mesh from a useful review angle and clearly reveal when those details are missing or misplaced. If that remains the main quality gap after the baseline works, evaluate a separate concept-projection or decal-baking step using the selected concept image.

### Review and iteration

The mesh preview is a review artifact, not an automatic quality score. It should use a neutral, repeatable studio setup and show enough of the model to judge texture scale, seams, and visible features. Save its camera/render settings with the stage output so repeated candidates can be compared fairly.

The iteration boundary is the material stage: retain the generated GLB, cleaned mesh, and UVs; regenerate or retune the material and rebake. Failures in material generation or baking must leave the approved Unity outputs intact and keep the error and candidate provenance available for inspection.

## Scope

Included:

- Agent-first operating instructions and examples, with the agent as prompt author and visual reviewer.
- An explicit exact-prompt path alongside the existing automatic style prompt.
- Separate storage of semantic description and actual generation prompt.
- Mesh-aware material projection, baking to standard UV textures, and textured mesh previews.
- A review/iteration path that reuses generated geometry and protects approved outputs.
- Documentation of what the bundled workflow consumes, what it ignores, and the limits of heuristic PBR maps.

Not included:

- An LLM service, prompt API provider, or automatic AI quality judge inside SlopForge.
- Replacing Hunyuan3D or adding a new generation dependency.
- Guaranteed seamless textures, physically accurate PBR maps, or exact recovery of every concept detail on all sides of a mesh.
- Unity scene/prefab authoring or custom Unity shaders.
- Automatic user approval. The agent may recommend; the user chooses.

## Alternatives considered

1. **Keep the current prompt builder and tune its template.** Smallest code change, but the agent still cannot control the actual positive prompt directly and prompt experiments remain entangled with static formatting. Retain the builder as a fallback, not the agent path.
2. **Generate or paint a UV atlas directly.** This can place object-specific detail precisely when it works, but current image models are unreliable at respecting UV island layouts. It also couples texture generation tightly to Blender atlas output. Defer until mesh previews show that general material projection is insufficient.
3. **Use object-space projection and bake.** Recommended first texture path. It uses Blender's existing mesh processing and UVs, reduces stretching, exports ordinary textures, and makes texture-only iteration cheap. It cannot by itself preserve all semantic detail from a single concept view; the preview makes that limitation visible and informs whether a later projection/decal pass is justified.

## Acceptance criteria

- An agent can pass a detailed prompt and SlopForge sends that positive prompt unchanged to the configured workflow.
- The manifest keeps the semantic description distinct from the exact prompt and records the resolved model/workflow and seed where available.
- Existing callers without an explicit prompt retain the current prompt-building behavior.
- On the alien terminal example and at least one materially different prop, the generated surface reads at a consistent scale across major mesh faces, with no severe UV-island stretching in the Blender preview.
- The baked texture is connected to the exported FBX material and remains available as an ordinary Unity image asset.
- A material-only iteration reuses the same generated mesh and leaves any previously approved Unity output untouched until final approval.
- A failure during texture generation or baking is visible in candidate/stage metadata and does not mark a partial result ready.
- Agent instructions tell the agent to inspect the actual mesh preview, compare it to the request, and ask the user before final approval.

## Verification approach

Use focused unit checks for exact prompt pass-through, fallback prompt construction, distinct prompt/description provenance, and failure-state output preservation. Use the existing Blender pipeline on the alien terminal and a second prop to create previews and baked textures. Visually inspect those outputs in Blender and Unity; file validation alone cannot establish texture quality. Compare prompt candidates with the same workflow and seed where the backend permits it, then review images against the asset brief.

## Risks and limits

- ComfyUI workflows differ in prompt nodes and conditioning behavior. Exact prompt support must target the configured graph's actual positive node and fail clearly when the graph cannot accept it.
- Object-space box projection and baking can expose seams on unusual topology or thin/overlapping geometry. The preview and a per-asset tiling adjustment provide the first diagnostic loop; specialized UV editing remains out of scope.
- Generated surface images may still contain object-like marks despite a surface-only prompt. Candidate review remains necessary.
- A front-facing concept and a generated 3D mesh can disagree. Surface tiling will not fix semantic geometry or transfer all control-panel details.
- The supplied project may use an empty or highly specific style pack. The agent must prioritize the user's brief and relevant style guidance, rather than treating empty prompt sections as content.
