# Typed 3D asset outputs

Manifest schema version 4 keeps each asset's path-only `outputs` compatibility map and adds execution lineage for the existing prop pipeline. A character or recipe may also record typed outputs. A file path is a location; the artifact's SHA-256 identifies its content.

## Prop execution lineage

Each v4 asset may contain `executions: []`. A prop invocation stores its unique execution ID, optional parent execution ID, canonical semantic identity inputs and digest, start time, status, and ordered stage attempts. Each stage stores its name and attempt number, status (`pending`, `running`, `succeeded`, or `failed`), timestamps, upstream and output artifact references, effective settings, provenance facts, and error text. A stage's `pending` state is saved before it is changed to `running`; terminal states and available hashes are saved after the boundary.

An artifact reference includes an execution-scoped ID, type, project-relative path, SHA-256 of the file bytes, producing stage and attempt, and `derived_from` artifact IDs and content hashes. Paths remain useful for locating files but never substitute for hashes. The existing candidate, `model_attempts`, source, and `outputs` fields remain compatibility views alongside these records.

Prop executions use the durable boundaries `concept_generation`, `conditioning_preparation`, `mesh_workflow_execution`, `mesh_raw_acquisition` where a workflow returns a separate raw mesh, `mesh_preparation` where used, `material_generation`, `mesh_output_acquisition`, `material_map_acquisition` for swatch-derived maps, `material_assembly_export`, and `final_publication`. Repeated stage entries retain attempt/outcome history. The 3D worker saves fully bound workflow identities and bindings as stage provenance before queueing; successful image-generation sidecars record source/effective graph identity and bindings after output acquisition. Generated-output bindings remain stage evidence and do not alter the semantic execution identity. Package 1 records these facts; it does not decide whether an artifact can be reused or whether a run can resume.

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
