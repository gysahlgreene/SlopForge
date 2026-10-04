# Repeatable SlopForge demo

This small demo generates two related inventory-icon candidates, records them in one resumable recipe, and creates the local review board. It uses real ComfyUI inference; it is not an offline showcase. The project needs the models named by `image_text2img_api.json`. The current default graph may return opaque backgrounds even when prompts request transparency.

```sh
mkdir -p ~/SlopForgeDemo/Assets
slopforge init ~/SlopForgeDemo

# Point at either a local ComfyUI server or a reachable remote one.
export COMFYUI_URL=http://127.0.0.1:8188
slopforge --project ~/SlopForgeDemo doctor

slopforge --project ~/SlopForgeDemo recipe run starter_icons --name first_icons
slopforge --project ~/SlopForgeDemo review
slopforge --project ~/SlopForgeDemo candidates first_icons_health
slopforge --project ~/SlopForgeDemo candidates first_icons_mana
```

For the H100 smoke, use its Tailscale URL and profile independently:

```sh
COMFYUI_URL=http://100.108.220.4:8188 SLOPFORGE_COMPUTE_PROFILE=h100 \
  slopforge --project ~/SlopForgeDemo doctor
COMFYUI_URL=http://100.108.220.4:8188 SLOPFORGE_COMPUTE_PROFILE=h100 \
  slopforge --project ~/SlopForgeDemo recipe run starter_icons --name first_icons
```

The example is opt-in because inference requires a running service and may use GPU time. A fresh project avoids name collisions; otherwise choose a new recipe instance name. Candidates remain unapproved. Open the generated `slopforge-review.html` in the project root, inspect the output files, and approve only the candidates you want to keep.

The checked-in images and per-candidate prompt/seed/model/workflow provenance from one actual H100 run are in [`media/`](media/manifest.json). The run did not verify transparent alpha; both PNGs were RGB with opaque white backgrounds. For automated smoke tests, use `SLOPFORGE_RUN_H100=1 COMFYUI_URL=... python -m pytest tests/test_recipe_h100.py -q -s`.
