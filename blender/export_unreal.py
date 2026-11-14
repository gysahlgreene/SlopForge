"""Export an approved model for Unreal, optionally broken into rigid parts (docs/UNREAL.md).

    Blender --background --python blender/export_unreal.py -- REQUEST.json

REQUEST: {"blend", "name", "out_dir", "report", and either "render_views" (a folder: the model's front and back,
orthographic, to box its parts on) or optional "parts" ([{"name", "masks": {"front"|"back": mask}}], masks on those
renders) and "body" (the part the others are cut from)}.

The model is set on its own floor, centred: the origin is the bottom centre of its bounds. It is written as
<out_dir>/<name>.fbx in the axes Unreal projects' own Blender exports use (forward -Y, up Z, metres), with no
embedded textures: the maps are delivered beside it.

With parts, each vertex takes a part (mesh_cleanup.rigid_labels): the views seed the vertices they see under each
part's mask, and the seeds grow over the surface. The views are the model's own orthographic renders, not its
concept: a perspective 3/4 concept fitted at 0.88 put limb mask edges on the parts beside them, and hid a leg (round
25's hand, 2026-11-13). Parts are cut off the body from the ends inwards
(mesh_cleanup.peel_order) by mesh_cleanup.separate_part, which closes both sides with caps and puts the part's origin
on its cut, its joint. Each part, and the body, is also written alone as <out_dir>/Parts/<name>_<part>.fbx with its
origin on its joint. The report lists each part's parent and joint in Unreal's centimetres and axes.
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from concept_view import image_mask, view_axes  # noqa: E402
from mesh_cleanup import merge_stray_islands, peel_order, rigid_labels, separate_part  # noqa: E402


def to_unreal(point):
    """Blender metres to Unreal centimetres, as an FBX written forward -Y, up Z imports: y mirrored."""
    return [round(point[0] * 100, 3), round(-point[1] * 100, 3), round(point[2] * 100, 3)]


def export(objects, path):
    bpy.ops.object.select_all(action="DESELECT")
    for item in objects:
        item.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={"MESH"}, apply_unit_scale=True,
                             apply_scale_options="FBX_SCALE_NONE", axis_forward="-Y", axis_up="Z",
                             mesh_smooth_type="FACE", path_mode="STRIP", embed_textures=False, add_leaf_bones=False,
                             bake_anim=False, use_custom_props=True)


def welded(obj):
    """Unique vertex positions (world), each original vertex's index into them, and the edges between them: a
    textured mesh is split along its UV seams, which would otherwise stop the parts' growth at every seam."""
    world = np.array([obj.matrix_world @ vertex.co for vertex in obj.data.vertices])
    size = float(np.ptp(world, 0).max())
    keys = np.round(world / (size * 1e-6)).astype(np.int64)
    unique, index = np.unique(keys, axis=0, return_inverse=True)
    index = index.reshape(-1)
    positions = np.zeros((len(unique), 3))
    np.add.at(positions, index, world)
    positions /= np.bincount(index, minlength=len(unique))[:, None]
    edges = np.array([edge.vertices[:] for edge in obj.data.edges], dtype=np.int64).reshape(-1, 2)
    edges = index[edges]
    edges = np.unique(np.sort(edges[edges[:, 0] != edges[:, 1]], 1), axis=0)
    return positions, index, edges


VIEWS = {"front": 0, "back": 180}  # turns about Z from the model's front (-Y), as concept_view.view_axes


def view_camera(obj, theta, size=1024):
    """An orthographic camera on the model from `theta` degrees, framing it with a margin; it renders the view a
    part is boxed on, and maps the model's points onto that render exactly (a concept's perspective did not)."""
    corners = np.array([vertex.co for vertex in obj.data.vertices])
    low, high = corners.min(0), corners.max(0)
    centre, extent = Vector(((low + high) / 2).tolist()), float((high - low).max())
    towards, _right, _up = view_axes(math.radians(theta), 0.0)
    scene = bpy.context.scene
    camera = scene.camera or bpy.data.objects.new("slopforge_view", bpy.data.cameras.new("slopforge_view"))
    if camera.name not in scene.collection.objects:
        scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.type, camera.data.ortho_scale = "ORTHO", extent * 1.1
    camera.location = centre + towards * extent * 3
    camera.rotation_euler = (-towards).to_track_quat("-Z", "Y").to_euler()
    camera.data.clip_end = extent * 10
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    bpy.context.view_layer.update()
    return camera, towards


def render_views(obj, out_dir):
    """The model's base colour from the front and back, transparent around it, for boxing its parts."""
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light, scene.display.shading.color_type = "FLAT", "TEXTURE"
    scene.render.film_transparent = True
    scene.render.image_settings.color_mode = "RGBA"
    for name, theta in VIEWS.items():
        view_camera(obj, theta)
        scene.render.filepath = str(Path(out_dir) / f"view_{name}.png")
        bpy.ops.render.render(write_still=True)


def contact(part, parent, share=0.05):
    """Where a part touches its parent without sharing an edge (a loose piece resting on it): the middle of its
    closest points to the parent, the nearest `share` of them."""
    from mathutils import kdtree
    if not len(part) or not len(parent):
        return None
    tree = kdtree.KDTree(len(parent))
    for number, point in enumerate(parent):
        tree.insert(point, number)
    tree.balance()
    found = sorted((tree.find(point)[2], tuple(point), tuple(tree.find(point)[0])) for point in part)
    nearest = found[:max(1, int(len(found) * share))]
    return Vector(np.mean([np.add(a, b) / 2 for _distance, a, b in nearest], 0).tolist())


def cut_parts(obj, request):
    """request["parts"]: [{"name", "masks": {view: mask path}}], masks on the renders of render_views."""
    from bpy_extras.object_utils import world_to_camera_view
    names = [part["name"] for part in request["parts"]]
    positions, index, edges = welded(obj)
    triangles = [[int(index[corner]) for corner in polygon.vertices] for polygon in obj.data.polygons]
    tree = BVHTree.FromPolygons([Vector(point) for point in positions], triangles)
    size = float(np.ptp(positions, 0).max())
    seeds, visible = np.full(len(positions), -1), np.zeros(len(positions), bool)
    for view, theta in VIEWS.items():
        masks = [(number, image_mask(part["masks"][view], channel=0)) for number, part in enumerate(request["parts"])
                 if view in part.get("masks", {})]
        if not masks:
            continue
        camera, towards = view_camera(obj, theta)
        height, width = masks[0][1].shape
        painted = np.full((height, width), -1)
        # A smaller mask wins where they overlap; a part declared "over" (a rifle across the chest, whose mask is
        # larger than the chest's) wins over all.
        over = {number for number, part in enumerate(request["parts"]) if part.get("over")}
        for number, mask in sorted(masks, key=lambda item: (item[0] in over, -item[1].sum())):
            painted[mask] = number
        scene = bpy.context.scene
        for vertex, point in enumerate(positions):
            if seeds[vertex] >= 0 or tree.ray_cast(Vector(point) + towards * size * 1e-4, towards, size * 4)[0]:
                continue  # seeded from an earlier view, or hidden from this one
            projected = world_to_camera_view(scene, camera, Vector(point))
            column, row = int(projected.x * width), int(projected.y * height)  # rows from the bottom, as image_mask
            if 0 <= column < width and 0 <= row < height:
                visible[vertex] = True
                seeds[vertex] = painted[row, column]
    labels = merge_stray_islands(rigid_labels(positions, edges, visible, seeds), edges)
    body = names.index(request["body"]) if request.get("body") in names else int(np.bincount(labels[labels >= 0]).argmax())
    for number, name in enumerate(names):
        group = obj.vertex_groups.new(name=f"slopforge_part_{name}")
        group.add([int(vertex) for vertex in np.flatnonzero(labels[index] == number)], 1.0, "REPLACE")
    basecolor = next((image for image in bpy.data.images if "basecolor" in image.name), None)
    parts = []
    declared = {names.index(part["name"]): names.index(part["parent"]) for part in request["parts"]
                if part.get("parent") in names}
    for number, parent in peel_order(labels, edges, body, declared or None):
        # The joint is the middle of the seam with the parent alone: a part also touching another (a hand resting on
        # a thigh) would otherwise pivot between the two.
        pair = np.sort(np.array([number, parent]))
        seam = edges[(np.sort(labels[edges], 1) == pair).all(1)].reshape(-1)
        joint = Vector(positions[np.unique(seam)].mean(0).tolist()) if len(seam) else contact(
            positions[labels == number], positions[labels == parent])
        child = separate_part(obj, names[number], "rigid", basecolor=basecolor)
        if child is not None and joint is not None:
            child.data.transform(Matrix.Translation(child.location - joint))
            child.location = joint
        record = {"name": names[number], "parent": names[parent],
                  "seeded_share": round(float((seeds == number).sum() / max(1, (labels == number).sum())), 4)}
        if child is None:
            record["error"] = "too few faces under its mask; left on its parent"
        else:
            record.update({"faces": len(child.data.polygons), "pivot": list(child.location)})
        parts.append(record)
        print(f"Part {names[number]} from {names[parent]}: {record}")
    return {"body": names[body], "parts": parts}


def main():
    request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    bpy.ops.wm.open_mainfile(filepath=request["blend"])
    roots = [item for item in bpy.context.scene.objects if item.type == "MESH" and item.parent is None]
    if not roots:
        raise SystemExit("The blend has no mesh")
    obj = max(roots, key=lambda item: len(item.data.polygons))
    if obj.children:
        raise SystemExit("The model already has parts (a weapon's moving parts); Unreal delivery of those is not built")
    # The model's own frame, on its floor: the transform into the mesh, then the bottom centre to the origin.
    obj.data.transform(obj.matrix_world)
    obj.matrix_world = Matrix.Identity(4)
    corners = np.array([vertex.co for vertex in obj.data.vertices])
    low, high = corners.min(0), corners.max(0)
    obj.data.transform(Matrix.Translation(-Vector(((low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]))))
    obj.data.update()
    report = {"name": request["name"], "size_m": [round(float(value), 4) for value in high - low]}
    out = Path(request["out_dir"])
    if request.get("render_views"):
        render_views(obj, request["render_views"])
        Path(request["report"]).write_text(json.dumps(report, indent=2) + "\n")
        return
    if request.get("parts"):
        report.update(cut_parts(obj, request))
    export([obj, *obj.children], out / f"{request['name']}.fbx")
    report["fbx"] = f"{request['name']}.fbx"
    if request.get("parts"):
        files = {}
        for child in list(obj.children):
            child.parent = None
            child.matrix_world = Matrix.Identity(4)  # its origin, on its joint, at the file's origin
            export([child], out / "Parts" / f"{request['name']}_{child.name}.fbx")
            files[child.name] = f"Parts/{request['name']}_{child.name}.fbx"
        export([obj], out / "Parts" / f"{request['name']}_{report['body']}.fbx")
        files[report["body"]] = f"Parts/{request['name']}_{report['body']}.fbx"
        for part in report["parts"]:
            if "pivot" in part:
                part["pivot_unreal_cm"] = to_unreal(part.pop("pivot"))
                part["fbx"] = files[part["name"]]
        report["body_fbx"] = files[report["body"]]
    Path(request["report"]).write_text(json.dumps(report, indent=2) + "\n")
    print(f"Unreal export: {json.dumps(report)}")


main()
