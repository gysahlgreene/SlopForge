"""Real Blender check for front concept projection onto a character's base color."""
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

# A 2 x 2 grid facing -Y (the model's front) with a box in front of its left part. The box's UVs are
# parked in a corner so only the grid owns the sampled texels.
FIXTURE = """import bpy, math, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_grid_add(x_subdivisions=24, y_subdivisions=24, size=2, rotation=(math.pi / 2, 0, 0))
grid = bpy.context.object
bpy.ops.mesh.primitive_cube_add(size=1, location=(-0.6, -0.6, 0))
box = bpy.context.object
box.scale = (0.4, 0.2, 0.8)
for loop in box.data.uv_layers.active.data:
    loop.uv = (0.99, 0.99)
bpy.ops.object.select_all(action="SELECT")
bpy.context.view_layer.objects.active = grid
bpy.ops.object.join()
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format="GLB")
"""


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class ProjectConceptTests(unittest.TestCase):
    def run_projection(self, root, concept_size, name):
        Image.new("RGBA", concept_size, (255, 0, 0, 255)).save(root / f"{name}_concept.png")
        request = {"model": str(root / "model.glb"), "basecolor": str(root / "voxel.png"),
                   "concept": str(root / f"{name}_concept.png"), "output": str(root / f"{name}.png"),
                   "report": str(root / f"{name}.json"), "size": 64}
        (root / f"{name}_request.json").write_text(json.dumps(request))
        subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                        str(ROOT / "blender/project_concept.py"), "--", str(root / f"{name}_request.json")],
                       check=True, capture_output=True, text=True)
        return json.loads((root / f"{name}.json").read_text())

    def test_projects_onto_visible_front_and_skips_mismatched_proportions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture.py").write_text(FIXTURE)
            subprocess.run([BLENDER, "--background", "--python", str(root / "fixture.py"), "--", str(root / "model.glb")],
                           check=True, capture_output=True, text=True)
            Image.new("RGB", (64, 64), (128, 128, 128)).save(root / "voxel.png")

            report = self.run_projection(root, (64, 64), "square")
            self.assertEqual(report["status"], "projected", report)
            image = Image.open(root / "square.png").convert("RGB")
            # UV u follows x: the right side faces the camera unobstructed and takes the concept color;
            # the left side sits behind the box and keeps the voxel color.
            right, left = image.getpixel((51, 32)), image.getpixel((12, 32))
            self.assertGreater(right[0], 200)
            self.assertLess(right[1], 40)
            self.assertTrue(all(abs(value - 128) < 12 for value in left), left)

            report = self.run_projection(root, (128, 64), "wide")
            self.assertEqual(report["status"], "skipped")
            self.assertFalse((root / "wide.png").exists())
