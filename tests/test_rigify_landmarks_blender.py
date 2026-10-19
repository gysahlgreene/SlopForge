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
