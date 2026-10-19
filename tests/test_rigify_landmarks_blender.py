import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"

FIXTURE = """import bpy, math, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
def cyl(r, depth, loc, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc, rotation=rot, vertices=24)
# A-pose humanoid, 1.8 m tall, facing -Y; separate overlapping parts like generated characters.
cyl(0.16, 0.62, (0, 0, 1.18))                      # torso
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, location=(0, 0, 1.64))  # head
cyl(0.05, 0.12, (0, 0, 1.51))                      # neck
for side in (1, -1):
    cyl(0.07, 0.86, (side * 0.09, 0, 0.45))         # leg
    bpy.ops.mesh.primitive_cube_add(size=1, location=(side * 0.09, -0.06, 0.03)); bpy.context.object.scale = (0.09, 0.24, 0.06)
    angle = math.radians(35)
    length = 0.62
    cx = side * (0.17 + math.sin(angle) * length / 2)
    cz = 1.43 - math.cos(angle) * length / 2
    cyl(0.045, length, (cx, 0, cz), (0, -side * angle, 0))  # arm hanging 35 degrees out
bpy.ops.object.select_all(action="SELECT")
bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
bpy.ops.object.join()
remesh = bpy.context.object.modifiers.new("dense", "REMESH")  # dense surface like a generated character
remesh.mode, remesh.voxel_size = "VOXEL", 0.012
bpy.ops.object.modifier_apply(modifier=remesh.name)
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format="GLB")
"""

PROBE = """import bpy, json, sys
rig = next(o for o in bpy.data.objects if o.type == "ARMATURE" and o.data.bones.get("DEF-forearm.L"))
mesh = next(o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers))
bone = rig.data.bones["DEF-forearm.L"]
mid = rig.matrix_world @ ((bone.head_local + bone.tail_local) / 2)
json.dump({"forearm_mid": list(mid), "unweighted": sum(not v.groups for v in mesh.data.vertices)}, open(sys.argv[-1], "w"))
"""


BVH = """HIERARCHY
ROOT Hips
{
  OFFSET 0 0 0
  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
  JOINT LeftUpLeg
  {
    OFFSET 9 0 0
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT LeftLeg
    {
      OFFSET 0 -45 0
      CHANNELS 3 Zrotation Xrotation Yrotation
      End Site
      {
        OFFSET 0 -45 0
      }
    }
  }
  JOINT RightUpLeg
  {
    OFFSET -9 0 0
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT RightLeg
    {
      OFFSET 0 -45 0
      CHANNELS 3 Zrotation Xrotation Yrotation
      End Site
      {
        OFFSET 0 -45 0
      }
    }
  }
}
MOTION
Frames: 2
Frame Time: 0.0333333
0 90 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
0 90 0 0 0 0 0 -40 0 0 0 0 0 0 0 0 0 0
"""

BVH_ZERO_LINK = BVH.replace("OFFSET 9 0 0", "OFFSET 9 -5 0").replace("OFFSET -9 0 0", "OFFSET -9 -5 0").replace(
    """  JOINT RightUpLeg""", """  JOINT LowerBack
  {
    OFFSET 0 0 0
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT Spine
    {
      OFFSET 0 30 30
      CHANNELS 3 Zrotation Xrotation Yrotation
      End Site
      {
        OFFSET 0 30 0
      }
    }
  }
  JOINT RightUpLeg""").split("MOTION")[0] + """MOTION
Frames: 2
Frame Time: 0.0333333
""" + " ".join(["0", "90"] + ["0"] * 22) + "\n" + " ".join(["0", "90", "0", "0", "0", "0", "0", "-40"] + ["0"] * 16) + "\n"
# Channel order: Hips(6) LeftUpLeg(3) LeftLeg(3) LowerBack(3) Spine(3) RightUpLeg(3) RightLeg(3) = 24.


# 61 frames of a left hip swinging +-30 degrees (period 20): the knee dips twice per swing period.
BVH_WALK = BVH.split("MOTION")[0] + "MOTION\nFrames: 61\nFrame Time: 0.0333333\n" + "".join(
    " ".join(["0", "90", "0", "0", "0", "0", "0", f"{30 * __import__('math').sin(2 * __import__('math').pi * f / 20):.3f}"]
             + ["0"] * 10) + "\n" for f in range(61))


# A walking clip (swinging left hip) whose actor holds a constant 20 degree forward lean in the lower
# back; channel order as BVH_ZERO_LINK (LeftUpLeg X at 7, LowerBack X at 13).
BVH_LEAN = BVH_ZERO_LINK.split("MOTION")[0] + "MOTION\nFrames: 61\nFrame Time: 0.0333333\n" + "".join(
    " ".join(["0", "90", "0", "0", "0", "0", "0", f"{30 * __import__('math').sin(2 * __import__('math').pi * f / 20):.3f}",
              "0", "0", "0", "0", "0", "20"] + ["0"] * 10) + "\n" for f in range(61))

# An actor whose rest pose faces +Z but who walks along +X (hips yawed 90 degrees), legs swinging in
# their own sagittal plane. Channel order as BVH: Hips(6) LeftUpLeg(3) LeftLeg(3) RightUpLeg(3) RightLeg(3).
BVH_HEADING = BVH.split("MOTION")[0] + "MOTION\nFrames: 61\nFrame Time: 0.0333333\n" + "".join(
    " ".join([f"{2 * f}", "90", "0", "0", "0", "90", "0", f"{30 * __import__('math').sin(2 * __import__('math').pi * f / 20):.3f}",
              "0", "0", "0", "0", "0", f"{-30 * __import__('math').sin(2 * __import__('math').pi * f / 20):.3f}", "0",
              "0", "0", "0"]) + "\n" for f in range(61))

# A walking clip with feet whose toe joint sits low and forward of the ankle (pitched about 45 degrees
# down, unlike the rig's foot). Channels: Hips(6) then Z X Y per joint: LeftUpLeg LeftLeg LeftFoot
# LeftToeBase RightUpLeg RightLeg RightFoot RightToeBase.
def _leg(side, x):
    return f"""  JOINT {side}UpLeg
  {{
    OFFSET {x} 0 0
    CHANNELS 3 Zrotation Xrotation Yrotation
    JOINT {side}Leg
    {{
      OFFSET 0 -42 0
      CHANNELS 3 Zrotation Xrotation Yrotation
      JOINT {side}Foot
      {{
        OFFSET 0 -42 0
        CHANNELS 3 Zrotation Xrotation Yrotation
        JOINT {side}ToeBase
        {{
          OFFSET 0 -6 6
          CHANNELS 3 Zrotation Xrotation Yrotation
          End Site
          {{
            OFFSET 0 0 4
          }}
        }}
      }}
    }}
  }}
"""
BVH_FEET = ("HIERARCHY\nROOT Hips\n{\n  OFFSET 0 0 0\n  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation\n"
            + _leg("Left", 9) + _leg("Right", -9) + "}\nMOTION\nFrames: 61\nFrame Time: 0.0333333\n" + "".join(
    " ".join(["0", "90", "0", "0", "0", "0"]
             + ["0", f"{30 * __import__('math').sin(2 * __import__('math').pi * f / 20):.3f}", "0"] + ["0"] * 9
             + ["0", f"{-30 * __import__('math').sin(2 * __import__('math').pi * f / 20):.3f}", "0"] + ["0"] * 9) + "\n"
    for f in range(61)))

FOOT_PROBE = """import bpy, json, sys, math
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
W = arm.matrix_world
rest = arm.data.bones["DEF-foot.L"]
rest_direction = (W.to_3x3() @ (rest.tail_local - rest.head_local)).normalized()
best = None
for frame in range(1, 61):
    bpy.context.scene.frame_set(frame)
    thigh = arm.pose.bones["DEF-thigh.L"]
    lean = abs((W @ thigh.tail - W @ thigh.head).normalized().y)
    if best is None or lean < best[0]:
        foot = arm.pose.bones["DEF-foot.L"]
        best = (lean, math.degrees(rest_direction.angle((W @ foot.tail - W @ foot.head).normalized())))
json.dump({"stance_foot_degrees": best[1]}, open(sys.argv[-1], "w"))
"""


HEADING_PROBE = """import bpy, json, sys
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
W = arm.matrix_world
side = (W @ arm.data.bones["DEF-thigh.L"].head_local - W @ arm.data.bones["DEF-thigh.R"].head_local).normalized()
worst, residue = 0.0, 0.0
for frame in range(1, 61):
    bpy.context.scene.frame_set(frame)
    bone = arm.pose.bones["DEF-thigh.L"]
    swing = (W @ bone.tail - W @ bone.head).normalized()
    worst = max(worst, abs(swing.dot(side)))
    residue = max([residue] + [b.location.length for b in arm.pose.bones if b.name != "DEF-spine"])
json.dump({"sideways": worst, "location_residue": residue}, open(sys.argv[-1], "w"))
"""


SPINE_PROBE = """import bpy, json, sys
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
rest = arm.data.bones["DEF-spine.001"]
rest_direction = (arm.matrix_world.to_3x3() @ (rest.tail_local - rest.head_local)).normalized()
bpy.context.scene.frame_set(30)
bone = arm.pose.bones["DEF-spine.001"]
direction = (arm.matrix_world @ bone.tail - arm.matrix_world @ bone.head).normalized()
json.dump({"lean_degrees": __import__("math").degrees(rest_direction.angle(direction))}, open(sys.argv[-1], "w"))
"""


HIPS_PROBE = """import bpy, json, sys
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
bpy.context.scene.frame_set(1)
hips, spine = arm.pose.bones["DEF-spine"], arm.pose.bones["DEF-spine.001"]
up = (arm.matrix_world @ spine.head - arm.matrix_world @ hips.head).normalized()
json.dump({"hips_up_z": up.z}, open(sys.argv[-1], "w"))
"""

RETARGET_PROBE = """import bpy, json, math, sys
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
def direction(name):
    b = arm.pose.bones[name]
    return (arm.matrix_world @ b.tail - arm.matrix_world @ b.head).normalized()
result = {}
for frame in (1, 2):
    bpy.context.scene.frame_set(frame)
    result[frame] = {"left": list(direction("DEF-thigh.L")), "right": list(direction("DEF-thigh.R"))}
json.dump(result, open(sys.argv[-1], "w"))
"""


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class RigifyLandmarkTests(unittest.TestCase):
    def test_a_pose_character_gets_landmark_joints_and_full_proxy_weights(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb = root / "humanoid.glb"
            (root / "fixture.py").write_text(FIXTURE)
            subprocess.run([BLENDER, "--background", "--python", str(root / "fixture.py"), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            poses = ["t_pose", "raised_arms", "crouch", "leg_lift", "elbow_bend", "shoulder_rotation"]
            request = {"source": str(glb), "rigged_model": str(root / "rig.fbx"), "rigged_blend": str(root / "rig.blend"),
                       "report": str(root / "report.json"), "topology_policy": "allow_for_review",
                       "evidence": {pose: str(root / f"{pose}.png") for pose in poses}}
            (root / "request.json").write_text(json.dumps(request))
            run = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                  str(ROOT / "blender/rigify_character.py"), "--", str(root / "request.json")],
                                 capture_output=True, text=True)
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["status"], "complete", run.stdout[-2000:])
            self.assertEqual(report["arm_depth_fit"]["strategy"], "mesh cross-section landmarks")
            # The evidence labelled t_pose is a real T-pose: upper arms level, not the rest A-pose.
            elevations = report["deformation_evidence"]["t_pose"]["upper_arm_elevation_degrees"]
            self.assertEqual(len(elevations), 2)
            self.assertTrue(all(abs(value) < 5 for value in elevations), elevations)
            binding = report["skin_binding"]["meshes"][0]
            self.assertEqual(binding["weighted_vertices"], binding["vertices"])
            (root / "probe.py").write_text(PROBE)
            subprocess.run([BLENDER, "--background", str(root / "rig.blend"), "--python", str(root / "probe.py"),
                            "--", str(root / "probe.json")], check=True, capture_output=True, text=True)
            probe = json.loads((root / "probe.json").read_text())
            x, y, z = probe["forearm_mid"]
            # The forearm sits on the hanging arm (out to the side, below the shoulder), not in T-pose air.
            self.assertGreater(x, 0.3)
            self.assertLess(z, 1.3)
            self.assertEqual(probe["unweighted"], 0)
            metrics_path = root / "metrics.json"
            subprocess.run([BLENDER, "--background", str(root / "rig.blend"), "--python",
                            str(ROOT / "blender/rig_stretch_metrics.py"), "--", str(metrics_path)],
                           check=True, capture_output=True, text=True)
            metrics = json.loads(metrics_path.read_text())
            self.assertEqual(set(metrics), {"raised_arms", "crouch", "leg_lift", "elbow_bend", "walk_stride"})
            self.assertTrue(all(0 <= item["edges_over_1_5x_pct"] <= 100 for item in metrics.values()))

            # Rest-relative retarget: a 40 degree hip swing in the clip swings the rig's thigh 40 degrees.
            (root / "clip.bvh").write_text(BVH)
            retarget = {"rig": str(root / "rig.fbx"), "motion": str(root / "clip.bvh"),
                        "output_blend": str(root / "walk.blend"), "report": str(root / "retarget.json"),
                        "bone_mapping": {"Hips": "DEF-spine", "LeftUpLeg": "DEF-thigh.L", "LeftLeg": "DEF-shin.L",
                                         "RightUpLeg": "DEF-thigh.R", "RightLeg": "DEF-shin.R"}}
            (root / "retarget_request.json").write_text(json.dumps(retarget))
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/retarget_mocap.py"), "--", str(root / "retarget_request.json")],
                           check=True, capture_output=True, text=True)
            self.assertEqual(json.loads((root / "retarget.json").read_text())["status"], "complete")
            (root / "retarget_probe.py").write_text(RETARGET_PROBE)
            subprocess.run([BLENDER, "--background", str(root / "walk.blend"), "--python", str(root / "retarget_probe.py"),
                            "--", str(root / "directions.json")], check=True, capture_output=True, text=True)
            directions = json.loads((root / "directions.json").read_text())
            import math
            def angle(a, b):
                return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))))
            self.assertAlmostEqual(angle(directions["1"]["left"], directions["2"]["left"]), 40, delta=3)
            self.assertLess(angle(directions["1"]["right"], directions["2"]["right"]), 1)

            # The clip's torso joints are placed differently (a zero-length LowerBack on Hips, then a joint
            # 45 degrees off vertical, like CMU's clavicles); at zero rotation the rig's hips stay upright.
            (root / "zero.bvh").write_text(BVH_ZERO_LINK)
            zero = {**retarget, "motion": str(root / "zero.bvh"), "output_blend": str(root / "zero.blend"),
                    "report": str(root / "zero.json"),
                    "bone_mapping": {**retarget["bone_mapping"], "LowerBack": "DEF-spine.001", "Spine": "DEF-spine.002"}}
            (root / "zero_request.json").write_text(json.dumps(zero))
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/retarget_mocap.py"), "--", str(root / "zero_request.json")],
                           check=True, capture_output=True, text=True)
            (root / "hips_probe.py").write_text(HIPS_PROBE)
            subprocess.run([BLENDER, "--background", str(root / "zero.blend"), "--python", str(root / "hips_probe.py"),
                            "--", str(root / "hips.json")], check=True, capture_output=True, text=True)
            self.assertGreater(json.loads((root / "hips.json").read_text())["hips_up_z"], 0.9)

            # Stride timing comes from the clip's own foot, so a looping cycle is found for any rig.
            (root / "walk.bvh").write_text(BVH_WALK)
            walk = {**retarget, "motion": str(root / "walk.bvh"), "output_blend": str(root / "walk2.blend"),
                    "report": str(root / "walk2.json")}
            (root / "walk_request.json").write_text(json.dumps(walk))
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/retarget_mocap.py"), "--", str(root / "walk_request.json")],
                           check=True, capture_output=True, text=True)
            cycle = json.loads((root / "walk2.json").read_text())["gait_cycle"]
            self.assertIsNotNone(cycle)
            self.assertIn(cycle[1] - cycle[0], (10, 20))

            # The actor's habitual posture (a constant lean) is not stamped onto the character's spine.
            (root / "lean.bvh").write_text(BVH_LEAN)
            lean = {**zero, "motion": str(root / "lean.bvh"), "output_blend": str(root / "lean.blend"),
                    "report": str(root / "lean.json")}
            (root / "lean_request.json").write_text(json.dumps(lean))
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/retarget_mocap.py"), "--", str(root / "lean_request.json")],
                           check=True, capture_output=True, text=True)
            self.assertIsNotNone(json.loads((root / "lean.json").read_text())["gait_cycle"])
            (root / "spine_probe.py").write_text(SPINE_PROBE)
            subprocess.run([BLENDER, "--background", str(root / "lean.blend"), "--python", str(root / "spine_probe.py"),
                            "--", str(root / "spine.json")], check=True, capture_output=True, text=True)
            self.assertLess(json.loads((root / "spine.json").read_text())["lean_degrees"], 3)

            # Legs swing along the character's forward axis even when the actor walks off its rest facing,
            # and no retargeted bone but the hips is left with a location offset.
            (root / "heading.bvh").write_text(BVH_HEADING)
            heading = {**retarget, "motion": str(root / "heading.bvh"), "output_blend": str(root / "heading.blend"),
                       "report": str(root / "heading.json")}
            (root / "heading_request.json").write_text(json.dumps(heading))
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/retarget_mocap.py"), "--", str(root / "heading_request.json")],
                           check=True, capture_output=True, text=True)
            (root / "heading_probe.py").write_text(HEADING_PROBE)
            subprocess.run([BLENDER, "--background", str(root / "heading.blend"), "--python",
                            str(root / "heading_probe.py"), "--", str(root / "heading_probe.json")],
                           check=True, capture_output=True, text=True)
            probe = json.loads((root / "heading_probe.json").read_text())
            self.assertLess(probe["sideways"], 0.2, probe)
            self.assertLess(probe["location_residue"], 1e-3, probe)

            # A flat-footed actor leaves the rig's foot at its own rest angle in stance, even though the two
            # skeletons place the toe joint differently.
            (root / "feet.bvh").write_text(BVH_FEET)
            feet = {**retarget, "motion": str(root / "feet.bvh"), "output_blend": str(root / "feet.blend"),
                    "report": str(root / "feet.json"),
                    "bone_mapping": {**retarget["bone_mapping"], "LeftFoot": "DEF-foot.L", "RightFoot": "DEF-foot.R",
                                     "LeftToeBase": "DEF-toe.L", "RightToeBase": "DEF-toe.R"}}
            (root / "feet_request.json").write_text(json.dumps(feet))
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/retarget_mocap.py"), "--", str(root / "feet_request.json")],
                           check=True, capture_output=True, text=True)
            (root / "foot_probe.py").write_text(FOOT_PROBE)
            subprocess.run([BLENDER, "--background", str(root / "feet.blend"), "--python", str(root / "foot_probe.py"),
                            "--", str(root / "foot_probe.json")], check=True, capture_output=True, text=True)
            self.assertLess(json.loads((root / "foot_probe.json").read_text())["stance_foot_degrees"], 6)
