# 2D character sprite packs

The `character_sprite_pack` recipe creates candidate sheets for `idle`, `walk`, `run`, `attack`, `hurt`, `death`, `jump`, `cast`, `block`, `interact`, and `dodge`. It accepts an approved identity library at run time, so every action can reuse the same ordered reference images without binding the recipe to one character or image model:

```sh
slopforge --project ~/UnityProjects/MyGame recipe run character_sprite_pack \
  --name pilot --reference-library character/pilot --quality-tier draft
```

Configure reference conditioning for the selected ComfyUI API workflow as described in [ComfyUI setup](COMFYUI.md) and [reference libraries](REFERENCE-LIBRARIES.md). The workflow must produce an eight-column, one-row sheet; the bundled text-to-image workflow does not add animation or identity conditioning. A custom ComfyUI workflow can use Wan, another motion model, or a pose-driven method. SlopForge stores the workflow, seed, selected identity references, and prompt per candidate; it does not assume a model or guarantee temporal consistency.

Review the recipe and approve the chosen sheet for each animation using the normal candidate workflow. Slice an approved sheet into equal RGBA frames, an atlas, and Unity timing/pivot metadata:

```sh
slopforge --project ~/UnityProjects/MyGame spritepack pilot_walk \
  --animation walk --grid 8 1 --fps 8 --pivot 0.5 0
```

The command refuses unapproved sheets, unsafe/missing source paths, invalid grids, and existing output directories. It writes to `Assets/Art/Generated/Characters/<sheet-asset>/<animation>/`, registers each frame, atlas, and `data.unity_animation` JSON as approved typed outputs derived from the approved source sheet, and records frame timing, loop mode, and normalized Unity pivot. `idle`, `walk`, and `run` loop by default; use `--no-loop` or `--loop` to override. The default pivot is bottom-center (`0.5, 0`).

This JSON is import metadata, not a Unity-generated `.meta` file or AnimatorController. Unity owns importer metadata and editor-generated animation assets. Alpha is preserved when supplied by the workflow; SlopForge does not silently remove a background from a character sheet.
