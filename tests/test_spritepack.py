import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from slopforge.spritepack import package_sprite_sheet
from slopforge.cli import main, parse_args
from slopforge.initializer import init_project
from slopforge.manifest import load_manifest, save_manifest


class SpritePackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sheet = self.root / "sheet.png"
        image = Image.new("RGBA", (4, 2), (0, 0, 0, 0))
        image.putpixel((0, 0), (255, 0, 0, 255))
        image.putpixel((2, 0), (0, 255, 0, 255))
        image.putpixel((0, 1), (0, 0, 255, 255))
        image.putpixel((2, 1), (255, 255, 0, 255))
        image.save(self.sheet)

    def tearDown(self):
        self.temp.cleanup()

    def test_grid_extraction_keeps_consistent_rgba_frames_and_unity_timing(self):
        result = package_sprite_sheet(self.sheet, self.root / "out", "walk", columns=2, rows=2,
                                      fps=8, pivot=(0.5, 0.0), loop=True)
        self.assertEqual(result["frame_size"], [2, 1])
        self.assertEqual(result["frame_count"], 4)
        self.assertEqual(result["frame_duration_seconds"], 0.125)
        self.assertEqual(result["pivot"], {"x": 0.5, "y": 0.0})
        self.assertTrue(result["loop"])
        self.assertEqual([Image.open(path).getpixel((0, 0)) for path in result["frame_paths"]],
                         [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)])
        self.assertEqual(json.loads(Path(result["metadata"]).read_text())["columns"], 2)

    def test_grid_must_divide_sheet_evenly_and_refuses_overwrite(self):
        with self.assertRaisesRegex(ValueError, "divisible"):
            package_sprite_sheet(self.sheet, self.root / "invalid", "walk", columns=3, rows=1, fps=8)
        package_sprite_sheet(self.sheet, self.root / "out", "walk", columns=2, rows=2, fps=8)
        with self.assertRaisesRegex(FileExistsError, "already exists"):
            package_sprite_sheet(self.sheet, self.root / "out", "walk", columns=2, rows=2, fps=8)

    def test_cli_packages_only_approved_character_sheet_and_registers_outputs(self):
        project = self.root / "game"
        (project / "Assets").mkdir(parents=True)
        init_project(project)
        source = project / "Assets/Art/Generated/Characters/Spritesheets/alice_walk.png"
        source.parent.mkdir(parents=True, exist_ok=True)
        self.sheet.replace(source)
        manifest_path = project / "ai/assets/manifest.json"
        manifest = load_manifest(manifest_path)
        manifest["assets"]["sprite_sheet:alice_walk"] = {
            "id": "alice-walk-id", "type": "sprite_sheet", "name": "alice_walk", "description": "Walk cycle",
            "status": "ready", "candidates": {"selected": 1, "items": [{"number": 1, "approval": "approved"}]},
            "outputs": {"image": "Assets/Art/Generated/Characters/Spritesheets/alice_walk.png"},
            "artifacts": {}, "generator": {"workflow": "character-sheet.json", "seed": 43},
        }
        save_manifest(manifest_path, manifest)
        parsed = parse_args(["--project", str(project), "spritepack", "alice_walk", "--animation", "walk",
                             "--grid", "2", "2", "--fps", "8"])
        self.assertEqual(parsed.command, "spritepack")
        with patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(main(["--project", str(project), "spritepack", "alice_walk", "--animation", "walk",
                                   "--grid", "2", "2", "--fps", "8"]), 0)
        manifest = load_manifest(manifest_path)
        asset = manifest["assets"]["sprite_sheet:alice_walk"]
        self.assertIn("sprites.walk.atlas", asset["artifacts"])
        self.assertEqual(asset["artifacts"]["sprites.walk.atlas"]["approval"]["status"], "approved")
        self.assertTrue((project / asset["artifacts"]["sprites.walk.atlas"]["path"]).is_file())
        self.assertTrue((project / asset["artifacts"]["sprites.walk.metadata"]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
