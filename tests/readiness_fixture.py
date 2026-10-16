def complete_measurements(**overrides):
    measurements = {
        "mesh_objects": 1, "vertex_count": 800, "face_count": 1400,
        "dimensions": [0.7, 1.8, 0.5], "transforms_applied": True,
        "component_count": 1, "boundary_edge_count": 0, "nonmanifold_edge_count": 0,
        "degenerate_face_count": 0, "zero_normal_count": 0, "face_budget": 60000,
        "uv_layers": 1, "mesh_without_uv_count": 0, "material_count": 1,
        "mesh_without_material_count": 0, "image_texture_count": 1,
        "mesh_without_texture_count": 0, "missing_textures": [],
        "coordinate_system": {"unit_system": "METRIC", "scale_length": 1.0,
                              "up_axis": "Z", "forward_axis": "-Y", "basis": "Blender world",
                              "measured_unit": "Blender units"},
        "rest_pose_status": "reviewed", "auxiliary_objects": [],
    }
    measurements.update(overrides)
    return measurements


def approve_source_review(root, manifest, selector, source_output="model", readiness_report_fallback=False):
    import json
    import hashlib
    from pathlib import Path
    from PIL import Image
    from slopforge.character_quality import (create_character_source_review,
        classify_character_source_findings, approve_character_source_review)
    from slopforge.manifest import find_asset

    root = Path(root)
    asset = find_asset(manifest, selector)
    model = asset["artifacts"][source_output]
    def image(relative):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4), (80, 100, 120)).save(path)
    for view in ("front", "side", "rear", "three_quarter"):
        relative = f"Assets/Characters/{asset['name']}/{view}.png"
        image(relative)
        asset["artifacts"][f"preview_{view}"] = {"id": f"preview-{view}", "type": f"preview.{view}",
            "path": relative, "status": "ready", "approval": {"status": "approved"}}
    texture = f"Assets/Characters/{asset['name']}/normal.png"
    image(texture)
    asset["artifacts"]["normal"] = {"id": "normal", "type": "texture.normal", "path": texture,
        "status": "ready", "approval": {"status": "approved"}}
    if not readiness_report_fallback:
        inspection_path = f"Assets/Characters/{asset['name']}/inspection.json"
        inspection = {"source": {"artifact_id": model["id"], "sha256": hashlib.sha256((root / model["path"]).read_bytes()).hexdigest()},
            "measured": {"component_count": 1, "boundary_edge_count": 0, "nonmanifold_edge_count": 0,
                "degenerate_face_count": 0, "component_details": [{"object_name": "Body", "component_index": 0,
                    "vertex_count": 3, "face_count": 1, "bounds_min": [0,0,0], "bounds_max": [1,1,1]}],
                "topology_diagnostics": []}}
        path = root / inspection_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(inspection))
        asset["artifacts"]["inspection"] = {"id": "inspection", "type": "inspection.json", "path": inspection_path,
            "status": "ready", "approval": {"status": "approved"}}
    concepts = {}
    for view in ("front", "left", "rear"):
        concepts[view] = f"ai/concepts/{view}.png"
        image(concepts[view])
    image("ai/concepts/crop.png")
    image(f"Assets/Characters/{asset['name']}/closeup.png")
    review = create_character_source_review(root, manifest, selector, concepts,
        [{"name": "body", "concept_crop": "ai/concepts/crop.png",
          "model_closeup": f"Assets/Characters/{asset['name']}/closeup.png"}], source_output=source_output)
    classify_character_source_findings(root, manifest, selector, review["id"],
        {finding["id"]: "intentional" for finding in review["findings"]})
    approve_character_source_review(root, manifest, selector, review["id"])
    return review
