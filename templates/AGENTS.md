# Working in this Unity project

Before creating an asset, check `ai/project.yaml`, the active style in `ai/styles/`, `ai/assets/manifest.json`, and existing Unity assets. Reuse suitable assets when possible, and follow the active style; SlopForge adds it to generation prompts automatically.

Generate candidates with `slopforge --project <project> generate <type> <name> "<description>"`, then inspect them with `candidates <name>`. Show the candidates and get the user's choice before running `approve <name> <number>`. Verify the approved output exists afterward.

Use Unity primitives for simple geometry. A generated flat image is not a physical prop unless it is intentionally a billboard, decal, or screen. Do not hand-edit Unity `.meta` files or scene/prefab YAML; let Unity import assets and use supported tools for scene changes.
