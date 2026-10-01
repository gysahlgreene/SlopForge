# Style system

`ai/project.yaml` selects a style pack by `asset_pipeline.active_style`; the engine loads `ai/styles/<key>/style.yaml`. The pack is validated and supplied to prompt generation as data. It can describe:

- name, version, genre, rendering approach, mood, and detail level;
- preferred and avoided shape language;
- palette and canonical material descriptions;
- surface treatment and lighting;
- per-asset-type rules and material-generation rules.

Copy `templates/style/style.yaml` into a new style directory and fill in project-specific data. `examples/minimal/style.yaml` is a small starting example; `examples/cozy-fantasy/style.yaml` demonstrates a filled alternate direction. Set only the active pack name in `ai/project.yaml` to switch styles.

Put approved references under `ai/styles/<key>/references/approved/` and tentative images under `references/candidates/`. The current `text_only` conditioning records no references as used. Switching to `reference` is rejected until a workflow actually consumes reference images.

Taxonomy rules live in `ai/asset_types/*.yaml`. Add a type definition with `name`, `pipeline`, `output_folder`, `requirements`, and `avoid`; 3D types also select a `face_budget` key. The command discovers these files instead of maintaining a hard-coded type list.
