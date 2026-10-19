"""Graft a higher-resolution head onto a generated character body.

Usage: blender --background --python graft_head.py -- request.json

request.json: {"body": body.glb, "body_maps": dir, "head": head.glb, "head_maps": dir,
               "concept": full concept cutout (RGBA), "head_box": [x0, y0, x1, y1] (concept pixels of the
               head-source crop), "head_crop": head-source cutout (RGBA), "neck_row": concept pixel row,
               "output": out.glb, "report": report.json}

Single-image generators spend about a seventh of their resolution on a full-body character's head, so
faces stay soft. A head source generated from a tighter crop of the same concept (refined to add real
detail) has sharper features. Both meshes were reconstructed from aligned front views, so the head
source is placed on the body through concept pixel coordinates, refined by similarity ICP on the head,
cut at the concept's neck row with a small overlap, capped, and joined with an exact boolean union.
Each part keeps its own material and UVs.
"""
import json
import sys
import traceback

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree


def load(path, maps, name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH"]
    if len(meshes) != 1:
        raise ValueError(f"Expected one mesh in {path}, found {len(meshes)}")
    obj = meshes[0]
    obj.name = name
    material = bpy.data.materials.new(name + "_material")
    material.use_nodes = True
    tree = material.node_tree
    bsdf = tree.nodes["Principled BSDF"]
    for channel, socket, color in (("basecolor", "Base Color", True), ("roughness", "Roughness", False),
                                   ("metallic", "Metallic", False)):
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(f"{maps}/{channel}.png")
        node.image.colorspace_settings.name = "sRGB" if color else "Non-Color"
        tree.links.new(node.outputs[0], bsdf.inputs[socket])
    node = tree.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(f"{maps}/normal.png")
    node.image.colorspace_settings.name = "Non-Color"
    normal = tree.nodes.new("ShaderNodeNormalMap")
    tree.links.new(node.outputs[0], normal.inputs["Color"])
    tree.links.new(normal.outputs[0], bsdf.inputs["Normal"])
    obj.data.materials.clear()
    obj.data.materials.append(material)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # glTF splits vertices along UV seams; weld them (UVs live on face corners) so the mesh is closed.
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    bmesh.ops.remove_doubles(mesh, verts=mesh.verts, dist=1e-6)
    mesh.to_mesh(obj.data)
    mesh.free()
    return obj


def alpha_box(path):
    image = bpy.data.images.load(path)
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    mask = pixels.reshape(height, width, 4)[:, :, 3] > 0.5
    rows, cols = np.where(mask.any(axis=1))[0], np.where(mask.any(axis=0))[0]
    # Image rows run bottom-up in Blender; convert to top-down pixel rows.
    return cols[0], height - 1 - rows[-1], cols[-1], height - 1 - rows[0], width, height


def points(obj):
    return np.array([vertex.co[:] for vertex in obj.data.vertices])


def similarity(source, target):
    """Umeyama similarity (scale, rotation, translation) mapping source points onto target points."""
    mu_s, mu_t = source.mean(axis=0), target.mean(axis=0)
    s, t = source - mu_s, target - mu_t
    u, d, vt = np.linalg.svd(t.T @ s / len(s))
    sign = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[2, 2] = -1
    rotation = u @ sign @ vt
    scale = np.trace(np.diag(d) @ sign) / s.var(axis=0).sum()
    return scale, rotation, mu_t - scale * rotation @ mu_s


def cut(obj, height, keep_below):
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    geometry = mesh.verts[:] + mesh.edges[:] + mesh.faces[:]
    result = bmesh.ops.bisect_plane(mesh, geom=geometry, plane_co=(0, 0, height), plane_no=(0, 0, 1),
                                    clear_outer=keep_below, clear_inner=not keep_below)
    edges = [item for item in result["geom_cut"] if isinstance(item, bmesh.types.BMEdge)]
    bmesh.ops.holes_fill(mesh, edges=edges, sides=0)
    mesh.to_mesh(obj.data)
    mesh.free()


def run(request):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    body = load(request["body"], request["body_maps"], "Body")
    head = load(request["head"], request["head_maps"], "Head")
    body_points, head_points = points(body), points(head)

    # Concept pixel <-> model coordinates for both meshes (front views; x across, z up).
    cx0, cy0, cx1, cy1, _, _ = alpha_box(request["concept"])
    blo, bhi = body_points.min(axis=0), body_points.max(axis=0)
    def concept_to_body(u, v):
        return (blo[0] + (u - cx0) / (cx1 - cx0) * (bhi[0] - blo[0]),
                bhi[2] - (v - cy0) / (cy1 - cy0) * (bhi[2] - blo[2]))
    hx0, hy0, hx1, hy1, crop_w, crop_h = alpha_box(request["head_crop"])
    box = request["head_box"]
    to_concept = (box[2] - box[0]) / crop_w
    hlo, hhi = head_points.min(axis=0), head_points.max(axis=0)
    def head_to_concept(x, z):
        u = hx0 + (x - hlo[0]) / (hhi[0] - hlo[0]) * (hx1 - hx0)
        v = hy0 + (hhi[2] - z) / (hhi[2] - hlo[2]) * (hy1 - hy0)
        return box[0] + u * to_concept, box[1] + v * to_concept
    # Initial similarity from two concept-aligned corner points.
    (u0, v0), (u1, v1) = head_to_concept(hlo[0], hhi[2]), head_to_concept(hhi[0], hlo[2])
    (bx0, bz0), (bx1, bz1) = concept_to_body(u0, v0), concept_to_body(u1, v1)
    scale = (bz0 - bz1) / (hhi[2] - hlo[2])
    neck_x, neck_z = concept_to_body(0, request["neck_row"])
    body_head = body_points[body_points[:, 2] > neck_z]
    if len(body_head) < 50:
        raise ValueError("Body has too few vertices above the neck row to align a head")
    translation = np.array([bx0 - scale * hlo[0], 0.0, bz0 - scale * hhi[2]])
    placed = head_points * scale + translation
    translation[1] += body_head[:, 1].mean() - placed[placed[:, 2] > neck_z][:, 1].mean()
    rotation = np.eye(3)

    # Similarity ICP on the head region (above the neck), body as the fixed target.
    tree = KDTree(len(body_head))
    for index, point in enumerate(body_head):
        tree.insert(point, index)
    tree.balance()
    current = head_points * scale + translation
    initial_rms = None
    for _ in range(25):
        source = current[current[:, 2] > neck_z]
        matches = np.array([tree.find(Vector(point))[0][:] for point in source])
        distances = np.linalg.norm(source - matches, axis=1)
        keep = distances < np.percentile(distances, 80)
        rms = float(np.sqrt((distances[keep] ** 2).mean()))
        initial_rms = initial_rms if initial_rms is not None else rms
        s, r, t = similarity(source[keep], matches[keep])
        current = (s * (r @ current.T)).T + t
    height = bhi[2] - blo[2]
    for vertex, point in zip(head.data.vertices, current):
        vertex.co = point

    # Cut both at the neck with an overlap so the union has volume to merge, then join.
    overlap = 0.012 * height
    cut(body, neck_z, keep_below=True)
    cut(head, neck_z - overlap, keep_below=False)
    union = body.modifiers.new("Graft", "BOOLEAN")
    # Generated characters self-intersect (belts and straps pass through the body).
    union.operation, union.solver, union.object = "UNION", "EXACT", head
    union.use_self, union.use_hole_tolerant = True, True
    union.material_mode = "TRANSFER"  # head faces keep the head material (index mode painted them with the body's)
    print("GRAFT faces before union", len(body.data.polygons), len(head.data.polygons))
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.modifier_apply(modifier=union.name)
    bpy.data.objects.remove(head, do_unlink=True)
    mesh = bmesh.new()
    mesh.from_mesh(body.data)
    boundary = sum(1 for edge in mesh.edges if edge.is_boundary)
    nonmanifold = sum(1 for edge in mesh.edges if not edge.is_manifold)
    mesh.free()
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.ops.export_scene.gltf(filepath=request["output"], export_format="GLB", use_selection=True)
    return {"status": "grafted", "scale": round(float(scale), 4), "icp_rms_initial": round(initial_rms / height, 5),
            "icp_rms_final": round(rms / height, 5), "neck_height": round(float((neck_z - blo[2]) / height), 4),
            "faces": len(body.data.polygons), "boundary_edges": boundary, "nonmanifold_edges": nonmanifold,
            "materials": len(body.data.materials)}


def main():
    request = json.loads(open(sys.argv[sys.argv.index("--") + 1]).read())
    try:
        result = run(request)
    except Exception as exc:
        result = {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
    with open(request["report"], "w") as stream:
        json.dump(result, stream, indent=2)
    if result["status"] == "failed":
        raise SystemExit(result["error"])


main()
