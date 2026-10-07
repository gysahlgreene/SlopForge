"""Validate and package a SkinTokens GLB as reviewable Blender evidence."""
import hashlib
import json
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalize_character import bake, has_map

POSES = ("neutral", "t_pose", "raised_arms", "shoulder_rotation",
         "elbow_bend", "crouch", "leg_lift")
CHANNELS = ("base_color", "roughness", "metallic", "normal")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def imported(path):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    if Path(path).suffix.lower() == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        bpy.ops.import_scene.gltf(filepath=str(path))
    return list(bpy.context.scene.objects)


def components(obj):
    mesh = obj.data
    parents = list(range(len(mesh.vertices)))
    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    for edge in mesh.edges:
        a, b = edge.vertices
        parents[find(a)] = find(b)
    return len({find(index) for index in range(len(parents))})


def weld_coincident_vertices(obj):
    """Remove exact per-face vertex duplicates from TokenRig GLB exports."""
    before = len(obj.data.vertices)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-7)
    bpy.ops.object.mode_set(mode="OBJECT")
    return before - len(obj.data.vertices)


def semantic_bones(rig):
    """Resolve limbs from branching and position; reject ambiguous geometry."""
    bones = list(rig.data.bones)
    roots = [bone for bone in bones if bone.parent is None]
    if len(roots) != 1:
        raise ValueError("Semantic mapping needs one root bone")
    hips = roots[0]
    height = max(b.head_local.z for b in bones) - min(b.head_local.z for b in bones)
    if height <= 0:
        raise ValueError("Bone geometry has no height")
    def only(candidates, label):
        if len(candidates) != 1:
            raise ValueError(f"Ambiguous semantic {label}: {len(candidates)} candidates")
        return candidates[0]
    def branch(parent, side, up, label):
        return only([bone for bone in parent.children
                     if bone.head_local.x * side > height * 0.025
                     and (bone.tail_local.z - bone.head_local.z) * up > height * 0.03], label)
    # The central upward chain may contain several spine bones. Its first side branches mark shoulders.
    spine = only([bone for bone in hips.children
                  if abs(bone.head_local.x - hips.head_local.x) < height * 0.04
                  and bone.tail_local.z > bone.head_local.z], "spine")
    torso = spine
    while not any(child.head_local.x > height * 0.025 for child in torso.children):
        central = [child for child in torso.children if abs(child.head_local.x) < height * 0.04
                   and child.tail_local.z > child.head_local.z]
        torso = only(central, "upper spine")
    mapping = {"hips": hips.name, "spine": spine.name}
    for sign, side in ((1, "right"), (-1, "left")):
        upper_candidates = []
        for branch_bone in torso.children:
            for bone in (branch_bone, *branch_bone.children):
                if (bone.head_local.x * sign > height * 0.025
                        and (bone.tail_local.x - bone.head_local.x) * sign > height * 0.03
                        and bone.tail_local.z - bone.head_local.z <= height * 0.03):
                    upper_candidates.append(bone)
        upper_candidates = [bone for bone in upper_candidates if bone.parent not in upper_candidates]
        upper = only(upper_candidates, side + " upper arm")
        forearm = only([bone for bone in upper.children if bone.head_local.x * sign > upper.head_local.x * sign],
                       side + " forearm")
        thigh = branch(hips, sign, -1, side + " thigh")
        shin = only([bone for bone in thigh.children if bone.tail_local.z < bone.head_local.z], side + " shin")
        mapping.update({side + "_upper_arm": upper.name, side + "_forearm": forearm.name,
                        side + "_thigh": thigh.name, side + "_shin": shin.name})
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Semantic bones overlap")
    return mapping


def name_humanoid_bones(rig, meshes, mapping):
    """Give SkinTokens' positional chains a conventional humanoid bone vocabulary."""
    bones = list(rig.data.bones)
    height = max(bone.tail_local.z for bone in bones) - min(bone.head_local.z for bone in bones)
    rename = {mapping["hips"]: "Hips", mapping["spine"]: "Spine"}
    central = {mapping["hips"], mapping["spine"]}
    current = rig.data.bones[mapping["spine"]]
    central_names = ("Chest", "UpperChest", "Neck", "Head")
    for name in central_names:
        children = [bone for bone in current.children
                    if abs(bone.head_local.x - rig.data.bones[mapping["hips"]].head_local.x) < height * 0.025
                    and bone.tail_local.z > bone.head_local.z]
        if len(children) != 1:
            break
        current = children[0]
        rename[current.name] = name
        central.add(current.name)

    for side, title in (("left", "Left"), ("right", "Right")):
        upper_name = mapping[f"{side}_upper_arm"]
        forearm_name = mapping[f"{side}_forearm"]
        upper = rig.data.bones[upper_name]
        if upper.parent and upper.parent.name not in central:
            rename[upper.parent.name] = title + "Shoulder"
        rename[upper_name] = title + "UpperArm"
        rename[forearm_name] = title + "LowerArm"
        hands = list(rig.data.bones[forearm_name].children)
        if len(hands) == 1:
            hand = hands[0]
            rename[hand.name] = title + "Hand"

            def rename_finger_chain(bone, index, segment):
                suffix = f"_{segment}" if segment > 1 else ""
                rename[bone.name] = f"{title}Finger{index}{suffix}"
                for child in bone.children:
                    rename_finger_chain(child, index, segment + 1)

            for index, finger in enumerate(hand.children, 1):
                rename_finger_chain(finger, index, 1)

        thigh_name = mapping[f"{side}_thigh"]
        shin_name = mapping[f"{side}_shin"]
        rename[thigh_name] = title + "UpperLeg"
        rename[shin_name] = title + "LowerLeg"
        feet = list(rig.data.bones[shin_name].children)
        if len(feet) == 1:
            foot = feet[0]
            rename[foot.name] = title + "Foot"
            toes = list(foot.children)
            if len(toes) == 1:
                rename[toes[0].name] = title + "Toes"

    if len(set(rename.values())) != len(rename):
        raise ValueError("Humanoid bone naming produced duplicate names")
    for bone in rig.data.bones:
        if bone.name in rename:
            bone.name = rename[bone.name]
        elif bone.name.startswith("bone_"):
            bone.name = "Extra_" + bone.name.removeprefix("bone_")
    for obj in meshes:
        for group in obj.vertex_groups:
            if group.name in rename:
                group.name = rename[group.name]
    return {semantic: rename.get(name, name) for semantic, name in mapping.items()}


def weight_metrics(meshes, rig):
    sums, counts = [], []
    bones = set(rig.data.bones.keys())
    for obj in meshes:
        for vertex in obj.data.vertices:
            weights = [group.weight for group in vertex.groups
                       if group.weight > 1e-6 and obj.vertex_groups[group.group].name in bones]
            sums.append(sum(weights))
            counts.append(len(weights))
    return {"unweighted_vertices": sum(value == 0 for value in counts),
            "weight_sum_min": min(sums, default=0), "weight_sum_max": max(sums, default=0),
            "max_influences": max(counts, default=0)}


def setup_material(obj):
    material = bpy.data.materials.new(obj.name + "_rebaked")
    material.use_nodes = True
    obj.data.materials.clear()
    obj.data.materials.append(material)
    bsdf = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    nodes = material.node_tree.nodes
    for channel, input_name in (("base_color", "Base Color"), ("roughness", "Roughness"),
                                ("metallic", "Metallic")):
        texture = nodes.new("ShaderNodeTexImage")
        texture.name = f"BakeTarget_{channel}"
        material.node_tree.links.new(texture.outputs["Color"], bsdf.inputs[input_name])
    texture = nodes.new("ShaderNodeTexImage")
    texture.name = "BakeTarget_normal"
    normal = nodes.new("ShaderNodeNormalMap")
    material.node_tree.links.new(texture.outputs["Color"], normal.inputs["Color"])
    material.node_tree.links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])


def transfer(source_meshes, meshes, output):
    bpy.context.scene.render.engine = "CYCLES"
    coverage = {}
    for target in meshes:
        setup_material(target)
        center = target.matrix_world @ target.data.vertices[0].co
        source = min(source_meshes, key=lambda obj: ((obj.matrix_world @ obj.data.vertices[0].co) - center).length)
        for channel in CHANNELS:
            if not has_map(source, channel):
                continue
            source_images = [node.image for material in source.data.materials if material and material.use_nodes
                             for node in material.node_tree.nodes
                             if node.type == "TEX_IMAGE" and node.image]
            resolution = max((max(image.size) for image in source_images), default=1024)
            image = bpy.data.images.new(target.name + "_" + channel, width=resolution, height=resolution, alpha=True)
            try:
                bake(source, target, image, channel)
            except Exception as exc:
                raise RuntimeError(f"Failed to rebake {channel} on {target.name}: {exc}") from exc
            destination = output / "Textures" / f"{target.name}_{channel}.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.filepath_raw = str(destination)
            image.file_format = "PNG"
            image.save()
            coverage[channel] = coverage.get(channel, 0) + len(target.data.vertices)
    vertex_count = sum(len(obj.data.vertices) for obj in meshes)
    return {channel: count / vertex_count for channel, count in coverage.items()}


def points(meshes):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    values = []
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        values.extend(tuple(obj.matrix_world @ vertex.co) for vertex in mesh.vertices)
        evaluated.to_mesh_clear()
    return values


def pose(rig, mapping, name):
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion = (1, 0, 0, 0)
    def rotate_world(semantic, axis, degrees, *, toward_height=False):
        bone = rig.pose.bones[mapping[semantic]]
        armature_axis = rig.matrix_world.to_3x3().inverted() @ Vector(axis)
        local_axis = bone.bone.matrix_local.to_3x3().inverted() @ armature_axis
        rotation = Quaternion(local_axis.normalized(), math.radians(degrees))
        if toward_height:
            candidates = []
            for sign in (1, -1):
                bone.rotation_quaternion = Quaternion(local_axis.normalized(), math.radians(degrees * sign))
                bpy.context.view_layer.update()
                candidates.append(((rig.matrix_world @ bone.tail).z, bone.rotation_quaternion.copy()))
            rotation = max(candidates, key=lambda candidate: candidate[0])[1]
        bone.rotation_quaternion = rotation
    def rotate_bone(semantic, axis, degrees):
        bone = rig.pose.bones[mapping[semantic]]
        bone.rotation_quaternion = Quaternion(Vector(axis), math.radians(degrees))
    if name == "t_pose":
        rotate_world("left_upper_arm", (0, 1, 0), 25)
        rotate_world("right_upper_arm", (0, 1, 0), -25)
    elif name == "raised_arms":
        rotate_world("left_upper_arm", (0, 1, 0), 65, toward_height=True)
        rotate_world("right_upper_arm", (0, 1, 0), 65, toward_height=True)
    elif name == "shoulder_rotation":
        rotate_bone("left_upper_arm", (0, 1, 0), 35)
        rotate_bone("right_upper_arm", (0, 1, 0), -35)
    elif name == "elbow_bend":
        rotate_world("left_forearm", (0, 1, 0), -65)
        rotate_world("right_forearm", (0, 1, 0), 65)
    elif name == "crouch":
        rotate_world("left_thigh", (1, 0, 0), -45)
        rotate_world("right_thigh", (1, 0, 0), -45)
        rotate_world("left_shin", (1, 0, 0), 65)
        rotate_world("right_shin", (1, 0, 0), 65)
    elif name == "leg_lift":
        rotate_world("left_thigh", (1, 0, 0), -60)
    bpy.context.view_layer.update()


def render_evidence(rig, meshes, mapping, request):
    from rigify_character import setup_render

    positions = [obj.matrix_world @ v.co for obj in meshes for v in obj.data.vertices]
    low = Vector(tuple(min(point[i] for point in positions) for i in range(3)))
    high = Vector(tuple(max(point[i] for point in positions) for i in range(3)))
    center = (low + high) * 0.5
    height = (high - low).z
    setup_render(low, high)
    scene = bpy.context.scene
    scene.render.resolution_x = scene.render.resolution_y = 256
    review_material = bpy.data.materials.new("Neutral deformation review")
    review_material.diffuse_color = (0.55, 0.55, 0.55, 1.0)
    scene.view_layers[0].material_override = review_material
    pose(rig, mapping, "neutral")
    neutral = points(meshes)
    neutral_arm_tips = {
        side: (rig.matrix_world @ rig.pose.bones[mapping[f"{side}_upper_arm"]].tail).z
        for side in ("left", "right")
    }
    neutral_left_thigh_tip_depth = (
        rig.matrix_world @ rig.pose.bones[mapping["left_thigh"]].tail).y
    metrics = {}
    images = []
    for name in POSES:
        pose(rig, mapping, name)
        side_view = name in {"crouch", "leg_lift"}
        camera_direction = (Vector((height * 3.5, 0, height * 0.1)) if side_view
                            else Vector((0, -height * 3.5, height * 0.1)))
        scene.camera.location = center + camera_direction
        scene.camera.rotation_euler = (center - scene.camera.location).to_track_quat("-Z", "Y").to_euler()
        current = points(meshes)
        metrics[name] = {"max_vertex_displacement": max((Vector(a) - Vector(b)).length
                                                       for a, b in zip(current, neutral))}
        metrics[name]["view"] = "side" if side_view else "front"
        metrics[name]["upper_arm_tip_height_delta"] = {
            side: (rig.matrix_world @ rig.pose.bones[mapping[f"{side}_upper_arm"]].tail).z - height
            for side, height in neutral_arm_tips.items()
        }
        metrics[name]["left_thigh_tip_depth_delta"] = (
            rig.matrix_world @ rig.pose.bones[mapping["left_thigh"]].tail).y - neutral_left_thigh_tip_depth
        path = Path(request["evidence"][name])
        path.parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        images.append(bpy.data.images.load(str(path), check_existing=False))
    sheet = bpy.data.images.new("contact_sheet", width=256 * len(images), height=256, alpha=True)
    pixels = [0.0] * (256 * len(images) * 256 * 4)
    for column, item in enumerate(images):
        source = list(item.pixels)
        for row in range(256):
            start = (row * 256 * len(images) + column * 256) * 4
            pixels[start:start + 256 * 4] = source[row * 256 * 4:(row + 1) * 256 * 4]
    sheet.pixels[:] = pixels
    sheet.filepath_raw = request["contact_sheet"]
    sheet.file_format = "PNG"
    sheet.save()
    pose(rig, mapping, "neutral")
    scene.view_layers[0].material_override = None
    return metrics, [256 * len(images), 256]


def run(request):
    if request.get("fixture"):
        make_fixture(request)
    source_meshes = [obj for obj in imported(request["source"]) if obj.type == "MESH"]
    if not source_meshes:
        raise ValueError("Source contains no textured mesh")
    # Keep source meshes available for selected-to-active baking while importing the raw rig.
    for obj in source_meshes:
        obj.name = "Source_" + obj.name
    bpy.ops.import_scene.gltf(filepath=request["raw"])
    raw_objects = [obj for obj in bpy.context.scene.objects if obj not in source_meshes]
    rigs = [obj for obj in raw_objects if obj.type == "ARMATURE"]
    if len(rigs) != 1:
        raise ValueError("Expected one SkinTokens armature")
    rig = rigs[0]
    rig_height = max(bone.head_local.z for bone in rig.data.bones) - min(bone.head_local.z for bone in rig.data.bones)
    meshes, helpers, unknown = [], [], []
    object_inventory = []
    for obj in raw_objects:
        entry = {"name": obj.name, "type": obj.type}
        if obj.type == "MESH":
            skinned = any(mod.type == "ARMATURE" and mod.object == rig for mod in obj.modifiers)
            if skinned:
                entry["welded_vertices"] = weld_coincident_vertices(obj)
                entry["components"] = components(obj)
                meshes.append(obj)
                entry["classification"] = "skinned_character"
            elif (obj.name.startswith("Icosphere") and not obj.vertex_groups
                  and ((len(obj.data.vertices), len(obj.data.polygons)) == (42, 80)
                       or (len(obj.data.vertices) <= 100 and len(obj.data.polygons) <= 80
                           and max(obj.dimensions) < rig_height * 0.05))):
                helpers.append(obj.name)
                entry["classification"] = "known_unskinned_helper"
                bpy.data.objects.remove(obj, do_unlink=True)
            else:
                unknown.append(obj.name)
                entry["classification"] = "unclassified"
        object_inventory.append(entry)
    if unknown or not meshes:
        raise ValueError(f"Unclassified geometry or missing skinned mesh: {unknown}")
    mapping = name_humanoid_bones(rig, meshes, semantic_bones(rig))
    output = Path(request["rigged_model"]).parent
    coverage = transfer(source_meshes, meshes, output)
    if coverage.get("base_color", 0) <= 0:
        raise ValueError("Base color transfer failed")
    for obj in source_meshes:
        bpy.data.objects.remove(obj, do_unlink=True)
    metrics = weight_metrics(meshes, rig)
    deformation, dimensions = render_evidence(rig, meshes, mapping, request)
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.export_scene.fbx(filepath=request["rigged_model"], use_selection=True,
                             add_leaf_bones=False, bake_anim=False, path_mode="COPY", embed_textures=True)
    return {"status": "complete", "armature_count": len(rigs),
            "skinned_component_count": sum(components(obj) for obj in meshes),
            "helper_objects": helpers, "unclassified_objects": unknown,
            "bind_pose_count": len(rig.data.bones), "material_coverage": coverage,
            "semantic_mapping": mapping, "bone_names": sorted(rig.data.bones.keys()),
            "deformation_evidence": deformation,
            "contact_sheet_dimensions": dimensions, "pose_parameters": "fixed skintokens_character.py v1",
            "source_sha256": sha(request["source"]), "raw_sha256": sha(request["raw"]),
            "rigged_model_sha256": sha(request["rigged_model"]),
            "checkpoint_sha256": request.get("checkpoint_sha256"),
            "skintokens_revision": request.get("skintokens_revision"),
            "blender_version": bpy.app.version_string, "object_inventory": object_inventory,
            "pose_parameters": "world_axis_hinge_v2", **metrics}


def make_fixture(request):
    """Small generic-named synthetic rig used only by the Blender integration test."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    image = bpy.data.images.new("fixture_color", width=16, height=16)
    image.pixels[:] = [0.8, 0.2, 0.1, 1.0] * (16 * 16)
    material = bpy.data.materials.new("fixture_texture")
    material.use_nodes = True
    tex = material.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = image
    bsdf = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    material.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    parts = (("Torso", (0, 0, 0.5), (0.35, 0.2, 0.5), "bone_1"),
             ("ArmL", (-0.6, 0, 0.65), (0.5, 0.16, 0.16), "bone_5"),
             ("ArmR", (0.6, 0, 0.65), (0.5, 0.16, 0.16), "bone_8"),
             ("LegL", (-0.18, 0, -0.5), (0.16, 0.2, 0.8), "bone_10"),
             ("LegR", (0.18, 0, -0.5), (0.16, 0.2, 0.8), "bone_12"))
    for name, location, scale, _bone in parts:
        bpy.ops.mesh.primitive_cube_add(size=1, location=location)
        obj = bpy.context.object
        obj.name = name
        obj.dimensions = scale
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        obj.data.materials.append(material)
    bpy.ops.export_scene.gltf(filepath=request["source"], export_format="GLB")
    bpy.ops.object.armature_add()
    rig = bpy.context.object
    rig.name = "Armature"
    bpy.ops.object.mode_set(mode="EDIT")
    rig.data.edit_bones.remove(rig.data.edit_bones[0])
    bones = (("bone_0", None, (0, 0, 0), (0, 0, 0.2)),
             ("bone_1", "bone_0", (0, 0, 0.2), (0, 0, 0.55)),
             ("bone_2", "bone_1", (0, 0, 0.55), (0, 0, 0.72)),
             ("bone_3", "bone_2", (-0.12, 0, 0.65), (-0.28, 0, 0.76)),
             ("bone_4", "bone_3", (-0.28, 0, 0.76), (-0.55, 0, 0.65)),
             ("bone_5", "bone_4", (-0.55, 0, 0.65), (-0.8, 0, 0.65)),
             ("bone_6", "bone_2", (0.12, 0, 0.65), (0.28, 0, 0.76)),
             ("bone_7", "bone_6", (0.28, 0, 0.76), (0.55, 0, 0.65)),
             ("bone_8", "bone_7", (0.55, 0, 0.65), (0.8, 0, 0.65)),
             ("bone_9", "bone_0", (-0.16, 0, 0.2), (-0.18, 0, -0.4)),
             ("bone_10", "bone_9", (-0.18, 0, -0.4), (-0.18, 0, -0.8)),
             ("bone_11", "bone_0", (0.16, 0, 0.2), (0.18, 0, -0.4)),
             ("bone_12", "bone_11", (0.18, 0, -0.4), (0.18, 0, -0.8)),
             ("bone_13", "bone_2", (0, 0, 0.72), (0, 0, 0.8)),
             ("bone_14", "bone_13", (0, 0, 0.8), (0, 0, 0.9)),
             ("bone_15", "bone_14", (0, 0, 0.9), (0, 0, 1.0)),
             ("bone_16", "bone_5", (-0.8, 0, 0.65), (-0.9, 0, 0.65)),
             ("bone_17", "bone_16", (-0.9, 0, 0.65), (-1.0, 0, 0.65)),
             ("bone_18", "bone_17", (-1.0, 0, 0.65), (-1.1, 0, 0.65)),
             ("bone_19", "bone_18", (-1.1, 0, 0.65), (-1.2, 0, 0.65)),
             ("bone_20", "bone_8", (0.8, 0, 0.65), (0.9, 0, 0.65)),
             ("bone_21", "bone_20", (0.9, 0, 0.65), (1.0, 0, 0.65)),
             ("bone_22", "bone_21", (1.0, 0, 0.65), (1.1, 0, 0.65)),
             ("bone_23", "bone_22", (1.1, 0, 0.65), (1.2, 0, 0.65)))
    for name, parent, head, tail in bones:
        bone = rig.data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        if parent:
            bone.parent = rig.data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, _location, _scale, bone in parts:
        obj = bpy.data.objects[name]
        group = obj.vertex_groups.new(name=bone)
        group.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
        obj.parent = rig
        obj.modifiers.new("Skin", "ARMATURE").object = rig
        obj.data.materials.clear()
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.02, location=(0, 0, 2))
    bpy.context.object.name = "Icosphere"
    bpy.ops.export_scene.gltf(filepath=request["raw"], export_format="GLB")


def main():
    request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    try:
        result = run(request)
    except Exception as exc:
        traceback.print_exc()
        result = {"status": "failed", "errors": [str(exc)]}
    path = Path(request["report"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    if result["status"] != "complete":
        sys.exit(1)


if __name__ == "__main__":
    main()
