# Agent integration

SlopForge is designed for an agent to operate. The agent brings creative judgment: it writes prompts, inspects candidates and mesh previews, and iterates. SlopForge uses a configurable local or remote ComfyUI service and runs Blender locally, preserving provenance and exporting approved assets. Set the inference URL and compute profile independently as described in [COMFYUI.md](COMFYUI.md). No LLM service or credentials are added to SlopForge. See [SETUP.md](SETUP.md) for setup.

For a person creating an asset, `slopforge --project /path/to/unity-project make` provides the guided terminal flow. Agents can use the explicit commands below when they need to control each step.

For a physical asset, keep the semantic brief and detailed model prompt separate. The prompt is sent unchanged to the configured positive conditioning node:

```sh
slopforge --project /path/to/unity-project generate prop inventory_key \
  "A brass key used by the lunar refinery crew" \
  --image-prompt "One detailed brass access key with a broad readable silhouette, engraved mechanical grooves, warm aged-metal highlights; complete object in three-quarter view against a plain neutral background."
slopforge --project /path/to/unity-project candidates inventory_key
slopforge --project /path/to/unity-project approve inventory_key 1
```

## Mesh-aware materials

For a prop with different materials on different parts, use the bundled `trellis2_image_to_model_api.json` workflow. It generates shape and PBR properties from the selected concept, prepares the mesh in Blender, and bakes the learned colors, roughness, and metallic values into its UVs. The Mac/default graph upsamples shape from 512 to 1024; final quality on H100 uses 1536 shape and 4096 textures. Blender preserves closed geometry and repairs open/nonmanifold sources before reducing them to a triangle budget. An optional Blender probe can bake tangent normals from the retained source onto the reduced mesh’s UVs; this is disabled in the production TRELLIS path after live close-ups showed severe black staircase artifacts. Character repair stays at the qualified voxel resolution 120: a live resolution-256 comparison erased whole body surfaces, and direct reduction of that dense raw mesh failed. Increasing a conversion setting does not establish better quality. ComfyUI bakes its PBR fields onto those same UVs. Only a workflow-provided normal map that has passed visual review should be enabled; neutral normals remain the TRELLIS baseline. Previews are 1024 pixels with neutral world lighting. Each selected concept produces one material set for review. Revise the concept to change the design; `retexture` applies only to the surface-swatch route below. On approval, SlopForge creates a Unity PBR `.mat`, packs roughness into the smoothness channel, and maps it to the FBX. This requires a valid Unity project and Unity CLI; verify the renderer's base color, normal, and metallic/smoothness maps after import.

On Apple MPS, this higher-resolution route can take many minutes per asset; the tested cutout run took about 25 minutes for shape upsampling and texture sampling before the remaining bake and Blender steps. Use it when color separation and shape detail justify the wait. Always inspect all three renders and the validation warnings before approval.

Add this under `asset_pipeline.workflows` in `ai/project.yaml`:

```yaml
model: trellis2_image_to_model_api.json
```

Install these official [Comfy-Org TRELLIS.2 weights](https://huggingface.co/Comfy-Org/TRELLIS.2/tree/main) in the corresponding ComfyUI model directories (about 8 GB total):

- `diffusion_models/trellis_2_int8_convrot.safetensors`
- `clip_vision/dino_v3_vit_l.safetensors`
- `vae/trellis_2_shape_vae_bf16.safetensors`
- `vae/trellis_2_texture_vae_bf16.safetensors`

Use a ComfyUI version with native TRELLIS.2 nodes, then run `slopforge --project <project> doctor`. For the affected Apple GPU/PyTorch build, apply `scripts/comfy_mps_sort_fix.patch` to ComfyUI with `git -C ~/ComfyUI apply /path/to/SlopForge/scripts/comfy_mps_sort_fix.patch`, restart ComfyUI, and run `~/ComfyUI/.venv/bin/python scripts/check_comfy_mps_sort.py ~/ComfyUI` from the SlopForge repo. The patch preserves exact integer voxel IDs during GPU sorting; missing neighbors otherwise leave holes in the decoded geometry and material field.

Describe the physical regions in the concept prompt, then approve without a surface prompt:

```sh
slopforge --project <project> generate prop power_relay "Alien power relay" \
  --image-prompt "One chunky graphite housing, broad turquoise ceramic front plate, copper side couplings, small amber glass lens; complete three-quarter view, isolated, evenly lit, detailed stylized game prop."
slopforge --project <project> approve power_relay 1
slopforge --project <project> candidates power_relay
slopforge --project <project> approve-texture power_relay 1
```

Review material placement and geometry in all three mesh views before final approval. Glass transmission and emission are not generated by this workflow; its emission map is zero. Unity appearance still needs an editor check.

## Surface swatches

With no model workflow configured, Hunyuan3D generates geometry and a separate repeating swatch provides an all-over material treatment. Author a surface-only `--material-prompt`; this route does not place separate colors or materials on named parts. Inspect the front, side, and rear mesh renders and iterate swatches on the saved mesh before final texture approval:

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
