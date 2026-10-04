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
