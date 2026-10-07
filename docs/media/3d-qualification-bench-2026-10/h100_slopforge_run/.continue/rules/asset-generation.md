# Local asset generation

Before creating assets, inspect `ai/project.yaml`, the active style, `ai/assets/manifest.json`, and existing Unity assets; reuse a suitable result when possible. Use Unity primitives for blockout geometry and model generation for distinctive physical game assets. Concept and material images are supporting inputs; do not treat them as finished 3D assets.

The agent owns creative direction. Write the exact image prompt for the configured model and preserve the short semantic description separately: `slopforge --project <project> generate <type> <name> "<semantic description>" --image-prompt "<specific prompt>"`. Review images against the request and style, explain differences, and revise the prompt when needed. Get the user's choice before concept approval.

For distinct materials on named parts, configure `asset_pipeline.workflows.model: trellis2_image_to_model_api.json` and check its dependencies with `doctor`. Specify each material region in `--image-prompt`, then `approve` the concept without `--material-prompt`; the workflow generates mesh-aware PBR maps. Revise the concept to change its material design. With no model workflow, use `--material-prompt` for an all-over flat repeatable swatch and iterate it with `retexture`; this route cannot assign named regions automatically.

Inspect front, side, and rear previews for geometry, coverage, seams, and intended material placement. Recommend a candidate with reasons, get the user's choice, then use `approve-texture <name> <number>`. `candidates <name>` lists both concept and material previews. Verify the approved FBX and maps exist.

Do not hand-edit Unity `.meta` files or scene/prefab YAML to place assets. Let Unity import files and use the editor or supported tools for scene changes.
