# Examples

Run these commands against an initialized Unity project.

## Generate and approve an icon

```sh
slopforge --project ~/UnityProjects/MyGame generate icon health_potion \
  "A bright red potion bottle with a glowing cap, clean icon silhouette, game UI style"
slopforge --project ~/UnityProjects/MyGame candidates health_potion
slopforge --project ~/UnityProjects/MyGame approve health_potion 1
```

## Generate and approve a 3D prop

```sh
slopforge --project ~/UnityProjects/MyGame generate prop stone_lantern \
  "A weathered stone lantern, medieval ruins, subtle wear"
slopforge --project ~/UnityProjects/MyGame candidates stone_lantern
slopforge --project ~/UnityProjects/MyGame approve stone_lantern 1
```

Approved files are copied to the output directory configured in `ai/project.yaml`.
