"""Blender 5.x Rigify humanoid fitting, skinning, evidence rendering, and FBX export."""
import json
import math
import sys
import traceback
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


POSES = {
    "t_pose": {},
    "raised_arms": {"upper_arm_fk.L": (1.4, 0.0, 0.0), "upper_arm_fk.R": (1.4, 0.0, 0.0)},
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
    for bone in edit_bones:
        for point in (bone.head, bone.tail):
            for axis in range(3):
                point[axis] = low[axis] + (point[axis] - rig_low[axis]) * scale[axis]
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
    for name in ("upper_arm_parent.L", "upper_arm_parent.R", "thigh_parent.L", "thigh_parent.R"):
        switch = rig.pose.bones.get(name)
        if switch is not None and "IK_FK" in switch:
            switch["IK_FK"] = 1.0
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
    if nonmanifold_edges:
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
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    for mesh in meshes:
        mesh.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    export_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(filepath=str(export_path), use_selection=True, object_types={"ARMATURE", "MESH"},
        use_armature_deform_only=True, add_leaf_bones=False, bake_anim=False, path_mode="COPY")
    if not export_path.is_file() or not export_path.stat().st_size:
        fail("Rigify FBX export is missing or empty")

    report = {"status": "complete", "provider": {"name": "Blender Rigify", "version": bpy.app.version_string,
        "source": "https://docs.blender.org/manual/en/5.1/addons/rigging/rigify/",
        "license": "GPL-2.0-or-later", "model": "Blender bundled human metarig",
        "model_license": "GPL-2.0-or-later"},
        "skeleton_mapping": {name: name for name in deform_bones},
        "unity_humanoid_mapping": {
            "Hips": "torso", "Spine": "spine_fk.003", "Head": "ORG-face",
            "LeftUpperArm": "DEF-upper_arm.L", "LeftLowerArm": "DEF-forearm.L", "LeftHand": "DEF-hand.L",
            "RightUpperArm": "DEF-upper_arm.R", "RightLowerArm": "DEF-forearm.R", "RightHand": "DEF-hand.R",
            "LeftUpperLeg": "DEF-thigh.L", "LeftLowerLeg": "DEF-shin.L", "LeftFoot": "DEF-foot.L",
            "RightUpperLeg": "DEF-thigh.R", "RightLowerLeg": "DEF-shin.R", "RightFoot": "DEF-foot.R"},
        "deformation_evidence": evidence_metrics,
        "mesh_repair": {"weld_tolerance": weld_distance, "meshes": mesh_reports},
        "validation": {"status": "not_run", "warnings": [
            "Rigify fitting uses source mesh bounds; inspect joint placement and all deformation poses.",
            "Automatic weights are candidates and are not a substitute for manual skin review."]}}
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
