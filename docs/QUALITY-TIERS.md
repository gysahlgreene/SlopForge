# Quality tiers and generation budgets

Quality tiers select configured generation budgets independently of the ComfyUI host. Use `--quality-tier draft|normal|final` for a one-off generation, or set `asset_pipeline.quality_tier` for the project. `SLOPFORGE_QUALITY_TIER` overrides the project default; an explicit CLI option has highest priority.

```sh
slopforge --project ~/UnityProjects/MyGame generate prop fuel_cell "Lunar refinery fuel cell" --quality-tier draft
slopforge --project ~/UnityProjects/MyGame recipe run starter_environment_kit --name refinery --quality-tier normal
```

The initialized project defaults to one candidate per atomic stage for `draft`, existing project counts for `normal`, and six image / three model / three material candidates for `final`. These are editable candidate budgets, not runtime/cost estimates. Explicit `--count` values continue to override the tier. Existing model face budgets can be overridden per tier with `model_budgets`.

Workflow-specific settings are configured against the selected workflow basename, not a machine or URL. A tier can provide fallback workflow choices, but an explicit compute-profile workflow wins so a profile can keep a host-compatible graph. Node IDs and inputs must already exist in the API-format workflow:

```yaml
quality_tier: normal
quality_tiers:
  draft:
    defaults: {image_candidates: 1, model_candidates: 1}
    workflow_inputs:
      image:
      image_text2img_api.json:
          "5": {width: 512, height: 512}
      model:
        trellis2_image_to_model_api.json:
          "20": {resolution: 512, texture_resolution: 1024}
  normal: {}
  final:
    defaults: {image_candidates: 6, model_candidates: 3}
    workflow_inputs:
      model:
        trellis2_image_to_model_api.json:
          "20": {resolution: 1536, texture_resolution: 4096}
```

The tier's `workflow_inputs` shape is `stage -> workflow basename -> node ID -> input values`. SlopForge validates that nodes and input names exist, then applies the configured values before upload/queue. Compute profiles independently choose compatible workflow files for Mac/H100 or other hosts. When a configured estimate is available, place it under `estimate`; SlopForge records it as supplied and does not invent prices or runtimes.

For model approval, `model_candidates` is the maximum number of mesh attempts. Every attempt keeps its raw GLB, generation metadata, source hashes, and material validation reports under the candidate directory. Promotion stops at the first structurally qualified candidate and still waits for human material approval. Blender inspection must include geometry, scale, UV, material, component, topology, texture, and front/side/rear/three-quarter preview evidence; incomplete reports fail closed. Character readiness, deformation review, and Unity animation validation remain separate gates before calling a character game-ready.

Recipes inherit the run tier. A recipe may set top-level `quality_tier`, and individual children may override it. The selected run tier and each child's effective tier are stored for resume/reproducibility. Candidate and mesh provenance records the effective tier/settings, including workflow input overrides; the review board shows these values under provenance.
