# Quality tiers and generation budgets

These tiers configure generation settings. Asset acceptance and pipeline evidence
statuses follow the [quality contract](QUALITY_CONTRACT.md) and
[product document precedence](PRODUCT_CONTRACT.md). `final` is a budget choice,
not an approval or qualification claim.

Quality tiers select configured generation budgets independently of the ComfyUI host. Use `--quality-tier draft|normal|final` for a one-off generation, or set `asset_pipeline.quality_tier` for the project. `SLOPFORGE_QUALITY_TIER` overrides the project default; an explicit CLI option has highest priority.

```sh
slopforge --project ~/UnityProjects/MyGame generate prop fuel_cell "Lunar refinery fuel cell" --quality-tier draft
slopforge --project ~/UnityProjects/MyGame recipe run starter_environment_kit --name refinery --quality-tier normal
```

New projects default to `final` and use the mesh-aware TRELLIS.2 workflow on Mac and Pixal3D on the H100 final profile. Install the selected workflow's weights before generation. `draft` uses one candidate per atomic stage, `normal` uses project counts, and `final` uses six image / three model / three material candidates. Model recipes use the image budget for concepts and the model budget for mesh attempts. Explicit `--count` values override concept counts. Existing model face budgets can be overridden per tier with `model_budgets`.

Final quality also adds a 10% cutout crop margin and raises the H100 base graph to 1536 shape resolution and a 4096 texture atlas. Mac/default profiles retain compatible 1024/2048 settings. Higher resolution and optional source-normal probes cost more time and memory; an atlas size alone cannot create missing detail. Explicit existing project tiers remain respected. Closed source geometry is preserved; open/nonmanifold sources use controlled repair. Character repair remains at voxel resolution 120 because the live resolution-256 comparison erased whole body regions. Source-normal probes also produced severe black staircase artifacts and remain disabled in the production TRELLIS path. Rigging remains a separate qualification step. Budgets are counted as exported triangles, including triangulation of remeshed quads.

Workflow-specific settings are configured against the selected workflow basename, not a machine or URL. A tier can provide fallback workflow choices, but an explicit compute-profile workflow wins so a profile can keep a host-compatible graph. Node IDs and inputs must already exist in the API-format workflow:

```yaml
quality_tier: final
quality_tiers:
  draft:
    defaults: {image_candidates: 1, model_candidates: 1}
  normal: {}
  final:
    defaults: {image_candidates: 6, model_candidates: 3}
    workflow_inputs:
      model:
        trellis2_image_to_model_h100_api.json:
          crop: {pad_factor: 1.1}
          shape_upsample_stage: {target_resolution: 1536}
          maps: {texture_size: 4096}
```

The tier's `workflow_inputs` shape is `stage -> workflow basename -> node ID -> input values`. SlopForge validates that nodes and input names exist, then applies the configured values before upload/queue. Compute profiles independently choose compatible workflow files for Mac/H100 or other hosts. When a configured estimate is available, place it under `estimate`; SlopForge records it as supplied and does not invent prices or runtimes.

For model approval, `model_candidates` is the maximum number of mesh attempts. Every attempt keeps its raw GLB, generation metadata, source hashes, and material validation reports under the candidate directory. Processing stops at the first candidate passing configured structural checks and still waits for human material approval. Blender inspection must include geometry, scale, UV, material, component, topology, texture, and front/side/rear/three-quarter preview evidence; incomplete reports fail closed. Character readiness, deformation review, and Unity animation validation remain separate gates before calling a character game-ready.

Recipes inherit the run tier. A recipe may set top-level `quality_tier`, and individual children may override it. The selected run tier and each child's effective tier are stored for resume/reproducibility. Candidate and mesh provenance records the effective tier/settings, including workflow input overrides; the review board shows these values under provenance.
