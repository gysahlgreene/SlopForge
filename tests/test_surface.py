import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from slopforge import surface
from slopforge.backends.comfyui import ComfyUIError

ROOT = Path(__file__).resolve().parents[1]


CLEARED = {"output_rights": [{"source": "z_image_turbo_bf16.safetensors", "status": "cleared", "terms": "Apache-2.0",
                               "terms_version": "model card", "read_on": "2026-10-27"}]}


class SurfaceTests(unittest.TestCase):
    def test_cutout_crops_to_the_plant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, out = root / "tuft.png", root / "cut.png"
            Image.new("RGB", (100, 80), "white").save(source)

            def fake_rembg(command, **_):  # stands in for prepare_3d_input.py's background removal
                cut = Path(command[command.index("--cutout") + 1])
                rgba = np.zeros((80, 100, 4), np.uint8)
                rgba[20:50, 30:40] = (40, 120, 30, 255)
                Image.fromarray(rgba).save(cut)
            with patch("slopforge.surface.subprocess.run", side_effect=fake_rembg), \
                    patch("slopforge.surface.python_executable", return_value="python3"):
                size = surface.make_cutout(root, {}, source, out)
            self.assertEqual(size, (10, 30))
            self.assertEqual(Image.open(out).mode, "RGBA")

    def test_tiling_material_tiles_and_records_its_steps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "grass.png"
            rng = np.random.default_rng(1)
            # Strong left-to-right and top-to-bottom ramps: the raw image does not tile at all.
            ramp = np.linspace(30, 220, 256)
            raw = (ramp[None, :, None] * 0.5 + ramp[:, None, None] * 0.5 + rng.normal(0, 8, (256, 256, 3)))
            Image.fromarray(np.clip(raw, 0, 255).astype(np.uint8)).save(source)
            client = Mock()
            client.upload_input.side_effect = lambda path, folder: {"name": Path(path).name, "subfolder": folder}
            client.queue_workflow.side_effect = ["seam", "up"]
            client.list_outputs.return_value = [{"filename": "out.png", "subfolder": "", "type": "output"}]
            uploads = []

            def download(output, destination):  # the image model "repaints" by returning its input; ESRGAN by 4x
                image = Image.open(uploads[-1]).convert("RGB")
                if len(uploads) == 2:
                    image = image.resize((image.width * 4, image.height * 4))
                image.save(destination)
            client.upload_input.side_effect = lambda path, folder: (uploads.append(Path(path)) or
                                                                    {"name": Path(path).name, "subfolder": folder})
            client.download_output.side_effect = download
            with patch("slopforge.surface.ComfyUIClient", return_value=client), \
                    patch("slopforge.surface.comfy_url", return_value="http://remote:8188"):
                paths, provenance = surface.make_tiling_material(root, {}, source, "meadow grass", root / "grass",
                                                                 seams="repaint")
            self.assertEqual(Image.open(paths["basecolor"]).size, (2048, 2048))
            for name in ("basecolor", "normal", "roughness", "height"):
                tile = np.asarray(Image.open(paths[name])).astype(float)
                wrap = np.abs(tile[:, 0] - tile[:, -1]).mean()
                neighbour = np.abs(tile[:, 1] - tile[:, 0]).mean()
                self.assertLess(wrap, 2 * neighbour + 2, name)  # the edges meet like neighbouring texels
            self.assertEqual([provenance["seamless"]["workflow"], provenance["upscale"]["workflow"]],
                             ["image_seamless_inpaint_api.json", "image_upscale_esrgan_api.json"])
            graph = client.queue_workflow.call_args_list[0].args[0]
            self.assertEqual(next(n for n in graph.values() if n["class_type"] == "CLIPTextEncode")["inputs"]["text"],
                             "meadow grass")

    def test_approval_runs_the_declared_processing(self):
        from slopforge.pipelines import image
        manifest = {"assets": {"foliage:tuft": {"outputs": {"image": "Foliage/tuft.png"}, "description": "tuft",
                                                "candidates": {"items": [{"number": 1, "generator": CLEARED}]}}}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Foliage").mkdir()
            Image.new("RGBA", (4, 4)).save(root / "Foliage/tuft.png")
            with patch("slopforge.pipelines.image.approve_image_candidate", return_value={"status": "passed"}), \
                    patch("slopforge.pipelines.image.make_cutout", return_value=(3, 4)) as cutout:
                image.approve(root, {}, {"name": "foliage", "processing": "cutout"}, manifest, "foliage:tuft", 1)
            cutout.assert_called_once()
            self.assertEqual(manifest["assets"]["foliage:tuft"]["processing"]["size"], [3, 4])
            with patch("slopforge.pipelines.image.approve_image_candidate", return_value={"status": "passed"}), \
                    self.assertRaisesRegex(ValueError, "unknown processing"):
                image.approve(root, {}, {"name": "x", "processing": "sharpen"}, manifest, "foliage:tuft", 1)

    def test_a_surface_job_that_saves_nothing_names_its_workflow(self):
        client = Mock()
        client.upload_input.return_value = {"name": "in.png"}
        client.list_outputs.return_value = [{"filename": "preview.png", "subfolder": "", "type": "temp"}]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Image.new("RGB", (4, 4)).save(root / "in.png")
            with self.assertRaisesRegex(ComfyUIError, "image_upscale_esrgan_api.json finished without saving"):
                surface._run(client, ROOT, "image_upscale_esrgan_api.json", root / "in.png", "upscale_source", root / "out.png")
        client.download_output.assert_not_called()

    def test_failed_processing_restores_the_published_image_and_its_record(self):
        from slopforge.pipelines import image
        record = {"outputs": {"image": "Foliage/tuft.png"}, "description": "tuft", "status": "ready",
                  "processing": {"kind": "cutout", "sha256": "old"},
                  "candidates": {"items": [{"number": 2, "generator": CLEARED}]}}
        manifest = {"assets": {"foliage:tuft": dict(record)}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Foliage").mkdir()
            Image.new("RGBA", (4, 4), (10, 200, 10, 255)).save(root / "Foliage/tuft.png")  # the approved cut-out

            def approve_new(*_args, **_kwargs):  # publishes candidate 2's uncut image, as the real approval does
                Image.new("RGB", (4, 4), (255, 255, 255)).save(root / "Foliage/tuft.png")
                manifest["assets"]["foliage:tuft"]["candidates"] = {"selected": 2,
                                                                    "items": [{"number": 2, "generator": CLEARED}]}
                return {"status": "passed"}
            with patch("slopforge.pipelines.image.approve_image_candidate", side_effect=approve_new), \
                    patch("slopforge.pipelines.image.make_cutout", side_effect=RuntimeError("rembg failed")), \
                    self.assertRaisesRegex(RuntimeError, "rembg"):
                image.approve(root, {}, {"name": "foliage", "processing": "cutout"}, manifest, "foliage:tuft", 2, True)
            self.assertEqual(Image.open(root / "Foliage/tuft.png").getpixel((0, 0)), (10, 200, 10, 255))
            self.assertEqual(manifest["assets"]["foliage:tuft"], record)

    def test_cut_seams_tile_and_keep_the_source_pixels(self):
        rng = np.random.default_rng(4)
        ramp = np.linspace(30, 220, 128)
        image = ramp[None, :, None] * 0.5 + ramp[:, None, None] * 0.5 + rng.normal(0, 6, (128, 128, 3))
        tile = surface.cut_seams(image)
        for edge, inner in ((np.abs(tile[:, 0] - tile[:, -1]), np.abs(tile[:, 1] - tile[:, 0])),
                            (np.abs(tile[0] - tile[-1]), np.abs(tile[1] - tile[0]))):
            self.assertLess(edge.mean(), 2 * inner.mean() + 1)  # both ways round
            self.assertLess(edge.max(), 3 * inner.max())  # and nowhere along an edge
        # away from the feathered joins (four, about 8 px wide, a quarter of this small tile), each pixel is one of
        # the source's own, rolled: nothing is invented
        sources = [np.roll(np.roll(image, dy, 0), dx, 1) for dy in (0, 64) for dx in (0, 64)]
        own = np.any([np.isclose(tile, source).all(-1) for source in sources], axis=0)
        self.assertGreater(own.mean(), 0.7)
