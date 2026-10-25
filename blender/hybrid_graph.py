"""Hybrid parts, step one: what the split of a generated surface needs (docs/WEAPONS.md, Hybrid parts).

Usage: blender --background --python hybrid_graph.py -- request.json
request.json: {"surface": TRELLIS.2 mesh (GLB), "parts": OmniPart's parts (GLB, one node per part, any frame),
               "concept": cutout (RGBA), "masks": {part name: mask PNG (L)}, "out": .npz path,
               "repaired": GLB path for the surface repaired into a closed manifold, which the split works on}

Writes, in the surface's own face order (every mesh object in name order, as hybrid_apply.py reads it):
centres, areas, normals; pairs of faces that share an edge (by vertex position, so UV seams do not cut the graph)
with the edge's length and the angle between the faces; surface vertices (to align the parts on); each part's
vertices and triangles as OmniPart made them; and per masked part a vote per face: +1 the concept's view sees the
face inside the mask, -1 outside, 0 unseen.
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from concept_view import fit_view, image_mask, view_axes  # noqa: E402


def mesh_objects():
    return sorted((o for o in bpy.context.scene.objects if o.type == "MESH" and o.data.polygons), key=lambda o: o.name)


def surface_arrays(objects):
    """World-space vertices and polygons of the objects in order, with each face's centre, area and normal."""
    vertices, polygons, centres, areas, normals = [], [], [], [], []
    for obj in objects:
        base = len(vertices)
        matrix = obj.matrix_world
        rotation = matrix.to_3x3().inverted_safe().transposed()
        vertices.extend(tuple(matrix @ v.co) for v in obj.data.vertices)
        for polygon in obj.data.polygons:
            polygons.append([base + index for index in polygon.vertices])
            centres.append(tuple(matrix @ polygon.center))
            areas.append(polygon.area * abs(matrix.determinant()) ** (2 / 3))
            normals.append(tuple((rotation @ polygon.normal).normalized()))
    return np.array(vertices), polygons, np.array(centres), np.array(areas), np.array(normals)


def face_graph(vertices, polygons, normals, digits=6):
    """Faces that share an edge, matched by the edge's end positions (a glTF splits vertices along UV seams)."""
    keys = [tuple(np.round(v, digits)) for v in vertices]
    edges = {}
    for face, polygon in enumerate(polygons):
        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
            key = (keys[a], keys[b]) if keys[a] <= keys[b] else (keys[b], keys[a])
            edges.setdefault(key, []).append(face)
    pairs, lengths, angles = [], [], []
    for (a, b), faces in edges.items():
        for i in range(len(faces)):
            for j in range(i + 1, len(faces)):
                pairs.append((faces[i], faces[j]))
                lengths.append(math.dist(a, b))
                cosine = float(np.clip(np.dot(normals[faces[i]], normals[faces[j]]), -1, 1))
                angles.append(math.degrees(math.acos(cosine)))
    return np.array(pairs, int).reshape(-1, 2), np.array(lengths), np.array(angles)


def mask_votes(vertices, polygons, centres, concept_path, masks):
    """+1 / -1 / 0 per face and masked part: seen inside, seen outside, unseen from the concept's best view."""
    concept = image_mask(concept_path)
    triangles = [p[:3] for p in polygons if len(p) == 3]
    rng = np.random.default_rng(0)
    weights = rng.dirichlet((1, 1, 1), size=(len(triangles), 4))
    samples = np.concatenate([np.einsum("tsk,tkd->tsd", weights, vertices[np.array(triangles)]).reshape(-1, 3),
                              vertices])
    fit, theta, phi = fit_view(samples, concept, full_turn=True)
    towards, right, up = view_axes(math.radians(theta), math.radians(phi))
    points = np.stack([vertices @ np.array(right), vertices @ np.array(up)], 1)
    rows, columns = np.nonzero(concept)
    low_c = np.array([columns.min(), rows.min()], float)
    span_c = np.array([columns.max(), rows.max()], float) - low_c
    low, span = points.min(0), points.max(0) - points.min(0)
    scale = span_c.max() / max(span.max(), 1e-9)
    centre_points = np.stack([centres @ np.array(right), centres @ np.array(up)], 1)
    pixels = np.round(low_c + (span_c - span * scale) / 2 + (centre_points - low) * scale).astype(int)
    tree = BVHTree.FromPolygons([Vector(v) for v in vertices], polygons)
    direction = -Vector(towards).normalized()  # from the camera towards the object
    extent = float(np.ptp(vertices, 0).max())
    seen = np.zeros(len(centres), bool)
    for i, centre in enumerate(centres):
        hit = tree.ray_cast(Vector(centre) - direction * extent * 4, direction)
        seen[i] = hit[0] is not None and (hit[0] - Vector(centre)).length < 0.003 * extent
    # A concept that looks along the object's thinnest axis (a weapon's flat side profile) shows each part through
    # the whole thickness: the far side, which it cannot see, lies under the same mask. A three-quarter view (a
    # chest) does not: there only the faces it sees vote (2026-10-25, the pistol's far side came out jagged).
    centred = vertices - vertices.mean(0)
    thinnest = np.linalg.eigh(centred.T @ centred)[1][:, 0]
    # Only a view within ~11 degrees of that axis: the pistol's 15-degree tilt moved its far side 3% (2026-10-25).
    through = abs(float(np.dot(thinnest, np.array(towards)))) > 0.98
    # A mask's edge, carried through a fitted view, lands a few millimetres off the surface's crease; at full weight
    # it pulled the cut across a smooth panel in teeth (2026-10-25). Within a margin of the edge (2% of the concept's
    # object) a face does not vote, and the crease decides.
    margin = max(1, round(0.02 * float(span_c.max())))
    votes = {}
    for name, path in masks.items():
        mask = image_mask(path, channel=0)
        core, hull = mask.copy(), mask.copy()
        for _ in range(margin):
            core &= np.roll(core, 1, 0) & np.roll(core, -1, 0) & np.roll(core, 1, 1) & np.roll(core, -1, 1)
            hull |= np.roll(hull, 1, 0) | np.roll(hull, -1, 0) | np.roll(hull, 1, 1) | np.roll(hull, -1, 1)
        inside = (pixels[:, 0] >= 0) & (pixels[:, 0] < mask.shape[1]) & (pixels[:, 1] >= 0) & (pixels[:, 1] < mask.shape[0])
        deep, near = np.zeros(len(centres), bool), np.zeros(len(centres), bool)
        deep[inside] = core[pixels[inside, 1], pixels[inside, 0]]
        near[inside] = hull[pixels[inside, 1], pixels[inside, 0]]
        voting = np.ones(len(centres), bool) if through else seen
        votes[name] = np.where(voting & deep, 1, np.where(voting & ~near, -1, 0)).astype(np.int8)
    return votes, {"theta": theta, "phi": phi, "fit": round(float(fit), 4), "seen": round(float(seen.mean()), 4),
                   "through": through}


def part_arrays(path):
    """Each node of the parts GLB as (vertices, triangles), keyed by its glTF node name."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mesh_cleanup import gltf_name
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    parts = {}
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or len(obj.data.polygons) < 4:
            continue
        mesh = obj.data
        mesh.calc_loop_triangles()
        matrix = obj.matrix_world
        vertices = np.array([tuple(matrix @ v.co) for v in mesh.vertices])
        triangles = np.array([tuple(t.vertices) for t in mesh.loop_triangles], int)
        parts[gltf_name(obj)] = (vertices, triangles)
    return parts


def repair_surface(source, destination):
    """The surface as one mesh with fully enclosed inner shells removed, written as a GLB the split works on (the
    face order hybrid_apply.py reads). Not repaired into a manifold: on a chest with 1,627 non-manifold edges the
    local repair deleted the faces around them and refilled the holes with untextured triangles across the lid
    (2026-10-25); openings with loose ends are capped instead (mesh_cleanup.close_openings)."""
    import bmesh
    from mesh_cleanup import remove_enclosed_components
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    objects = mesh_objects()
    for obj in objects:
        obj.data.transform(obj.matrix_world)
        obj.matrix_world.identity()
    if len(objects) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        bpy.ops.object.join()
    surface = bpy.context.view_layer.objects.active or objects[0]
    span = max(surface.dimensions)
    removed = remove_enclosed_components(surface.data, span * 1e-5)
    bm = bmesh.new()
    bm.from_mesh(surface.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=span * 1e-7)  # recorded: openings the split will meet
    boundary = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
    nonmanifold = sum(1 for edge in bm.edges if len(edge.link_faces) > 2)
    bm.free()
    bpy.ops.export_scene.gltf(filepath=str(destination), export_format="GLB", export_yup=True)
    return {"enclosed_vertices_removed": removed, "boundary_edges": boundary, "non_manifold_edges": nonmanifold}


def main(request):
    out = Path(request["out"])
    parts = part_arrays(request["parts"])
    repaired = repair_surface(request["surface"], request["repaired"])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(request["repaired"]))  # the faces in the order hybrid_apply.py reads
    vertices, polygons, centres, areas, normals = surface_arrays(mesh_objects())
    pairs, lengths, angles = face_graph(vertices, polygons, normals)
    votes, view = mask_votes(vertices, polygons, centres, request["concept"], request.get("masks") or {})
    arrays = {"centres": centres, "areas": areas, "normals": normals, "pairs": pairs, "lengths": lengths,
              "angles": angles, "surface_vertices": vertices, "part_names": np.array(sorted(parts))}
    for name, (part_vertices, triangles) in parts.items():
        arrays[f"part_vertices_{name}"] = part_vertices
        arrays[f"part_triangles_{name}"] = triangles
    for name, vote in votes.items():
        arrays[f"mask_{name}"] = vote
    np.savez_compressed(out, **arrays)
    report = {"faces": len(centres), "pairs": len(pairs), "parts": sorted(parts), "view": view, "repair": repaired}
    out.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print("HYBRID_GRAPH " + json.dumps(report))


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text()))
