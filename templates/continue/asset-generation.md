# Local asset generation

Before creating artwork, inspect `ai/assets/manifest.json` and existing Unity assets; reuse a suitable result when possible. Use Unity primitives for simple geometry. Use the proper 2D type for flat artwork and model generation for distinctive physical objects. A flat image is not a physical prop unless intentionally used as a billboard, decal, or screen.

Use `slopforge --project <project> generate <type> <name> "<semantic description>"`. The selected project style is injected automatically. Review candidates with `candidates`, approve a selected result, and verify the expected file exists before continuing. `primitive` records a Unity-native geometry route.

Do not hand-edit Unity `.meta` files or scene/prefab YAML to place assets. Let Unity import files and use the editor or supported tools for scene changes.
