import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from slopforge.failures import StageFailure
from slopforge.kit_material import kit_swatch, make_seamless, match_roughness

ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"


class KitMaterialTests(unittest.TestCase):
    def test_seamless_swatch_wraps_like_neighbouring_texels(self):
        with tempfile.TemporaryDirectory() as temporary:
            rng = np.random.default_rng(3)
            # Noise on a left-to-right ramp: its left and right edges differ a lot.
            ramp = np.linspace(40, 220, 128)[None, :, None]
            noise = rng.normal(0, 6, (128, 128, 1))
            Image.fromarray(np.clip(ramp + noise, 0, 255).repeat(3, 2).astype(np.uint8)).save(Path(temporary) / "s.png")
            make_seamless(Path(temporary) / "s.png", Path(temporary) / "t.png")
            tile = np.asarray(Image.open(Path(temporary) / "t.png")).astype(float)
        wrap = np.abs(tile[:, 0] - tile[:, -1]).mean()
        neighbour = np.abs(tile[:, 1] - tile[:, 0]).mean()
        self.assertLess(wrap, 2 * neighbour + 1)

    def test_kit_swatch_needs_an_approved_texture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = {"name": "ruin_wall", "kit_material": {"asset_key": "texture:ruin_stone", "tile_size": 2}}
            self.assertIsNone(kit_swatch(root, {"assets": {}}, {"name": "crate"}))
            texture = {"name": "ruin_stone", "status": "candidate", "outputs": {}}
            with self.assertRaisesRegex(StageFailure, "approve ruin_stone"):
                kit_swatch(root, {"assets": {"texture:ruin_stone": texture}}, asset)
            (root / "stone.png").write_bytes(b"png")
            texture.update(status="ready", outputs={"image": "stone.png"})
            self.assertEqual(kit_swatch(root, {"assets": {"texture:ruin_stone": texture}}, asset),
                             (root / "stone.png", 2.0))

    def test_module_roughness_moves_to_the_kits_finish_and_keeps_its_variation(self):
        # M2-v1 K1: a flagstone floor decoded at 0.22 beside walls at 0.67 read as a glossy, sky-blue floor.
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "roughness.png"
            glossy = np.zeros((64, 64), np.uint8)  # black UV padding on the left
            glossy[:, 16:40], glossy[:, 40:] = 46, 66  # two islands around 0.22
            Image.fromarray(glossy).convert("RGB").save(path)
            match_roughness(path, 0.75)
            result = np.asarray(Image.open(path)).astype(float)[..., 0] / 255
        islands = result[:, 16:]
        self.assertAlmostEqual(islands.mean(), 0.75, delta=0.02)
        self.assertGreater(result[:, 40:].mean(), result[:, 16:40].mean() + 0.1)  # its own rougher island stays rougher


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderKitMaterialTests(unittest.TestCase):
    def test_module_takes_the_swatch_colour_and_keeps_its_own_brightness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb = root / "module.glb"
            subprocess.run([BLENDER, "--background", "--python-expr",
                            "import bpy, sys; bpy.ops.wm.read_factory_settings(use_empty=True); "
                            "bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.5)); "
                            "bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.uv.smart_project(); "
                            "bpy.ops.object.mode_set(mode='OBJECT'); "
                            f"bpy.ops.export_scene.gltf(filepath={str(glb)!r}, export_format='GLB')"],
                           check=True, capture_output=True)
            maps = [root / f"{name}.png" for name in ("basecolor", "normal", "roughness", "metallic", "emission")]
            # The module's own colour: blue, its left half twice as bright as its right.
            own = np.zeros((64, 64, 3), np.uint8)
            own[:, :32], own[:, 32:] = (40, 60, 200), (20, 30, 100)
            Image.fromarray(own).save(maps[0])
            for path, value in zip(maps[1:], ((128, 128, 255), (200,) * 3, (0,) * 3, (0,) * 3)):
                Image.new("RGB", (64, 64), value).save(path)
            swatch = root / "swatch.png"
            Image.new("RGB", (32, 32), (200, 60, 50)).save(swatch)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/prepare_model.py"), "--", str(glb), str(root / "module.fbx"),
                            str(root / "module.blend"), *map(str, maps), "--face-budget", "1000", "--preserve-uvs",
                            "--target-size", "1,1,1", "--kit-material", str(swatch), "--kit-tile-size", "2"],
                           check=True, capture_output=True, text=True)
            baked = np.asarray(Image.open(maps[0]).convert("RGB")).astype(float)
        covered = baked.sum(2) > 30
        red, blue = baked[..., 0][covered].mean(), baked[..., 2][covered].mean()
        self.assertGreater(red, 2 * blue)  # the swatch's colour replaced the module's blue
        self.assertFalse((baked.max(2) == 0).any())  # no black outside the islands to bleed into Unity's mips
        brightness = baked.mean(2)
        left, right = brightness[:, :32][covered[:, :32]].mean(), brightness[:, 32:][covered[:, 32:]].mean()
        self.assertGreater(left, 1.2 * right)  # the module's own brighter half stays brighter


if __name__ == "__main__":
    unittest.main()
