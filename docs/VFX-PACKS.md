# VFX sprite-sheet packs

`slopforge init` installs `starter_vfx_pack`, a data-driven recipe for projectile, impact, cast, hit-spark, smoke, heal, and fire sheets plus a matching impact decal. Run it with the ordinary recipe and approval commands:

```sh
slopforge --project ~/UnityProjects/MyGame recipe run starter_vfx_pack \
  --name lunar_combat --reference-library style/default --quality-tier draft
slopforge --project ~/UnityProjects/MyGame candidates lunar_combat_impact
slopforge --project ~/UnityProjects/MyGame approve lunar_combat_impact 1
```

The configured image workflow must return the requested 4x4 animation sheet with transparent background. Model/workflow support for temporal animation and alpha varies; SlopForge records the workflow and seed but does not invent or repair motion. Review and approve each sheet before packaging it.

Package an approved sheet into ordered RGBA frames, an atlas, and playback metadata:

```sh
slopforge --project ~/UnityProjects/MyGame spritepack lunar_combat_impact \
  --animation impact --grid 4 4 --fps 16 --no-loop
```

For a sheet that should play continuously, use `--loop`. SlopForge refuses an unapproved sheet, an invalid grid, unsafe paths, and an existing pack directory. Frames, atlas, and JSON are recorded as approved typed outputs derived from the approved sheet.

With Unity installed and the UGUI-independent particle shaders available in the project, add `--particle-prefab` to create a texture-sheet `ParticleSystem` prefab and material from a `vfx_sheet`:

```sh
slopforge --project ~/UnityProjects/MyGame spritepack lunar_combat_fire \
  --animation fire --grid 4 4 --fps 12 --loop --particle-prefab
```

The optional Unity Editor step imports alpha, assigns the atlas material, configures the sheet grid, and registers the prefab and material with provenance. It does not create a complete VFX graph or tune effect-specific particle forces; adjust those in Unity for the target game. The normal automated tests use fixtures and do not require Unity or ComfyUI.
