# Agent integration

SlopForge is designed for an agent to operate. The agent brings creative judgment: it writes prompts, inspects candidates and mesh previews, and iterates. SlopForge runs ComfyUI and Blender, preserves provenance, and exports approved assets. No LLM service or credentials are added to SlopForge. See [SETUP.md](SETUP.md) for setup.

For a person creating an asset, `slopforge --project /path/to/unity-project make` provides the guided terminal flow. Agents can use the explicit commands below when they need to control each step.

For a 2D image, keep the semantic brief and model prompt separate. The prompt is sent unchanged to the configured positive conditioning node:

```sh
slopforge --project /path/to/unity-project generate icon inventory_key \
  "Key icon for the inventory" \
  --image-prompt "Single small brass key, broad readable silhouette, three-quarter angle, hand-painted fantasy game icon, warm highlights, dark teal background, centered with clear margins."
slopforge --project /path/to/unity-project candidates inventory_key
slopforge --project /path/to/unity-project approve inventory_key 1
```

For a 3D prop, author both the concept prompt and a surface-only material prompt. Concept approval generates the mesh once and creates initial material candidates. Inspect the front, side, and rear mesh renders; iterate without rerunning mesh generation, then get the user's choice before final texture approval:

```sh
slopforge --project /path/to/unity-project generate prop alien_terminal \
  "A wall terminal that controls sealed doors" \
  --image-prompt "A waist-high wall-mounted alien control terminal, broad rectangular silhouette, one recessed cyan screen above three large tactile controls, front three-quarter view, complete object visible, isolated against a plain neutral background, stylized painted sci-fi game prop."
slopforge --project /path/to/unity-project candidates alien_terminal
slopforge --project /path/to/unity-project approve alien_terminal 1 \
  --material-prompt "Flat repeating surface material swatch: aged dark gunmetal, restrained brushed grain, muted teal enamel panels, small cyan emissive accents; even lighting, no object, no perspective, no text."
slopforge --project /path/to/unity-project retexture alien_terminal \
  --material-prompt "Flat repeating material: cleaner charcoal ceramic with worn brass trim color, fine scale, subdued finish; even lighting, no object, no perspective, no text." --count 2
slopforge --project /path/to/unity-project candidates alien_terminal
slopforge --project /path/to/unity-project approve-texture alien_terminal 3
```

`slopforge init` installs `AGENTS.md` for Codex and other agents, a `CLAUDE.md` that imports it, and the Continue rules under `.continue/rules/`. Existing instruction files are preserved. The agent must be able to run the SlopForge CLI in a shell, either from its activated venv or by executable path.

The shared instructions tell agents to inspect the project, author prompts, compare candidates, iterate materials on the saved mesh, and get the user's choice before final approval. They also cover Unity-native geometry and keeping `.meta` files and scene/prefab edits in Unity-supported tools. `make` remains available as a guided fallback.
