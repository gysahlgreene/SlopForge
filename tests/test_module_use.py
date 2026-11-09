import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from slopforge.module_use import clear_opening, opening_height, row_gap, walk_levels
from slopforge.validation import apply_module_use

ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"


def _report(**measured):
    return {"status": "passed", "errors": [], "failure_codes": [], "measured": measured}


class ModuleUseMeasurementTests(unittest.TestCase):
    # Round 23's street kit, measured in the game (2026-11-09, issue #189): every piece's bounds were exact.
    def test_a_wall_whose_plinth_sets_its_width_leaves_a_gap_in_a_row(self):
        # The 6 m warehouse bay: its plinth reaches the bounds, and its body is 5.57 m wide above it.
        left = np.array([-3.0, -3.0] + [-2.785] * 16)
        self.assertAlmostEqual(row_gap(left, -left, 6.0), 0.43, places=3)
        self.assertIsNone(row_gap([np.nan], [np.nan], 6.0))

    def test_walking_surfaces_are_the_flat_ones_wide_enough_to_walk_on(self):
        # A 3 x 6 m stair, at 0.1 m cells: treads 0.3 m deep, a landing at 3.92 m, 0.3 m parapets to 4.5 m.
        heights = np.full((60, 30), np.nan)
        for row in range(45):
            heights[row, :] = 0.26 * (row // 3 + 1)
        heights[45:, :] = 3.92
        heights[:, :3] = heights[:, -3:] = 4.5
        self.assertEqual(walk_levels(heights, np.isfinite(heights)), [3.92])
        self.assertEqual(walk_levels(heights, np.zeros_like(heights, bool)), [])  # nothing flat
        # Round 23's 6 x 6 m gate tower: its roof at 12.5 m inside a parapet whose 1 m thick top is wide enough too.
        tower = np.full((60, 60), 12.5)
        tower[:10, :] = tower[-10:, :] = tower[:, :10] = tower[:, -10:] = 13.5
        self.assertEqual(walk_levels(tower, np.ones_like(tower, bool)), [13.5, 12.5])

    def test_the_clear_opening_is_how_tall_a_passage_of_each_width_is(self):
        # A 9 m tunnel mouth with a 2.7 x 3.7 m opening, at 0.1 m cells (rows from the ground up).
        through = np.zeros((75, 90), bool)
        through[:37, 31:58] = True
        profile = clear_opening(through)
        self.assertAlmostEqual(opening_height(profile, 2.5), 3.7)
        self.assertEqual(opening_height(profile, 5.0), 0.0)
        self.assertEqual(opening_height(clear_opening(np.zeros((75, 90), bool)), 1.0), 0.0)  # gates shut


class ModuleUseCheckTests(unittest.TestCase):
    def test_a_piece_that_cannot_be_used_as_declared_stops_for_a_new_concept(self):
        from slopforge.failures import candidate_quality_rejection
        from slopforge.pipelines.model import _validation_failure
        asset = {"target_size": [9, 3, 7.5], "tiles": True, "walk_height": 4.5, "clear_opening": [5, 5]}
        failed = apply_module_use(_report(row_gap=0.43, walk_levels=[3.92],
                                          clear_opening=[[2.5, 3.7], [5.0, 0.0]]), asset)
        self.assertEqual(failed["failure_codes"], ["module_row_gap", "module_walk_height", "module_opening"])
        self.assertIn("a row of it leaves 0.43 m gaps", failed["errors"][0])
        self.assertIn("no walking surface at the declared 4.5 m (it has them at 3.92 m)", failed["errors"][1])
        self.assertIn("5 m wide is 0 m tall", failed["errors"][2])
        self.assertFalse(candidate_quality_rejection(failed))  # the concept drew it: another seed repeats it
        stop = _validation_failure(failed, stage="material_assembly_export", attempt=1)
        self.assertEqual(stop["remedy"], "approve a concept closer to the module's declared size and use")

    def test_a_piece_that_fits_its_use_or_declares_none_passes(self):
        asset = {"target_size": [9, 3, 7.5], "tiles": True, "walk_height": 4.5, "clear_opening": [5, 5]}
        fitted = apply_module_use(_report(row_gap=0.02, walk_levels=[5.5, 4.47], clear_opening=[[5.0, 5.2]]), asset)
        self.assertEqual((fitted["status"], fitted["failure_codes"]), ("passed", []))
        self.assertEqual(fitted["limits"]["max_row_gap"], 0.05)
        undeclared = apply_module_use(_report(row_gap=0.43, walk_levels=[3.92]), {"target_size": [6, 1, 9]})
        self.assertEqual((undeclared["status"], undeclared["failure_codes"]), ("passed", []))

    def test_a_declared_use_that_was_not_measured_fails(self):
        failed = apply_module_use(_report(), {"tiles": True, "walk_height": 4.5, "clear_opening": [5, 5]})
        self.assertEqual(failed["failure_codes"], ["module_row_gap", "module_walk_height", "module_opening"])
        self.assertTrue(all("not measured" in error for error in failed["errors"]))


FIXTURE = """import bpy, sys
from pathlib import Path
out = Path(sys.argv[-1])

def box(x0, y0, z0, x1, y1, z1):
    bpy.ops.mesh.primitive_cube_add(size=1, location=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    bpy.context.object.scale = (x1 - x0, y1 - y0, z1 - z0)
    bpy.ops.object.transform_apply(scale=True)

def save(name, boxes):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for corners in boxes:
        box(*corners)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / name))

# A 3 m wall bay whose 0.3 m plinth reaches the bounds and whose body stops 0.1 m short of each end.
save("wall.blend", [(-1.5, -0.3, 0, 1.5, 0.3, 0.3), (-1.4, -0.25, 0.3, 1.4, 0.25, 4.5)])
# A stair head: a 3 x 1.5 m landing at 3.9 m between 0.3 m parapets to 4.5 m.
save("stair.blend", [(-1.2, -0.75, 0, 1.2, 0.75, 3.9), (-1.5, -0.75, 0, -1.2, 0.75, 4.5),
                     (1.2, -0.75, 0, 1.5, 0.75, 4.5)])
# A 9 m tunnel mouth with a 2.7 x 3.7 m opening between its piers and under its lintel.
save("tunnel.blend", [(-4.5, -1.5, 0, -1.35, 1.5, 7.5), (1.35, -1.5, 0, 4.5, 1.5, 7.5),
                      (-1.35, -1.5, 3.7, 1.35, 1.5, 7.5)])
"""


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class ModuleUseBlenderTests(unittest.TestCase):
    def test_inspection_measures_how_a_sized_piece_is_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture.py").write_text(FIXTURE)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(root / "fixture.py"),
                            "--", str(root)], check=True, capture_output=True)
            measured = {}
            for name in ("wall", "stair", "tunnel"):
                subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                str(ROOT / "blender/inspect_model.py"), "--", str(root / f"{name}.blend"),
                                str(root / f"{name}.json"), "1000", "--real-scale"], check=True, capture_output=True)
                measured[name] = json.loads((root / f"{name}.json").read_text())["measured"]
        self.assertAlmostEqual(measured["wall"]["row_gap"], 0.2, delta=0.02)
        self.assertEqual(len(measured["stair"]["walk_levels"]), 1)
        self.assertAlmostEqual(measured["stair"]["walk_levels"][0], 3.9, delta=0.02)
        self.assertAlmostEqual(opening_height(measured["tunnel"]["clear_opening"], 2.5), 3.7, delta=0.1)
        self.assertEqual(opening_height(measured["tunnel"]["clear_opening"], 5.0), 0.0)


if __name__ == "__main__":
    unittest.main()
