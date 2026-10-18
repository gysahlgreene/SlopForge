import json
import runpy
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from slopforge.config import load_project
from slopforge.initializer import init_project
from slopforge.manifest import save_manifest
from slopforge.pipelines.model import material_candidate_paths

ROOT = Path(__file__).resolve().parents[1]


class MaterialShowcaseTests(unittest.TestCase):
    def test_strip_and_provenance_cover_concept_maps_and_renders(self):
        build = runpy.run_path(str(ROOT / "scripts/material_showcase.py"))["build"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            init_project(root)
            config = load_project(root)
            paths = material_candidate_paths(root, config, "jug", 1)
            for key in ("basecolor", "normal", "roughness", "metallic", "emission", "preview_front", "preview_three_quarter"):
                paths[key].parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (64, 64), (20, 40, 160)).save(paths[key])
            (root / "concept.png").parent.mkdir(exist_ok=True)
            Image.new("RGB", (64, 64), "white").save(root / "concept.png")
            asset = {"name": "jug", "type": "prop", "materials": [{"region": "jug", "class": "nonmetal", "description": ""}],
                     "candidates": {"selected": 2, "items": [{"number": 2, "path": "concept.png"}]},
                     "material_candidates": {"items": [{"number": 1, "normal_source": "workflow",
                                                        "emission_source": "none",
                                                        "validation": {"status": "passed", "warnings": []}}]}}
            save_manifest(root / config["asset_pipeline"]["manifest"], {"schema_version": 4, "assets": {"prop:jug": asset}})
            out = root / "showcase/jug.png"
            summary = build(root, "jug", 1, out, size=32)
            with Image.open(out) as strip:
                self.assertEqual(strip.size, (32 * 8, 32 + 28))
            saved = json.loads(out.with_suffix(".json").read_text())
            self.assertEqual(saved, summary)
            self.assertEqual(saved["normal_source"], "workflow")
            self.assertEqual(saved["concept_candidate"], 2)
            self.assertEqual(set(saved["sha256"]), {"concept", "basecolor", "normal", "roughness", "metallic",
                                                    "emission", "preview_front", "preview_three_quarter"})


class TurntableGifTests(unittest.TestCase):
    def test_frames_become_a_looping_gif(self):
        build = runpy.run_path(str(ROOT / "scripts/turntable_gif.py"))["build"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, color in enumerate(((200, 40, 40), (40, 200, 40), (40, 40, 200))):
                Image.new("RGB", (32, 32), color).save(root / f"frame_{index:03d}.png")
            self.assertEqual(build(root, root / "spin.gif", size=16), 3)
            with Image.open(root / "spin.gif") as gif:
                self.assertEqual((gif.n_frames, gif.size, gif.info.get("loop")), (3, (16, 16), 0))
