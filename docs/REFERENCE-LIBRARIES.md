# Reference libraries

Project reference libraries live at `ai/libraries/<kind>/<name>.yaml`. They are ordered lists of membership records, so the same approved asset or external file can be reused by different recipes without copying it. Kinds are domain labels such as `character`, `style`, `material`, `ui`, and `environment`; they do not name ComfyUI nodes.

```yaml
name: Alice
kind: character
version: 1
entries:
  - id: front_portrait
    path: References/alice-front.png
    category: identity
    strength: 0.8
    # Optional: sha256: <64 lowercase hex characters> pins this file version.
  - id: approved_portrait
    asset:
      asset_id: 6ef8... # stable id from ai/assets/manifest.json
      output_id: image
    category: face
```

`path` can be project-relative or absolute for an external file; files are referenced in place and never copied. `asset` resolves an output from the project manifest and accepts only an approved typed artifact or a ready legacy asset with an approved selected candidate. Each resolved entry reports its ordered position, category, strength, source, current SHA-256, and `ready`, `missing`, or `changed` status. Add `sha256` when membership should detect later file changes; actual hashes are recorded in generation provenance either way.

Inspect libraries with:

```sh
slopforge --project ~/UnityProjects/MyGame library list
slopforge --project ~/UnityProjects/MyGame library show character/alice
```

Conditioning consumes the same resolved membership records without depending on library kind or workflow graph. Enable `asset_pipeline.conditioning.strategy: reference` and configure `workflow_inputs` for the active image workflow, then select a library with `slopforge generate ... --reference-library character/alice`. A recipe child can set `reference_library: character/alice`; the runner validates its membership before creating the run and resolves it again when the child executes. Missing or changed files block the operation. A library's optional per-entry strength overrides the project's default reference strength.
