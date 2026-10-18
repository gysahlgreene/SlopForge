"""Edge-stretch deformation metric for a rigged Rigify character under a fixed FK pose set.

Usage: blender --background <rig.blend> --python rig_stretch_metrics.py -- <out.json>

For each pose it reports the share of mesh edges stretched past 1.5x and 2x their rest length and
the largest ratio. Lower is better; the fixed poses make rig versions comparable. It measures
stretching only, not how a pose looks, so review the renders as well.
"""
import json
import sys

import bpy
POSES = {"raised_arms": {"upper_arm_fk.L": (1.3, 0, 0), "upper_arm_fk.R": (1.3, 0, 0)},
         "crouch": {"thigh_fk.L": (0.8, 0, 0), "thigh_fk.R": (0.8, 0, 0), "shin_fk.L": (-1.0, 0, 0), "shin_fk.R": (-1.0, 0, 0)},
         "leg_lift": {"thigh_fk.L": (0.9, 0, 0), "shin_fk.L": (-0.8, 0, 0)},
         "elbow_bend": {"forearm_fk.L": (1.2, 0, 0), "forearm_fk.R": (1.2, 0, 0)},
         "walk_stride": {"thigh_fk.L": (0.42, 0, 0), "thigh_fk.R": (-0.42, 0, 0), "shin_fk.R": (-0.85, 0, 0),
                         "upper_arm_fk.L": (0, 0, 0.35), "upper_arm_fk.R": (0, 0, 0.35)}}
rig = next(o for o in bpy.data.objects if o.type == "ARMATURE" and o.pose.bones.get("thigh_fk.L"))
meshes = [o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
for sw in ("upper_arm_parent.L", "upper_arm_parent.R", "thigh_parent.L", "thigh_parent.R"):
    b = rig.pose.bones.get(sw)
    if b is not None and "IK_FK" in b: b["IK_FK"] = 1.0
def lengths():
    dg = bpy.context.evaluated_depsgraph_get(); out = []
    for m in meshes:
        ev = m.evaluated_get(dg); me = ev.to_mesh()
        co = [m.matrix_world @ v.co for v in me.vertices]
        out.extend((co[e.vertices[0]] - co[e.vertices[1]]).length for e in me.edges)
        ev.to_mesh_clear()
    return out
def reset():
    for b in rig.pose.bones: b.rotation_mode = "XYZ"; b.rotation_euler = (0, 0, 0)
reset(); bpy.context.view_layer.update(); rest = lengths()
result = {}
for name, controls in POSES.items():
    reset()
    for bone, rot in controls.items(): rig.pose.bones[bone].rotation_euler = rot
    bpy.context.view_layer.update(); posed = lengths()
    ratios = [p / r for p, r in zip(posed, rest) if r > 1e-6]
    result[name] = {"edges_over_1_5x_pct": round(100 * sum(x > 1.5 for x in ratios) / len(ratios), 3),
                    "edges_over_2x_pct": round(100 * sum(x > 2 for x in ratios) / len(ratios), 3),
                    "max_ratio": round(max(ratios), 2)}
out = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else None
if out:
    with open(out, "w") as handle:
        json.dump(result, handle, indent=2)
print("METRICS", json.dumps(result))
