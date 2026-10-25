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
from mathutils.kdtree import KDTree

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


def component_details(obj):
    mesh = obj.data
    parent = list(range(len(mesh.vertices)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    positions = {}
    for vertex in mesh.vertices:
        other = positions.setdefault(tuple(vertex.co), vertex.index)
        other_root, vertex_root = find(other), find(vertex.index)
        if other_root != vertex_root:
            parent[vertex_root] = other_root
    for polygon in mesh.polygons:
        if not polygon.vertices:
            continue
        first = find(polygon.vertices[0])
        for index in polygon.vertices[1:]:
            other = find(index)
            if first != other:
                parent[other] = first
    groups = {}
    for vertex in mesh.vertices:
        groups.setdefault(find(vertex.index), []).append(vertex.index)
    face_groups = {root: [] for root in groups}
    for polygon in mesh.polygons:
        if polygon.vertices:
            face_groups[find(polygon.vertices[0])].append(polygon)
    ordered = sorted(groups.items(), key=lambda item: min(item[1]))
    details = []
    for component_index, (root, indices) in enumerate(ordered):
        points = [obj.matrix_world @ mesh.vertices[index].co for index in indices]
        minimum = [float(min(point[axis] for point in points)) for axis in range(3)]
        maximum = [float(max(point[axis] for point in points)) for axis in range(3)]
        details.append({"object_name": obj.name, "component_index": component_index,
                        "vertex_count": len(indices), "face_count": len(face_groups[root]),
                        "source_vertex_indices": indices, "bounds_min": minimum, "bounds_max": maximum})
    return details


def topology_diagnostics(obj, weld_distance):
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld_distance)
    tree = KDTree(len(mesh.vertices))
    for vertex in mesh.vertices:
        tree.insert(vertex.co, vertex.index)
    tree.balance()

    def source_indices(position):
        return sorted(index for _, index, _ in tree.find_range(position, weld_distance))

    world = obj.matrix_world
    diagnostics = []
    for edge in bm.edges:
        if edge.is_boundary:
            kind = "boundary_edge"
        elif not edge.is_manifold:
            kind = "nonmanifold_edge"
        else:
            continue
        endpoints = sorted((edge.verts[0].co.copy(), edge.verts[1].co.copy()), key=lambda co: tuple(co))
        endpoint_indices = [source_indices(point) for point in endpoints]
        points = [world @ point for point in endpoints]
        diagnostics.append({"object_name": obj.name, "component_index": None, "kind": kind,
                            "source_vertex_indices": sorted({index for group in endpoint_indices for index in group}),
                            "endpoint_vertex_indices": endpoint_indices,
                            "positions": [[float(value) for value in point] for point in points],
                            "midpoint": [float(value) for value in (points[0] + points[1]) / 2]})
    bm.free()
    for polygon in mesh.polygons:
        if polygon.area > 1e-12:
            continue
        center = world @ polygon.center
        diagnostics.append({"object_name": obj.name, "component_index": None, "kind": "degenerate_face",
                            "polygon_index": polygon.index, "source_vertex_indices": list(polygon.vertices),
                            "center": [float(value) for value in center], "area": float(polygon.area)})
    component_of = {index: part["component_index"] for part in component_details(obj)
                    for index in part["source_vertex_indices"]}
    for item in diagnostics:
        item["component_index"] = min((component_of[index] for index in item["source_vertex_indices"]
                                       if index in component_of), default=None)
    return sorted(diagnostics, key=lambda item: (item["object_name"], item["component_index"] or 0,
                                                 item["kind"], item.get("positions", [item.get("center", [])]),
                                                 item.get("polygon_index", -1)))


def footprint_quadrants(objects, minimum, maximum, cells=32):
    """Share of each footprint quadrant (+X+Y, -X+Y, -X-Y, +X-Y about the bounds centre) that holds geometry,
    on a top-down grid. An L-shaped corner leaves one quadrant nearly empty."""
    width, depth = maximum[0] - minimum[0], maximum[1] - minimum[1]
    if width <= 1e-9 or depth <= 1e-9:
        return [0.0, 0.0, 0.0, 0.0]
    cell_area = width * depth / cells ** 2
    occupied = set()

    def mark(x, y):
        occupied.add((min(cells - 1, max(0, int((x - minimum[0]) / width * cells))),
                      min(cells - 1, max(0, int((y - minimum[1]) / depth * cells)))))
    for obj in objects:
        points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
        for point in points:
            mark(point.x, point.y)
        # Decimated flat faces have few vertices, so sample each face across its top-down area as well.
        for polygon in obj.data.polygons:
            corners = [points[index] for index in polygon.vertices]
            for b, c in zip(corners[1:], corners[2:]):
                a = corners[0]
                area = abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)) / 2
                steps = math.ceil(math.sqrt(area / cell_area)) * 2 if area > cell_area / 4 else 0
                for i in range(1, steps):
                    for j in range(1, steps - i):
                        u, v = i / steps, j / steps
                        mark(a.x + u * (b.x - a.x) + v * (c.x - a.x), a.y + u * (b.y - a.y) + v * (c.y - a.y))
    half = cells // 2
    quadrants = (lambda i, j: i >= half and j >= half, lambda i, j: i < half and j >= half,
                 lambda i, j: i < half and j < half, lambda i, j: i >= half and j < half)
    return [sum(1 for cell in occupied if inside(*cell)) / (half * half) for inside in quadrants]


def corner_profile(points, quadrants, minimum, maximum):
    """For an L corner (one footprint quarter nearly empty): the open side's (x, y) signs and each arm's thickness.

    An arm is measured from its outer edge, on the open side of the other arm, where the two do not overlap.
    Returns None for other shapes.
    """
    if not quadrants or min(quadrants) > 0.15:
        return None
    open_index = quadrants.index(min(quadrants))
    ox, oy = (1 if open_index in (0, 3) else -1), (1 if open_index in (0, 1) else -1)
    centre_x, centre_y = (minimum[0] + maximum[0]) / 2, (minimum[1] + maximum[1]) / 2
    width, depth = maximum[0] - minimum[0], maximum[1] - minimum[1]
    outer_x = minimum[0] if ox > 0 else maximum[0]
    outer_y = minimum[1] if oy > 0 else maximum[1]
    along_y = sorted(abs(p[0] - outer_x) for p in points if (p[1] - centre_y) * oy > 0.1 * depth)
    along_x = sorted(abs(p[1] - outer_y) for p in points if (p[0] - centre_x) * ox > 0.1 * width)
    if not along_y or not along_x:
        return None
    return (ox, oy), [along_y[int(0.98 * (len(along_y) - 1))], along_x[int(0.98 * (len(along_x) - 1))]]


def arm_taper(points, signs, minimum, maximum):
    """Each arm's thickness across the middle of its far half over that across its end (at least 1).

    An L's arms are even slabs: 1.00-1.03 on every M2 corner published by 2026-10-23. M2-v2 run T2's corner came out
    a wedge whose arms thinned from 2.9 m beside the other arm to 0.46 m at the end; it passed the open-quarter
    check. Thickness is the 98th percentile of the distance from the arm's outer face, as in corner_profile.
    """
    ox, oy = signs
    outer = (minimum[0] if ox > 0 else maximum[0], minimum[1] if oy > 0 else maximum[1])
    spans = (maximum[0] - minimum[0], maximum[1] - minimum[1])
    ratios = []
    for axis in (0, 1):  # the arm along y is measured across x, and the other way round
        other, thickness = 1 - axis, []
        for start, end in ((0.5, 0.75), (0.75, 1.0)):  # along the arm, from the other arm's outer face
            across = sorted(abs(p[axis] - outer[axis]) for p in points
                            if start * spans[other] <= abs(p[other] - outer[other]) <= end * spans[other])
            if not across:
                return None
            thickness.append(across[int(0.98 * (len(across) - 1))])
        ratios.append(round(max(thickness) / max(min(thickness), 1e-6), 3))
    return ratios


def inspect(source, face_budget, real_scale=False):
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
    mesh_without_uv_count = sum(not obj.data.uv_layers for obj in objects)
    polygons = [polygon for obj in objects for polygon in obj.data.polygons]
    # Sum of per-face UV areas on the active UV layer; overlapping faces count twice, so this is not unique coverage.
    uv_area, uv_loops, uv_loops_outside = 0.0, 0, 0
    for obj in objects:
        layer = obj.data.uv_layers.active
        if not layer:
            continue
        for polygon in obj.data.polygons:
            points = [layer.data[index].uv for index in polygon.loop_indices]
            uv_area += abs(sum(a.x * b.y - b.x * a.y for a, b in zip(points, points[1:] + points[:1]))) / 2
            uv_loops += len(points)
            uv_loops_outside += sum(not (0 <= p.x <= 1 and 0 <= p.y <= 1) for p in points)
    zero_area_faces = sum(polygon.area <= 1e-12 for polygon in polygons)
    zero_normals = sum(polygon.normal.length <= 1e-8 for polygon in polygons)
    assigned_materials = []
    for obj in objects:
        indices = {polygon.material_index for polygon in obj.data.polygons}
        assigned_materials.append([obj.data.materials[index] if 0 <= index < len(obj.data.materials) else None
                                   for index in indices])
    materials = [material for assignments in assigned_materials for material in assignments if material]
    mesh_without_material_count = sum(not assignments or any(material is None for material in assignments)
                                      for assignments in assigned_materials)
    def linked_images(material):
        if not material or not material.use_nodes or not material.node_tree:
            return []
        # ponytail: node-link presence only; traverse active shader outputs if graph qualification is added.
        return [node.image for node in material.node_tree.nodes
                if node.type == "TEX_IMAGE" and node.image
                and any(output.is_linked for output in node.outputs)]
    image_nodes = [image for material in materials for image in linked_images(material)]
    mesh_without_texture_count = sum(
        not any(linked_images(material) for material in assignments) for assignments in assigned_materials)
    missing_textures = []
    for image in image_nodes:
        filepath = Path(bpy.path.abspath(image.filepath))
        if not image.packed_file and not filepath.is_file():
            missing_textures.append(str(filepath))
    # World matrix: glTF imports use quaternion rotation, and parents can rotate or scale a mesh too.
    scales_applied = all(rotation.angle < 1e-4 and all(abs(value - 1.0) < 1e-4 for value in scale)
                         for _, rotation, scale in (obj.matrix_world.decompose() for obj in objects))
    component_sizes = [connected_components(obj.data) for obj in objects]
    # A weapon's moving parts are separate pieces by design; the component budget counts the rest.
    components = sum(len(sizes) for obj, sizes in zip(objects, component_sizes) if "slopforge_part" not in obj)
    parts = [{"name": obj.name, "kind": obj["slopforge_part"], "faces": len(obj.data.polygons),
              "components": len(sizes), "parent": obj.parent.name if obj.parent else None,
              "pivot": [float(value) for value in obj.matrix_world.translation]}
             for obj, sizes in zip(objects, component_sizes) if "slopforge_part" in obj]
    part_coverage = next(({name: float(value) for name, value in json.loads(obj["slopforge_part_coverage"]).items()}
                          for obj in objects if isinstance(obj.get("slopforge_part_coverage"), str)), None)
    part_overflow = next(({name: float(value) for name, value in json.loads(obj["slopforge_part_overflow"]).items()}
                          for obj in objects if isinstance(obj.get("slopforge_part_overflow"), str)), None)
    component_records = [part for obj in objects for part in component_details(obj)]
    weld_distance = max(dimensions) * 1e-5
    topology_edges = [topology_edge_counts(obj.data, weld_distance) for obj in objects]
    boundary_edges = sum(item[0] for item in topology_edges)
    nonmanifold_edges = sum(item[1] for item in topology_edges)
    topology_records = [record for obj in objects for record in topology_diagnostics(obj, weld_distance)]
    object_bounds = []
    for obj in objects:
        points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        obj_min = [min(point[axis] for point in points) for axis in range(3)]
        obj_max = [max(point[axis] for point in points) for axis in range(3)]
        object_bounds.append({"name": obj.name, "bounds_min": obj_min, "bounds_max": obj_max,
                              "dimensions": [obj_max[i] - obj_min[i] for i in range(3)],
                              "origin": [float(value) for value in obj.matrix_world.translation],
                              "rotation_degrees": [math.degrees(value) for value in obj.rotation_euler]})
    auxiliary_objects = [{"name": obj.name, "type": obj.type} for obj in bpy.context.scene.objects
                         if obj.type not in {"MESH", "CAMERA", "LIGHT"}]
    coordinate_system = {"unit_system": bpy.context.scene.unit_settings.system or "NONE",
                         "scale_length": float(bpy.context.scene.unit_settings.scale_length),
                         "up_axis": "Z", "forward_axis": "-Y", "basis": "Blender world",
                         "measured_unit": "Blender units"}
    measured = {"mesh_objects": len(objects), "vertex_count": vertices, "face_count": faces,
                **({"part_coverage": part_coverage} if part_coverage is not None else {}),
                **({"part_overflow": part_overflow} if part_overflow is not None else {}),
                **({"part_components": {part["name"]: part["components"] for part in parts}} if parts else {}),
                "bounds_min": minimum, "bounds_max": maximum, "dimensions": dimensions, "origins": origins,
                "objects": object_bounds,
                "uv_layers": uv_layers, "mesh_without_uv_count": mesh_without_uv_count,
                "uv_area_sum": uv_area, "uv_loop_outside_unit_fraction": (uv_loops_outside / uv_loops if uv_loops else 0.0),
                "material_count": len(materials), "mesh_without_material_count": mesh_without_material_count,
                "image_texture_count": len(image_nodes), "mesh_without_texture_count": mesh_without_texture_count,
                "missing_textures": missing_textures,
                "coordinate_system": coordinate_system, "rest_pose_status": "visual_review_required",
                "auxiliary_objects": auxiliary_objects,
                "transforms_applied": scales_applied,
                "normal_count": len(polygons), "zero_normal_count": zero_normals,
                "degenerate_face_count": zero_area_faces,
                "component_count": components, "boundary_edge_count": boundary_edges,
                "nonmanifold_edge_count": nonmanifold_edges, "component_details": component_records,
                "topology_diagnostics": topology_records, "face_budget": face_budget,
                "footprint_quadrants": footprint_quadrants(objects, minimum, maximum), "parts": parts}
    points = [obj.matrix_world @ vertex.co for obj in objects for vertex in obj.data.vertices]
    corner = corner_profile(points, measured["footprint_quadrants"], minimum, maximum)
    measured["arm_thickness"] = corner[1] if corner else None
    measured["arm_taper"] = arm_taper(points, corner[0], minimum, maximum) if corner else None
    stretches = [float(obj["slopforge_axis_stretch"]) for obj in objects if "slopforge_axis_stretch" in obj]
    measured["axis_stretch"] = max(stretches) if stretches else None
    views = [list(obj["slopforge_concept_view"]) for obj in objects if "slopforge_concept_view" in obj]
    if views:  # [fit, theta, phi] of the view a weapon was oriented from
        measured["concept_view"] = {"fit": views[0][0], "theta": views[0][1], "phi": views[0][2],
                                    **({"tip_alignment": views[0][3]} if len(views[0]) > 3 else {})}
    if faces > face_budget:
        errors.append(f"face count {faces} exceeds budget {face_budget}")
    if not uv_layers:
        errors.append("mesh has no UV map")
    if uv_layers and uv_area <= 1e-9:
        warnings.append("UV map has zero total area; textures cannot map onto the surface")
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
    elif max(dimensions) > 1.5 and not real_scale:
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
    real_scale = "--real-scale" in args  # sized in metres (kit modules), not normalised to 1
    args = [arg for arg in args if arg != "--real-scale"]
    if len(args) != 3:
        raise SystemExit("Usage: blender --background --python blender/inspect_model.py -- "
                         "model.{blend,glb,fbx} validation.json face_budget [--real-scale]")
    source, output, budget = Path(args[0]).resolve(), Path(args[1]).resolve(), int(args[2])
    if not source.is_file():
        raise SystemExit(f"Model file not found: {source}")
    result = inspect(source, budget, real_scale)
    result["animation_readiness"] = classify_character_readiness(result)
    write_result(output, result)


if __name__ == "__main__":
    main()
