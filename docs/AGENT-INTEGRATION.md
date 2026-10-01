# Agent integration

Coding agents can use the same CLI as a developer. They do not need an editor extension or a separate generation service. Continue and its LLM are optional and separate from ComfyUI: the LLM plans/calls tools, while ComfyUI generates images/models. Configure Continue's provider/model in Continue itself; SlopForge does not need the LLM credentials. See [SETUP.md](SETUP.md) for the end-to-end setup.

```sh
slopforge --project /path/to/unity-project generate icon inventory_key "Small inventory key icon"
slopforge --project /path/to/unity-project candidates inventory_key
slopforge --project /path/to/unity-project approve inventory_key 1
```

Copy `templates/continue/asset-generation.md` and `templates/continue/art-direction.md` into an agent's project rules when useful. For Continue, the project rule directory is `.continue/rules/`; the rules are generic templates and do not depend on a user's global Continue setup. The agent must be able to run the SlopForge CLI in a shell, either from its activated venv or by executable path.

Agent guidance should be to inspect the manifest and existing assets first, reuse when appropriate, make simple geometry in Unity, choose the correct 2D/3D asset type, rely on project style injection, review candidates before approval, and verify output files. A flat image is not a substitute for physical 3D geometry unless intentionally used as a billboard, decal, or screen. Let Unity manage `.meta` files and use supported tools rather than hand-editing scenes or prefabs.
