"""B4 (AI motion sources plan, B4; docs/CREATURES.md, "Computed walk"): a walk built on a creature's B1 rig, saved
as an Action for B6's bake (blender/bake_extracted_motion.py), as video2rig's import_motion saves a fitted clip, with
the review's front and side cameras (`cameras`) the bake renders through.

    blender <rig.blend> --background --factory-startup --python blender/procedural_gait.py -- request.json

The rig faces -Y with its left on +X (B1). The body travels forward at stride / period with a small bob and sway.
Each foot is planted for `duty` of the period where the body will be at mid-stance, and swings to its next plant on a
lifted arc, in the walk's order (hind left, front left, hind right, front right, a quarter period apart). The paw
bone of each leg and the two bones above it follow their foot by IK, its pole set to keep the leg's rest bend; the
tail sways a step behind. The period is snapped to whole frames, the poles travel with the body, and the body is
carried as low as the longest reach needs. Everything is baked to keys on every frame and the IK removed; a leg bone
that turns past FLIPPED from rest is refused.
"""
import json
import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

FORWARD, UP = Vector((0.0, -1.0, 0.0)), Vector((0.0, 0.0, 1.0))
PHASE = {"hind.L": 0.0, "front.L": 0.25, "hind.R": 0.5, "front.R": 0.75}
BOB, SWAY, TAIL_SWAY = 0.012, 0.008, math.radians(10)   # shares of the height; the tail's sideways turn
FLIPPED = 90.0   # degrees a leg bone may not turn from rest in a walk: beyond it the IK has flipped the joint
MARGIN, PANEL = 1.3, 540   # the review views' room around the creature, and their height in pixels
BREATH = 0.004   # an idle's breath: the whole body sinks this share of the height
REACH = 0.97   # a planted foot stays within this share of its leg's length: the body drops to keep it so


def foot_at(rest, phase, t, period, duty, stride, lift):
    """A foot's world position at `t`: planted where the body will be at mid-stance, then swung to the next plant."""
    u = t / period - phase   # a leg's phase delays its cycle: hind left, front left, hind right, front right
    k, c = math.floor(u), u - math.floor(u)
    planted = rest + FORWARD * (stride * (k + phase + duty / 2))
    if c < duty:
        return planted
    s = (c - duty) / (1 - duty)
    return planted + FORWARD * (stride * (1 - math.cos(math.pi * s)) / 2) + UP * (lift * math.sin(math.pi * s))


def cameras(corners, reach):
    """The review's front and side orthographic views, as video2rig's start cameras.json records its own (right, up,
    forward; ortho sizes in metres, panels in pixels), framing the creature at rest with `reach` added along its
    length for the feet's swing."""
    low = Vector([min(c[k] for c in corners) for k in range(3)])
    high = Vector([max(c[k] for c in corners) for k in range(3)])
    centre, size = (low + high) / 2, high - low
    tall = MARGIN * size.z
    views, x0 = [], 0
    for name, forward, right, across in (("front", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), size.x),
                                         ("side", (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), size.y + reach)):
        width = max(160, round(PANEL * MARGIN * across / tall))
        views.append({"name": name, "width_px": width, "height_px": PANEL, "type": "ortho",
                      "location": list(centre - Vector(forward) * 10.0), "right": list(right), "up": [0.0, 0.0, 1.0],
                      "forward": list(forward), "ortho_width": tall * width / PANEL, "ortho_height": tall,
                      "x0_px": x0})
        x0 += width
    return {"frame_px": [x0, PANEL], "views": views}


def chain_error(rig, names, rest):
    return sum((rig.matrix_world @ rig.pose.bones[name].tail - rest[name]).length for name in names)


def leg_ik(rig, chain, empties):
    """IK from the paw bone over it and the two bones above, its target at the paw's tail, its pole on the side the
    leg bends at rest and its pole angle the one that keeps the rest pose. Returns (target empty, rest foot, the
    chain's top joint at rest, the chain's length, pole empty)."""
    world = rig.matrix_world
    paw = next(name for name in chain if "Paw" in name)
    index = chain.index(paw)
    ik = chain[max(0, index - 2):index + 1]
    bones = rig.data.bones
    top, middle = world @ bones[ik[0]].head_local, world @ bones[ik[1]].head_local
    foot = world @ bones[paw].tail_local
    line = (foot - top).normalized()
    bend = middle - (top + line * (middle - top).dot(line))
    bend = bend.normalized() if bend.length > 1e-6 else FORWARD
    target = bpy.data.objects.new(f"IK_{paw}", None)
    pole = bpy.data.objects.new(f"Pole_{paw}", None)
    for empty in (target, pole):
        bpy.context.scene.collection.objects.link(empty)
        empties.append(empty)
    target.location = foot
    pole.location = middle + bend * (foot - top).length
    constraint = rig.pose.bones[paw].constraints.new("IK")
    constraint.target, constraint.pole_target, constraint.chain_count = target, pole, len(ik)
    rest = {name: world @ bones[name].tail_local for name in ik}
    best = None
    for angle in range(-180, 180, 5):
        constraint.pole_angle = math.radians(angle)
        bpy.context.view_layer.update()
        error = chain_error(rig, ik, rest)
        if best is None or error < best[0]:
            best = (error, angle)
    constraint.pole_angle = math.radians(best[1])
    # the toes keep their rest angle to the ground, so a planted foot's tip stays planted as the leg turns over it
    if index + 1 < len(chain):
        toes = chain[index + 1]
        level = bpy.data.objects.new(f"Level_{toes}", None)
        bpy.context.scene.collection.objects.link(level)
        empties.append(level)
        level.matrix_world = world @ bones[toes].matrix_local
        hold = rig.pose.bones[toes].constraints.new("COPY_ROTATION")
        hold.target, hold.owner_space, hold.target_space = level, "WORLD", "WORLD"
    return target, foot.copy(), top.copy(), sum(bones[name].length * world.median_scale for name in ik), pole


def build(request):
    scene = bpy.context.scene
    fps = request.get("fps", 24)
    scene.render.fps, scene.render.fps_base = fps, 1.0
    rigs = [obj for obj in scene.objects if obj.type == "ARMATURE"]
    if len(rigs) != 1:
        raise ValueError(f"the rig .blend must hold one armature, found {len(rigs)}")
    rig = rigs[0]
    if rig.animation_data:
        rig.animation_data.action = None
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion, bone.location, bone.scale = (1, 0, 0, 0), (0, 0, 0), (1, 1, 1)
    bpy.context.view_layer.update()
    walking = request["motion"] == "walk"
    if request["motion"] not in ("walk", "idle"):
        raise ValueError(f"unknown procedural motion {request['motion']!r}")
    frames = int(round(request["seconds"] * fps)) + 1
    if walking:
        duty, stride, lift = request["duty"], request["stride_m"], request["lift_m"]
        period = round(request["period_s"] * fps) / fps   # a whole number of frames, so the loop closes on a frame
    else:
        stride, period = 0.0, (frames - 1) / fps          # the idle is one loop, closing on its last frame
    corners = [obj.matrix_world @ Vector(corner) for obj in scene.objects if obj.type == "MESH"
               for corner in obj.bound_box]
    height = max(c.z for c in corners) - min(c.z for c in corners)
    if request.get("cameras"):
        Path(request["cameras"]).write_text(json.dumps(cameras(corners, stride), indent=1))
    empties, feet = [], {}
    for leg, chain in request["legs"].items():
        feet[leg] = leg_ik(rig, chain, empties)
    root = rig.pose.bones[request["root"]]
    to_rig = rig.matrix_world.inverted().to_3x3()
    rest_root = root.matrix.copy()
    tail, neck = ([rig.pose.bones[name] for name in request.get(key, [])] for key in ("tail", "neck"))
    speed = stride / period

    def pose_at(t):
        """The body's shift and each foot's goal at `t`: a walk's travel, bob and sway with its feet stepping; an
        idle's weight shift and breath with its feet where they stand."""
        if walking:
            shift = FORWARD * (speed * t) + UP * (BOB * height * math.cos(4 * math.pi * t / period))
            shift += Vector((SWAY * height * math.sin(2 * math.pi * t / period), 0.0, 0.0))
            return shift, {leg: foot_at(rest, PHASE[leg], t, period, duty, stride, lift)
                           for leg, (_, rest, _, _, _) in feet.items()}
        u, sway = 2 * math.pi * t / period, request["sway_m"]
        shift = Vector((sway * math.sin(u), 0.4 * sway * math.sin(2 * u), -BREATH * height * breath_at(t)))
        return shift, {leg: rest for leg, (_, rest, _, _, _) in feet.items()}

    def breath_at(t):
        return (1 - math.cos(2 * math.pi * request["breaths"] * t / period)) / 2

    def drop_at(t):
        """How far the body must drop at `t` for its farthest foot to stay within reach."""
        shift, goals = pose_at(t)
        drop = 0.0
        for leg, (_, _, top, length, _) in feet.items():
            gap = top + shift - goals[leg]
            flat = math.hypot(gap.x, gap.y)
            if flat < REACH * length:
                drop = max(drop, gap.z - math.sqrt((REACH * length) ** 2 - flat ** 2))
        return drop

    # the body carries itself as low as the stride's longest reach needs for the whole walk, not dipping at each reach
    drop = max(drop_at(k * period / 48) for k in range(48))
    poles = {leg: pole.location.copy() for leg, (_, _, _, _, pole) in feet.items()}
    for frame in range(frames):
        t = frame / fps
        shift, goals = pose_at(t)
        shift -= UP * drop
        root.matrix = Matrix.Translation(to_rig @ shift) @ rest_root
        root.keyframe_insert("location", frame=frame + 1)
        u = 2 * math.pi * t / period
        sways = 1 if walking else 2   # the tail sways once a stride, twice in an idle's loop
        swing = TAIL_SWAY if walking else math.radians(request["tail_deg"])
        for k, bone in enumerate(tail):   # each tail bone a little later than the one before
            bone.rotation_quaternion = Quaternion((0.0, 0.0, 1.0), swing * math.sin(sways * u - 0.6 * (k + 1)))
            bone.keyframe_insert("rotation_quaternion", frame=frame + 1)
        # an idle's head looks to each side once a loop, nodding; it breathes with its whole body (pose_at): a spine
        # bent with each breath lifted the wolf's neck 29 mm on 3 mm at the hips, which the owner found weird
        if not walking:
            look = math.radians(request["look_deg"])
            for k, bone in enumerate(neck):
                nod = 0.25 * look * math.sin(2 * u) if k == len(neck) - 1 else 0.0
                bone.rotation_quaternion = (Quaternion((1.0, 0.0, 0.0), nod)
                                            @ Quaternion((0.0, 0.0, 1.0), look / len(neck) * math.sin(u + 0.5)))
                bone.keyframe_insert("rotation_quaternion", frame=frame + 1)
        for leg, (target, _, _, _, pole) in feet.items():
            target.location = goals[leg]
            target.keyframe_insert("location", frame=frame + 1)
            pole.location = poles[leg] + shift   # the pole travels with the body, or a knee bent forward flips round
            pole.keyframe_insert("location", frame=frame + 1)
    # how far each paw ends from its target: a target out of the leg's reach would leave a planted foot sliding
    miss, hips, front = 0.0, [], []
    paws = {leg: next(name for name in request["legs"][leg] if "Paw" in name) for leg in feet}
    for frame in range(1, frames + 1, 3):
        scene.frame_set(frame)
        hips.append((rig.matrix_world @ root.head).z)
        front.append((rig.matrix_world @ (neck[0] if neck else root).head).z)   # the base of the neck
        for leg, (target, _, _, _, _) in feet.items():
            miss = max(miss, (rig.matrix_world @ rig.pose.bones[paws[leg]].tail - target.matrix_world.translation).length)
    scene.frame_start, scene.frame_end = 1, frames
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.nla.bake(frame_start=1, frame_end=frames, only_selected=False, visual_keying=True,
                     clear_constraints=True, use_current_action=True, bake_types={"POSE"})
    bpy.ops.object.mode_set(mode="OBJECT")
    for empty in empties:
        bpy.data.objects.remove(empty, do_unlink=True)
    turn, look = 0.0, 0.0   # the baked keys' largest turn of a leg bone from rest, and of the head from its rest
    for frame in range(1, frames + 1, 3):
        scene.frame_set(frame)
        turn = max([turn] + [math.degrees(rig.pose.bones[name].matrix_basis.to_quaternion().angle)
                             for chain in request["legs"].values() for name in chain])
        if neck:
            head = neck[-1]
            look = max(look, math.degrees(head.matrix.to_quaternion().rotation_difference(
                head.bone.matrix_local.to_quaternion()).angle))
    if turn > FLIPPED:
        raise ValueError(f"a leg bone turns {turn:.0f} degrees from its rest pose during the {request['motion']}: "
                         "its IK flipped the knee or elbow round")
    bpy.ops.wm.save_as_mainfile(filepath=request["save"], copy=True)
    return {"status": "complete", "frames": frames, "fps": fps, "period_s": round(period, 4), "speed_mps": round(speed, 4), "height_m": round(height, 4),
            "ik_miss_max_m": round(miss, 4), "body_drop_m": round(drop, 4), "hips_rise_m": round(max(hips) - min(hips), 4),
            "leg_turn_max_deg": round(turn, 1), "front_rise_m": round(max(front) - min(front), 4),
            **({"head_turn_max_deg": round(look, 1)} if neck else {}),
            "legs": {leg: [round(v, 4) for v in rest] for leg, (_, rest, _, _, _) in feet.items()}}


def main():
    request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    try:
        report = build(request)
    except Exception as exc:  # noqa: BLE001 - the report carries every failure to the pipeline
        report = {"status": "error", "errors": [f"{type(exc).__name__}: {exc}"], "traceback": traceback.format_exc()}
    Path(request["report"]).write_text(json.dumps(report, indent=1))


main()
