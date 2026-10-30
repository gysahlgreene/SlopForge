"""B3's motion exam (docs/CREATURES.md): a known motion's truth and video2rig's fit of it posed on the creature's
armature and read back per frame as armature-space heads and tails, with what slopforge/creature_exam.py needs to
measure them (spike #129's exam_compare.py, its posing only).

    blender creature.blend --background --python exam_pose.py -- request.json

request: {"truth": the exam folder (poses.npz, truth.json, labels.npz), "fit": video2rig's out/<clip>.npz,
          "facing": the rig's facing (-Y), "out": the .npz to write, "report": the .json to write}
"""
import json
import sys
import traceback

import bpy
import numpy as np
from mathutils import Quaternion, Vector

AXES = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0)}


def posed(rig, bones, rotations, root, location):
    """Every bone's head and tail (armature space) for one frame's basis rotations and root location."""
    for bone in rig.pose.bones:
        bone.rotation_quaternion = (1, 0, 0, 0)
        bone.location = (0, 0, 0)
    for name, rotation in zip(bones, rotations):
        if name in rig.pose.bones:
            rig.pose.bones[name].rotation_quaternion = Quaternion(rotation)
    rig.pose.bones[root].location = Vector(location)
    bpy.context.view_layer.update()
    return ([tuple(bone.head) for bone in rig.pose.bones], [tuple(bone.tail) for bone in rig.pose.bones])


def run(request):
    scene = bpy.context.scene
    rig = next(obj for obj in scene.objects if obj.type == "ARMATURE")
    if rig.animation_data:
        rig.animation_data.action = None
    for bone in rig.pose.bones:
        bone.rotation_mode = "QUATERNION"
    names = [bone.name for bone in rig.pose.bones]
    truth = json.loads(open(f"{request['truth']}/truth.json").read())
    known = np.load(f"{request['truth']}/poses.npz")
    true = [posed(rig, [str(name) for name in known["bones"]], known["quats"][i], str(known["root"]),
                  known["root_location"][i]) for i in range(len(known["quats"]))]
    # the truth must be what render_poses drew: its own labels, posed the same way
    labels = np.load(f"{request['truth']}/labels.npz")
    order = [list(map(str, labels["names"])).index(name) for name in names]
    label_gap = max(float(np.abs(labels["heads"][i][order] - np.array(true[i][0])).max()) for i in range(len(true)))
    fitted = np.load(request["fit"])
    fit = [posed(rig, [str(name) for name in fitted["bones"]], fitted["quaternions"][k], str(fitted["root"]),
                 fitted["root_location"][k]) for k in range(len(fitted["times"]))]
    # the creature's height: its rest skin along up, in armature space, as video2rig measures it
    for bone in rig.pose.bones:
        bone.rotation_quaternion = (1, 0, 0, 0)
        bone.location = (0, 0, 0)
    bpy.context.view_layer.update()
    to_armature = rig.matrix_world.to_3x3().inverted()
    up = (to_armature @ Vector((0, 0, 1))).normalized()
    forward = (to_armature @ Vector(AXES[request["facing"]])).normalized()
    inverse, graph, heights = rig.matrix_world.inverted(), bpy.context.evaluated_depsgraph_get(), []
    for obj in scene.objects:
        if obj.type == "MESH" and obj.visible_get():
            mesh = obj.evaluated_get(graph).to_mesh()
            heights += [(inverse @ (obj.matrix_world @ vertex.co)).dot(up) for vertex in mesh.vertices]
            obj.evaluated_get(graph).to_mesh_clear()
    np.savez(request["out"], names=np.array(names),
             parents=np.array([bone.parent.name if bone.parent else "" for bone in rig.data.bones]),
             root=str(truth["root"]), fps=float(truth["fps"]), height=max(heights) - min(heights), up=np.array(up),
             forward=np.array(forward), true_heads=np.array([frame[0] for frame in true]),
             true_tails=np.array([frame[1] for frame in true]), fit_heads=np.array([frame[0] for frame in fit]),
             fit_tails=np.array([frame[1] for frame in fit]), times=np.asarray(fitted["times"], float),
             moved=np.array(truth["moved_bones"]))
    return {"status": "complete", "label_gap": label_gap, "frames_true": len(true), "frames_fitted": len(fit)}


if __name__ == "__main__":
    request = json.loads(open(sys.argv[sys.argv.index("--") + 1]).read())
    try:
        report = run(request)
    except Exception as exc:
        report = {"status": "error", "errors": [f"{type(exc).__name__}: {exc}"], "trace": traceback.format_exc()}
    open(request["report"], "w").write(json.dumps(report))
