"""Nearest-surface colour lookup used to dress template characters."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import importlib.util

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("scipy"), "scipy is not installed (optional template-character tooling)")
class NearestSolveTests(unittest.TestCase):
    def test_texels_take_the_colour_of_the_nearest_source_sample_within_reach(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            color = np.zeros((2, 2, 4), np.float32)
            color[0, 0], color[0, 1] = (1, 0, 0, 1), (0, 1, 0, 1)  # uv (0,0) red, uv (1,0) green
            np.savez(root / "in.npz", positions=np.array([[0.01, 0, 0], [0.99, 0, 0], [5, 5, 5]]),
                     used=np.zeros((3, 2), int), samples=np.array([[0, 0, 0], [1, 0, 0]], float),
                     sample_uvs=np.array([[0, 0], [1, 0]], float), color=color, rough=np.zeros(0), reach=0.1)
            subprocess.run([sys.executable, str(ROOT / "processing/template_nearest_solve.py"),
                            str(root / "in.npz"), str(root / "out.npz")], check=True, capture_output=True)
            out = np.load(root / "out.npz")
            self.assertEqual(out["hit"].tolist(), [True, True, False])
            self.assertEqual(out["color"][0][:3].tolist(), [1, 0, 0])
            self.assertEqual(out["color"][1][:3].tolist(), [0, 1, 0])
            self.assertEqual(out["color"][2].tolist(), [0, 0, 0, 0])
