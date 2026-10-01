# Agent integration

Coding agents can use the same CLI as a developer. They do not need an editor extension or a separate generation service. Continue and its LLM are optional and separate from ComfyUI: the LLM plans/calls tools, while ComfyUI generates images/models. Configure Continue's provider/model in Continue itself; SlopForge does not need the LLM credentials. See [SETUP.md](SETUP.md) for the end-to-end setup.

```sh
slopforge --project /path/to/unity-project generate icon inventory_key "Small inventory key icon"
slopforge --project /path/to/unity-project candidates inventory_key
slopforge --project /path/to/unity-project approve inventory_key 1
```

`slopforge init` installs `AGENTS.md` for Codex and other agents, a `CLAUDE.md` that imports it, and the Continue rules under `.continue/rules/`. Existing instruction files are preserved. The agent must be able to run the SlopForge CLI in a shell, either from its activated venv or by executable path.

The shared instructions tell agents to inspect the manifest, active style, and existing assets; reuse suitable assets; generate and review candidates; get the user's choice before approval; and verify the output. They also cover Unity-native geometry and keeping `.meta` files and scene/prefab edits in Unity-supported tools.
