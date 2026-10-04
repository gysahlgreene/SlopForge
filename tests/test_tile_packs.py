import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from slopforge.cli import main, parse_args
from slopforge.initializer import init_project
from slopforge.manifest import load_manifest, save_manifest
from slopforge.recipes import load_recipe
from slopforge.taxonomy import load_taxonomy


class TilePackTests(unittest.TestCase):
    def test_starter_recipe_contains_coherent_terrain_categories(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)
            _, children = load_recipe(project, "starter_tileset_pack", load_taxonomy(project))
        self.assertEqual(len(children), 8)
        self.assertEqual({child["type"] for child in children}, {"tile_sheet"})
        self.assertIn("transitions", [child["id"] for child in children])

    def test_cli_packages_only_approved_tile_sheets_and_registers_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)
            source = project / "Assets/Art/Generated/Tilesets/Spritesheets/ground.png"
            source.parent.mkdir(parents=True)
            Image.new("RGBA", (4, 4), (40, 100, 60, 255)).save(source)
            manifest_path = project / "ai/assets/manifest.json"
            manifest = load_manifest(manifest_path)
            manifest["assets"]["tile_sheet:ground"] = {
                "id": "ground-id", "type": "tile_sheet", "name": "ground", "description": "Ground",
                "status": "ready", "candidates": {"selected": 1, "items": [{"number": 1, "approval": "approved"}]},
                "outputs": {"image": "Assets/Art/Generated/Tilesets/Spritesheets/ground.png"}, "artifacts": {},
            }
            save_manifest(manifest_path, manifest)
            args = ["--project", str(project), "tilepack", "ground", "--grid", "2", "2",
                    "--tile-size", "2", "2", "--transition-mask", "0", "--transition-mask", "1",
                    "--transition-mask", "2", "--transition-mask", "3"]
            self.assertEqual(parse_args(args).command, "tilepack")
            def unity_tiles(project_root, tile_paths, output_directory, **kwargs):
                output_directory.mkdir(parents=True, exist_ok=True)
                tiles = []
                for index, _ in enumerate(tile_paths):
                    tile = output_directory / f"tile_{index:03d}.asset"
                    tile.write_text("Unity Tile")
                    tiles.append(tile)
                return tiles
            with patch("slopforge.cli.create_tile_assets", side_effect=unity_tiles), patch("sys.stdout"):
                self.assertEqual(main(args + ["--unity-assets"]), 0)
            manifest = load_manifest(manifest_path)
            asset = manifest["assets"]["tile_sheet:ground"]
            self.assertEqual(asset["artifacts"]["tiles.000"]["type"], "image.tile")
            self.assertEqual(asset["artifacts"]["tiles.metadata"]["approval"]["status"], "approved")
            metadata = json.loads((project / asset["artifacts"]["tiles.metadata"]["path"]).read_text())
            self.assertIn("3", metadata["transition_rules"])
            self.assertTrue((project / asset["artifacts"]["tiles.atlas"]["path"]).is_file())
            self.assertEqual(asset["artifacts"]["tiles.unity_000"]["type"], "unity.tile")
            with patch("slopforge.cli.create_tile_assets") as create_tiles, patch("sys.stdout"):
                self.assertEqual(main(["--project", str(project), "tile-unity", "ground"]), 0)
            create_tiles.assert_not_called()


if __name__ == "__main__":
    unittest.main()
