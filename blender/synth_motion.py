"""B2 for creatures: a known motion of a rigged creature, as the poses.npz video2rig's blender/render_poses.py renders
(every bone's basis rotation per frame, w x y z, and the root's location). Promoted from spike #129's exam_motion.py.

    blender creature.blend --background --factory-startup --python blender/synth_motion.py -- request.json

request: creature (creature.json: fit_bones, hinges, joints ranges, root_bone, facing), kind (random | gait | action),
seed, frames, action (kind action), loops, out (poses.npz), truth (truth.json), report.
- random: every fitted bone follows its own smooth seeded noise (three sines, 0.25-1.2 Hz), eased in over half a
  second, by role (degrees about local X across the body, Y the twist, Z), each inside 0.9 of the bone's declared
  range; knees and elbows fold their own way only, 0-40 degrees; the whole body turns a little and its lowest skin
  stays on the floor.
- gait: an in-place walk (left hind, left fore, right hind, right fore, a quarter cycle apart): legs swing, knees and
  elbows fold in the swing, paws flex, spine, head and tail sway; lowest skin on the floor.
- action: an authored action of the .blend, eased in from the start pose, looped, lifted by one constant so that no
  frame's skin goes under the start pose's floor.
Every motion starts at the start pose. A motion that turns a bone past its declared range on any of its three channels,
or a knee or elbow past video2rig's own hinge limits, is refused (exam v1: the truth stays inside the reader's ranges).
"""
import json
import math
import os
import re
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Quaternion, Vector

sys.path.append(os.environ.get("SLOPFORGE_PACKAGE_ROOT", str(Path(__file__).resolve().parents[1])))
from slopforge.creature_views import range_violations  # noqa: E402

FPS = 24
# degrees about X (across the body), Y (twist) and Z, by the role of B1's generic names
AMPLITUDES = (("Tail", (25, 6, 25)), ("Spine|Chest|Hips", (8, 5, 6)), ("Neck|Head", (18, 8, 18)),
              ("Thigh|UpperArm|Scapula", (25, 5, 8)), ("", (25, 5, 5)))
HIND, FRONT = re.compile(r"^(Thigh|Shin|HindPaw|HindToes)"), re.compile(r"^(Scapula|UpperArm|Forearm|FrontPaw|FrontToes)")


def lowest(meshes):
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    z = math.inf
    for obj in meshes:
        evaluated = obj.evaluated_get(deps)
        mesh = evaluated.to_mesh()
        co = np.empty(len(mesh.vertices) * 3)
        mesh.vertices.foreach_get("co", co)
        world = np.array(evaluated.matrix_world)
        z = min(z, float((co.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3])[:, 2].min()))
        evaluated.to_mesh_clear()
    return z


def ease(frames):
    t = np.clip(np.arange(frames) / (FPS * 0.5), 0, 1)
    return t * t * (3 - 2 * t)


def noise(rng, frames):
    t = np.arange(frames) / FPS
    x = sum(rng.uniform(0.4, 1) * np.sin(2 * np.pi * rng.uniform(0.25, 1.2) * t + rng.uniform(0, 2 * np.pi))
            for _ in range(3))
    x = x - x[0]                                   # start at the start pose
    return x / max(np.abs(x).max(), 1e-9)


def make(request):
    config = request["creature"]
    scene = bpy.context.scene
    rig = next(obj for obj in scene.objects if obj.type == "ARMATURE")
    meshes = [obj for obj in scene.objects if obj.type == "MESH" and obj.visible_get()]
    if rig.animation_data:
        rig.animation_data.action = None
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion, bone.location, bone.scale = (1, 0, 0, 0), (0, 0, 0), (1, 1, 1)
    names = [bone.name for bone in rig.data.bones]
    root_name, hinges = config["root_bone"], config["hinges"]
    moved = [name for name in names if name in set(config["fit_bones"])]
    ranges = {name: math.degrees(item["range"]) for name, item in config["joints"].items()}
    world = rig.matrix_world
    forward = (world.to_3x3().inverted() @ Vector({"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0),
                                                    "-Y": (0, -1, 0)}[config["facing"]])).normalized()

    def fold_sign(name, way):
        """+1 or -1: the turn about the bone's local X that moves its tail back (a knee) or forward (an elbow)."""
        bone = rig.pose.bones[name]
        bpy.context.view_layer.update()
        before = bone.tail.copy()
        bone.rotation_quaternion = Quaternion((1, 0, 0), 0.3)
        bpy.context.view_layer.update()
        moved_by = (bone.tail - before).dot(forward)
        bone.rotation_quaternion = (1, 0, 0, 0)
        bpy.context.view_layer.update()
        return (1.0 if moved_by < 0 else -1.0) if way == "back" else (1.0 if moved_by > 0 else -1.0)

    folds = {name: fold_sign(name, way) for name, way in hinges.items()}
    # one bone swings a leg and the paw and toes flex, never a scapula above it or an end bone below: a B1 front leg has
    # a scapula and B1 fits the end bones, and swinging or curling those too kicked a leg level (B3's exam, 2026-10-30)
    swings = {name: fold_sign(name, "front") for name in moved if re.match(r"(Thigh|UpperArm)\.[LR]$", name)}
    flexes = {name: fold_sign(name, "back") for name in moved
              if re.match(r"(FrontPaw|HindPaw|FrontToes|HindToes)\.[LR]$", name)}

    def amplitude(name):
        role = next(degrees for pattern, degrees in AMPLITUDES if re.match(pattern, name))
        cap = 0.9 * ranges.get(name, math.inf)       # inside the declared range, with room for the three channels
        return tuple(min(value, cap) for value in role)

    root = rig.pose.bones[root_name]
    root_frame = (world @ root.bone.matrix_local).to_3x3()
    floor = lowest(meshes)
    frames = request.get("frames", 96)
    rng = np.random.default_rng(request.get("seed", 0))
    kind = request["kind"]
    quats = np.tile(np.array([1, 0, 0, 0], np.float32), (frames, len(names), 1))
    locs = np.zeros((frames, 3), np.float32)
    sink = 0.0

    def settle(frame):
        root.location = (0, 0, 0)
        lift = floor - lowest(meshes)
        root.location = root_frame.inverted() @ Vector((0, 0, lift))
        locs[frame] = tuple(root.location)

    if kind == "random":
        e = ease(frames)
        curves = {}
        for name in moved:
            degrees = (10, 6, 4) if name == root_name else amplitude(name)
            curves[name] = [np.radians(d) * noise(rng, frames) * e for d in degrees]
            if name in hinges:                     # one way only: 0 .. 40 degrees folded
                curves[name][0] = folds[name] * np.radians(40) * (noise(rng, frames) + 1) / 2 * e
                curves[name][1] = curves[name][2] = np.zeros(frames)
        for f in range(frames):
            for name in moved:
                x, y, z = (curve[f] for curve in curves[name])
                q = Quaternion((1, 0, 0), x) @ Quaternion((0, 1, 0), y) @ Quaternion((0, 0, 1), z)
                rig.pose.bones[name].rotation_quaternion = q
                quats[f, names.index(name)] = tuple(q)
            settle(f)
    elif kind == "gait":
        t, e = np.arange(frames) / FPS, ease(frames)
        phase = {("hind", "L"): 0.0, ("front", "L"): 0.25, ("hind", "R"): 0.5, ("front", "R"): 0.75}
        for f in range(frames):
            for name in moved:
                if name == root_name:
                    continue
                side = name[-1] if name[-2:] in (".L", ".R") else None
                end = "hind" if HIND.match(name) else "front" if FRONT.match(name) else None
                x = z = 0.0
                if side and end:
                    s = 2 * np.pi * (t[f] + phase[(end, side)])          # one stride a second
                    swing, lift = math.sin(s), max(0.0, math.sin(s + np.pi / 2))
                    if name in hinges:
                        x = folds[name] * np.radians(35) * lift
                    elif name in swings:
                        x = np.radians(min(20, 0.9 * ranges.get(name, 20))) * swing * swings[name]
                    elif name in flexes:
                        x = np.radians(min(20, 0.9 * ranges.get(name, 20))) * lift * flexes[name]
                elif name.startswith("Tail"):
                    z = np.radians(12) * math.sin(2 * np.pi * t[f])
                elif name.startswith("Neck") or name == "Head":
                    x = np.radians(6) * math.sin(4 * np.pi * t[f])
                elif name.startswith(("Spine", "Chest")):
                    z = np.radians(3) * math.sin(2 * np.pi * t[f])
                q = Quaternion((1, 0, 0), x * e[f]) @ Quaternion((0, 0, 1), z * e[f])
                rig.pose.bones[name].rotation_quaternion = q
                quats[f, names.index(name)] = tuple(q)
            settle(f)
    elif kind == "action":
        action = bpy.data.actions[request["action"]]
        cycle = list(range(int(action.frame_range[0]), int(action.frame_range[1])))   # the last key repeats the first
        lead_in = FPS // 2
        frames = lead_in + request.get("loops", 4) * len(cycle)
        quats = np.tile(np.array([1, 0, 0, 0], np.float32), (frames, len(names), 1))
        locs = np.zeros((frames, 3), np.float32)
        rig.animation_data_create()
        sampled = []
        for key in cycle:
            rig.animation_data.action = action
            scene.frame_set(key)
            bpy.context.view_layer.update()
            pose = {name: rig.pose.bones[name].rotation_quaternion.copy() for name in moved}
            basis = root.bone.matrix_local.inverted() @ root.matrix
            pose[root_name] = basis.to_quaternion()
            sampled.append((pose, basis.to_translation()))
        rig.animation_data.action = None
        e = ease(lead_in)
        for f in range(frames):
            if f < lead_in:
                pose, loc = sampled[0]
                pose, loc = {name: Quaternion().slerp(pose[name], float(e[f])) for name in moved}, loc * float(e[f])
            else:
                pose, loc = sampled[(f - lead_in) % len(cycle)]
            for name in moved:
                quats[f, names.index(name)] = tuple(pose[name])
            locs[f] = tuple(loc)
        for f in range(frames):   # lift the whole action by one constant so no frame goes under the start floor
            for name in moved:
                rig.pose.bones[name].rotation_quaternion = Quaternion(quats[f, names.index(name)])
            root.location = Vector(locs[f])
            sink = max(sink, floor - lowest(meshes))
        locs += np.array(tuple(root_frame.inverted() @ Vector((0, 0, sink))), np.float32)
    else:
        raise ValueError(f"unknown motion kind {kind!r}")

    # each bone's turns about its X, Y and Z as video2rig bounds them: intrinsic XYZ (scipy as_euler('XYZ')), which is
    # Blender's Euler order ZYX; every motion here is composed X @ Y @ Z, so these are its own channel angles
    channels = {name: np.degrees([tuple(Quaternion(q).to_euler("ZYX")) for q in quats[:, names.index(name)]])
                for name in moved if name != root_name}
    violations = range_violations(channels, config["joints"], hinges)
    if violations:
        raise ValueError(f"the {kind} motion turns bones past their declared ranges: {json.dumps(violations)}")
    np.savez_compressed(request["out"], bones=np.array(names), root=root_name, quats=quats, root_location=locs)
    truth = {"kind": kind, "seed": request.get("seed", 0), "frames": int(frames), "fps": FPS,
             "action": request.get("action"), "root": root_name, "moved_bones": moved, "hinges": hinges,
             "fold_signs": folds, "facing": config["facing"], "lift_world_units": float(sink),
             "max_turn_degrees": {name: [round(float(value), 3) for value in np.abs(series).max(0)]
                                  for name, series in channels.items()}}
    Path(request["truth"]).write_text(json.dumps(truth, indent=2, sort_keys=True) + "\n")
    return {"status": "complete", "frames": int(frames), "moved_bones": len(moved)}


def main():
    request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
    try:
        result = make(request)
    except Exception as exc:
        traceback.print_exc()
        result = {"status": "error", "errors": [f"{type(exc).__name__}: {exc}"]}
    Path(request["report"]).write_text(json.dumps(result, indent=2) + "\n")
    if result["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
