import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from slopforge.vegetation import build_leaf_atlas, is_current, make_vegetation

ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"


def _cutout(path, colour):
    rgba = np.zeros((60, 40, 4), np.uint8)
    rgba[10:50, 10:30] = (*colour, 255)
    Image.fromarray(rgba).save(path)


class VegetationTests(unittest.TestCase):
    def test_leaf_atlas_fills_four_tinted_quarters(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _cutout(root / "a.png", (60, 140, 40))
            build_leaf_atlas([root / "a.png"], root / "atlas.png", size=256)
            atlas = np.asarray(Image.open(root / "atlas.png")).astype(float)
        quarters = [atlas[y:y + 128, x:x + 128] for y in (0, 128) for x in (0, 128)]
        self.assertTrue(all(q[..., 3].max() == 255 for q in quarters))  # one cut-out repeats into every quarter
        greens = [q[..., 1][q[..., 3] > 0].mean() for q in quarters]
        self.assertGreater(max(greens) - min(greens), 3)  # with different tints

    def _manifest(self, root):
        Image.new("RGB", (8, 8), (90, 80, 60)).save(root / "bark.png")
        Image.new("RGB", (8, 8), (128, 128, 255)).save(root / "bark_n.png")
        _cutout(root / "sprig.png", (60, 140, 40))
        return {"assets": {
            "tiling_material:oak_bark": {"name": "oak_bark", "status": "ready",
                                         "outputs": {"tiling_basecolor": "bark.png", "tiling_normal": "bark_n.png"}},
            "foliage:oak_sprig": {"name": "oak_sprig", "status": "ready", "outputs": {"image": "sprig.png"}}}}

    def test_tree_is_built_from_approved_bark_and_foliage_and_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._manifest(root)
            config = {"asset_pipeline": {"output_root": "Assets/Art/Generated"}}

            def fake_blender(command, **_):
                report = Path(command[command.index("--") + 2])
                report.write_text(json.dumps({"species": "oak", "faces": 900, "leaf_cards": 400, "dimensions": [5, 6, 9]}))
            with patch("slopforge.vegetation.subprocess.run", side_effect=fake_blender), \
                    patch("slopforge.vegetation.blender_executable", return_value="blender"):
                record = make_vegetation(root, config, manifest, "oak_a", "oak", 9.0, 11, "oak_bark", ["oak_sprig"])
            self.assertEqual(manifest["assets"]["vegetation:oak_a"], record)
            self.assertEqual(record["outputs"]["fbx"], "Assets/Art/Generated/Vegetation/oak_a/oak_a.fbx")
            self.assertTrue((root / record["outputs"]["leaves"]).is_file())
            self.assertEqual(record["generator"]["seed"], 11)
            self.assertEqual(len(record["sources"]["bark"]["sha256"]), 64)
            manifest["assets"]["foliage:oak_sprig"]["status"] = "candidate"
            with self.assertRaisesRegex(ValueError, "not approved"):
                make_vegetation(root, config, manifest, "oak_b", "oak", 9.0, 11, "oak_bark", ["oak_sprig"])
            with self.assertRaisesRegex(ValueError, "Species"):
                make_vegetation(root, config, manifest, "palm", "palm", 9.0, 11, "oak_bark", ["oak_sprig"])
            with self.assertRaisesRegex(ValueError, "Asset name"):  # would write outside the output folder
                make_vegetation(root, config, manifest, "../../x", "oak", 9.0, 11, "oak_bark", ["oak_sprig"])

    def test_a_built_plant_is_reused_only_while_its_spec_and_sources_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._manifest(root)
            config = {"asset_pipeline": {"output_root": "Assets/Art/Generated"}}

            def fake_blender(command, **_):
                Path(command[command.index("--") + 1]).write_bytes(b"fbx")
                Path(command[command.index("--") + 2]).write_text(json.dumps({"species": "oak"}))
            with patch("slopforge.vegetation.subprocess.run", side_effect=fake_blender), \
                    patch("slopforge.vegetation.blender_executable", return_value="blender"):
                record = make_vegetation(root, config, manifest, "oak_a", "oak", 9.0, 11, "oak_bark", ["oak_sprig"])
            spec = ("oak", 9.0, 11, "oak_bark", ["oak_sprig"])
            self.assertTrue(is_current(root, manifest, record, *spec))
            # 2026-10-23 audit: only the seed was compared, so a new height or species kept the old tree.
            self.assertFalse(is_current(root, manifest, record, "oak", 12.0, 11, "oak_bark", ["oak_sprig"]))
            self.assertFalse(is_current(root, manifest, record, "pine", 9.0, 11, "oak_bark", ["oak_sprig"]))
            _cutout(root / "sprig.png", (150, 60, 40))  # the foliage was re-approved with a new image
            self.assertFalse(is_current(root, manifest, record, *spec))
            _cutout(root / "sprig.png", (60, 140, 40))
            self.assertTrue(is_current(root, manifest, record, *spec))
            (root / record["outputs"]["fbx"]).unlink()
            self.assertFalse(is_current(root, manifest, record, *spec))


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderVegetationTests(unittest.TestCase):
    def test_each_species_builds_at_its_height_with_bark_and_leaf_cards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for species, height in (("oak", 8.0), ("birch", 10.0), ("pine", 9.0), ("shrub", 1.5)):
                with self.subTest(species=species):
                    fbx, report = root / f"{species}.fbx", root / f"{species}.json"
                    subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                    str(ROOT / "blender/vegetation.py"), "--", str(fbx), str(report), species,
                                    str(height), "3"], check=True, capture_output=True, text=True)
                    measured = json.loads(report.read_text())
                    self.assertTrue(fbx.is_file())
                    self.assertGreater(measured["leaf_cards"], 100)
                    self.assertLess(measured["faces"], 8000)  # card trees stay light
                    self.assertAlmostEqual(measured["dimensions"][2], height, delta=0.01)  # exactly the requested height
