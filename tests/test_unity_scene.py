import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from slopforge.unity_scene import build_kit_scene

UNITY_PROJECT = os.environ.get("SLOPFORGE_UNITY_PROJECT")
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"


@unittest.skipUnless(os.environ.get("SLOPFORGE_RUN_UNITY_IMPORT") == "1" and UNITY_PROJECT,
                     "set SLOPFORGE_RUN_UNITY_IMPORT=1 and SLOPFORGE_UNITY_PROJECT to a Built-in or URP project")
class KitSceneLiveTests(unittest.TestCase):
    """Real Unity: prefabs, grounding, seam gaps and a corner turned to face the layout's centre."""

    def setUp(self):
        self.root = Path(UNITY_PROJECT).resolve()
        self.folder = self.root / f"Assets/SlopForgeSceneTest_{uuid.uuid4().hex[:8]}"
        self.folder.mkdir(parents=True)
        self.kit = f"scene_test_{uuid.uuid4().hex[:8]}"
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for path in (self.folder, self.root / f"Assets/Art/Generated/Prefabs/{self.kit}"):
            shutil.rmtree(path, ignore_errors=True)
            Path(f"{path}.meta").unlink(missing_ok=True)
        for scene in (self.root / "Assets/Art/Generated/Scenes").glob(f"{self.kit}_*"):
            scene.unlink()

    def _export(self, name, boxes, origin_at_top=False):
        """An FBX made of (centre, size) boxes, exported as approve-texture does; its origin is its bottom centre,
        or its top centre (a floor tile) with origin_at_top."""
        parts = "; ".join(f"bpy.ops.mesh.primitive_cube_add(size=1, location={centre}); "
                          f"bpy.context.object.scale = {size}" for centre, size in boxes)
        script = ("import bpy; bpy.ops.wm.read_factory_settings(use_empty=True); " + parts + "; "
                  "bpy.ops.object.select_all(action='SELECT'); "
                  "bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]; "
                  "bpy.ops.object.join(); bpy.ops.object.transform_apply(location=True, scale=True); "
                  + ("bpy.context.scene.cursor.location = (0, 0, max((bpy.context.object.matrix_world @ v.co).z "
                     "for v in bpy.context.object.data.vertices)); bpy.ops.object.origin_set(type='ORIGIN_CURSOR'); "
                     if origin_at_top else "") +
                  "bpy.ops.mesh.uv_texture_add(); "
                  "obj = bpy.context.object; obj.data.materials.append(bpy.data.materials.new('box')); "
                  f"bpy.ops.export_scene.fbx(filepath={str(self.folder / f'{name}.fbx')!r}, use_selection=True, "
                  "object_types={'MESH'}, axis_forward='-Z', axis_up='Y', apply_unit_scale=True, "
                  "bake_space_transform=False, add_leaf_bones=False)")
        subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script],
                       check=True, capture_output=True)
        return (self.folder / f"{name}.fbx").relative_to(self.root).as_posix()

    def test_scene_reports_grounding_seams_and_a_corner_facing_inward(self):
        block = self._export("block", [((0, 0, 0.5), (1, 1, 1))])
        # An L whose arms run along -X and -Y in Blender; its open side is wherever Unity puts +X+Y.
        corner = self._export("corner", [((-0.4, 0, 0.5), (0.2, 1, 1)), ((0, -0.4, 0.5), (1, 0.2, 1))])
        slab = self._export("slab", [((0, 0, 0.1), (1, 1, 0.2))], origin_at_top=True)
        place = lambda module, fbx, x, z, rotation="0", pivot="bottom_center": {
            "module": module, "fbx": fbx, "pivot": pivot, "x": x, "y": 0.0, "z": z, "rotation": rotation}
        placements = [place("block", block, 0.0, 0.0), place("block", block, 1.0, 0.0),
                      place("block", block, 2.2, 0.0), place("corner", corner, -2.0, 2.0, "auto"),
                      place("slab", slab, -2.0, -2.0, pivot="top_center")]
        with tempfile.TemporaryDirectory() as temporary:
            render = Path(temporary) / "scene.png"
            report = build_kit_scene(self.root, self.kit, "test", placements, grid=1.0, tolerance=0.05, render=render)
            self.assertTrue(render.is_file())
        self.assertTrue((self.root / report["scene"]).is_file())
        self.assertTrue(all(item["collider"] and item["is_static"] for item in report["instances"]))
        self.assertTrue(all(abs(item["ground_error"]) < 0.01 for item in report["instances"]), report["instances"])
        gaps = {(seam["a"], seam["b"]): round(seam["gap"], 2) for seam in report["seams"]}
        self.assertEqual(gaps, {(1, 2): 0.2})
        self.assertEqual(len(report["errors"]), 1)
        self.assertIn("0.200 m gap", report["errors"][0])
        opening = report["instances"][3]["opening"]
        centre = (-0.16, 0.0)  # the five placements' mean x and z
        self.assertGreater(opening[0] * (centre[0] + 2.0) + opening[2] * (centre[1] - 2.0), 0)


if __name__ == "__main__":
    unittest.main()
