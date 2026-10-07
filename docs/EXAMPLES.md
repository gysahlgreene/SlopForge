# 3D examples

Run these commands against an initialized Unity project.

## Guided workflow

```sh
slopforge --project ~/UnityProjects/MyGame make
```

The guided flow asks for an asset type and description, generates candidates, and opens them for review. Model candidates continue through mesh processing and material preview; approval remains explicit.

## Explore prop variations

Exploration creates separate concept candidates for a model asset. Review and promote the preferred design, then continue through the normal 3D pipeline:

```sh
slopforge --project ~/UnityProjects/MyGame explore prop relay_ideas \
  "Compact lunar-refinery power relay" \
  --variation "silhouette=wide, low housing; motif=three concentric rings" \
  --variation "silhouette=tall, narrow housing; motif=vertical status lights"
slopforge --project ~/UnityProjects/MyGame review
slopforge --project ~/UnityProjects/MyGame promote relay_ideas 2 --name power_relay
slopforge --project ~/UnityProjects/MyGame approve power_relay 1
```

Exploration candidates do not export directly. Promotion creates a normal tracked model candidate and retains its prompt, seed, workflow, model, and variation provenance.

## Generate a 3D prop

```sh
slopforge --project ~/UnityProjects/MyGame generate prop stone_lantern \
  "Weathered stone lantern for a fantasy ruin" \
  --image-prompt "A squat carved stone lantern with a broad square cap, open sides and a warm glass core; complete front three-quarter view, isolated on neutral background."
slopforge --project ~/UnityProjects/MyGame candidates stone_lantern
slopforge --project ~/UnityProjects/MyGame approve stone_lantern 1
slopforge --project ~/UnityProjects/MyGame candidates stone_lantern
slopforge --project ~/UnityProjects/MyGame approve-texture stone_lantern 1
```

Inspect front, side, and rear previews. If mesh shape, topology, or material coverage is poor, reject the candidate and try a revised brief or workflow. The 3D generators do not guarantee game-ready output.

## Generate and inspect a character

```sh
slopforge --project ~/UnityProjects/MyGame recipe run character_3d_pack --name pilot
slopforge --project ~/UnityProjects/MyGame candidates pilot_character
slopforge --project ~/UnityProjects/MyGame approve pilot_character 1
slopforge --project ~/UnityProjects/MyGame character readiness pilot_character
```

Continue with provider setup and rigging only after reviewing the readiness report. See [3D character rigging](CHARACTER-RIGGING.md) and [animation libraries](CHARACTER-ANIMATIONS.md). Structural checks do not establish deformation quality.

## Coordinate an environment kit

```sh
slopforge --project ~/UnityProjects/MyGame recipe run starter_environment_kit --name refinery
slopforge --project ~/UnityProjects/MyGame review
slopforge --project ~/UnityProjects/MyGame recipe resume refinery
slopforge --project ~/UnityProjects/MyGame environment-check refinery
```

The kit recipe generates separate modules and validates configured dimensions, grid placement, and pivots. It does not assemble a room scene or guarantee a coherent visual set; inspect and approve each module.
