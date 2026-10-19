"""Retarget a BVH/FBX motion-capture clip onto a rigged character's deform skeleton.

Usage: blender --background --python retarget_mocap.py -- request.json

request.json: {"rig": rig.fbx, "motion": clip.bvh, "output_blend": out.blend, "report": report.json,
               "bone_mapping": {source: target}, "in_place": true}

Rest poses of mocap (usually T-pose) and generated characters (A-pose) differ, so copying local
rotations or pose transforms bends limbs into the body. Each limb bone is first aligned to its
source bone's rest direction (a swing rotation); every mapped bone then follows the source bone's
world-space change from a reference, so limbs point where the actor's limbs point while the torso and
clavicles keep the character's own build. Limbs are referenced to the actor's rest (T-pose); torso,
neck, head and end bones to the actor's average posture over one detected stride, so the actor's
habitual posture is not stamped onto the character. The source is turned to face the
character and scaled to its hip height. With in_place, horizontal hip travel is removed so the
character walks on the spot for review.
"""
import json
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector


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


# Unreal-style game-engine skeleton names (MakeHuman/MPFB "game_engine" rig, UE mannequin).
CMU_TO_GAME_ENGINE = {
    "Hips": "pelvis", "LowerBack": "spine_01", "Spine": "spine_02", "Spine1": "spine_03", "Neck": "neck_01", "Head": "head",
    "LeftShoulder": "clavicle_l", "LeftArm": "upperarm_l", "LeftForeArm": "lowerarm_l",
    "RightShoulder": "clavicle_r", "RightArm": "upperarm_r", "RightForeArm": "lowerarm_r",
    "LeftUpLeg": "thigh_l", "LeftLeg": "calf_l", "LeftFoot": "foot_l", "LeftToeBase": "ball_l",
    "RightUpLeg": "thigh_r", "RightLeg": "calf_r", "RightFoot": "foot_r", "RightToeBase": "ball_r",
}


MAX_ARM_CLEARANCE_DEGREES = 15

# CMU limb names without their Left/Right prefix.
LIMB_BONES = {"Arm", "ForeArm", "UpLeg", "Leg"}
# Feet are referenced to the actor's flat (stance) foot, not its rest direction: skeletons put the toe
# joint at different points (CMU: ball of the foot; SkinTokens: further forward and lower), so copying
# the ankle-to-toe direction held generated feet 12-40 degrees toe-up and folded their boots.
FOOT_BONES = {"Foot", "ToeBase"}


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


def clear_arms(target, meshes, mapping, forward, frames, scene):
    """Swing each arm outward just enough that forearm and hand clear the character's own body.

    Limbs copy the actor's hang angle, but generated characters are often much wider at the hips
    (holsters, armour, stylized waists), so the actor's angle drives the hand through the thigh.
    From the rest mesh, the smallest hang angle at which the arm line (elbow to fingertip) clears
    the body silhouette is found; when the actor's arm hangs closer on more than a tenth of the
    stride, the whole arm chain is rotated outward about the shoulder by a constant offset, keeping
    the actor's swing. Returns the offset in degrees per side.
    """
    up = Vector((0, 0, 1))
    world = target.matrix_world
    height = max((world @ bone.head_local).z for bone in target.data.bones) - min(
        (world @ bone.head_local).z for bone in target.data.bones)
    offsets = {}
    for side in ("Left", "Right"):
        upper, lower = mapping.get(side + "Arm"), mapping.get(side + "ForeArm")
        if not upper or not lower:
            continue
        chain = {upper} | {bone.name for bone in target.data.bones[upper].children_recursive}
        shoulder = world @ target.data.bones[upper].head_local
        outward = shoulder - world @ target.data.bones[mapping["Hips"]].head_local
        outward -= forward * outward.dot(forward)
        outward.z = 0
        outward.normalize()
        arm_points, body = [], []
        for obj in meshes:
            groups = {group.index: group.name for group in obj.vertex_groups}
            for vertex in obj.data.vertices:
                weights = [(item.weight, groups.get(item.group)) for item in vertex.groups]
                if not weights:
                    continue
                point = obj.matrix_world @ vertex.co
                (arm_points if max(weights)[1] in chain else body).append(point)
        if not arm_points or not body:
            continue
        reach = max((point - shoulder).length for point in arm_points)
        margin, band = 0.02 * height, 0.012 * height
        silhouette = [((point - shoulder).dot(outward), point.z) for point in body]

        def clear(angle):
            direction = outward * math.sin(angle) - up * math.cos(angle)
            for fraction in (0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.0):
                point = shoulder + direction * reach * fraction
                lateral = point - shoulder
                if any(u > lateral.dot(outward) - margin for u, z in silhouette if abs(z - point.z) < band):
                    return False
            return True

        needed = next((math.radians(degrees / 2) for degrees in range(0, 121) if clear(math.radians(degrees / 2))),
                      math.radians(60))
        hand_name = (target.data.bones[lower].children[0].name if target.data.bones[lower].children else None)
        angles = []
        for frame in frames:
            scene.frame_set(frame)
            head = world @ target.pose.bones[upper].head
            wrist = world @ (target.pose.bones[hand_name].head if hand_name else target.pose.bones[lower].tail)
            hang = wrist - head
            angles.append(math.atan2(hang.dot(outward), -hang.z))
        angles.sort()
        # Capped: bulky clothes (jacket pockets) would otherwise hold the arms out like wings; a
        # little cloth contact reads better than a stiff, spread pose.
        offset = min(max(0.0, needed - angles[len(angles) // 10]), math.radians(MAX_ARM_CLEARANCE_DEGREES))
        offsets[side] = round(math.degrees(offset), 1)
        if offset < math.radians(0.5):
            continue
        sign = 1 if (Matrix.Rotation(offset, 3, forward) @ -up).dot(outward) > 0 else -1
        rotation = Matrix.Rotation(sign * offset, 4, forward)
        inverse = world.inverted()
        for frame in frames:
            scene.frame_set(frame)
            pivot = world @ target.pose.bones[upper].head
            swing = Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot)
            # Capture both before changing either: the forearm inherits its parent's new rotation.
            targets = [(name, swing @ (world @ target.pose.bones[name].matrix)) for name in (upper, lower)]
            for name, matrix in targets:
                bone = target.pose.bones[name]
                bone.matrix = inverse @ matrix
                bpy.context.view_layer.update()
                bone.keyframe_insert("rotation_quaternion" if bone.rotation_mode == "QUATERNION" else "rotation_euler",
                                     frame=frame)
    return offsets


def widen_stance(target, mapping, forward, frames, scene, floor=0.5):
    """Keep each foot on its own side of the body, as a constant outward swing of the leg.

    Mocap actors often walk with a foot reaching the midline (CMU 07_02's right ankle does), which
    on a slimmer or stylized character reads as legs crossing on a catwalk line. Each ankle's
    sideways distance from the pelvis centre is measured in units of the character's hip half-width;
    when its 10th percentile over the stride is below `floor`, thigh and shin swing outward about
    the hip by a constant angle, and the foot keeps its world orientation so soles stay flat.
    Returns the swing in degrees per side.
    """
    world = target.matrix_world
    inverse = world.inverted()
    up = Vector((0, 0, 1))
    swings = {}
    for side in ("Left", "Right"):
        thigh, shin, foot = (mapping.get(side + name) for name in ("UpLeg", "Leg", "Foot"))
        if not (thigh and shin and foot):
            continue
        other = mapping["RightUpLeg" if side == "Left" else "LeftUpLeg"]
        laterals, leg = [], (world @ target.data.bones[foot].head_local - world @ target.data.bones[thigh].head_local).length
        for frame in frames:
            scene.frame_set(frame)
            mine, theirs = world @ target.pose.bones[thigh].head, world @ target.pose.bones[other].head
            across = mine - theirs
            across.z = 0
            half = across.length / 2
            ankle = world @ target.pose.bones[foot].head
            laterals.append(((ankle - (mine + theirs) / 2).dot(across.normalized()) / half, half))
        laterals.sort()
        shortfall, half = laterals[len(laterals) // 10]
        angle = max(0.0, (floor - shortfall) * half / leg)
        swings[side] = round(math.degrees(angle), 1)
        if angle < math.radians(0.5):
            continue
        outward = (world @ target.data.bones[thigh].head_local) - (world @ target.data.bones[other].head_local)
        outward.z = 0
        outward.normalize()
        rotation_sign = 1 if (Matrix.Rotation(angle, 3, forward) @ -up).dot(outward) > 0 else -1
        rotation = Matrix.Rotation(rotation_sign * angle, 4, forward)
        for frame in frames:
            scene.frame_set(frame)
            pivot = world @ target.pose.bones[thigh].head
            swing = Matrix.Translation(pivot) @ rotation @ Matrix.Translation(-pivot)
            # Toes keep their local rotation and follow the foot; moving their head separately left an
            # unkeyed location offset that carried across frames and twisted the toes sideways.
            chain = [(name, world @ target.pose.bones[name].matrix) for name in (thigh, shin, foot)]
            for name, matrix in chain:
                if name in (thigh, shin):
                    matrix = swing @ matrix
                else:
                    # Same orientation, carried to where the swung shin now puts it.
                    matrix = Matrix.Translation((swing @ matrix.translation) - matrix.translation) @ matrix
                bone = target.pose.bones[name]
                bone.matrix = inverse @ matrix
                bpy.context.view_layer.update()
                bone.keyframe_insert("rotation_quaternion" if bone.rotation_mode == "QUATERNION" else "rotation_euler",
                                     frame=frame)
    return swings


def relax_hands(target, mapping, frame):
    """Curl each finger toward the palm, as a relaxed walking hand holds it.

    Mocap wrists and fingers are not retargeted (CMU wrist data is noisy), so generated hands kept
    their modelled pose: fingers straight and splayed. Each finger joint is rotated about the
    knuckle line (index to little-finger bases) toward the palm, which faces the body midline at
    rest; the thumb, whose base sits nearest the wrist, curls less. Returns the curled bone count.
    """
    world = target.matrix_world
    hips = world @ target.data.bones[mapping["Hips"]].head_local
    curled = 0
    for side in ("Left", "Right"):
        lower = mapping.get(side + "ForeArm")
        if not lower or not target.data.bones[lower].children:
            continue
        hand = target.data.bones[lower].children[0]
        fingers = [child for child in hand.children
                   if any(key in child.name.lower() for key in ("finger", "thumb", "index", "middle", "ring", "pinky"))]
        if not fingers:
            continue
        wrist = world @ hand.head_local
        thumb = min(fingers, key=lambda bone: ((world @ bone.head_local) - wrist).length) if len(fingers) > 1 else None
        tips = [world @ bone.tail_local for finger in fingers for bone in [finger, *finger.children_recursive]]
        along = (sum(tips, Vector()) / len(tips) - wrist).normalized()
        inward = hips - wrist
        inward.z = 0
        bases = [world @ bone.head_local for bone in fingers if bone is not thumb]
        if len(bases) >= 2:
            first, last = max(((a, b) for a in bases for b in bases), key=lambda pair: (pair[0] - pair[1]).length)
            axis = (last - first).normalized()
            palm = axis.cross(along).normalized()
            if palm.dot(inward) < 0:
                palm = -palm
        else:
            # Too few fingers for a knuckle line (SkinTokens sometimes predicts two per hand).
            palm = (inward - along * inward.dot(along)).normalized()
            axis = along.cross(palm).normalized()
        for finger in fingers:
            for depth, bone in enumerate([finger, *finger.children_recursive]):
                angle = math.radians(15 if finger is thumb else (20, 30, 25)[min(depth, 2)])
                vector = (world.to_3x3() @ (bone.tail_local - bone.head_local))
                if (Matrix.Rotation(angle, 3, axis) @ vector - vector).dot(palm) < 0:
                    angle = -angle
                local_axis = ((world.to_3x3() @ bone.matrix_local.to_3x3()).inverted() @ axis).normalized()
                pose = target.pose.bones[bone.name]
                pose.rotation_mode = "QUATERNION"
                pose.rotation_quaternion = Quaternion(local_axis, angle)
                pose.keyframe_insert("rotation_quaternion", frame=frame)
                curled += 1
    return curled


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
    if rig_path.suffix.lower() == ".blend":
        # A .blend keeps node materials that an FBX round trip loses (template characters).
        bpy.ops.wm.open_mainfile(filepath=str(rig_path))
        target_objects = list(bpy.data.objects)
    else:
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
        (CMU_TO_RIGIFY, CMU_TO_HUMANOID, CMU_TO_GAME_ENGINE),
        key=lambda table: sum(name in target.data.bones for name in table.values()))
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

    # Stride timing belongs to the clip: measure it on the actor's ankle, not on the character, whose
    # foot motion depends on its own proportions and weights. Toes roll through stance and give no
    # clean plants; without a LeftFoot joint, use the lowest mapped left joint.
    left = [name for name in mapping if name.startswith("Left") and name in source.pose.bones]
    foot = "LeftFoot" if "LeftFoot" in left else (
        min(left, key=lambda name: rest_world(source, name).translation.z) if left else None)
    cycle = gait_cycle(source, foot, start, end)
    if cycle:
        # Face the actor's walking direction (hip travel over the stride), not its rest pose: CMU 07_02
        # walks about 30 degrees off its rest facing, so the pelvis (referenced to the stride's average
        # posture) faced forward while legs and arms swung along the real heading, twisting the legs.
        scene.frame_set(cycle[0])
        first = (source.matrix_world @ source.pose.bones["Hips"].matrix).translation
        scene.frame_set(cycle[1])
        travel = (source.matrix_world @ source.pose.bones["Hips"].matrix).translation - first
        travel.z = 0
        if travel.length > 0.1 * scale * max(source_hips.z - lowest, 1e-6):
            heading = travel.normalized().rotation_difference(target_forward).to_matrix().to_4x4()
            source.matrix_world = Matrix.Translation(target_hips) @ heading @ Matrix.Translation(-target_hips) \
                @ source.matrix_world
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

    if cycle:
        # Posture reference: the BVH zero pose is a synthetic straight-spined T-pose, so following the
        # change from it stamps the actor's habitual posture (CMU 08_01: neck ~9 degrees forward, lower
        # back arched) onto every character. Torso, neck, head and end bones follow the change from the
        # actor's average posture over one stride instead, keeping the character's own sculpted posture
        # and the actor's sway and bob.
        # Feet: the same, averaged only over that side's stance (ankle in the lowest quarter of its
        # height range), where the actor's foot is flat like the character's rest foot.
        heights = {side: [] for side in ("Left", "Right")}
        for frame in range(cycle[0], cycle[1]):
            scene.frame_set(frame)
            for side in heights:
                if side + "Foot" in source.pose.bones:
                    heights[side].append((source.matrix_world @ source.pose.bones[side + "Foot"].head).z)
        stance = {}
        for side, values in heights.items():
            if values:
                ordered = sorted(values)
                limit = ordered[0] + 0.25 * (ordered[-1] - ordered[0])
                stance[side] = {cycle[0] + index for index, value in enumerate(values) if value <= limit}
        def part(name):
            return name.removeprefix("Left").removeprefix("Right")
        torso = [index for index, pair in enumerate(pairs) if part(pair[0]) not in LIMB_BONES]
        sums = {index: None for index in torso}
        for frame in range(cycle[0], cycle[1]):
            scene.frame_set(frame)
            for index in torso:
                name = pairs[index][0]
                if part(name) in FOOT_BONES:
                    side = "Left" if name.startswith("Left") else "Right"
                    if side in stance and frame not in stance[side]:
                        continue
                quaternion = (source.matrix_world @ source.pose.bones[name].matrix).to_quaternion()
                if sums[index] is None:
                    sums[index] = quaternion
                else:
                    if sums[index].dot(quaternion) < 0:
                        quaternion.negate()
                    sums[index] = Quaternion([a + b for a, b in zip(sums[index], quaternion)])
        for index in torso:
            name, target_name, _, target_rest_3x3, align = pairs[index]
            pairs[index] = (name, target_name, sums[index].normalized().to_matrix(), target_rest_3x3, align)

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
    arm_offsets = clear_arms(target, [obj for obj in target_objects if obj.type == "MESH"], mapping,
                             target_forward, range(start, end + 1), scene)
    leg_swings = widen_stance(target, mapping, target_forward, range(start, end + 1), scene)
    curled = relax_hands(target, mapping, start)
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
        "method": "limb rest-direction-aligned, torso stride-posture-referenced world rotation retarget", "scale": scale,
        "in_place": bool(request.get("in_place", True)), "arm_clearance_offset_degrees": arm_offsets,
        "relaxed_finger_bones": curled, "stance_widening_degrees": leg_swings,
        "bone_mapping": mapping}, indent=2) + "\n")


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
