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
