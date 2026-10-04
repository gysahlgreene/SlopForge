# Examples

Run these commands against an initialized Unity project.

## Guided terminal workflow

Let SlopForge walk through style, asset type, description, generation, candidate review, and approval:

```sh
slopforge --project ~/UnityProjects/MyGame make
```

It opens candidates in the system image viewer. Choose a concept number, `r` to generate more, or `q` to stop and keep the candidates for later. For a model, it then shows material previews on the mesh and offers material iteration and final texture approval.

## Generate and approve an icon

```sh
slopforge --project ~/UnityProjects/MyGame generate icon health_potion \
  "A bright red potion bottle with a glowing cap, clean icon silhouette, game UI style"
slopforge --project ~/UnityProjects/MyGame candidates health_potion
slopforge --project ~/UnityProjects/MyGame approve health_potion 1
```

## Explore alternatives, then promote one

Exploration creates a separate candidate set. Each candidate has an explicit design variation; the default tier is `draft`. Workflow resolution is controlled by that tier's project configuration. Review the variations, promote one to a new production name, then use the normal approval path:

```sh
slopforge --project ~/UnityProjects/MyGame explore prop relay_ideas \
  "Compact lunar-refinery power relay" \
  --variation "silhouette=wide, low housing; motif=three concentric rings" \
  --variation "silhouette=tall, narrow housing; motif=vertical status lights" \
  --variation "shape_language=angular industrial shell; materials=painted steel and ceramic"
slopforge --project ~/UnityProjects/MyGame review
slopforge --project ~/UnityProjects/MyGame promote relay_ideas 2 --name power_relay
slopforge --project ~/UnityProjects/MyGame approve power_relay 1
```

Exploration never exports directly to Unity. The review board records the variation and gives exploration candidates a promote action. Promotion creates a regular tracked asset candidate with its prompt, seed, workflow/model and variation provenance intact; approval remains an explicit production step. Pass `--quality-tier` to override the `draft` default. Configure the tier's workflow node inputs if exploration should use lower resolutions or fewer processing steps.

## Generate and package 2D character animations

After creating an approved identity reference library, run the sample character recipe and package each approved eight-frame sheet. The selected ComfyUI workflow must support reference conditioning and sheet generation; the bundled text-to-image graph is not an animation workflow.

```sh
slopforge --project ~/UnityProjects/MyGame recipe run character_sprite_pack \
  --name pilot --reference-library character/pilot --quality-tier draft
slopforge --project ~/UnityProjects/MyGame candidates pilot_walk
slopforge --project ~/UnityProjects/MyGame approve pilot_walk 1
slopforge --project ~/UnityProjects/MyGame spritepack pilot_walk \
  --animation walk --grid 8 1 --fps 8
```

See [2D character sprite packs](SPRITE-PACKS.md) for the full animation list, reference workflow setup, and Unity metadata contract.

## Generate a coordinated recipe pack

```sh
slopforge --project ~/UnityProjects/MyGame recipe list
slopforge --project ~/UnityProjects/MyGame recipe run starter_icons --name first_hud
slopforge --project ~/UnityProjects/MyGame candidates first_hud_health
slopforge --project ~/UnityProjects/MyGame approve first_hud_health 1
slopforge --project ~/UnityProjects/MyGame recipe resume first_hud
```

`recipe resume` continues incomplete children and refreshes the aggregate pack after approvals. `recipe regenerate first_hud mana` adds candidates for only the mana child. See [Recipe and pack orchestration](RECIPES.md) for the recipe format and statuses.

## Generate and approve a 3D prop

```sh
slopforge --project ~/UnityProjects/MyGame generate prop stone_lantern \
  "A weathered stone lantern, medieval ruins, subtle wear" \
  --image-prompt "A squat carved stone lantern with a broad square cap, four open sides and a warm glass core, complete front three-quarter view, isolated against a neutral background, hand-painted fantasy game prop."
slopforge --project ~/UnityProjects/MyGame candidates stone_lantern
slopforge --project ~/UnityProjects/MyGame approve stone_lantern 1 \
  --material-prompt "Flat surface texture: aged gray stone with fine pores and restrained moss in creases, warm amber glass glow accents; even light, no lantern, no perspective."
slopforge --project ~/UnityProjects/MyGame candidates stone_lantern
slopforge --project ~/UnityProjects/MyGame approve-texture stone_lantern 1
```

If the mesh previews show poor scale or coverage, run `retexture stone_lantern --material-prompt "..." --count 2`, compare front/side/rear views, then approve the selected material. Approved files are copied to the output directory configured in `ai/project.yaml`.
