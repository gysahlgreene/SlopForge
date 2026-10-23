import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from slopforge.failures import StageFailure
from slopforge.kit_material import kit_texture, match_hue, match_roughness
from slopforge.validation import _lab

ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"


class KitMaterialTests(unittest.TestCase):
    def test_kit_texture_needs_an_approved_texture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = {"name": "ruin_wall", "kit_material": {"asset_key": "texture:ruin_stone"}}
            self.assertIsNone(kit_texture(root, {"assets": {}}, {"name": "crate"}))
            texture = {"name": "ruin_stone", "status": "candidate", "outputs": {}}
            with self.assertRaisesRegex(StageFailure, "approve ruin_stone"):
                kit_texture(root, {"assets": {"texture:ruin_stone": texture}}, asset)
            (root / "stone.png").write_bytes(b"png")
            texture.update(status="ready", outputs={"image": "stone.png"})
            self.assertEqual(kit_texture(root, {"assets": {"texture:ruin_stone": texture}}, asset), root / "stone.png")

    def test_module_roughness_moves_to_the_kits_finish_and_keeps_its_variation(self):
        # M2-v1 K1: a flagstone floor decoded at 0.22 beside walls at 0.67 read as a glossy, sky-blue floor.
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "roughness.png"
            glossy = np.zeros((64, 64), np.uint8)  # black UV padding on the left
            glossy[:, 16:40], glossy[:, 40:] = 46, 66  # two islands around 0.22
            Image.fromarray(glossy).convert("RGB").save(path)
            match_roughness(path, 0.75)
            result = np.asarray(Image.open(path)).astype(float)[..., 0] / 255
        self.assertAlmostEqual(result.mean(), 0.75, delta=0.01)
        self.assertAlmostEqual(result[:, :16].min(), 0.75, delta=0.01)  # padding, not glossy black
        self.assertGreater(result[:, 40:].mean(), result[:, 16:40].mean() + 0.1)  # its own rougher island stays rougher

    def test_module_takes_the_kits_tint_and_keeps_its_own_lightness_and_variation(self):
        # Owner's choice, 2026-10-23: own generated colours with the average tint matched, not a baked swatch.
        with tempfile.TemporaryDirectory() as temporary:
            module, kit = Path(temporary) / "module.png", Path(temporary) / "kit.png"
            sandy = np.zeros((64, 64, 3), np.uint8)  # black UV padding on the left
            sandy[:, 16:40], sandy[:, 40:] = (150, 130, 100), (110, 95, 70)  # two warm islands, one darker
            Image.fromarray(sandy).save(module)
            Image.new("RGB", (32, 32), (120, 122, 126)).save(kit)  # a cool neutral grey stone
            before = _lab(np.asarray(sandy)[:, 16:].reshape(-1, 3).astype(float))
            match_hue(module, kit)
            after_rgb = np.asarray(Image.open(module)).astype(float)
        after = _lab(after_rgb[:, 16:].reshape(-1, 3))
        target = _lab(np.array([[120.0, 122.0, 126.0]]))[0]
        self.assertTrue(np.allclose(after.mean(0)[1:], target[1:], atol=1.0))  # the kit's tint
        self.assertAlmostEqual(after[:, 0].mean(), before[:, 0].mean(), delta=1.0)  # its own lightness
        self.assertGreater(after_rgb[:, 16:40].mean(), after_rgb[:, 40:].mean() + 20)  # its lighter island stays lighter
        self.assertEqual(after_rgb[:, :16].max(), 0)  # padding untouched
