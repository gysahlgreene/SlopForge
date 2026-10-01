#!/usr/bin/env python3
"""Inspect a processed Blend without changing it; run through Blender's Python."""
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector


def write_result(path, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def connected_components(mesh):
    parent = list(range(len(mesh.vertices)))
    size = [1] * len(parent)

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for polygon in mesh.polygons:
        vertices = polygon.vertices
        if not vertices:
            continue
        first = find(vertices[0])
        for vertex in vertices[1:]:
            other = find(vertex)
            if first != other:
                parent[other] = first
                size[first] += size[other]
    return sorted((size[i] for i in range(len(parent)) if find(i) == i), reverse=True)


def inspect(blend, face_budget):
    errors, warnings = [], []
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not objects:
        errors.append("no mesh object exists in the Blend")
        return {"status": "failed", "errors": errors, "warnings": warnings, "measured": {"mesh_objects": 0}}
    vertices = sum(len(obj.data.vertices) for obj in objects)
    faces = sum(len(obj.data.polygons) for obj in objects)
    world_points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    minimum = [min(point[axis] for point in world_points) for axis in range(3)]
    maximum = [max(point[axis] for point in world_points) for axis in range(3)]
    dimensions = [maximum[i] - minimum[i] for i in range(3)]
    origins = [[float(value) for value in obj.matrix_world.translation] for obj in objects]
    uv_layers = sum(len(obj.data.uv_layers) for obj in objects)
    materials = [material for obj in objects for material in obj.data.materials if material]
    image_nodes = [node.image for material in materials if material.use_nodes for node in material.node_tree.nodes if node.type == "TEX_IMAGE" and node.image]
    missing_textures = []
    for image in image_nodes:
        filepath = Path(bpy.path.abspath(image.filepath))
        if not image.packed_file and not filepath.is_file():
            missing_textures.append(str(filepath))
    scales_applied = all(all(abs(value - 1.0) < 1e-4 for value in obj.scale) and all(abs(value) < 1e-4 for value in obj.rotation_euler) for obj in objects)
    component_sizes = [connected_components(obj.data) for obj in objects]
    components = sum(len(sizes) for sizes in component_sizes)
    measured = {"mesh_objects": len(objects), "vertex_count": vertices, "face_count": faces,
                "bounds_min": minimum, "bounds_max": maximum, "dimensions": dimensions, "origins": origins,
                "uv_layers": uv_layers, "material_count": len(materials), "image_texture_count": len(image_nodes),
                "missing_textures": missing_textures, "transforms_applied": scales_applied,
                "component_count": components, "face_budget": face_budget}
    if faces > face_budget:
        errors.append(f"face count {faces} exceeds budget {face_budget}")
    if not uv_layers:
        errors.append("mesh has no UV map")
    if not materials:
        errors.append("mesh has no material")
    if missing_textures:
        errors.append("one or more referenced texture files are missing")
    if not scales_applied:
        errors.append("mesh rotation or scale is not applied")
    if not all(math.isfinite(value) and value > 1e-5 for value in dimensions):
        errors.append("mesh bounds are degenerate or non-finite")
    if any(not all(minimum[axis] - 1e-4 <= origin[axis] <= maximum[axis] + 1e-4 for axis in range(3)) for origin in origins):
        warnings.append("one or more mesh origins fall outside the combined bounds")
    if max(dimensions) > 100:
        errors.append("mesh bounds are implausibly large")
    elif max(dimensions) > 1.5:
        warnings.append("largest mesh dimension exceeds expected normalized scale")
    if components > len(objects):
        warnings.append(f"mesh contains {components} disconnected components; inspect for detached geometry")
    if any(size <= max(8, int(vertices * 0.001)) for sizes in component_sizes for size in sizes[1:]):
        warnings.append("mesh has a very small disconnected component; inspect for debris")
    if not image_nodes:
        warnings.append("no image textures are connected to mesh materials")
    return {"status": "failed" if errors else "passed_with_warnings" if warnings else "passed", "errors": errors, "warnings": warnings, "measured": measured}


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(args) != 3:
        raise SystemExit("Usage: blender --background --python blender/inspect_model.py -- model.blend validation.json face_budget")
    blend, output, budget = Path(args[0]).resolve(), Path(args[1]).resolve(), int(args[2])
    if not blend.is_file():
        raise SystemExit(f"Blend file not found: {blend}")
    write_result(output, inspect(blend, budget))


if __name__ == "__main__":
    main()
