# Prototype content plans

`prototype propose` writes an editable plan under `ai/prototypes/`; it does not call ComfyUI or generate candidates. The initial proposal combines the project description/style with the selected existing recipes and their child asset briefs. By default it includes all project recipes and orders them as explicit approval checkpoints. Edit the stage list, dependencies, quality tier, candidate budget, and content briefs before approving.

```sh
slopforge --project ~/UnityProjects/MyGame prototype propose lunar_run \
  "Top-down extraction game in an abandoned lunar refinery" \
  --recipe starter_environment_kit --recipe starter_ui_pack --recipe starter_vfx_pack \
  --quality-tier draft --candidate-budget 40
# Review/edit ai/prototypes/lunar_run.yaml
slopforge --project ~/UnityProjects/MyGame prototype approve lunar_run
slopforge --project ~/UnityProjects/MyGame prototype run lunar_run
```

Approval records a fingerprint of the plan. Any edits require approval again. Execution composes the existing recipe runner, propagates quality tiers, records prototype-to-pack dependencies and provenance in the manifest, and stops at recipe approval gates. Approve child candidates with the normal asset command, then run `prototype resume`. `prototype regenerate NAME STAGE CHILD_ID` targets one child after that stage's dependencies have approved outputs.

The candidate budget is a cap over estimated candidate outputs, not a monetary or wall-time promise. Estimates use recipe counts and configured quality-tier defaults. Explicit per-child counts remain in force. Each recipe stage is resumable and incomplete dependent stages stay blocked. This plan builder is deterministic and user-editable; it does not currently ask an LLM to invent characters, props, or narrative content. It does not create a Unity demo scene.
