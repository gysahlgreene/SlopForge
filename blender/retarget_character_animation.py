"""Retarget an FBX action onto an imported character armature and export FBX."""
import json
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector


def fail(message):
    raise RuntimeError(message)


def import_source(path):
    before = set(bpy.data.objects)
    if path.suffix.lower() == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif path.suffix.lower() == ".glb":
        bpy.ops.import_scene.gltf(filepath=str(path))
    else:
        fail(f"Unsupported retarget source format: {path.suffix}")
    return [obj for obj in bpy.data.objects if obj not in before]


def one_armature(objects, label):
    armatures = [obj for obj in objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        fail(f"{label} must contain exactly one armature; found {len(armatures)}")
    return armatures[0]


def evaluated_vertices(meshes):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    vertices = []
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        vertices.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
        evaluated.to_mesh_clear()
    return vertices


def run(request):
    rig_file = Path(request["rig"]).resolve()
    animation_file = Path(request["animation"]).resolve()
    output = Path(request["output"]).resolve()
    if not rig_file.is_file() or not rig_file.stat().st_size:
        fail(f"Character rig is missing or empty: {rig_file}")
    if not animation_file.is_file() or not animation_file.stat().st_size:
        fail(f"Animation source is missing or empty: {animation_file}")
    if output.exists():
        fail(f"Refusing to overwrite animation output: {output}")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    rig_objects = import_source(rig_file)
    target = one_armature(rig_objects, "Character rig")
    meshes = [obj for obj in rig_objects if obj.type == "MESH"]
    source_objects = import_source(animation_file)
    source = one_armature(source_objects, "Animation source")
    actions = [action for action in bpy.data.actions if action.name in {
        source.animation_data.action.name if source.animation_data and source.animation_data.action else ""}]
    if not actions:
        actions = [action for action in bpy.data.actions if len(action.fcurves) > 0]
    if len(actions) != 1:
        fail(f"Animation FBX must provide exactly one action; found {len(actions)}")
    action = actions[0]
    if source.animation_data is None:
        source.animation_data_create()
    source.animation_data.action = action

    mapping = request.get("bone_mapping")
    if not isinstance(mapping, dict) or not mapping:
        fail("Animation requires an explicit non-empty source-to-target bone mapping")
    for source_name, target_name in mapping.items():
        if source.pose.bones.get(source_name) is None:
            fail(f"Animation source has no mapped bone {source_name!r}")
        target_bone = target.pose.bones.get(target_name)
        if target_bone is None:
            fail(f"Character rig has no mapped bone {target_name!r}")
        constraint = target_bone.constraints.new("COPY_TRANSFORMS")
        constraint.name = "SlopForge retarget " + source_name
        constraint.target = source
        constraint.subtarget = source_name
        constraint.owner_space = "POSE"
        constraint.target_space = "POSE"

    start, end = (int(math.floor(value)) for value in action.frame_range)
    if end < start:
        fail("Animation action has an invalid frame range")
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = start, end
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    baseline = None
    maximum_displacement = 0.0
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        current = evaluated_vertices(meshes)
        if baseline is None:
            baseline = current
        elif len(current) != len(baseline):
            fail("Evaluated mesh vertex count changed during retarget deformation")
        else:
            maximum_displacement = max(maximum_displacement,
                max(((left - right).length for left, right in zip(baseline, current)), default=0.0))
    bpy.ops.nla.bake(frame_start=start, frame_end=end, only_selected=True, visual_keying=True,
                     clear_constraints=True, use_current_action=True, bake_types={"POSE"})
    bpy.ops.object.mode_set(mode="OBJECT")
    source.select_set(False)
    for obj in source_objects:
        bpy.data.objects.remove(obj, do_unlink=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.export_scene.fbx(filepath=str(output), use_selection=True, object_types={"ARMATURE"},
        add_leaf_bones=False, bake_anim=True, bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False, bake_anim_force_startend_keying=True,
        bake_anim_step=1.0, bake_anim_simplify_factor=0.0)
    if not output.is_file() or not output.stat().st_size:
        fail("Retargeted animation FBX is missing or empty")
    Path(request["report"]).write_text(json.dumps({"status": "complete", "frames": end - start + 1,
        "frame_start": start, "frame_end": end, "max_vertex_displacement": maximum_displacement,
        "bone_mapping": mapping, "loop": bool(request.get("loop")),
        "root_motion": bool(request.get("root_motion"))}, indent=2) + "\n")


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(args) != 1:
        raise SystemExit("Usage: blender --background --python retarget_character_animation.py -- request.json")
    request = json.loads(Path(args[0]).read_text())
    try:
        run(request)
    except Exception as exc:
        traceback.print_exc()
        Path(request["report"]).write_text(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
