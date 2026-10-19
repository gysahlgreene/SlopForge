"""Retarget a BVH/FBX motion-capture clip onto a rigged character's deform skeleton.

Usage: blender --background --python retarget_mocap.py -- request.json

request.json: {"rig": rig.fbx, "motion": clip.bvh, "output_blend": out.blend, "report": report.json,
               "bone_mapping": {source: target}, "in_place": true}

Rest poses of mocap (usually T-pose) and generated characters (A-pose) differ, so copying local
rotations or pose transforms bends limbs into the body. Each limb bone is first aligned to its
source bone's rest direction (a swing rotation); every mapped bone then follows the source bone's
world-space change from rest, so limbs point where the actor's limbs point while the torso and
clavicles keep the character's own build. The source is turned to face the
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


# Unity Humanoid bone names, as written by the SkinTokens post-processor.
CMU_TO_HUMANOID = {
    "Hips": "Hips", "LowerBack": "Spine", "Spine": "Chest", "Spine1": "UpperChest", "Neck": "Neck", "Head": "Head",
    "LeftShoulder": "LeftShoulder", "LeftArm": "LeftUpperArm", "LeftForeArm": "LeftLowerArm",
    "RightShoulder": "RightShoulder", "RightArm": "RightUpperArm", "RightForeArm": "RightLowerArm",
    "LeftUpLeg": "LeftUpperLeg", "LeftLeg": "LeftLowerLeg", "LeftFoot": "LeftFoot", "LeftToeBase": "LeftToes",
    "RightUpLeg": "RightUpperLeg", "RightLeg": "RightLowerLeg", "RightFoot": "RightFoot", "RightToeBase": "RightToes",
}


# CMU limb names without their Left/Right prefix.
LIMB_BONES = {"Arm", "ForeArm", "UpLeg", "Leg", "Foot"}


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
    # Percentiles, not min/max: mocap clips often start with a calibration T-pose whose foot height
    # is outside the walk's range and would push the plant threshold below every step.
    ordered = sorted(heights)
    low, high = ordered[len(ordered) // 10], ordered[len(ordered) * 9 // 10]
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
    mapping = request.get("bone_mapping") or max(
        (CMU_TO_RIGIFY, CMU_TO_HUMANOID), key=lambda table: sum(name in target.data.bones for name in table.values()))
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

    # Per mapped bone: the rest alignment (swing only) and both rest orientations.
    pairs = []
    def first_mapped_ancestor(armature, name, names):
        bone = armature.data.bones[name].parent
        while bone is not None and bone.name not in names:
            bone = bone.parent
        return bone.name if bone else None

    def towards(armature, name, child):
        """Direction to the paired next joint; FBX/glTF bone tails are guesses, joints are not."""
        vector = armature.data.bones[child].head_local - armature.data.bones[name].head_local
        return (armature.matrix_world.to_3x3() @ vector).normalized()

    for source_name, target_name in mapping.items():
        source_rest = rest_world(source, source_name)
        target_rest = rest_world(target, target_name)
        # Limbs carry posture in their rest pose (A-pose arms, T-pose actor): swing the target onto the
        # source's rest direction so limbs point where the actor's do. Torso, neck, clavicle and end bones
        # differ only in where each skeleton puts its joints (CMU's clavicle rises from mid-chest, a
        # SkinTokens clavicle falls from the neck), so they follow only the source's change from rest.
        align = Matrix.Identity(3)
        if source_name.removeprefix("Left").removeprefix("Right") in LIMB_BONES:
            children = [other for other in mapping if first_mapped_ancestor(source, other, mapping) == source_name]
            source_child, target_child = (children[0], mapping[children[0]]) if len(children) == 1 else (None, None)
            if source_child is None:
                # Unmapped next joint (forearm -> wrist): use it when both skeletons have exactly one.
                source_children = list(source.data.bones[source_name].children)
                target_children = list(target.data.bones[target_name].children)
                if len(source_children) == 1 and len(target_children) == 1:
                    source_child, target_child = source_children[0].name, target_children[0].name
            if source_child:
                align = towards(target, target_name, target_child).rotation_difference(
                    towards(source, source_name, source_child)).to_matrix()
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
    # Stride timing belongs to the clip: measure it on the actor's ankle, not on the character, whose
    # foot motion depends on its own proportions and weights. Toes roll through stance and give no
    # clean plants; without a LeftFoot joint, use the lowest mapped left joint.
    left = [name for name in mapping if name.startswith("Left") and name in source.pose.bones]
    foot = "LeftFoot" if "LeftFoot" in left else (
        min(left, key=lambda name: rest_world(source, name).translation.z) if left else None)
    cycle = gait_cycle(source, foot, start, end)
    for obj in source_objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    scene.frame_start, scene.frame_end = start, end
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
        "method": "limb rest-direction-aligned world rotation retarget", "scale": scale,
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
