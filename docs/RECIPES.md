# Recipe and pack orchestration

Project recipes live in `ai/recipes/<id>.yaml`. `slopforge init` installs a small `starter_icons` example. A recipe describes atomic children, their asset types, optional prompt/count overrides, and dependency ordering; omitted counts use the project's existing image/model candidate defaults. The runner calls the existing image or model pipeline registered for each child type. Unsupported pipeline types fail validation before creating a recipe run.

```yaml
id: starter_icons
version: 1
description: A coordinated inventory icon set.
children:
  - id: health
    type: icon
    description: Red health potion icon.
    generation_prompt: Single centered red potion, transparent background, no text.
  - id: mana
    type: icon
    description: Blue mana potion icon.
    generation_prompt: Single centered blue potion, transparent background, no text.
    depends_on: [health]
```

Run and review a pack through the same atomic commands used for standalone assets:

```sh
slopforge --project ~/UnityProjects/MyGame recipe list
slopforge --project ~/UnityProjects/MyGame recipe run starter_icons --name first_hud
slopforge --project ~/UnityProjects/MyGame candidates first_hud_health
slopforge --project ~/UnityProjects/MyGame approve first_hud_health 1
slopforge --project ~/UnityProjects/MyGame recipe resume first_hud
slopforge --project ~/UnityProjects/MyGame recipe regenerate first_hud mana
```

The instance name namespaces child asset names (`<instance>_<child-id>`). Each child is an ordinary manifest asset linked to its recipe parent, and each dependency is also recorded by asset ID. The recipe snapshots its definition and records stage state, attempts, errors, and pipeline provenance. Stage transitions are saved through the manifest's atomic writer before and after each pipeline call.

`recipe run` creates candidates but does not approve them. Approve or inspect children using the existing commands. `recipe resume` retries failed/interrupted stages, skips completed stages, and recognizes children that have since been approved. Once every child is ready, resume refreshes the pack's typed aggregate outputs and marks the recipe ready. A failed child is reported as partial; dependents stay blocked while independent children can finish. `recipe regenerate` targets one child and appends candidates; when that child already has an approved output, its approval and selected output are retained.

The current dependency contract orders generation and records relationships. It does not automatically pass dependency images or models as visual references; reference conditioning is configured separately by issue #6. Recipe definitions use the project's existing workflow and compute-profile settings, so local and remote ComfyUI remain selectable through the normal configuration.

The normal test suite is offline. To opt into the remote ComfyUI smoke test, set both `SLOPFORGE_RUN_H100=1` and `COMFYUI_URL` when running `tests/test_recipe_h100.py`; the test creates and removes a temporary Unity fixture.
