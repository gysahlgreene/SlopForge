import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"
SCRIPT = Path(__file__).resolve().parents[1] / "blender/shape_guide.py"


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class ShapeGuideRenderTest(unittest.TestCase):
    def _render(self, shape, ratio):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "guide.png"
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(SCRIPT), "--",
                            str(out), "320", "240", shape, str(ratio)], check=True, capture_output=True)
            return np.asarray(Image.open(out).convert("L"))

    @staticmethod
    def _apparent_ratio(depth):
        rows, cols = np.where(depth.any(1))[0], np.where(depth.any(0))[0]
        return (rows.max() - rows.min() + 1) / (cols.max() - cols.min() + 1)

    def test_cylinder_guide_is_a_near_bright_depth_map_of_the_declared_proportion(self):
        depth = self._render("cylinder", 0.5)
        self.assertEqual(depth[:8, :8].max(), 0)  # black background
        self.assertGreater(depth.max(), 220)  # nearest surface bright
        # A cylinder half as tall as it is wide reads 0.77 from the guide's three-quarter camera (2026-10-22).
        self.assertAlmostEqual(self._apparent_ratio(depth > 5), 0.77, delta=0.04)

    def test_same_request_renders_identical_pixels_without_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = [Path(temp) / f"guide_{index}.png" for index in range(2)]
            for path in paths:
                subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(SCRIPT), "--",
                                str(path), "160", "120", "box", "1.25"], check=True, capture_output=True)
            # Its hash joins the concept identity, so repeating a request must not look like a new guide.
            self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
            self.assertFalse({"Date", "File", "RenderTime"} & set(Image.open(paths[0]).info))

    def test_box_guide_follows_its_ratio(self):
        self.assertGreater(self._apparent_ratio(self._render("box", 1.6) > 5),
                           self._apparent_ratio(self._render("box", 0.8) > 5) + 0.4)

    def test_unknown_shape_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(SCRIPT), "--",
                                     str(Path(temp) / "guide.png"), "320", "240", "cone", "1"], capture_output=True,
                                    text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
