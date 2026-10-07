"""Real Blender fixture for the SkinTokens postprocess boundary."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLENDER = (os.environ.get("BLENDER_BIN") or shutil.which("blender")
           or "/Applications/Blender.app/Contents/MacOS/Blender")


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class SkinTokensBlenderTests(unittest.TestCase):
    def test_fixture_cleanup_bake_structure_and_fixed_poses(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = {"fixture": True, "source": str(root / "source.glb"),
                       "raw": str(root / "raw.glb"), "rigged_model": str(root / "rig.fbx"),
                       "report": str(root / "report.json"),
                       "contact_sheet": str(root / "contact.png"),
                       "evidence": {pose: str(root / f"{pose}.png") for pose in
                                    ("neutral", "t_pose", "raised_arms", "shoulder_rotation",
                                     "elbow_bend", "crouch", "leg_lift")}}
            path = root / "request.json"
            path.write_text(json.dumps(request))
            process = subprocess.run([BLENDER, "--background", "--factory-startup", "--python",
                            str(ROOT / "blender/skintokens_character.py"), "--", str(path)],
                           capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertTrue(Path(request["report"]).is_file(), process.stdout + process.stderr)
            report = json.loads(Path(request["report"]).read_text())
            self.assertEqual(report["status"], "complete")
            self.assertTrue(report["helper_objects"])
            self.assertTrue(all(name.startswith("Icosphere") for name in report["helper_objects"]))
            self.assertGreaterEqual(report["skinned_component_count"], 2)
            self.assertGreater(report["material_coverage"]["base_color"], 0)
            self.assertEqual(report["unweighted_vertices"], 0)
            mapping = report["semantic_mapping"]
            self.assertEqual(mapping["left_upper_arm"], "LeftUpperArm")
            self.assertEqual(mapping["left_forearm"], "LeftLowerArm")
            self.assertEqual(mapping["right_upper_arm"], "RightUpperArm")
            self.assertEqual(mapping["right_forearm"], "RightLowerArm")
            bone_names = set(report["bone_names"])
            self.assertTrue({"Hips", "Spine", "Chest", "UpperChest", "Neck", "Head",
                             "LeftUpperArm", "LeftLowerArm", "RightUpperArm", "RightLowerArm",
                             "LeftHand", "RightHand", "LeftFinger1_3", "RightFinger1_3",
                             "LeftUpperLeg", "LeftLowerLeg", "RightUpperLeg", "RightLowerLeg"}
                            .issubset(bone_names))
            self.assertFalse(any(name.startswith(("bone_", "Extra_")) for name in bone_names))
            self.assertTrue(all(value["max_vertex_displacement"] > 0
                                for pose, value in report["deformation_evidence"].items()
                                if pose != "neutral"))
            raised = report["deformation_evidence"]["raised_arms"]["upper_arm_tip_height_delta"]
            self.assertGreater(raised["left"], 0)
            self.assertGreater(raised["right"], 0)
            leg_lift = report["deformation_evidence"]["leg_lift"]["left_thigh_tip_depth_delta"]
            self.assertLess(leg_lift, 0)
            self.assertEqual(report["deformation_evidence"]["leg_lift"]["view"], "side")
            self.assertEqual(tuple(report["contact_sheet_dimensions"]), (7 * 256, 256))
            self.assertTrue(Path(request["rigged_model"]).is_file())
            # A conventional arm without a shoulder stub must select its first segment.
            script = root / "standard_arm.py"
            script.write_text(f"""import bpy, sys
sys.path.insert(0, {str(ROOT / 'blender')!r})
from skintokens_character import semantic_bones
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath={request['raw']!r})
rig = next(obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE')
bpy.context.view_layer.objects.active = rig; rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for shoulder, upper in [('bone_3', 'bone_4'), ('bone_6', 'bone_7')]:
    rig.data.edit_bones[upper].parent = rig.data.edit_bones['bone_2']
    rig.data.edit_bones.remove(rig.data.edit_bones[shoulder])
bpy.ops.object.mode_set(mode='OBJECT')
mapping = semantic_bones(rig)
assert mapping['left_upper_arm'] == 'bone_4', mapping
assert mapping['right_upper_arm'] == 'bone_7', mapping
""")
            standard = subprocess.run([BLENDER, "--background", "--factory-startup",
                                       "--python", str(script)], capture_output=True, text=True)
            self.assertEqual(standard.returncode, 0, standard.stdout + standard.stderr)

