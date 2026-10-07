#!/usr/bin/env python3
"""Inspect a processed Blend without changing it; run through Blender's Python."""
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

sys.path.append(os.environ.get("SLOPFORGE_PACKAGE_ROOT", str(Path(__file__).resolve().parents[1])))
from slopforge.character_readiness import classify_character_readiness


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

    # glTF duplicates vertices along UV and normal seams; they still share geometry.
    positions = {}
    for vertex in mesh.vertices:
        other = positions.setdefault(tuple(vertex.co), vertex.index)
        root = find(other)
        if root != vertex.index:
            parent[vertex.index] = root
            size[root] += 1

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


def topology_edge_counts(mesh, weld_distance):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld_distance)
    boundary_edges = sum(edge.is_boundary for edge in bm.edges)
    nonmanifold_edges = sum(not edge.is_manifold and not edge.is_boundary for edge in bm.edges)
    bm.free()
    return boundary_edges, nonmanifold_edges


def inspect(source, face_budget):
    errors, warnings = [], []
    extension = source.suffix.lower()
    if extension == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(source))
    elif extension == ".glb":
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(source))
    elif extension == ".fbx":
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=str(source))
    else:
        raise ValueError(f"Unsupported model format for inspection: {extension or 'no extension'}")
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
    polygons = [polygon for obj in objects for polygon in obj.data.polygons]
    zero_area_faces = sum(polygon.area <= 1e-12 for polygon in polygons)
    zero_normals = sum(polygon.normal.length <= 1e-8 for polygon in polygons)
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
    weld_distance = max(dimensions) * 1e-5
    topology_edges = [topology_edge_counts(obj.data, weld_distance) for obj in objects]
    boundary_edges = sum(item[0] for item in topology_edges)
    nonmanifold_edges = sum(item[1] for item in topology_edges)
    object_bounds = []
    for obj in objects:
        points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        obj_min = [min(point[axis] for point in points) for axis in range(3)]
        obj_max = [max(point[axis] for point in points) for axis in range(3)]
        object_bounds.append({"name": obj.name, "bounds_min": obj_min, "bounds_max": obj_max,
                              "dimensions": [obj_max[i] - obj_min[i] for i in range(3)],
                              "origin": [float(value) for value in obj.matrix_world.translation],
                              "rotation_degrees": [math.degrees(value) for value in obj.rotation_euler]})
    measured = {"mesh_objects": len(objects), "vertex_count": vertices, "face_count": faces,
                "bounds_min": minimum, "bounds_max": maximum, "dimensions": dimensions, "origins": origins,
                "objects": object_bounds,
                "uv_layers": uv_layers, "material_count": len(materials), "image_texture_count": len(image_nodes),
                "missing_textures": missing_textures, "transforms_applied": scales_applied,
                "normal_count": len(polygons), "zero_normal_count": zero_normals,
                "degenerate_face_count": zero_area_faces,
                "component_count": components, "boundary_edge_count": boundary_edges,
                "nonmanifold_edge_count": nonmanifold_edges, "face_budget": face_budget}
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
        raise SystemExit("Usage: blender --background --python blender/inspect_model.py -- model.{blend,glb,fbx} validation.json face_budget")
    source, output, budget = Path(args[0]).resolve(), Path(args[1]).resolve(), int(args[2])
    if not source.is_file():
        raise SystemExit(f"Model file not found: {source}")
    result = inspect(source, budget)
    result["animation_readiness"] = classify_character_readiness(result)
    write_result(output, result)


if __name__ == "__main__":
    main()
