# Style system

`ai/project.yaml` selects a style pack by `asset_pipeline.active_style`; the engine loads `ai/styles/<key>/style.yaml`. The pack is validated and supplied to prompt generation as data. It can describe:

- name, version, genre, rendering approach, mood, and detail level;
- preferred and avoided shape language;
- palette and canonical material descriptions;
- surface treatment and lighting;
- per-asset-type rules and material-generation rules.

Copy `templates/style/style.yaml` into a new style directory and fill in project-specific data. `examples/minimal/style.yaml` is a small starting example; `examples/cozy-fantasy/style.yaml` demonstrates a filled alternate direction. Set only the active pack name in `ai/project.yaml` to switch styles.

New candidates record the style-pack key, name, version, and a SHA-256 fingerprint of the style data. A 3D approval checks that the active pack still matches before starting inference: its concept and material stages must use the same art direction. If you switched or edited the pack, restore the original pack or generate new candidates. Legacy candidates without a fingerprint can only be checked by style name and version.

Approving a 2D candidate restores that candidate's semantic description, style identity, and generator provenance to the asset record. Image approval validates a temporary copy before replacing the canonical output, so a corrupt candidate cannot overwrite the approved image.

Material prompts request a flat surface without standalone objects, perspective, text, cast shadows, or baked lighting. Physical prop requirements remain in concept prompts; concept art is not projected into the material. The normal map derives from the generated surface's luminance. Roughness, metallic, and emission use prompt-guided heuristics, so these maps are not physically accurate and textures are not guaranteed seamless.

Put approved references under `ai/styles/<key>/references/approved/` and tentative images under `references/candidates/`. The current `text_only` conditioning records no references as used. Switching to `reference` is rejected until a workflow actually consumes reference images.

Taxonomy rules live in `ai/asset_types/*.yaml`. Add a type definition with `name`, `pipeline`, `output_folder`, `requirements`, and `avoid`; 3D types also select a `face_budget` key. The command discovers these files instead of maintaining a hard-coded type list.
