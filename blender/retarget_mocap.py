"""Retarget a BVH/FBX motion-capture clip onto a rigged character's deform skeleton.

Usage: blender --background --python retarget_mocap.py -- request.json

request.json: {"rig": rig.fbx, "motion": clip.bvh, "output_blend": out.blend, "report": report.json,
               "bone_mapping": {source: target}, "in_place": true}

Rest poses of mocap (usually T-pose) and generated characters (A-pose) differ, so copying local
rotations or pose transforms bends limbs into the body. Each target bone is first aligned to its
source bone's rest direction (a swing rotation), then follows the source bone's world-space change
from rest; limbs therefore point where the actor's limbs point. The source is turned to face the
character and scaled to its hip height. With in_place, horizontal hip travel is removed so the
character walks on the spot for review.
"""
import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


# Hands follow the forearms: CMU wrist data is noisy and turned palms outward on retargeted characters.
CMU_TO_RIGIFY = {
    "Hips": "DEF-spine", "LowerBack": "DEF-spine.001", "Spine": "DEF-spine.002", "Spine1": "DEF-spine.003",
    "Neck": "DEF-spine.004", "Neck1": "DEF-spine.005", "Head": "DEF-spine.006",
    "LeftShoulder": "DEF-shoulder.L", "LeftArm": "DEF-upper_arm.L", "LeftForeArm": "DEF-forearm.L",
    "RightShoulder": "DEF-shoulder.R", "RightArm": "DEF-upper_arm.R", "RightForeArm": "DEF-forearm.R",
    "LeftUpLeg": "DEF-thigh.L", "LeftLeg": "DEF-shin.L", "LeftFoot": "DEF-foot.L", "LeftToeBase": "DEF-toe.L",
    "RightUpLeg": "DEF-thigh.R", "RightLeg": "DEF-shin.R", "RightFoot": "DEF-foot.R", "RightToeBase": "DEF-toe.R",
}


def fail(message):
    raise RuntimeError(message)


def imported(action):
    before = set(bpy.data.objects)
    action()
    return [obj for obj in bpy.data.objects if obj not in before]


def armature_of(objects, label):
    armatures = [obj for obj in objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        fail(f"{label} must contain exactly one armature; found {len(armatures)}")
    return armatures[0]


def rest_world(armature, name):
    return armature.matrix_world @ armature.data.bones[name].matrix_local


def facing(armature, left, right):
    """Forward direction in world space: perpendicular to the hip line, horizontal."""
    across = rest_world(armature, right).translation - rest_world(armature, left).translation
    forward = Vector((0, 0, 1)).cross(across)
    forward.z = 0
    return forward.normalized()


def bvh_fps(path):
    if path.suffix.lower() != ".bvh":
        return None
    for line in path.read_text(errors="ignore").splitlines():
        if line.strip().lower().startswith("frame time:"):
            seconds = float(line.split(":", 1)[1])
            return round(1.0 / seconds, 3) if seconds > 0 else None
    return None


def gait_cycle(armature, foot, start, end):
    """One full stride (left foot plant to the next left foot plant) for a seamless loop."""
    if not foot or foot not in armature.pose.bones:
        return None
    heights = []
    for frame in range(start, end + 1):
        bpy.context.scene.frame_set(frame)
        heights.append((armature.matrix_world @ armature.pose.bones[foot].head).z)
    low, high = min(heights), max(heights)
    threshold = low + 0.25 * (high - low)
    plants = [start + index for index in range(1, len(heights) - 1)
              if heights[index] <= threshold and heights[index - 1] > threshold]
    return (plants[0], plants[1]) if len(plants) >= 2 else None


def run(request):
    rig_path, motion_path = Path(request["rig"]).resolve(), Path(request["motion"]).resolve()
    for path in (rig_path, motion_path):
        if not path.is_file() or not path.stat().st_size:
            fail(f"Missing or empty input: {path}")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    target_objects = imported(lambda: bpy.ops.import_scene.fbx(filepath=str(rig_path)))
    target = armature_of(target_objects, "Character rig")
    if motion_path.suffix.lower() == ".bvh":
        source_objects = imported(lambda: bpy.ops.import_anim.bvh(filepath=str(motion_path), rotate_mode="NATIVE",
                                                                  axis_forward="-Z", axis_up="Y"))
    else:
        source_objects = imported(lambda: bpy.ops.import_scene.fbx(filepath=str(motion_path)))
    source = armature_of(source_objects, "Motion source")
    action = source.animation_data.action if source.animation_data else None
    if action is None:
        fail("Motion source has no animation action")
    mapping = request.get("bone_mapping") or CMU_TO_RIGIFY
    mapping = {s: t for s, t in mapping.items() if s in source.data.bones and t in target.data.bones}
    for needed in ("Hips", "LeftUpLeg", "RightUpLeg"):
        if needed not in mapping:
            fail(f"Bone mapping needs the source bone {needed!r} and its target")

    # Face the actor the same way as the character, and match hip height so root motion scales.
    scene = bpy.context.scene
    start, end = (int(value) for value in action.frame_range)
    scene.frame_set(start)
    target_forward = facing(target, mapping["LeftUpLeg"], mapping["RightUpLeg"])
    source_forward = facing(source, "LeftUpLeg", "RightUpLeg")
    turn = source_forward.rotation_difference(target_forward).to_matrix().to_4x4()
    target_hips = rest_world(target, mapping["Hips"]).translation
    source_hips = rest_world(source, "Hips").translation
    lowest = min((source.matrix_world @ bone.head_local).z for bone in source.data.bones)
    scale = (target_hips.z - min((target.matrix_world @ b.head_local).z for b in target.data.bones)) / max(
        source_hips.z - lowest, 1e-6)
    source.matrix_world = Matrix.Translation(target_hips) @ turn @ Matrix.Diagonal((scale, scale, scale, 1)) \
        @ Matrix.Translation(-source_hips) @ source.matrix_world
    bpy.context.view_layer.update()

    # Per mapped bone: align the target rest direction to the source rest direction (swing only).
    pairs = []
    for source_name, target_name in mapping.items():
        source_rest = rest_world(source, source_name)
        target_rest = rest_world(target, target_name)
        source_direction = (source_rest.to_3x3() @ Vector((0, 1, 0))).normalized()
        target_direction = (target_rest.to_3x3() @ Vector((0, 1, 0))).normalized()
        align = target_direction.rotation_difference(source_direction).to_matrix()
        pairs.append((source_name, target_name, source_rest.to_3x3(), target_rest.to_3x3(), align))
    order = {bone.name: len(bone.parent_recursive) for bone in target.data.bones}
    pairs.sort(key=lambda item: order[item[1]])

    rest_hips_world = (source.matrix_world @ source.pose.bones["Hips"].matrix).translation.copy()
    target_object_inverse = target.matrix_world.inverted()
    for frame in range(start, end + 1):
        scene.frame_set(frame)
        for source_name, target_name, source_rest_3x3, target_rest_3x3, align in pairs:
            source_now = (source.matrix_world @ source.pose.bones[source_name].matrix).to_3x3()
            delta = source_now @ source_rest_3x3.inverted()
            rotation = (delta @ align @ target_rest_3x3).normalized()
            bone = target.pose.bones[target_name]
            world = bone.id_data.matrix_world @ bone.matrix
            location = world.translation
            if source_name == "Hips":
                hips = (source.matrix_world @ source.pose.bones["Hips"].matrix).translation
                offset = hips - rest_hips_world
                if request.get("in_place", True):
                    offset.x = offset.y = 0.0
                location = target_hips + offset
            bone.matrix = target_object_inverse @ (Matrix.Translation(location) @ rotation.to_4x4())
            bpy.context.view_layer.update()
            bone.keyframe_insert("rotation_quaternion" if bone.rotation_mode == "QUATERNION" else "rotation_euler",
                                 frame=frame)
            if source_name == "Hips":
                bone.keyframe_insert("location", frame=frame)
    for obj in source_objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    scene.frame_start, scene.frame_end = start, end
    cycle = gait_cycle(target, mapping.get("LeftFoot"), start, end)
    if cycle:
        scene["gait_cycle"] = list(cycle)
    capture_fps = bvh_fps(motion_path)
    if capture_fps:
        scene["capture_fps"] = capture_fps
    if request.get("output_blend"):
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(request["output_blend"]).resolve()))
    Path(request["report"]).write_text(json.dumps({
        "status": "complete", "frames": end - start + 1, "frame_start": start, "frame_end": end,
        "capture_fps": capture_fps, "gait_cycle": list(cycle) if cycle else None,
        "method": "rest-direction-aligned world rotation retarget", "scale": scale,
        "in_place": bool(request.get("in_place", True)), "bone_mapping": mapping}, indent=2) + "\n")


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(args) != 1:
        raise SystemExit("Usage: blender --background --python retarget_mocap.py -- request.json")
    request = json.loads(Path(args[0]).read_text())
    try:
        run(request)
    except Exception as exc:
        traceback.print_exc()
        Path(request["report"]).write_text(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
