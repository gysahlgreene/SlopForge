# 3D recipe orchestration

Recipes in `ai/recipes/<id>.yaml` coordinate related 3D assets. `slopforge init` installs `character_3d_pack` and `starter_environment_kit`. A recipe describes children, asset types, prompts, dependencies, and optional generation counts. The runner calls the existing model or supporting image pipeline for each child and records progress, dependencies, and provenance in the manifest.

A small recipe can coordinate a character and an associated prop:

```yaml
id: scout_set
version: 1
description: A riggable scout character and a matching field scanner.
children:
  - id: character
    type: character
    description: Full-body scout in a neutral A-pose, with a clean silhouette and readable materials.
    count: 1
  - id: scanner
    type: hero_prop
    description: Handheld field scanner using the same material palette and design language.
    depends_on: [character]
```

Run, review, and resume a recipe with the same commands used for standalone 3D assets:

```sh
slopforge --project ~/UnityProjects/MyGame recipe list
slopforge --project ~/UnityProjects/MyGame recipe run character_3d_pack --name scout
slopforge --project ~/UnityProjects/MyGame candidates scout_character
slopforge --project ~/UnityProjects/MyGame approve scout_character 1
slopforge --project ~/UnityProjects/MyGame recipe resume scout
```

The instance name namespaces child asset names (`<instance>_<child-id>`). Children are ordinary tracked assets with recipe parent/dependency links. Stage state, attempts, errors, and provenance are saved around each pipeline call. Resume retries failed or interrupted stages, skips completed stages, and waits for human approval. A failed child is reported as partial; dependent children remain blocked while independent stages may continue.

Dependencies order and record generation; they do not automatically turn one child's output into another child's visual reference. Configure reference libraries and workflow inputs separately. Local and remote ComfyUI use the same HTTP backend contract.

Recipes do not turn an unconstrained game pitch into a concept-aware 3D asset inventory. Edit or create a 3D recipe explicitly, then review the plan before spending generation time.

## Character recipe

`character_3d_pack` generates one full-body humanoid character in a neutral pose. Approve the model candidate, run the readiness check, choose and run a rigging provider, inspect deformation poses, then validate animation in Unity. The recipe does not claim the generated character is riggable or production-ready; see [character rigging](CHARACTER-RIGGING.md).
