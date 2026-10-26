"""Hybrid parts, step three: the generated surface as one glTF node per part (docs/WEAPONS.md, Hybrid parts).

Usage: blender --background --python hybrid_apply.py -- request.json
request.json: {"surface": TRELLIS.2 mesh (GLB), "labels": .npy of part names per face in hybrid_graph.py's order,
               "out": GLB path}

The faces keep their UVs and materials; each node is named after its part ("body" for the rest), which the final
pass tags by (prepare_model.py --parts-json) before it separates the parts, sets their pivots and closes the
openings the split left.
"""
import json
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np


def refine_cut(bm, labels, rings=2, iterations=4):
    """Split the faces along the cut between labels instead of along their edges; returns the labels of bm's faces.

    Labels are per face, so on a reduced mesh's large triangles a cut can only step along their edges: HP12's
    slide/frame cut ran in triangle-sized teeth, flush at rest, and racked back they parted and showed the closing
    faces between them as grey shards (2026-10-26). Each vertex takes its faces' area-weighted share of each label,
    smoothed `iterations` times within `rings` of the cut; an edge whose ends prefer different labels is split where
    their shares are equal, and a face crossed twice is split between the two points. Away from the cut nothing
    changes; a cut along a crease, its vertices shared evenly, stays on it."""
    names = sorted(set(labels))
    position = {name: index for index, name in enumerate(names)}
    bm.verts.index_update()
    bm.faces.index_update()
    share = np.zeros((len(bm.verts), len(names)))
    for face in bm.faces:
        area = face.calc_area()
        for vertex in face.verts:
            share[vertex.index, position[labels[face.index]]] += area
    share /= np.maximum(share.sum(1, keepdims=True), 1e-20)
    band = (share > 1e-9).sum(1) > 1
    for _ in range(rings):
        grown = band.copy()
        for edge in bm.edges:
            a, b = edge.verts[0].index, edge.verts[1].index
            if band[a] or band[b]:
                grown[a] = grown[b] = True
        band = grown
    neighbours = [[edge.other_vert(vertex).index for edge in vertex.link_edges] for vertex in bm.verts]
    for _ in range(iterations):
        mean = np.array([share[around].mean(0) if around else share[index] for index, around in enumerate(neighbours)])
        share = np.where(band[:, None], 0.5 * (share + mean), share)
    best = {vertex: int(share[vertex.index].argmax()) for vertex in bm.verts}
    original = {face: position[labels[face.index]] for face in bm.faces}
    crossings = {}
    for edge in list(bm.edges):
        a, b = edge.verts
        la, lb = best[a], best[b]
        if la == lb:
            continue
        above = share[a.index, la] - share[a.index, lb]  # a prefers la, b prefers lb
        below = share[b.index, la] - share[b.index, lb]
        t = above / (above - below) if above - below > 1e-12 else 0.5
        if not 0.2 < t < 0.8:
            continue  # the cut passes through the corner: a split this close to it leaves a sliver, which shaded as a
            # thin dark line on HP12's slide and showed its back (2026-10-26)
        faces = list(edge.link_faces)
        _edge, point = bmesh.utils.edge_split(edge, a, t)
        for face in faces:
            crossings.setdefault(face, []).append(point)
    for face, points in crossings.items():
        if len(points) == 2 and face.is_valid:
            new, _loop = bmesh.utils.face_split(face, points[0], points[1])
            original[new] = original[face]
    bm.faces.index_update()
    out = []
    for face in bm.faces:
        votes = [best[vertex] for vertex in face.verts if vertex in best]
        counts = np.bincount(votes, minlength=len(names)) if votes else np.zeros(len(names))
        winner = int(counts.argmax())
        out.append(names[winner if counts[winner] > counts.sum() / 2 else original.get(face, winner)])
    return out


def main(request):
    labels = np.load(request["labels"], allow_pickle=True).astype(str)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(request["surface"]))
    objects = sorted((o for o in bpy.context.scene.objects if o.type == "MESH" and o.data.polygons),
                     key=lambda o: o.name)
    total = sum(len(o.data.polygons) for o in objects)
    if total != len(labels):
        raise SystemExit(f"labels for {len(labels)} faces, the surface has {total}")
    for obj in objects:  # one mesh in world space, faces in the same order as hybrid_graph.py
        obj.data.transform(obj.matrix_world)
        obj.matrix_world.identity()
    if len(objects) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        bpy.ops.object.join()
    surface = bpy.context.view_layer.objects.active or objects[0]
    bm = bmesh.new()
    bm.from_mesh(surface.data)
    labels = np.array(refine_cut(bm, list(labels)))
    bm.to_mesh(surface.data)
    bm.free()
    counts = {}
    for name in sorted(set(labels)):
        bm = bmesh.new()
        bm.from_mesh(surface.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if labels[f.index] != name], context="FACES")
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        for material in surface.data.materials:
            mesh.materials.append(material)
        piece = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(piece)
        counts[name] = len(mesh.polygons)
    bpy.data.objects.remove(surface)
    bpy.ops.export_scene.gltf(filepath=str(request["out"]), export_format="GLB", export_yup=True)
    print("HYBRID_APPLY " + json.dumps(counts))


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text()))
