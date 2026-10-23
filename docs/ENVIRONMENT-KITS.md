# Modular environment kits

`slopforge init` installs `starter_environment_kit`, a recipe that composes modular floor, wall, corner, ceiling, doorway, door, column, pipe, terminal, crate, and surface assets. It uses the existing atomic 3D/model pipelines and supporting material-image workflow, so configured providers, references, and local or remote ComfyUI remain unchanged.

Start with one candidate per child to keep the first pass inexpensive:

```sh
slopforge --project ~/UnityProjects/MyGame recipe run starter_environment_kit \
  --name lunar_refinery --quality-tier draft --reference-library environment/lunar-refinery
```

Review and approve child assets through the normal candidate commands. Resume the pack after each approval; successful approved children remain intact while unfinished children continue:

```sh
slopforge --project ~/UnityProjects/MyGame recipe resume lunar_refinery
slopforge --project ~/UnityProjects/MyGame environment-check lunar_refinery
```

Each module can declare `target_size: [x, y, z]` in metres, with `null` for an axis that keeps its generated proportion (a wall is `[3, null, 3]`, a floor `[3, 3, null]`, a column `[null, null, 3]`). Mesh preparation turns the long horizontal side onto the declared axis, scales declared axes exactly, scales free axes by the mean of the declared factors, and prints the axis stretch ratio; modules without a target are normalised to a largest side of 1.0 like other assets. A standalone structure or prop gets the same real sizing with `generate --target-size=-,-,3.2` (3.2 m tall, other axes in proportion), and then stands on a bottom-centre pivot. A stretch ratio well above 1 means the concept's proportions did not match the module, so revise the concept instead of accepting a distorted module. See the [structure showcase](media/structure-showcase-2026-10/README.md) for a five-module kit.

A module's `pivot` (or the kit's default `pivot`) places its origin in the exported FBX:
- `bottom_center` for walls, doorways, corners and columns, which stand on their origin;
- `top_center` for floors, whose walkable top sits at it;
- `center` (the default) keeps the bounds centre.

Unity keeps the FBX origin as the model's pivot. On 2026-10-22, centre-pivoted modules placed at ground level sank
halfway into it. The size and pivot join the model's assembly-stage settings, so changing either rebuilds the
model rather than reusing it. Sized modules are inspected at real scale, so a 3 m module is not flagged as larger
than the normalised size.

Inspection also records `footprint_quadrants`: how much of each quarter of the module's top-down footprint holds
geometry, in the order +X+Y, −X+Y, −X−Y, +X−Y. An L-shaped corner leaves one quadrant nearly empty, which shows
which way it opens. The 2026-10-22 stone corner measured 0.69, 0.0, 0.69 and 0.90.

## Shared kit material

Modules generated one at a time do not match: in the first assembled courtyard the columns came out sandy and the
walls grey. A kit can name one texture child as its material:

```yaml
kit_constraints:
  material: {source: stone, roughness: 0.75}   # the kit's tint and finish
children:
  - id: stone
    type: texture
    generation_prompt: Seamless, front-facing, evenly lit surface of weathered grey granite ...
```

**Order of approval:** approve the texture first (`approve <run>_stone <number>`), then each module. Approving a
module before its kit texture stops before any inference and names the texture to approve.

**What happens to each module** declared in `kit_constraints.modules`, in its mesh-aware material stage:
- **Tint:** its base colour keeps its own generated colours, weathering and lightness. Only its average CIELAB
  a and b, its tint, move to the kit texture's. UV padding is left as it is.
- **Finish:** with `roughness`, its roughness map moves to that mean, keeping its own variation softened to 60%.
  UV padding takes the declared value.

The kit texture's hash, the tint shift and the roughness join the module's assembly-stage settings.

**Why tint, not a baked swatch:** until 2026-10-23 each module's base colour was re-baked from the seamless
swatch. That made modules match, but flattened them to the same light grey and read as clay. On the same meshes
in Unity, the owner chose each module's own colours with the tint matched
([comparison](media/kits-hue-match-2026-10/README.md)).

**Why a finish:** in M2-v1 run K1, TRELLIS decoded the flagstone floor at roughness 0.22 beside walls at 0.67, so
Unity rendered a glossy floor that reflected the blue sky.

**Limits:**
- Lightness still differs between modules: K2's stone modules averaged L 48–60 against the texture's 73.
- The tint of an invented back face is matched like the rest, but its pattern stays invented.

## Layouts and the Unity test scene

A recipe's `layouts` place modules to test that they work together. Each placement gives:
- `module`: a 3D child;
- `position`: `[x, z]` or `[x, y, z]` in metres on Unity's axes (y up);
- `rotation`: quarter turns about the vertical, or `auto` for a corner, which turns it so its open side faces the
  layout's centre.

`init` installs `stone_ruin_kit`, which has a `courtyard` layout and a `corner_joint` layout. Once every module in
a layout is published with `approve-texture`, build its scene:

```sh
slopforge --project ~/UnityProjects/MyGame environment-scene ruin courtyard
```

What it does in Unity (batch mode):
- **Prefabs:** each module becomes a prefab under `Assets/Art/Generated/Prefabs/<run>/`. It gets an identity
  root, which hides the FBX axis rotation, a mesh collider and static flags (batching, occlusion, reflection
  probes). Lightmap contribution is left off, because it needs lightmap UVs that would change the published import
  settings.
- **Scene:** it places the layout in `Assets/Art/Generated/Scenes/<run>_<layout>.unity` and renders four views.
- **Checks:**
  - each module stands at its placement height for its pivot;
  - it has a collider and is static;
  - neighbouring modules leave no gap wider than `snap_tolerance`.
- **Report:** `ai/assets/environment_scenes/<run>_<layout>.json` and `.png`. The command exits nonzero when a
  check fails.

A corner's open side is read from the placed mesh, so it needs no assumption about the FBX axes.

**Joints:**
- **Declared thickness:** declare walls and doorways with their thickness as part of `target_size`, such as
  `[3, 0.75, 3]`, and give the corner the same `arm_thickness`.
- **Why:** the corner's arms lie inside its bounds, so Blender finds its open side, measures each arm, and rescales
  across the arms only, keeping the outer bounds exact. Generated stone corners had arms of 0.98–1.16 m against
  walls of 0.74–0.88 m, so in the first `corner_joint` scene the corner stepped out past the walls.
- **Placement:** with one thickness, place walls inside a cell edge with their outer face on it, as the corner's
  arms are, and they continue the corner flush.
- **Check:** `environment-check` compares each published corner's measured arm thickness with the declared one.
- **Wedges are retried:** inspection records `arm_taper`, each arm's thickness across the middle of its far half
  over that across its end.
  - An L's arms are even slabs: every corner published by 2026-10-23 measured 1.00–1.01.
  - In M2-v2 run T2 a timber corner came out a wedge, filled diagonally inside its L. It passed the open-quarter
    check because its open quarter was empty. Its arms measured 1.72 and 1.82, and the kit check failed it on
    0.27 m arms.
  - Above 1.25 the candidate fails as `module_taper`, and the next seed is tried, as for a solid block. The 1.25
    limit is set from that evidence; the owner has not set it.
- **Show the arms' tops:** timber corners seen from eye level, looking straight into the L, mostly reconstructed as
  wedges or solid blocks.
  - On T2's six seeds through the shape stage: one solid block, four wedges, and one L stretched past 1.3.
  - Seen from a high angle with the flat tops of both arms showing: three Ls and three solid blocks
    ([evidence](media/kits-provisional-2026-10-v3/QUALIFICATION-RECORD.md)).
  - The timber kit's corner asks for that view. The stone and sci-fi corners passed on eye-level views.

**Stretch:**
- **What it is:** sizing a module to its declared size stretches it when its concept's proportions differ. Blender
  records the ratio (`axis_stretch`).
- **The limit:** `max_stretch` (kit-wide or per module) fails a module that stretches past it, as `module_stretch`.
- **No retry:** another mesh seed from the same concept would stretch again, so approval stops and asks for a
  concept closer to the module's proportions. A doorway concept on 2026-10-22 stretched 1.45 to fit 3 × 3 m.
- **In `environment-check`:** the limit is applied too.
- **The canvas:** a child's `aspect` (`square`, `portrait` or `landscape`) sets its concept canvas. Corners use
  landscape. Sci-fi walls use portrait: on M2-v1 run S1's six seeds, square-canvas walls reconstructed 1.27–1.64
  times wider than tall and portrait ones 1.15–1.28. Stone and timber walls stayed within 1.15 on square canvases.
  - **Concept outlines don't predict it:** S1's wall concept outline was 1.09 tall for its width, but its mesh was
    1.49 times wider than tall.
  - **Measure the mesh instead:** compare a change on fixed seeds through TRELLIS's detailed shape, built from the
    RGBA cut-out the pipeline sends ([evidence](media/kits-provisional-2026-10-v2/QUALIFICATION-RECORD.md)).

**Budgets:**
- **Declaring them:** a module rule can declare `face_budget`, the faces it is decimated to on the GPU and in
  Blender, and `texture_size`, its maps' resolution (256 to 4096). Otherwise it takes its asset type's budget.
  Architecture's is 60,000 faces and 4096² maps on the final tier; a flat 3 × 3 m floor tile used 59,988.
- **Reporting:** `environment-check` reports each module's faces and map texels (base colour, normal,
  metallic/smoothness and emission), and the kit's totals under `budgets`.
- **Not yet:** a kit-wide limit waits for the owner's M2 criteria
  ([#94](https://github.com/gysahlgreene/SlopForge/issues/94)).

`kit_constraints` lives in the recipe definition and is snapshotted into each recipe run. It sets a grid, tolerances, maximum module dimensions, pivot expectations, and optional snap axes per child. `environment-check` reads the saved Blender measurements for bounds, dimensions, origins, and applied transforms. It writes a typed validation artifact at `ai/assets/environment_checks/<name>.json`; incomplete packs produce a partial report and a nonzero exit, while failed geometry checks remain visible in the manifest.

The checks report modular measurements; they do not rescale or rotate geometry, apply materials to models, or assemble a room scene. Intended front-facing direction and visual seams still need review in Blender/Unity. Use the supplied grid constraints as a starting profile and adjust them per kit rather than treating one grid size as universal.
