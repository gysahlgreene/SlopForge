# Typed 3D asset outputs

Manifest schema version 4 keeps each asset's path-only `outputs` compatibility map and adds execution lineage for the existing prop pipeline. A character or recipe may also record typed outputs. A file path is a location; the artifact's SHA-256 identifies its content.

## Prop execution lineage

Each v4 asset may contain `executions: []`. A prop invocation stores its unique execution ID, optional parent execution ID, canonical semantic identity inputs and digest, start time, status, and ordered stage attempts. Each stage has a unique ID and stores its name and attempt number, status (`pending`, `running`, `succeeded`, or `failed`), timestamps, upstream and output artifact references, effective settings, provenance facts, error text, and optional structured failure metadata. A stage's `pending` state is saved before it is changed to `running`; terminal states and available hashes are saved after the boundary.

An artifact reference includes an execution-scoped ID, type, project-relative path, SHA-256 of the file bytes, producing stage and attempt, and `derived_from` artifact IDs and content hashes. Paths remain useful for locating files but never substitute for hashes. The existing candidate, `model_attempts`, source, and `outputs` fields remain compatibility views alongside these records.

Prop executions use the durable boundaries `concept_generation`, `conditioning_preparation`, `mesh_workflow_execution`, `mesh_raw_acquisition` where a workflow returns a separate raw mesh, `mesh_preparation` where used, `material_generation`, `mesh_output_acquisition`, `material_map_acquisition` for swatch-derived maps, `material_assembly_export`, and `final_publication`. Repeated stage entries retain attempt/outcome history. The 3D worker saves fully bound workflow identities and bindings as stage provenance before queueing; successful image-generation sidecars record source/effective graph identity and bindings after output acquisition. Generated-output bindings remain stage evidence and do not alter the semantic execution identity. Package 1 records lineage; Package 2 governs reuse and invalidation; Package 3 classifies failures and bounds candidate retries. For swatch materials, `material_map_acquisition` records the flat tiles under `material_NN/Tiles/`; assembly bakes copies of them onto the mesh UVs, packs `metallic_gloss` from the baked maps, and records the baked maps as `material_assembly_export` outputs, so recorded hashes keep matching the files. Failed material candidates stay in the manifest, and `approve-texture` refuses a material whose asset has since had its concepts regenerated, before any file changes.

Failed stages may store `failure` with `category`, `stage`, `stage_id`, `attempt`, `operation`, `message`, `remedy`, `retryable`, `exception_type`, and JSON-safe `evidence`. `retry_decisions` records mesh candidate-slot use and whether the run advanced, stopped, or exhausted its budget. `blocked_stages` records downstream work that did not run. These are additive schema-v4 fields; they do not change execution identity or stage status values.

## Prop reuse and resume

`approve --resume` selects the latest incomplete or failed execution whose recorded selected-concept hash and candidate identity match the requested candidate. It preserves that execution's seeds. A changed selected concept is rejected before conditioning or model inference. At each stage boundary, the pipeline compares the prior stage's semantic inputs, settings, and required output references with the requested stage. A current execution records a separate reuse decision and an adopted stage that points at the original artifact references; the earlier execution and its stage status remain unchanged.

The invalidation boundaries follow the prop stages:

| Change or evidence failure | First recomputed stage | Preserved compatible work |
| --- | --- | --- |
| Selected concept identity or content changes | Resume is rejected; select the intended candidate and start a new approval | No descendants are adopted under the changed concept |
| Conditioning strategy/input or conditioning output changes | `conditioning_preparation` | The selected concept artifact |
| Model workflow content, mesh settings, seed, or generated mesh integrity changes | `mesh_workflow_execution` | The selected concept and compatible conditioning images |
| Material prompt/workflow/maps change | `material_generation` or `material_map_acquisition` | Concept, conditioning, and compatible generated mesh |
| Material scale, face budget, Blender processing inputs, or assembly output changes | `material_assembly_export` | Compatible concept, mesh, and material/map artifacts |
| A candidate preview is missing or hash-mismatched | `material_assembly_export` for that candidate | Mesh and material/map artifacts; inference is not rerun |

Reuse requires the recorded artifact at its recorded project-relative path to exist and match its SHA-256. The stage's output IDs, stage/attempt identity, derivation links, ordered inputs, and settings must also match. A duplicate basename elsewhere does not substitute for a missing file. Relocation is not supported. A prior `succeeded` status is historical truth and does not make its output valid for a new request. Unknown or absent lineage is not treated as a match.

An ordinary exception leaves the failed stage and execution recorded as failed; a process interruption can leave the last persisted stage running. `--resume` reevaluates both and starts at the earliest stage whose evidence is incomplete or stale, while retaining valid upstream artifacts. Automatic candidate advancement is limited to complete validation reports that reject only allowlisted topology budgets and stops at the configured mesh-candidate limit. Configuration, environment, inference, processing, unknown, and interruption failures do not consume speculative retries. When a worker failure leaves remote inference outcome unknown, resume stops and requires service-state inspection before another submission.

Recipe resume applies the same conservative check to prop/model children. Reuse requires a succeeded concept-generation record, an intact candidate artifact, and matching child brief/prompt and configured workflow/quality identity where available. Missing legacy provenance makes the child stale. `retexture` reuses a processed mesh only when a succeeded mesh-preparation or material-assembly record links the exact source mesh and settings to the processed-mesh artifact and its hash still matches; otherwise Blender receives the source GLB for processing.

The recorded backend facts remain bounded by what the worker observes. Unknown model-weight or custom-node revisions cannot establish equivalence across executions. Final publication records hashes and derivation links, but `approve-texture` does not adopt publication outputs as a resume cache; existing final files require the explicit overwrite path before replacement. Reuse evidence is not visual, structural, readiness, qualification, live-inference, or Unity-runtime evidence.

Provenance wrappers distinguish `{ "status": "known", "value": ... }`, `{ "status": "unavailable", "reason": ... }`, and `{ "status": "not_recorded", "reason": ... }`. A workflow hash identifies graph bytes, not installed weights or custom-node revisions. A configured model filename is only a filename fact. Legacy v3 assets migrate with no synthetic execution or artifact records and carry `lineage_status.status: "unknown"` with the reason `legacy manifest predates execution lineage`.

```json
{
  "artifacts": {
    "concept": {
      "id": "concept",
      "type": "image.concept",
      "status": "ready",
      "path": "ai/assets/candidates/pilot/concept.png",
      "provenance": {"workflow": "image_text2img_api.json", "seed": 1234},
      "approval": {"status": "approved"}
    },
    "model": {
      "id": "model",
      "type": "model.glb",
      "status": "ready",
      "path": "Assets/Art/Generated/Characters/pilot/model.glb",
      "derived_from": [{"asset_id": "pilot-id", "output_id": "concept"}],
      "approval": {"status": "pending"}
    },
    "rig": {
      "id": "rig",
      "type": "model.rigged",
      "status": "candidate",
      "path": "ai/assets/candidates/pilot/rigged.fbx",
      "derived_from": [{"asset_id": "pilot-id", "output_id": "model"}],
      "approval": {"status": "pending"},
      "validation": {"status": "not_run", "warnings": ["Deformation and Unity playback need review"]}
    }
  }
}
```

The legacy `outputs` map remains a path-only compatibility view. `register_artifact()` updates both views. Artifacts are independent, so a model may be approved while a rig remains pending. `parent_id`, `dependencies`, and `derived_from` use IDs rather than paths.

For file-backed ComfyUI generation, provenance can include the workflow SHA-256, sidecar ID/version, model identifiers, and seed. A graph hash does not identify installed custom-node revisions or model weights. Unknown values stay unknown. See the [workflow inventory](WORKFLOWS.md).
