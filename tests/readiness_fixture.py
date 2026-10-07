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
