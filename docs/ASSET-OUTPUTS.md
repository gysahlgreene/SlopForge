# Typed asset outputs

Manifest schema version 3 adds optional typed output records to the existing asset model. Atomic assets keep using the current `outputs` path map and need no new fields. Compound assets can add an `artifacts` map, a `parent_id`, and `dependencies` when those relationships are useful.

Each artifact has a stable ID, type, relative path, generation status, provenance, validation, approval state, and optional `derived_from` references:

```json
{
  "artifacts": {
    "sprites.idle": {
      "id": "sprites.idle",
      "type": "image.sprite_sheet",
      "status": "candidate",
      "path": "Assets/Characters/pilot/idle.png",
      "derived_from": [{"asset_id": "pilot-id", "output_id": "concept"}],
      "provenance": {"workflow": "sprite-sheet.json", "seed": 1234},
      "approval": {"status": "pending"},
      "validation": {"status": "passed", "errors": [], "warnings": []}
    }
  },
  "outputs": {"sprites.idle": "Assets/Characters/pilot/idle.png"}
}
```

The legacy `outputs` map remains a path-only compatibility view. `register_artifact()` updates both views. Artifact records are independent, so one output can be approved while another remains pending. Validation and provenance live on the artifact they describe.

`parent_id` is the stable asset ID of the owning pack or character. `children_of()` derives child assets from those one-way links, avoiding a duplicated child list. `dependencies` contains asset IDs and may name a required output ID. `derived_from` records which output(s) produced a particular artifact. Relationships use IDs rather than paths; paths remain project-relative POSIX paths.

Default atomic records stay unchanged. Schema-v2 manifests are upgraded by copying all fields and changing only `schema_version`; older manifests retain their original fields under each record's `legacy` value. Unsupported future schema versions are rejected instead of being silently rewritten.

Representative compound structure:

The following abbreviated shape shows how different products can live under one character asset; each artifact uses the complete fields shown above.

```json
{
  "id": "pilot-id",
  "type": "character",
  "artifacts": {
    "concept": {"id": "concept", "type": "image.concept", "path": "ai/candidates/pilot.png"},
    "portrait": {"id": "portrait", "type": "image.portrait", "path": "Assets/Characters/pilot/portrait.png"},
    "model": {"id": "model", "type": "model.glb", "path": "Assets/Characters/pilot/model.glb"},
    "rig": {"id": "rig", "type": "model.rigged", "path": "Assets/Characters/pilot/rigged.fbx"},
    "animations.idle": {"id": "animations.idle", "type": "animation.fbx", "path": "Assets/Characters/pilot/idle.fbx"}
  }
}
```

This schema represents outputs and their relationships; recipe scheduling, aggregate review, and bulk migrations are separate features.
