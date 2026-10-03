# Unity projects

Unity is an output target, not a generation dependency. Initialize an existing Unity project with `slopforge init /path/to/project`; its `Assets/` directory must already exist. The standalone engine stays installed outside that project. Initialization creates:

- `ai/project.yaml`, `ai/assets/manifest.json`, and `ai/asset_types/`.
- `ai/styles/default/style.yaml` with approved/candidate reference folders.
- `ai/workflows/` for project-specific workflow overrides.
- `Assets/Art/Generated/` folders for supported asset types.

SlopForge writes ordinary PNG, GLB, Blend, and FBX files under the configured Unity `output_root`. Unity owns `.meta` files. This tool does not modify scenes or prefabs.

The Unity Editor may be closed during generation. Open the project afterward to import the new files and let Unity create `.meta` files.

Texture approval creates a Unity Lit material for the Built-in Render Pipeline or URP. HDRP and custom render pipelines currently stop with an explicit unsupported-pipeline error rather than receiving a mismatched shader.

3D model outputs are arranged under `Models/<name>/`: `Source/` holds the concept, cutout, white-background Hunyuan input, and source GLB; `Materials/` holds base color, normal, roughness, metallic, and emission maps; the folder root holds preview Blend and FBX. The pipeline retains source files for provenance and debugging.

Use `slopforge --project /path/to/project assets` and `inspect <name>` to query the manifest without requiring Unity to be open.
