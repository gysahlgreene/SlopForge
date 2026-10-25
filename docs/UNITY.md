# Unity projects

Unity is an output target, not a generation dependency. Initialize an existing Unity project with `slopforge init /path/to/project`; its `Assets/` directory must already exist. The standalone engine stays installed outside that project. Initialization creates:

- `ai/project.yaml`, `ai/assets/manifest.json`, and `ai/asset_types/`.
- `ai/styles/default/style.yaml` with approved/candidate reference folders.
- `ai/workflows/` for project-specific workflow overrides.
- `Assets/Art/Generated/` folders for supported asset types.

SlopForge writes ordinary GLB, Blend, FBX, and material files under the configured Unity `output_root`. Unity owns `.meta` files. Character animation setup can create a controller and character prefab through an explicit command. Weapons, and asset types that set `unity_prefab: true`, publish a prefab with convex colliders, a Rigidbody, sockets and an Animator a game script can drive ([Weapons](WEAPONS.md#the-prefab-a-game-uses)). `environment-scene` assembles a kit layout and `scene-render` a recipe's showcase scene, both for review; SlopForge does not build game levels.

The Unity Editor may be closed during generation. Open the project afterward to import the new files and let Unity create `.meta` files.

Texture approval creates a Unity Lit material for the Built-in Render Pipeline or URP. HDRP and custom render pipelines currently stop with an explicit unsupported-pipeline error rather than receiving a mismatched shader.

An approved asset keeps its Unity identity when it is published again. Its files have fixed paths under the asset's name. Approval replaces them in place and leaves their `.meta` files alone, and it reuses an existing material, so the asset keeps its GUIDs. Scene and prefab references therefore keep pointing at the new version. A new asset name gives new files with new GUIDs and leaves the old asset untouched. After each import, Unity reports for the FBX, the material and each map:
- its path and GUID;
- its importer type;
- a hash of its importer settings.

SlopForge adds each file's SHA-256 and records the report as `unity_import` on the asset, under its logical ID (for example `prop:crate`). Approval stops before it is recorded in two cases: the material does not reference the published maps, or republishing changed a GUID at the same path, for example when a `.meta` file was lost and Unity made a new one on a checkout without its `Library/` cache. The previous files and `.meta` files are then restored. Restore the `.meta` files from version control, or publish under a new name. On a machine whose `Library/` still knows the path, Unity gave a deleted `.meta` its old GUID back.

To check a material candidate in Unity before anyone approves it, run `slopforge --project <project> unity-preview <name> <material-number>`. It copies the candidate's FBX and maps to `<output_root>/CandidatePreviews/<name>/material_NN/`, imports them with the same Lit material assignment check as approval, and saves a four-view render from the active pipeline to the candidate's `unity_preview.png`. The result and the hashes of its inputs are recorded as `unity_preview` on the candidate; the candidate's status, approval and the asset's published outputs are not changed. This is an editor batch render, not a Play-mode or in-scene check.

3D model outputs are arranged under `Models/<name>/` or `Characters/<name>/`: `Source/` holds the concept, cutout, white-background Hunyuan input, and source GLB; `Materials/` holds base color, normal, roughness, metallic, and emission maps; the folder root holds preview Blend and FBX. The pipeline retains source files for provenance and debugging.

Use `slopforge --project /path/to/project assets` and `inspect <name>` to query the manifest without requiring Unity to be open.
