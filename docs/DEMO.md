# 3D character pipeline demo

This is a live ComfyUI and Blender workflow, not an offline showcase. Start with a fresh Unity project so the sample recipe and asset names do not collide with existing data.

```sh
# First create a real 3D Unity project at ~/SlopForgeDemo using Unity Hub.
slopforge init ~/SlopForgeDemo

# Local or remote ComfyUI; host and compute profile are independent.
export COMFYUI_URL=http://127.0.0.1:8188
slopforge --project ~/SlopForgeDemo doctor

slopforge --project ~/SlopForgeDemo recipe run character_3d_pack --name scout
slopforge --project ~/SlopForgeDemo review
slopforge --project ~/SlopForgeDemo candidates scout_character
slopforge --project ~/SlopForgeDemo approve scout_character 1
slopforge --project ~/SlopForgeDemo character readiness scout_character
```

A passing readiness report is a structural gate only. Follow [character rigging](CHARACTER-RIGGING.md) to prepare the provider, rig the approved mesh, inspect deformation evidence, and continue to Unity. Do not treat a successful process exit or FBX import as visual approval.

The H100 workflow uses the same HTTP interface with `COMFYUI_URL` and a separate `SLOPFORGE_COMPUTE_PROFILE=h100`. Generation can use substantial GPU time. Candidate output remains unapproved until a person reviews it.
