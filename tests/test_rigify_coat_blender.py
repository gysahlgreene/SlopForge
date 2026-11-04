"""A long-coated body built from a separate head and a headless body: what the first such character tore on."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"

# A-pose, 1.8 m, facing -Y. Thick sleeves, a long skirt, arms that leave the body at different heights,
# a head that is its own piece, and a small scrap sitting on the hem.
FIXTURE = """import bpy, math, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
def cyl(r, depth, loc, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc, rotation=rot, vertices=24)
cyl(0.16, 0.62, (0, 0, 1.18))
cyl(0.05, 0.12, (0, 0, 1.51))
bpy.ops.mesh.primitive_cone_add(radius1=0.25, radius2=0.16, depth=0.6, location=(0, 0, 0.67), vertices=32)
for side, degrees in ((1, 40), (-1, 28)):
    cyl(0.07, 0.86, (side * 0.09, 0, 0.45))
    bpy.ops.mesh.primitive_cube_add(size=1, location=(side * 0.09, -0.06, 0.03)); bpy.context.object.scale = (0.09, 0.24, 0.06)
    angle = math.radians(degrees)
    length = 0.62
    cyl(0.085, length, (side * (0.17 + math.sin(angle) * length / 2), 0, 1.43 - math.cos(angle) * length / 2), (0, -side * angle, 0))
bpy.ops.object.select_all(action="SELECT")
bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
bpy.ops.object.join()
body = bpy.context.object
remesh = body.modifiers.new("dense", "REMESH")
remesh.mode, remesh.voxel_size = "VOXEL", 0.012
bpy.ops.object.modifier_apply(modifier=remesh.name)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=0.14, location=(0, 0, 1.68))
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.008, location=(0.22, -0.1, 0.42))
# A coat flap hanging beside the hip, clear of the torso and lower than the hand.
bpy.ops.mesh.primitive_cube_add(size=1, location=(-0.27, 0.1, 0.85)); bpy.context.object.scale = (0.03, 0.06, 0.28)
bpy.ops.object.select_all(action="SELECT")
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format="GLB")
"""

PROBE = """import bpy, json, sys
from mathutils import Vector
rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
mesh = next(o for o in bpy.data.objects if o.type == "MESH")
names = [g.name for g in mesh.vertex_groups]
def weights(v):
    return {names[g.group]: g.weight for g in v.groups}
points = [(mesh.matrix_world @ v.co, weights(v)) for v in mesh.data.vertices]
bone = rig.data.bones
elbow, wrist = (rig.matrix_world @ bone[n].head_local for n in ("DEF-forearm.L", "DEF-hand.L"))
mid = (elbow + wrist) / 2
sleeve = [w for p, w in points if (p - mid).length < 0.1]
knee = [w for p, w in points if abs(p.z - 0.55) < 0.02]
head = [w for p, w in points if p.z > 1.6]
scrap = [w for p, w in points if (p - Vector((0.22, -0.1, 0.42))).length < 0.009]
json.dump({
    "armatures": sum(o.type == "ARMATURE" for o in bpy.data.objects),
    "lowest_head_weight": min((p.z for p, w in points if w.get("DEF-spine.006", 0) > 0.01), default=None),
    "sleeve_forearm_share": sum(sum(v for k, v in w.items() if k.startswith(("DEF-forearm.L", "DEF-hand.L"))) > 0.5 for w in sleeve) / len(sleeve),
    "knee_leg_weight": max(sum(v for k, v in w.items() if k.startswith(("DEF-shin", "DEF-foot"))) for w in knee),
    "knee_thigh_balance": max(abs(w.get("DEF-thigh.L", 0) - w.get("DEF-thigh.R", 0)) for w in knee),
    "boot_leg_weight": min(sum(v for k, v in w.items() if k.startswith(("DEF-shin", "DEF-foot", "DEF-toe"))) for p, w in points if p.z < 0.1),
    "head_bone_share": min(sum(v for k, v in w.items() if k in ("DEF-spine.004", "DEF-spine.006")) for w in head),
    "face_on_head": min(w.get("DEF-spine.006", 0) for p, w in points if p.z > 1.62),
    "scrap_leg_weight": max(sum(v for k, v in w.items() if k.startswith(("DEF-shin", "DEF-foot"))) for w in scrap),
}, open(sys.argv[-1], "w"))
"""

SKELETON = """import bpy, json, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=sys.argv[-2])
rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
def chain(name):
    bone, out = rig.data.bones[name], []
    while bone:
        out.append(bone.name)
        bone = bone.parent
    return out
json.dump({"bones": [b.name for b in rig.data.bones], "thigh": chain("DEF-thigh.L"), "hand": chain("DEF-hand.R")}, open(sys.argv[-1], "w"))
"""

RINGS = """import json, math, sys
sys.path.insert(0, sys.argv[-2])
import numpy as np
import rigify_character as rc
def ring(radius, heights, cx=0.0):
    return [(cx + radius * math.cos(a), radius * math.sin(a), z) for z in heights for a in np.linspace(0, 6.283, 32, endpoint=False)]
heights = np.arange(0.2, 0.8, 0.02)
axis = lambda z: (np.zeros_like(z), np.zeros_like(z))
leg, skirt = ring(0.08, heights), ring(0.25, heights)
hollow = np.array(leg + skirt)
found = rc.inside_leg_ring(hollow, axis, 0.13, 0.02)
solid = rc.inside_leg_ring(np.array(ring(0.25, heights, cx=0.12)), axis, 0.13, 0.02)
line = np.array([(i, i + 1) for i in range(9)])
holed = np.array([True] * 4 + [False] + [True] * 3 + [False] * 2)
spiked = np.array([False] * 4 + [True] + [False] * 5)
json.dump({"leg_found": float(found[:len(leg)].mean()), "skirt_found": float(found[len(leg):].mean()), "solid_found": float(solid.mean()),
           "hole_closed": bool(rc.tidy_mask(holed, line, 1)[4]), "spike_dropped": not bool(rc.tidy_mask(spiked, line, 1)[4])}, open(sys.argv[-1], "w"))
"""

SOLID = """import bpy, json, sys
sys.path.insert(0, sys.argv[-2])
import rigify_character as rc
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5)
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.45)  # an inner layer a voxel remesh keeps as a second shell
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=0.03, location=(0.9, 0, 0))
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.join()
proxy, scraps = rc.solid_proxy(bpy.context.object, 60)
radii = [(proxy.matrix_world @ v.co).length for v in proxy.data.vertices]
json.dump({"scraps": scraps, "innermost": min(radii), "outermost": max(radii)}, open(sys.argv[-1], "w"))
"""


def blender(*arguments):
    return subprocess.run([BLENDER, "--background", "--python-exit-code", "1", *arguments], capture_output=True, text=True)


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class CoatedCharacterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        root = cls.root = Path(cls.temporary.name)
        (root / "fixture.py").write_text(FIXTURE)
        made = blender("--python", str(root / "fixture.py"), "--", str(root / "coat.glb"))
        assert made.returncode == 0, made.stderr[-2000:]
        poses = ["t_pose", "raised_arms", "crouch", "leg_lift", "elbow_bend", "shoulder_rotation"]
        (root / "request.json").write_text(json.dumps({
            "source": str(root / "coat.glb"), "rigged_model": str(root / "rig.fbx"), "rigged_blend": str(root / "rig.blend"),
            "report": str(root / "report.json"), "topology_policy": "allow_for_review", "long_skirt": True, "solid_only": True,
            "evidence": {pose: str(root / f"{pose}.png") for pose in poses}}))
        rigged = blender("--python", str(ROOT / "blender/rigify_character.py"), "--", str(root / "request.json"))
        cls.report = json.loads((root / "report.json").read_text())
        assert cls.report["status"] == "complete", (cls.report.get("error"), rigged.stdout[-2000:])
        (root / "probe.py").write_text(PROBE)
        probed = blender(str(root / "rig.blend"), "--python", str(root / "probe.py"), "--", str(root / "probe.json"))
        assert probed.returncode == 0, probed.stdout[-2000:]
        cls.probe = json.loads((root / "probe.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_breast_bones_give_no_weight_to_the_head(self):
        self.assertGreater(self.probe["lowest_head_weight"], 1.45)

    def test_a_flap_beside_the_hip_is_not_taken_for_the_hand(self):
        hand = self.report["arm_depth_fit"]["joints"]["hand.R"]
        self.assertLess(hand[1][0], -0.4, hand)
        self.assertLess(self.report["arm_depth_fit"]["joints"]["hand.L"][1][0] * -1, -0.4)

    def test_the_report_counts_each_arms_vertices_and_passes_a_sound_rig(self):
        counts = self.report["arm_vertices"]
        self.assertGreater(min(counts.values()), 0.5 * max(counts.values()), counts)
        self.assertFalse([w for w in self.report["validation"]["warnings"] if "Arm bones" in w])

    def test_a_shell_body_goes_straight_to_the_solid_proxy(self):
        self.assertIn("solid_divisions", self.report["skin_binding"]["meshes"][0]["proxy_attempts"][0])

    def test_a_thick_sleeve_follows_its_forearm(self):
        self.assertGreater(self.probe["sleeve_forearm_share"], 0.85)

    def test_torso_width_is_not_measured_across_a_merged_arm(self):
        slices = self.report["arm_depth_fit"]["torso_slices"]
        self.assertTrue(slices)
        for _, low, high in slices:
            self.assertGreater(low, -0.3)
            self.assertLess(high, 0.3)

    def test_a_long_skirt_moves_as_one_tube(self):
        self.assertEqual(self.probe["knee_leg_weight"], 0)
        self.assertLess(self.probe["knee_thigh_balance"], 0.3)
        self.assertTrue(self.report["skin_weighting"][0]["long_skirt"]["skirt_vertices"])

    def test_boots_below_the_hem_keep_their_legs(self):
        self.assertGreater(self.report["skin_weighting"][0]["long_skirt"]["hem_z"], 0.3)
        self.assertGreater(self.probe["boot_leg_weight"], 0.9)

    def test_a_scrap_on_the_hem_follows_the_skirt(self):
        self.assertEqual(self.probe["scrap_leg_weight"], 0)

    def test_a_separate_head_follows_the_head_and_neck(self):
        self.assertGreater(self.report["skin_weighting"][0]["separate_head_vertices"], 0)
        self.assertGreater(self.probe["head_bone_share"], 0.99)
        self.assertGreater(self.probe["face_on_head"], 0.99)  # a jaw half on the neck shears when the head turns

    def test_the_delivered_skeleton_is_one_tree_of_deform_bones(self):
        (self.root / "skeleton.py").write_text(SKELETON)
        run = blender("--python", str(self.root / "skeleton.py"), "--", str(self.root / "rig.fbx"), str(self.root / "skeleton.json"))
        self.assertEqual(run.returncode, 0, run.stdout[-2000:])
        skeleton = json.loads((self.root / "skeleton.json").read_text())
        self.assertTrue(all(name.startswith("DEF-") and "breast" not in name for name in skeleton["bones"]), skeleton["bones"])
        self.assertIn("DEF-spine", skeleton["thigh"])
        self.assertIn("DEF-spine.003", skeleton["hand"])

    def test_the_rigged_blend_can_take_a_clip(self):
        self.assertEqual(self.probe["armatures"], 1)

    def test_a_leg_inside_a_hollow_skirt_is_told_from_the_skirt(self):
        (self.root / "rings.py").write_text(RINGS)
        run = blender("--python", str(self.root / "rings.py"), "--", str(ROOT / "blender"), str(self.root / "rings.json"))
        self.assertEqual(run.returncode, 0, run.stdout[-2000:])
        rings = json.loads((self.root / "rings.json").read_text())
        self.assertEqual(rings["leg_found"], 1.0)
        self.assertEqual(rings["skirt_found"], 0.0)
        self.assertEqual(rings["solid_found"], 0.0)  # a solid body has no leg to find, so it all stays skirt
        self.assertTrue(rings["hole_closed"])
        self.assertTrue(rings["spike_dropped"])

    def test_the_solid_proxy_fills_shells_and_drops_scraps(self):
        (self.root / "solid.py").write_text(SOLID)
        run = blender("--python", str(self.root / "solid.py"), "--", str(ROOT / "blender"), str(self.root / "solid.json"))
        self.assertEqual(run.returncode, 0, run.stdout[-2000:])
        solid = json.loads((self.root / "solid.json").read_text())
        self.assertEqual(solid["scraps"], 1)
        self.assertGreater(solid["innermost"], 0.4)  # no surface left inside
        self.assertLess(solid["outermost"], 0.7)


if __name__ == "__main__":
    unittest.main()
