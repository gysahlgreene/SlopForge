import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
# Stand-in for rembg whose native teardown aborts at interpreter exit, as onnxruntime did in 2 of 64
# background-removal runs on macOS (SIGABRT, "recursive_mutex lock failed") after the outputs were written.
STUB = '''import atexit, os
from PIL import Image, ImageDraw
atexit.register(os.abort)
def remove(image):
    cutout = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(cutout).rectangle((8, 8, 40, 56), fill=(200, 60, 60, 255))
    return cutout
'''


class BackgroundRemovalExitTests(unittest.TestCase):
    def _run(self, temporary, *args):
        stub = Path(temporary) / "stub"
        (stub / "rembg").mkdir(parents=True, exist_ok=True)
        (stub / "rembg/__init__.py").write_text(STUB)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(stub), str(ROOT)]))
        return subprocess.run([sys.executable, *args], env=env, capture_output=True, text=True)

    def test_a_teardown_abort_after_the_outputs_are_written_is_not_a_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "concept.png"
            Image.new("RGB", (64, 64), "white").save(image)
            out = Path(temporary) / "out"
            conditioning = self._run(temporary, str(ROOT / "processing/prepare_3d_input.py"), "--input", str(image),
                                     "--cutout", str(out / "cutout.png"), "--output", str(out / "input.png"))
            views = self._run(temporary, str(ROOT / "processing/prepare_views.py"), "--view", f"front={image}",
                              "--view", f"back={image}", "--output-dir", str(out / "views"),
                              "--report", str(out / "views.json"))
            for result in (conditioning, views):
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((out / "input.png").is_file() and (out / "views/view_back.png").is_file())

    def test_real_errors_still_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self._run(temporary, str(ROOT / "processing/prepare_3d_input.py"), "--input", "missing.png",
                               "--cutout", "c.png", "--output", "o.png")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Input image missing", result.stderr)
