# Working in this Unity project

Before creating an asset, check `ai/project.yaml`, the active style in `ai/styles/`, `ai/assets/manifest.json`, and existing Unity assets. Reuse suitable assets when possible. You own creative direction: write a specific prompt for the configured image model instead of relying on a short description expanded by a generic template. Keep the short semantic description separate and pass the full prompt with `--image-prompt`.

Generate candidates with `slopforge --project <project> generate <type> <name> "<semantic description>" --image-prompt "<specific prompt>"`. Inspect the images against the request and style, explain meaningful differences, and iterate the prompt when all candidates miss. Show the candidates and get the user's choice before approving one.

For coordinated packs, inspect `ai/recipes/`, then use `recipe run <recipe> --name <instance>`. Review and approve child assets with the normal asset commands, and use `recipe resume <instance>` to refresh pack status and aggregate outputs. Regenerate only the missed child with `recipe regenerate <instance> <child-id>`; approved child outputs are retained.

For props with distinct material regions, use the mesh-aware workflow `asset_pipeline.workflows.model: trellis2_image_to_model_api.json` after `doctor` confirms its models are installed. Specify each region's color and material in `--image-prompt`, then approve the concept without `--material-prompt`. The workflow generates colors, roughness, and metallic properties with the mesh, upsamples its shape to 1024, and uses smooth geometric normals with a flat tangent normal map. This route can take many minutes on Apple MPS. Revise the concept to change its material design.

When no model workflow is configured, Hunyuan3D generates geometry and `--material-prompt` describes a flat repeatable surface swatch. This route suits an all-over surface treatment; it does not place distinct materials on named parts. Iterate its swatches with `retexture <name> --material-prompt "<revised surface prompt>" --count 2`.

Review the saved front, side, and rear mesh previews for coverage, seams, geometry, and intended material placement. Compare them with the request, then ask the user to choose and run `approve-texture <name> <number>`. Approval creates a Unity PBR material, packs roughness into Unity's smoothness channel, and explicitly maps the material to the FBX; this requires the project to have Unity metadata and the Unity CLI installed. Verify the FBX, `.mat`, and maps exist and confirm the imported renderer uses that material. `candidates <name>` lists both concept and material candidates.

Use Unity primitives for simple geometry. A generated flat image is not a physical prop unless it is intentionally a billboard, decal, or screen. Do not hand-edit Unity `.meta` files or scene/prefab YAML; let Unity import assets and use supported tools for scene changes.
