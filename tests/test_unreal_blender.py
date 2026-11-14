import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"

# A figure as one mesh of loose pieces: a body block with a head cube on top, an arm beside it and a leg below; floating 0.5 m up and off centre, so the export must set it on its floor.
FIGURE = """import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
for size, at in (((0.4, 0.3, 0.6), (0, 0, 1.3)), ((0.2, 0.2, 0.2), (0, 0, 1.75)), ((0.1, 0.1, 0.5), (0.27, 0, 1.25)),
                 ((0.15, 0.15, 0.5), (0.12, 0, 0.75))):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(at[0] + 2, at[1] + 1, at[2]))
    bpy.context.object.scale = size
    bpy.ops.object.transform_apply(scale=True)
for item in bpy.context.scene.objects:
    item.select_set(True)
bpy.context.view_layer.objects.active = bpy.context.scene.objects[0]
bpy.ops.object.join()
obj = bpy.context.object
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.subdivide(number_cuts=6)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
"""

READ = """import bpy, json, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=sys.argv[-2])
points = [o.matrix_world @ v.co for o in bpy.context.scene.objects if o.type == "MESH" for v in o.data.vertices]
json.dump({"objects": sorted(o.name for o in bpy.context.scene.objects if o.type == "MESH"),
           "low": [min(p[i] for p in points) for i in range(3)], "high": [max(p[i] for p in points) for i in range(3)]},
          open(sys.argv[-1], "w"))
"""


def _blender(*args):
    return subprocess.run([BLENDER, "--background", "--python-exit-code", "1", *args], capture_output=True, text=True)


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class UnrealExportTests(unittest.TestCase):
    def test_a_figure_breaks_into_parts_on_their_joints_from_masks_on_its_own_views(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "figure.py").write_text(FIGURE)
            self.assertEqual(_blender("--python", str(root / "figure.py"), "--", str(root / "figure.blend")).returncode, 0)
            views = root / "views"
            request = {"blend": str(root / "figure.blend"), "name": "figure", "out_dir": str(root / "out"),
                       "render_views": str(views), "report": str(root / "views.json")}
            (root / "views_request.json").write_text(json.dumps(request))
            result = _blender("--python", str(ROOT / "blender/export_unreal.py"), "--", str(root / "views_request.json"))
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            # Masks as SAM would cut them from boxes on the renders: the head's rows, the arm's columns, the rest body.
            masks = {}
            for view in ("front", "back"):
                alpha = np.asarray(Image.open(views / f"view_{view}.png"))[..., 3] > 0
                rows, columns = np.nonzero(alpha)
                height = rows.max() - rows.min()
                head = alpha & (np.arange(alpha.shape[0])[:, None] < rows.min() + 0.17 * height)
                # the arm is the figure's +X side: on the right of the front view, the left of the back view
                arm_columns = np.arange(alpha.shape[1]) > columns.max() - 0.13 * (columns.max() - columns.min()) \
                    if view == "front" else np.arange(alpha.shape[1]) < columns.min() + 0.13 * (columns.max() - columns.min())
                arm = alpha & arm_columns[None, :] & ~head
                for name, mask in (("head", head), ("arm", arm), ("body", alpha & ~head & ~arm)):
                    path = root / f"{view}_{name}.png"
                    Image.fromarray((mask * 255).astype(np.uint8)).save(path)
                    masks.setdefault(name, {})[view] = str(path)
            request = {"blend": str(root / "figure.blend"), "name": "figure", "out_dir": str(root / "out"),
                       "report": str(root / "report.json"), "body": "body",
                       "parts": [{"name": "head", "masks": masks["head"], "parent": "body"},
                                 {"name": "arm", "masks": masks["arm"], "parent": "body"},
                                 {"name": "body", "masks": masks["body"]}]}
            (root / "request.json").write_text(json.dumps(request))
            result = _blender("--python", str(ROOT / "blender/export_unreal.py"), "--", str(root / "request.json"))
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            report = json.loads((root / "report.json").read_text())
            parts = {part["name"]: part for part in report["parts"]}
            self.assertEqual(set(parts), {"head", "arm"})
            # The head's joint is its neck, the top of the body at 1.6 m above the figure's floor (0.5 m in the file),
            # in Unreal's centimetres. Both are loose pieces, as generated meshes have: the arm hangs 2 cm off the
            # body's side, so its joint is the middle of that gap.
            self.assertAlmostEqual(parts["head"]["pivot_unreal_cm"][2], 110, delta=4)
            self.assertAlmostEqual(parts["arm"]["pivot_unreal_cm"][0], 21, delta=2)
            self.assertTrue(50 <= parts["arm"]["pivot_unreal_cm"][2] <= 100)
            for name in ("figure", "Parts/figure_head", "Parts/figure_arm", "Parts/figure_body"):
                self.assertTrue((root / "out" / f"{name}.fbx").is_file(), name)
            (root / "read.py").write_text(READ)
            for name, check in (("figure", "whole"), ("Parts/figure_head", "head")):
                _blender("--python", str(root / "read.py"), "--", str(root / "out" / f"{name}.fbx"), str(root / "r.json"))
                read = json.loads((root / "r.json").read_text())
                if check == "whole":  # on its floor, centred, every part a separate object
                    self.assertAlmostEqual(read["low"][2], 0, delta=0.01)
                    self.assertAlmostEqual(read["high"][2], 1.35, delta=0.01)
                    self.assertEqual(len(read["objects"]), 3)
                else:  # the head alone, its origin on its neck: it rises from 0 to 0.2 m
                    self.assertAlmostEqual(read["low"][2], 0, delta=0.03)
                    self.assertAlmostEqual(read["high"][2], 0.2, delta=0.03)


# A weapon as the final pass leaves it: a body (grip at its origin, the object moved 1 m along X) with a trigger child
# whose origin is its pivot, 0.1 m forward (Blender -Y) and 0.05 m down from the grip.
WEAPON = """import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1)
body = bpy.context.object
body.scale = (0.04, 0.6, 0.1)
bpy.ops.object.transform_apply(scale=True)
body.location = (1, 0, 0)
bpy.ops.mesh.primitive_cube_add(size=0.02, location=(1, -0.1, -0.08))
trigger = bpy.context.object
trigger.name = "trigger"
trigger.data.transform(__import__("mathutils").Matrix.Translation((0, 0, -0.01)))
trigger.location = (1, -0.1, -0.05)
trigger.parent = body
trigger.matrix_parent_inverse = body.matrix_world.inverted()
trigger["slopforge_part"] = "hinge"
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
"""


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class UnrealWeaponTests(unittest.TestCase):
    def test_a_weapons_moving_parts_keep_their_pivots_and_the_grip_stays_the_origin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "weapon.py").write_text(WEAPON)
            self.assertEqual(_blender("--python", str(root / "weapon.py"), "--", str(root / "w.blend")).returncode, 0)
            trigger = {"name": "trigger", "kind": "hinge", "axis": "x", "min": 0.0, "max": 20.0}
            request = {"blend": str(root / "w.blend"), "name": "gun", "out_dir": str(root / "out"),
                       "report": str(root / "report.json"), "moving": [trigger], "keep_origin": True}
            (root / "request.json").write_text(json.dumps(request))
            result = _blender("--python", str(ROOT / "blender/export_unreal.py"), "--", str(root / "request.json"))
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            report = json.loads((root / "report.json").read_text())
            (part,) = report["moving_parts"]
            # 0.1 m forward of the grip (the body's origin, 1 m along X in the file) and 0.05 m down: Unreal (0, 10, -5)
            self.assertEqual(part["pivot_unreal_cm"], [0.0, 10.0, -5.0])
            self.assertEqual((part["axis_unreal"], part["range"], part["range_unit"]), ([-1, 0, 0], [0.0, 20.0], "degrees"))
            (root / "read.py").write_text(READ)
            for name, objects in (("gun", 2), ("Parts/gun_trigger", 1), ("Parts/gun_body", 1)):
                self.assertEqual(_blender("--python", str(root / "read.py"), "--", str(root / "out" / f"{name}.fbx"),
                                          str(root / "r.json")).returncode, 0)
                read = json.loads((root / "r.json").read_text())
                self.assertEqual(len(read["objects"]), objects, name)
                if name == "Parts/gun_trigger":  # its origin on its pivot: the cube hangs 0.02 m below it
                    self.assertAlmostEqual(read["high"][2], 0.0, delta=0.002)
                    self.assertAlmostEqual(read["low"][2], -0.02, delta=0.002)
            # An undeclared child is refused: the game would not know how it moves
            request["moving"] = []
            (root / "request.json").write_text(json.dumps(request))
            result = _blender("--python", str(ROOT / "blender/export_unreal.py"), "--", str(root / "request.json"))
            self.assertNotEqual(result.returncode, 0)


class UnrealMapTests(unittest.TestCase):
    def test_unreal_gets_an_orm_map_and_a_directx_normal(self):
        from slopforge.unreal import unreal_maps
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Image.new("RGB", (4, 4), (128, 200, 255)).save(root / "normal.png")
            Image.new("L", (4, 4), 180).save(root / "roughness.png")
            Image.new("L", (4, 4), 40).save(root / "metallic.png")
            unreal_maps(root / "normal.png", root / "roughness.png", root / "metallic.png", root / "orm.png",
                        root / "normal_dx.png")
            self.assertEqual(Image.open(root / "orm.png").getpixel((1, 1)), (255, 180, 40))
            self.assertEqual(Image.open(root / "normal_dx.png").getpixel((1, 1)), (128, 55, 255))


if __name__ == "__main__":
    unittest.main()
