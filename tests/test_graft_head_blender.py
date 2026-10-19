"""Real Blender check that a separately generated head is placed and joined onto a body."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BLENDER = (os.environ.get("BLENDER_BIN") or shutil.which("blender")
           or "/Applications/Blender.app/Contents/MacOS/Blender")

# Body: torso cylinder (z 0..1.4, radius 0.2) and a head sphere (centre z 1.6, radius 0.15) on a neck.
# Head source: the same head and neck generated three times larger and offset elsewhere.
FIXTURE = """import bpy, sys
out = sys.argv[-1]
def export(name, parts):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for kind, location, size in parts:
        if kind == "cyl":
            bpy.ops.mesh.primitive_cylinder_add(radius=size[0], depth=size[1], location=location, vertices=48)
        else:
            bpy.ops.mesh.primitive_uv_sphere_add(radius=size[0], location=location, segments=48, ring_count=24)
    bpy.ops.object.select_all(action="SELECT")
    bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
    bpy.ops.object.join()
    remesh = bpy.context.object.modifiers.new("r", "REMESH"); remesh.mode, remesh.voxel_size = "VOXEL", 0.012 * size_scale[name]
    bpy.ops.object.modifier_apply(modifier="r")
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT"); bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.export_scene.gltf(filepath=f"{out}/{name}.glb", export_format="GLB")
size_scale = {"body": 1.0, "head": 3.0}
export("body", [("cyl", (0, 0, 0.7), (0.2, 1.4)), ("cyl", (0, 0, 1.42), (0.06, 0.12)), ("sph", (0, 0, 1.6), (0.15,))])
export("head", [("sph", (5, 2, 10), (0.45,)), ("cyl", (5, 2, 9.4), (0.18, 0.6))])
"""


def mask(path, size, box):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste((200, 180, 160, 255), box)
    image.save(path)


def maps(folder, color):
    folder.mkdir()
    for name, value in (("basecolor", color), ("roughness", (128, 128, 128)), ("metallic", (0, 0, 0)),
                        ("normal", (128, 128, 255))):
        Image.new("RGB", (16, 16), value).save(folder / f"{name}.png")


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class GraftHeadTests(unittest.TestCase):
    def test_head_source_is_aligned_cut_and_joined_with_its_own_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture.py").write_text(FIXTURE)
            subprocess.run([BLENDER, "--background", "--python", str(root / "fixture.py"), "--", str(root)],
                           check=True, capture_output=True, text=True)
            maps(root / "body_maps", (40, 160, 160))
            maps(root / "head_maps", (230, 120, 40))
            # Concept: 1 px = 0.005 m. Body silhouette x -0.2..0.2 -> cols 160..240, z 0..1.75 -> rows 50..400.
            mask(root / "concept.png", (400, 450), (160, 50, 241, 401))
            # Head crop of concept rows 50..140 (z 1.75..1.30), cols 170..230, scaled 4x into 240x360 pixels;
            # the head source spans the same region three times larger.
            mask(root / "crop.png", (240, 360), (0, 0, 241, 361))
            request = {"body": str(root / "body.glb"), "body_maps": str(root / "body_maps"),
                       "head": str(root / "head.glb"), "head_maps": str(root / "head_maps"),
                       "concept": str(root / "concept.png"), "head_box": [170, 50, 230, 140],
                       "head_crop": str(root / "crop.png"), "neck_row": 106,
                       "output": str(root / "grafted.glb"), "report": str(root / "report.json")}
            (root / "request.json").write_text(json.dumps(request))
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/graft_head.py"), "--", str(root / "request.json")],
                           check=True, capture_output=True, text=True)
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["status"], "grafted", report)
            self.assertAlmostEqual(report["scale"], 1 / 3, delta=0.03)
            self.assertLess(report["icp_rms_final"], 0.01)
            self.assertEqual(report["materials"], 2)
            self.assertEqual(report["boundary_edges"], 0)
