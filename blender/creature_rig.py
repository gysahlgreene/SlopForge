"""B1 for creatures in Blender: measure a raw SkinTokens rig and check it, or finish the chosen one.

    blender --background --factory-startup --python blender/creature_rig.py -- request.json

request["action"]:
- "check": import `raw`, measure it into slopforge.creature_rig.structure's arrays, check it against `limbs` and
  `limits`, and render `views` (front and side; the skin see-through, joints coloured by leg) for the seed sheet.
- "finish": import `source` and `raw`; give the rig `names`, bone tails along their chains and each bone's local X
  across the body (video2rig bends a joint about the local axis nearest its side-to-side axis); take the source's
  material back (as blender/skintokens_character.py does); export `rigged_model` (FBX) and `blend`; render `poses`.
- "fixture": build `source` and `raw` GLBs from `fixture` arrays (the Blender integration test only).
The report goes to request["report"]; a crash writes {"status": "error"}.
"""
import json
import math
import os
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Quaternion, Vector

sys.path.append(os.environ.get("SLOPFORGE_PACKAGE_ROOT", str(Path(__file__).resolve().parents[1])))
from slopforge.creature_rig import check_rig  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skintokens_character import imported, sha, transfer, weld_coincident_vertices  # noqa: E402
from rigify_character import bind_with_proxy  # noqa: E402

LEG_COLOURS = {("front", "L"): (0.9, 0.2, 0.2, 1), ("front", "R"): (0.2, 0.4, 0.95, 1),
               ("hind", "L"): (0.95, 0.6, 0.1, 1), ("hind", "R"): (0.2, 0.8, 0.9, 1)}


def import_rig(path):
    """The raw rig's armature and skinned meshes; the importer's bone-shape icospheres are removed."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path), bone_heuristic="TEMPERANCE")
    objects = [obj for obj in bpy.data.objects if obj not in before]
    for obj in [obj for obj in objects if obj.type == "MESH" and obj.name.startswith("Icosphere")
                and not obj.vertex_groups]:
        objects.remove(obj)
        bpy.data.objects.remove(obj, do_unlink=True)
    armatures = [obj for obj in objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in objects if obj.type == "MESH"]
    return armatures, meshes


def measure(armatures, meshes):
    """structure()'s arrays, in world space: the skin of every mesh, weights by bone, joints and parents."""
    rig = armatures[0]
    bones = [bone.name for bone in rig.data.bones]
    index = {name: k for k, name in enumerate(bones)}
    vertices, triangles, rows = [], [], []
    for obj in meshes:
        offset = len(vertices)
        vertices += [tuple(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices]
        obj.data.calc_loop_triangles()
        triangles += [[offset + k for k in tri.vertices] for tri in obj.data.loop_triangles]
        groups = {group.index: group.name for group in obj.vertex_groups}
        for vertex in obj.data.vertices:
            row = np.zeros(len(bones))
            for item in vertex.groups:
                if groups.get(item.group) in index and item.weight > 0:
                    row[index[groups[item.group]]] += item.weight
            rows.append(row)
    return {"vertices": np.array(vertices), "triangles": np.array(triangles, int), "weights": np.array(rows),
            "bones": bones, "parents": [bone.parent.name if bone.parent else None for bone in rig.data.bones],
            "heads": np.array([tuple(rig.matrix_world @ bone.head_local) for bone in rig.data.bones]),
            "armature_count": len(armatures)}


def axes(facing):
    forward = Vector({"-Y": (0, -1, 0), "+Y": (0, 1, 0), "-X": (-1, 0, 0), "+X": (1, 0, 0)}[facing])
    return forward, Vector((0, 0, 1)).cross(forward)


def ortho_camera(low, high, scale):
    scene = bpy.context.scene
    camera = bpy.data.objects.new("ReviewCamera", bpy.data.cameras.new("ReviewCamera"))
    scene.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(high - low) * scale
    camera.rotation_mode = "QUATERNION"
    scene.camera = camera
    return camera


def aim(camera, centre, direction, distance):
    camera.location = centre + direction.normalized() * distance
    camera.rotation_quaternion = (centre - camera.location).to_track_quat("-Z", "Y")


def check(request):
    armatures, meshes = import_rig(request["raw"])
    if not armatures or not meshes:
        raise ValueError(f"the raw rig has {len(armatures)} armatures and {len(meshes)} skinned meshes")
    arrays = measure(armatures, meshes)
    report = check_rig(arrays, request["limbs"], request["limits"])
    report["objects"] = [{"name": obj.name, "type": obj.type} for obj in armatures + meshes]
    # the seed sheet: front and side, the skin see-through, joints coloured by leg and magenta outside the skin
    colour = {bone: LEG_COLOURS[(limb["end"], limb["side"])] for limb in report["limbs"] if limb["side"]
              for bone in limb["chain"]}
    heads = dict(zip(arrays["bones"], arrays["heads"]))
    height = report["measured"]["height"]
    for name, parent in zip(arrays["bones"], arrays["parents"]):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.02 * height, location=heads[name], segments=12, ring_count=6)
        bpy.context.object.color = ((1, 0, 1, 1) if name in report["joints_outside"]
                                    else colour.get(name, (0.1, 0.9, 0.2, 1)))
        if parent:
            a, b = Vector(heads[parent]), Vector(heads[name])
            bpy.ops.mesh.primitive_cylinder_add(radius=0.006 * height, depth=max((b - a).length, 1e-6),
                                                location=(a + b) / 2, vertices=8)
            bpy.context.object.rotation_mode = "QUATERNION"
            bpy.context.object.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(b - a)
            bpy.context.object.color = (0.95, 0.95, 0.95, 1)
    for obj in meshes:
        obj.color = (0.75, 0.72, 0.68, 1)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "OBJECT"
    scene.display.shading.show_xray = True
    scene.display.shading.xray_alpha = 0.12
    scene.render.resolution_x, scene.render.resolution_y = 600, 540
    low, high = arrays["vertices"].min(0), arrays["vertices"].max(0)
    centre = Vector(((low + high) / 2).tolist())
    camera = ortho_camera(low, high, 1.15)
    forward, left = axes(report["facing"])
    for view, direction in (("front", forward), ("side", left)):
        aim(camera, centre, direction, 10 * height)
        scene.render.filepath = request["views"][view]
        bpy.ops.render.render(write_still=True)
    return report


def set_bones(rig, meshes, names, left):
    """Tails along each chain and local X across the body; then the generic names (vertex groups follow)."""
    kids = {bone.name: [child.name for child in bone.children] for bone in rig.data.bones}
    to_rig = rig.matrix_world.inverted()
    led = {}
    for obj in meshes:
        groups = {group.index: group.name for group in obj.vertex_groups}
        for vertex in obj.data.vertices:
            if vertex.groups:
                top = max(vertex.groups, key=lambda item: item.weight)
                led.setdefault(groups.get(top.group), []).append(to_rig @ (obj.matrix_world @ vertex.co))
    lateral = (rig.matrix_world.to_3x3().inverted() @ left).normalized()
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    edit = rig.data.edit_bones
    span = max(rig.dimensions) or 1.0
    for bone in edit:
        children = kids[bone.name]
        if len(children) == 1:
            bone.tail = edit[children[0]].head.copy()
        elif children:   # a hub points at the mean of its children
            bone.tail = sum((edit[child].head for child in children), Vector()) / len(children)
        elif bone.parent:   # a leaf runs on along its chain to the farthest skin it leads that way
            way = (bone.head - bone.parent.head).normalized()
            points = led.get(bone.name, [])
            bone.tail = (max(points, key=lambda point: (point - bone.head).dot(way)) if points
                         else bone.head + way * 0.05 * span)
        if (bone.tail - bone.head).length < 1e-4 * span:
            way = (bone.head - bone.parent.head).normalized() if bone.parent else Vector((0, 0, 1))
            bone.tail = bone.head + way * 0.01 * span
    for bone in edit:
        along = (bone.tail - bone.head).normalized()
        bone.align_roll(lateral.cross(along) if abs(along.dot(lateral)) < 0.7 else Vector((0, 0, 1)))
    bpy.ops.object.mode_set(mode="OBJECT")
    for bone in rig.data.bones:   # two passes, so no final name is ever taken by a bone not yet renamed
        bone.name = "__creature_" + bone.name
    for bone in rig.data.bones:
        bone.name = names[bone.name.removeprefix("__creature_")]
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
    # how well each bone's X follows the body's side-to-side axis, taken square to the bone (1: exactly)
    across = []
    for bone in rig.data.bones:
        x_axis, y_axis = ((rig.matrix_world.to_3x3() @ bone.matrix_local.to_3x3().col[k]).normalized() for k in (0, 1))
        side = left - y_axis * left.dot(y_axis)
        if side.length > 0.7:
            across.append(abs(x_axis.dot(side.normalized())))
    return min(across, default=1.0)


def proxy_heat(rig, meshes, limit=4):
    """The model's weights replaced by bone heat on a closed voxel proxy of the skin (the character route's
    bind_with_proxy), at rest, each vertex kept to its `limit` strongest bones. Owner ruling 2026-10-30 (#154): on the
    wolf it cut the chest and face stretch 3-5x. The skin keeps its place; only the weights change."""
    for bone in rig.pose.bones:
        bone.rotation_mode, bone.rotation_quaternion = "QUATERNION", (1, 0, 0, 0)
        bone.location, bone.scale = (0, 0, 0), (1, 1, 1)
    bpy.context.view_layer.update()
    placed = {obj.name: obj.matrix_world.copy() for obj in meshes}
    for obj in meshes:
        for modifier in [m for m in obj.modifiers if m.type == "ARMATURE"]:
            obj.modifiers.remove(modifier)
        obj.vertex_groups.clear()
    corners = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    report = bind_with_proxy(rig, meshes, max(c.z for c in corners) - min(c.z for c in corners))
    bones = {bone.name for bone in rig.data.bones if bone.use_deform}
    most = 0
    for obj in meshes:
        obj.matrix_world = placed[obj.name]   # bind_with_proxy re-parents; the skin stays where it was
        names = {group.index: group.name for group in obj.vertex_groups}
        for vertex in obj.data.vertices:
            items = sorted(((names[g.group], g.weight) for g in vertex.groups if g.weight > 0 and names[g.group] in bones),
                           key=lambda item: item[1], reverse=True)[:limit]
            total = sum(weight for _, weight in items)
            if total <= 0:
                raise ValueError(f"bone heat left a vertex of {obj.name} unweighted")
            for index in [g.group for g in vertex.groups]:   # indices first: removing invalidates the elements
                obj.vertex_groups[index].remove([vertex.index])
            for name, weight in items:
                obj.vertex_groups[name].add([vertex.index], weight / total, "REPLACE")
            most = max(most, len(items))
    return {**report, "influences_max": most}


def make_opaque(meshes):
    """A creature's skin is opaque. Blender's FBX import wires the published base colour's Color into Alpha, and
    Cycles (video2rig's studio renders) then drew the B1 wolf see-through. Returns the links removed."""
    removed = 0
    for material in {material for obj in meshes for material in obj.data.materials if material and material.use_nodes}:
        for node in material.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                for link in list(node.inputs["Alpha"].links):
                    material.node_tree.links.remove(link)
                    removed += 1
                node.inputs["Alpha"].default_value = 1.0
    return removed


def render_poses(rig, meshes, poses, images, forward, left):
    scene = bpy.context.scene
    low = np.min([obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box], axis=0)
    high = np.max([obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box], axis=0)
    centre = Vector(((low + high) / 2).tolist())
    camera = ortho_camera(low, high, 1.35)
    # lit as the material previews are (blender/prepare_model.py render_previews), turned to the creature's facing:
    # one sun left the wolf's near side dark (mean luminance 64), the character review's lights blew it out (218)
    scene.render.engine = "BLENDER_EEVEE"
    scene.view_settings.view_transform = "AgX"
    scene.world = scene.world or bpy.data.worlds.new("ReviewWorld")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.18, 0.18, 0.18, 1.0)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.5
    turn = Vector((0, -1, 0)).rotation_difference(forward)
    for offset, energy, size in (((-3, -4, 4), 450, 4), ((3, -1, 2), 220, 3), ((0, 2, 3), 300, 3)):
        light = bpy.data.objects.new("ReviewLight", bpy.data.lights.new("ReviewLight", "AREA"))
        scene.collection.objects.link(light)
        light.data.energy, light.data.shape, light.data.size = energy, "DISK", size
        light.location = centre + turn @ Vector(offset)
        light.rotation_euler = (centre - light.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.resolution_x, scene.render.resolution_y = 640, 480
    for pose, image in zip(poses, images):
        for bone in rig.pose.bones:
            bone.rotation_quaternion = (1, 0, 0, 0)
        for name, (x, y, z) in pose["rotations"].items():
            rig.pose.bones[name].rotation_quaternion = (Quaternion((1, 0, 0), math.radians(x))
                                                        @ Quaternion((0, 1, 0), math.radians(y))
                                                        @ Quaternion((0, 0, 1), math.radians(z)))
        # seen from the front left, or from behind on the right for the right hind leg
        rear = pose["label"] == "right hind lifted"
        aim(camera, centre, (-forward - left if rear else forward + left) + Vector((0, 0, 0.8)), 3 * max(high - low))
        bpy.context.view_layer.update()
        scene.render.filepath = image
        bpy.ops.render.render(write_still=True)
    for bone in rig.pose.bones:
        bone.rotation_quaternion = (1, 0, 0, 0)


def finish(request):
    source_meshes = [obj for obj in imported(request["source"]) if obj.type == "MESH"]   # FBX or GLB
    for obj in source_meshes:
        obj.name = "Source_" + obj.name
    armatures, meshes = import_rig(request["raw"])
    rig = armatures[0]
    forward, left = axes(request["facing"])
    lateral_x = set_bones(rig, meshes, request["names"], left)
    welded = sum(weld_coincident_vertices(obj) for obj in meshes)
    weights = (proxy_heat(rig, meshes) if request.get("skin_weights") == "proxy_heat"
               else {"method": "skintokens"})
    coverage, methods = transfer(source_meshes, meshes, Path(request["rigged_model"]).parent)
    if coverage.get("base_color", 0) <= 0:
        raise ValueError("the source's base colour did not transfer to the rig")
    alpha_links = make_opaque(meshes)
    for obj in source_meshes:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in [rig, *meshes]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.export_scene.fbx(filepath=request["rigged_model"], use_selection=True, add_leaf_bones=False,
                             bake_anim=False, path_mode="COPY", embed_textures=True)
    bpy.context.scene.render.fps = 24
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=request["blend"], copy=True)
    render_poses(rig, meshes, request["poses"], request["pose_images"], forward, left)
    return {"status": "complete", "bone_names": [bone.name for bone in rig.data.bones],
            "lateral_x_min": lateral_x, "welded_vertices": welded, "material_coverage": coverage,
            "alpha_links_removed": alpha_links, "skin_weights": weights,
            "material_transfer": methods, "rigged_model_sha256": sha(request["rigged_model"]),
            "blend_sha256": sha(request["blend"]), "blender_version": bpy.app.version_string}


def fixture(request):
    """Source and raw GLBs from arrays: one skinned mesh with planar UVs and a textured material."""
    data = request["fixture"]
    mesh = bpy.data.meshes.new("Creature")
    mesh.from_pydata([tuple(v) for v in data["vertices"]], [], [tuple(t) for t in data["triangles"]])
    uv = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        co = mesh.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = (co.x + 0.5, co.y + 0.5)
    image = bpy.data.images.new("fixture_basecolor", width=16, height=16)
    image.pixels[:] = [0.6, 0.5, 0.4, 1.0] * 256
    image.filepath_raw = str(Path(request["source"]).with_name("fixture_basecolor.png"))   # an FBX embeds files
    image.file_format = "PNG"
    image.save()
    material = bpy.data.materials.new("Fur")
    material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    shader = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    material.node_tree.links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])   # as the model pipeline wires it
    mesh.materials.append(material)
    body = bpy.data.objects.new("Creature", mesh)
    bpy.context.scene.collection.objects.link(body)
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    if request["source"].lower().endswith(".fbx"):
        bpy.ops.export_scene.fbx(filepath=request["source"], use_selection=True, path_mode="COPY", embed_textures=True)
    else:
        bpy.ops.export_scene.gltf(filepath=request["source"], export_format="GLB", use_selection=True)
    rig = bpy.data.objects.new("Armature", bpy.data.armatures.new("Armature"))
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for name, parent, head in zip(data["bones"], data["parents"], data["heads"]):
        bone = rig.data.edit_bones.new(name)
        bone.head, bone.tail = head, (head[0], head[1], head[2] + 0.02)
    for name, parent in zip(data["bones"], data["parents"]):
        if parent:
            rig.data.edit_bones[name].parent = rig.data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for name in data["bones"]:
        body.vertex_groups.new(name=name)
    for index, bone in enumerate(data["leads"]):
        body.vertex_groups[bone].add([index], 1.0, "REPLACE")
    body.parent = rig
    body.modifiers.new("Skin", "ARMATURE").object = rig
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.01, location=(0, 0, 2))
    bpy.context.object.name = "Icosphere"
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=request["raw"], export_format="GLB", use_selection=True)
    return {"status": "complete"}


def main():
    request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        result = {"check": check, "finish": finish, "fixture": fixture}[request["action"]](request)
    except Exception as exc:
        traceback.print_exc()
        result = {"status": "error", "errors": [f"{type(exc).__name__}: {exc}"]}
    Path(request["report"]).parent.mkdir(parents=True, exist_ok=True)
    Path(request["report"]).write_text(json.dumps(result, indent=2) + "\n")
    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
