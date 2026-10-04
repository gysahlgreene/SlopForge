# Modular environment kits

`slopforge init` installs `starter_environment_kit`, a recipe that composes modular floor, wall, corner, ceiling, doorway, door, column, pipe, terminal, crate, surface, and decal assets. It uses the existing atomic image/model pipelines, so configured workflows, references, and local or remote ComfyUI remain unchanged.

Start with one candidate per child to keep the first pass inexpensive:

```sh
slopforge --project ~/UnityProjects/MyGame recipe run starter_environment_kit \
  --name lunar_refinery --quality-tier draft --reference-library environment/lunar-refinery
```

Review and approve child assets through the normal candidate commands. Resume the pack after each approval; successful approved children remain intact while unfinished children continue:

```sh
slopforge --project ~/UnityProjects/MyGame recipe resume lunar_refinery
slopforge --project ~/UnityProjects/MyGame environment-check lunar_refinery
```

`kit_constraints` lives in the recipe definition and is snapshotted into each recipe run. It sets a grid, tolerances, maximum module dimensions, pivot expectations, and optional snap axes per child. `environment-check` reads the saved Blender measurements for bounds, dimensions, origins, and applied transforms. It writes a typed validation artifact at `ai/assets/environment_checks/<name>.json`; incomplete packs produce a partial report and a nonzero exit, while failed geometry checks remain visible in the manifest.

The checks report modular measurements; they do not rescale or rotate geometry, apply materials to models, or assemble a room scene. Intended front-facing direction and visual seams still need review in Blender/Unity. Use the supplied grid constraints as a starting profile and adjust them per kit rather than treating one grid size as universal.
