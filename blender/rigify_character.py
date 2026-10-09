"""Blender 5.x Rigify humanoid fitting, skinning, evidence rendering, and FBX export."""
import json
import hashlib
import math
import sys
import traceback
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


POSES = {
    "t_pose": {},
    "raised_arms": {"hand_ik.L": (0.0, 0.0, 0.55), "hand_ik.R": (0.0, 0.0, 0.55)},
    "crouch": {"thigh_fk.L": (0.8, 0.0, 0.0), "thigh_fk.R": (0.8, 0.0, 0.0),
               "shin_fk.L": (-1.0, 0.0, 0.0), "shin_fk.R": (-1.0, 0.0, 0.0)},
    "leg_lift": {"thigh_fk.L": (-0.9, 0.0, 0.0), "shin_fk.L": (0.35, 0.0, 0.0)},
    "elbow_bend": {"forearm_fk.L": (-1.2, 0.0, 0.0), "forearm_fk.R": (-1.2, 0.0, 0.0)},
    "shoulder_rotation": {"upper_arm_fk.L": (0.0, 0.8, 0.0), "upper_arm_fk.R": (0.0, -0.8, 0.0)},
}


def fail(message):
    raise RuntimeError(message)


def imported_meshes(source):
    before = set(bpy.data.objects)
    suffix = source.suffix.lower()
    if suffix == ".glb":
        bpy.ops.import_scene.gltf(filepath=str(source))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(source))
    else:
        fail("Rigify provider accepts GLB or FBX character models")
    meshes = [obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH"]
    if not meshes:
        fail("Source model contains no mesh objects")
    return meshes


def bounds(objects):
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    low = Vector(tuple(min(point[axis] for point in points) for axis in range(3)))
    high = Vector(tuple(max(point[axis] for point in points) for axis in range(3)))
    if any(not math.isfinite(high[i] - low[i]) or high[i] - low[i] <= 1e-5 for i in range(3)):
        fail("Character mesh has degenerate bounds; cannot fit a humanoid metarig")
    return low, high


def fit_metarig(metarig, low, high):
    bpy.context.view_layer.objects.active = metarig
    metarig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = list(metarig.data.edit_bones)
    points = [point for bone in edit_bones for point in (bone.head.copy(), bone.tail.copy())]
    rig_low = Vector(tuple(min(point[axis] for point in points) for axis in range(3)))
    rig_high = Vector(tuple(max(point[axis] for point in points) for axis in range(3)))
    rig_span, mesh_span = rig_high - rig_low, high - low
    if min(rig_span) <= 1e-5:
        fail("Rigify human metarig has degenerate bounds")
    scale = Vector(tuple(mesh_span[axis] / rig_span[axis] for axis in range(3)))
    connections = [(bone, bone.use_connect) for bone in edit_bones]
    for bone, _ in connections:
        bone.use_connect = False
    for bone in edit_bones:
        for point in (bone.head, bone.tail):
            for axis in range(3):
                point[axis] = low[axis] + (point[axis] - rig_low[axis]) * scale[axis]
    for bone, connected in connections:
        bone.use_connect = connected
    bpy.ops.object.mode_set(mode="OBJECT")


def evaluated_points(meshes):
    bpy.context.view_layer.update()
    result = []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        result.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
        evaluated.to_mesh_clear()
    return result


def max_displacement(before, after):
    if len(before) != len(after):
        return float("inf")
    return max((a - b).length for a, b in zip(before, after)) if before else 0.0


def cap_influences(mesh, rig, limit):
    allowed = {bone.name for bone in rig.data.bones if bone.use_deform and
               (bone.name == "DEF-spine" or bone.name.startswith((
                   "DEF-spine.", "DEF-pelvis.", "DEF-thigh.", "DEF-shin.", "DEF-foot.",
                   "DEF-toe.", "DEF-shoulder.", "DEF-upper_arm.", "DEF-forearm.", "DEF-hand.")))}
    if not allowed:
        fail("Rigify armature has no supported body deform bones")
    destinations = {}
    for bone in rig.data.bones:
        ancestor = bone
        while ancestor and ancestor.name not in allowed:
            ancestor = ancestor.parent
        destinations[bone.name] = ancestor.name if ancestor else "DEF-spine.006"
    groups = {group.name: group for group in mesh.vertex_groups}
    for name in sorted(set(destinations.values())):
        if name not in groups:
            groups[name] = mesh.vertex_groups.new(name=name)
    parent = list(range(len(mesh.data.vertices)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for edge in mesh.data.edges:
        left, right = (find(index) for index in edge.vertices)
        if left != right:
            parent[right] = left
    components = {}
    for vertex in mesh.data.vertices:
        components.setdefault(find(vertex.index), []).append(vertex)
    largest = max(components, key=lambda root: len(components[root]))
    core_bones = [bone for bone in rig.data.bones if bone.name in allowed]

    def nearest_bone(vertices):
        points = [mesh.matrix_world @ vertex.co for vertex in vertices]
        best_name, best_distance = None, float("inf")
        for bone in core_bones:
            head, tail = rig.matrix_world @ bone.head_local, rig.matrix_world @ bone.tail_local
            segment = tail - head
            length_squared = max(segment.length_squared, 1e-12)
            distance = 0.0
            for point in points:
                t = max(0.0, min(1.0, (point - head).dot(segment) / length_squared))
                distance += (point - (head + t * segment)).length_squared
            distance /= len(points)
            if distance < best_distance:
                best_name, best_distance = bone.name, distance
        return best_name

    component_vertices = set()
    component_report = []
    for root, vertices in components.items():
        if root == largest:
            continue
        bound = {}
        for vertex in vertices:
            component_vertices.add(vertex.index)
            name = nearest_bone([vertex])
            bound[name] = bound.get(name, 0) + 1
        component_report.append({"vertices": len(vertices), "bound_bones": bound})

    def arm_weights(point):
        point = mesh.matrix_world @ point
        side = "L" if point.x > 0 else "R"
        if abs(point.x) < 0.22 or not 0.9 <= point.z <= 1.56:
            return None
        if abs(point.x) < 0.42 and point.z < 1.10:
            return None
        candidates = [rig.data.bones.get(f"DEF-{part}.{side}") for part in (
            "shoulder", "upper_arm", "upper_arm.001", "forearm", "forearm.001", "hand")]
        candidates = [bone for bone in candidates if bone and bone.name in allowed]
        scores = []
        for bone in candidates:
            head, tail = rig.matrix_world @ bone.head_local, rig.matrix_world @ bone.tail_local
            segment = tail - head
            t = max(0.0, min(1.0, (point - head).dot(segment) / max(segment.length_squared, 1e-12)))
            distance_squared = (point - (head + t * segment)).length_squared
            scores.append((bone.name, 1.0 / (distance_squared + 0.003)))
        scores = sorted(scores, key=lambda item: item[1], reverse=True)[:limit]
        total = sum(weight for _, weight in scores)
        return [(name, weight / total) for name, weight in scores] if total else None

    maximum = 0
    for vertex in mesh.data.vertices:
        old_weights = [(item.group, item.weight) for item in vertex.groups]
        spatial = arm_weights(vertex.co)
        if spatial:
            kept, total = spatial, 1.0
        elif vertex.index in component_vertices:
            kept, total = [(nearest_bone([vertex]), 1.0)], 1.0
        else:
            aggregated = {}
            for index, weight in old_weights:
                name = destinations.get(mesh.vertex_groups[index].name, "DEF-spine.006")
                aggregated[name] = aggregated.get(name, 0.0) + weight
            kept = sorted(aggregated.items(), key=lambda item: item[1], reverse=True)[:limit]
            total = sum(weight for _, weight in kept)
            if total <= 0:
                kept, total = [("DEF-spine.006", 1.0)], 1.0
        for index, _ in old_weights:
            mesh.vertex_groups[index].remove([vertex.index])
        for name, weight in kept:
            groups[name].add([vertex.index], weight / total, "REPLACE")
        maximum = max(maximum, len(vertex.groups))
    return maximum, {"strategy": "3D nearest limb segments for arm-zone vertices; nearest core bone on other disconnected islands; remapped heat weights elsewhere",
                     "disconnected_islands": component_report}


def weld_mesh(mesh, distance):
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=distance)
    merged = before - len(bm.verts)
    bm.to_mesh(mesh.data)
    boundary_edges = sum(edge.is_boundary for edge in bm.edges)
    nonmanifold_edges = sum(not edge.is_manifold and not edge.is_boundary for edge in bm.edges)
    bm.free()
    mesh.data.update()
    return {"merged_vertices": merged, "boundary_edges": boundary_edges,
            "nonmanifold_edges": nonmanifold_edges}


def setup_render(low, high):
    scene = bpy.context.scene
    center = (low + high) * 0.5
    height = (high - low).z
    camera_data = bpy.data.cameras.new("SlopForgeReviewCamera")
    camera = bpy.data.objects.new("SlopForgeReviewCamera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = center + Vector((0, -height * 3.5, height * 0.1))
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = max((high - low).x, height) * 1.45
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera
    light_data = bpy.data.lights.new("SlopForgeReviewLight", "AREA")
    light = bpy.data.objects.new("SlopForgeReviewLight", light_data)
    scene.collection.objects.link(light)
    light.location = center + Vector((-height, -height * 2, height * 2))
    light_data.energy = max(500, height * height * 900)
    light_data.shape = "DISK"
    light_data.size = height * 1.5
    light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.12, 0.12, 0.12)


def render_pose(rig, meshes, pose, controls, destination):
    use_ik = any(name.startswith("hand_ik.") for name in controls)
    for name in ("upper_arm_parent.L", "upper_arm_parent.R", "thigh_parent.L", "thigh_parent.R"):
        switch = rig.pose.bones.get(name)
        if switch is not None and "IK_FK" in switch:
            switch["IK_FK"] = 0.0 if use_ik and name.startswith("upper_arm_parent.") else 1.0
    for bone in rig.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0, 0, 0)
        bone.scale = (1, 1, 1)
    missing = []
    for name, rotation in controls.items():
        bone = rig.pose.bones.get(name)
        if bone is None:
            missing.append(name)
        elif name.startswith("hand_ik."):
            matrix = bone.matrix.copy()
            matrix.translation += Vector(rotation)
            bone.matrix = matrix
        else:
            bone.rotation_mode = "XYZ"
            bone.rotation_euler = rotation
    destination.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(destination)
    bpy.ops.render.render(write_still=True)
    return {"missing_controls": missing}


def run(request):
    source = Path(request["source"]).resolve()
    export_path = Path(request["rigged_model"]).resolve()
    if not source.is_file() or not source.stat().st_size:
        fail(f"Character source is missing or empty: {source}")
    if export_path.exists():
        fail(f"Refusing to overwrite existing rigged model: {export_path}")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    meshes = imported_meshes(source)
    low, high = bounds(meshes)
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    bpy.ops.object.select_all(action="DESELECT")
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    weld_distance = max(high - low) * float(request.get("weld_relative_tolerance", 1e-5))
    mesh_reports = [weld_mesh(mesh, weld_distance) for mesh in meshes]
    nonmanifold_edges = sum(item["nonmanifold_edges"] for item in mesh_reports)
    boundary_edges = sum(item["boundary_edges"] for item in mesh_reports)
    topology_review_only = request.get("topology_policy") == "allow_for_review"
    if (nonmanifold_edges or boundary_edges) and not topology_review_only:
        fail(f"Character mesh has {nonmanifold_edges} non-manifold edges after welding; repair it before rigging")
    low, high = bounds(meshes)

    bpy.ops.preferences.addon_enable(module="rigify")
    bpy.ops.object.armature_human_metarig_add()
    metarig = bpy.context.object
    fit_metarig(metarig, low, high)
    bpy.context.view_layer.objects.active = metarig
    metarig.select_set(True)
    bpy.ops.pose.rigify_generate()
    rig = bpy.context.object
    if rig.type != "ARMATURE" or rig == metarig:
        fail("Rigify did not create a generated control rig")

    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = rig
    try:
        bind_result = bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except Exception as exc:
        fail("Automatic skin weighting failed; inspect the source mesh or adjust its fit: " + str(exc))
    if "FINISHED" not in bind_result:
        fail("Automatic skin weighting was cancelled; inspect the source mesh and humanoid fit")
    for mesh in meshes:
        modifiers = [modifier for modifier in mesh.modifiers if modifier.type == "ARMATURE"]
        if not any(modifier.object == rig for modifier in modifiers):
            fail(f"Automatic skinning created no armature modifier for {mesh.name}")
        if not mesh.vertex_groups:
            fail(f"Automatic skinning created no vertex weights for {mesh.name}")
        if not any(vertex.groups for vertex in mesh.data.vertices):
            fail(f"Automatic skinning assigned no weighted vertices for {mesh.name}")

    influence_limit = int(request.get("max_influences", 4))
    if influence_limit <= 0:
        fail("Maximum skin influences must be positive")
    skin_weighting = [cap_influences(mesh, rig, influence_limit) for mesh in meshes]
    max_influences = max(item[0] for item in skin_weighting)

    deform_bones = [bone.name for bone in rig.data.bones if bone.use_deform]
    if not deform_bones:
        fail("Generated Rigify armature contains no deform bones")
    low, high = bounds(meshes)
    setup_render(low, high)
    evidence_metrics = {}
    baseline = evaluated_points(meshes)
    for pose_name, controls in POSES.items():
        control_report = render_pose(rig, meshes, pose_name, controls,
                                     Path(request["evidence"][pose_name]))
        posed = evaluated_points(meshes)
        evidence_metrics[pose_name] = {**control_report, "max_vertex_displacement": max_displacement(baseline, posed)}
    for bone in rig.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0, 0, 0)
        bone.scale = (1, 1, 1)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    for mesh in meshes:
        mesh.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    export_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(filepath=str(export_path), use_selection=True, object_types={"ARMATURE", "MESH"},
        use_armature_deform_only=True, add_leaf_bones=False, bake_anim=False,
        path_mode="COPY", embed_textures=True)
    if not export_path.is_file() or not export_path.stat().st_size:
        fail("Rigify FBX export is missing or empty")
    if request.get("rigged_blend"):
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(request["rigged_blend"]).resolve()))

    report = {"status": "complete", "provider": {"name": "Blender Rigify", "version": bpy.app.version_string,
        "source": "https://docs.blender.org/manual/en/5.1/addons/rigging/rigify/",
        "license": "GPL-2.0-or-later", "model": "Blender bundled human metarig",
        "model_license": "GPL-2.0-or-later"},
        "source": {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        "skeleton_mapping": {name: name for name in deform_bones},
        "unity_humanoid_mapping": {
            "Hips": "torso", "Spine": "spine_fk.003", "Head": "ORG-face",
            "LeftUpperArm": "DEF-upper_arm.L", "LeftLowerArm": "DEF-forearm.L", "LeftHand": "DEF-hand.L",
            "RightUpperArm": "DEF-upper_arm.R", "RightLowerArm": "DEF-forearm.R", "RightHand": "DEF-hand.R",
            "LeftUpperLeg": "DEF-thigh.L", "LeftLowerLeg": "DEF-shin.L", "LeftFoot": "DEF-foot.L",
            "RightUpperLeg": "DEF-thigh.R", "RightLowerLeg": "DEF-shin.R", "RightFoot": "DEF-foot.R"},
        "deformation_evidence": evidence_metrics,
        "max_influences": max_influences,
        "skin_weighting": [item[1] for item in skin_weighting],
        "mesh_repair": {"weld_tolerance": weld_distance, "meshes": mesh_reports,
                        "topology_policy": "allow_for_review" if topology_review_only else "strict",
                        "review_only": bool(topology_review_only and (nonmanifold_edges or boundary_edges))},
        "validation": {"status": "not_run", "warnings": [
            "Rigify fitting uses source mesh bounds; inspect joint placement and all deformation poses.",
            "Automatic weights are candidates and are not a substitute for manual skin review.",
            *([f"Review-only topology: {nonmanifold_edges} non-manifold and {boundary_edges} boundary edges remain; production eligibility is not established."
              ] if topology_review_only and (nonmanifold_edges or boundary_edges) else [])]}}
    Path(request["report"]).write_text(json.dumps(report, indent=2) + "\n")


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(args) != 1:
        raise SystemExit("Usage: blender --background --python rigify_character.py -- request.json")
    request = json.loads(Path(args[0]).read_text())
    try:
        run(request)
    except Exception as exc:
        traceback.print_exc()
        Path(request["report"]).write_text(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
