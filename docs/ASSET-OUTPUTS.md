# Typed 3D asset outputs

Manifest schema version 3 supports typed artifacts alongside each asset's path-only `outputs` map. A character or recipe can record a concept, source model, processed model, rig, material maps, animation clips, and validation reports with stable artifact IDs, provenance, approval status, and derivation links.

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
