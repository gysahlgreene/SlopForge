# Unreal delivery

A project delivers to Unreal Engine instead of Unity with `engine: unreal` under `project:` in `ai/project.yaml`.
Everything up to texture approval is the same. `approve-texture` then publishes, in the asset's output folder:

| File | What it is |
| --- | --- |
| `<name>.fbx` | The model in Unreal's axes: written forward -Y, up Z, in metres, as Unreal's own Blender exports are. It stands on its origin, centred: the origin is the bottom centre of its bounds. No textures are embedded. |
| `Materials/<name>_basecolor.png`, `_emission.png` | Base colour (sRGB) and emission. |
| `Materials/<name>_normal.png` | DirectX normal map (green flipped from the bake's OpenGL). Import it as a normal map without flipping. |
| `Materials/<name>_orm.png` | Packed occlusion (R, white: none is baked), roughness (G) and metallic (B), linear. |
| `Materials/<name>_roughness.png`, `_metallic.png` | The same two channels, separately. |
| `<name>_preview.blend`, `Previews/`, `Source/` | The Blender source, four renders, the concept and the GLB. |
| `unreal.json` | What the export measured: size in metres, and any parts with their joints. |

It writes no Unity material, `.meta` files, Unity smoothness map or prefab, and needs no Unity install.

## Breaking a model into rigid parts

A model that breaks apart when killed (an automaton) is cut into rigid parts at delivery, after its material is
chosen, so nothing upstream is generated again:

1. `slopforge break-views <name> <material>` renders the model's front and back, orthographic, as
   `break_views/view_front.png` and `view_back.png` in the material candidate's folder.
2. Box each part on those renders, as fractions from the top left, in a JSON file:

   ```json
   {"body": "chest",
    "parents": {"head": "chest", "upperarm_l": "chest", "forearm_l": "upperarm_l"},
    "views": {"front": {"chest": [0.37, 0.18, 0.63, 0.36], "head": [0.42, 0.04, 0.58, 0.22]},
              "back": {"chest": [0.38, 0.10, 0.62, 0.36], "head": [0.43, 0.04, 0.57, 0.18]}}}
   ```

   Every part but the body names its parent. The model's left is on the right of the front view and on the left
   of the back view.
3. `slopforge approve-texture <name> <material> --break-parts parts.json`.

**Build it with its hidden faces.** A type with `remove_hidden_faces: true` (`hero_prop`, `prop`) deletes the faces
no ray from outside reaches, which opens the generator's closed mesh: round 25's hand went from 5 open edges to 22,734,
and once broken apart its chest showed a hole where the head had sat. `approve-texture --break-parts` refuses such a
model; build it with a type that sets `remove_hidden_faces: false`.

How the cut is made (`blender/export_unreal.py`):
- SAM 2.1 masks each part from its box on each view (the part masks tool, `tools.parts_host`).
- Each vertex a view sees takes the part whose mask covers it (a smaller mask wins where they overlap). The rest of
  the surface takes the part of its nearest seen vertex, measured over the surface; a loose piece no seed reaches takes
  its nearest seed's part (`mesh_cleanup.rigid_labels`).
- A part's small islands (under a quarter of its largest piece) join the part they touch most, so slivers of one
  part left inside another by a mask's edge do not fly off as debris (`mesh_cleanup.merge_stray_islands`).
- Parts are cut off from the ends of the declared tree inwards, and both sides of each cut are closed with flat caps
  in the colour beside them (`mesh_cleanup.separate_part`).
- A part's joint, its origin, is the middle of its seam with its parent alone, so a hand resting on a thigh does not
  move the forearm's joint. A part that only touches its parent takes the middle of their closest points.
- Every part, and the body, is also written alone as `Parts/<name>_<part>.fbx` with its origin on its joint;
  `unreal.json` lists each part's parent and joint in Unreal centimetres (x, -y, z of Blender's metres).

**Why the model's own views, not its concept:** the first cuts seeded the parts from masks on the approved concept.
A 3/4 perspective concept fits the orthographic model at about 0.88, so limb mask edges landed on the part beside them,
and the concept hid one leg behind a forearm. On round 25's hand both versions left the arms and legs patchy; the
model's own front and back cut all 13 parts cleanly (2026-11-13).

**Limits:** checked on one generated humanoid and a test figure. A part neither view sees (between the legs, inside an
arm) is filled from its neighbours. The cut follows the surface, not a plane, so a cap can be uneven. Moving parts
(a weapon's hinges and slides) are not delivered to Unreal yet; `approve-texture` refuses such a model.
