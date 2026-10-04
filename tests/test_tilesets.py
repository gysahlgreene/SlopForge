import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from slopforge.tileset import package_tileset


class TilesetTests(unittest.TestCase):
    def test_slices_rgba_tiles_with_margin_padding_and_edge_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sheet.png"
            sheet = Image.new("RGBA", (7, 7), (0, 0, 0, 0))
            sheet.paste((255, 0, 0, 255), (1, 1, 3, 3))
            sheet.paste((255, 0, 0, 255), (4, 1, 6, 3))
            sheet.paste((0, 255, 0, 255), (1, 4, 3, 6))
            sheet.paste((0, 255, 0, 255), (4, 4, 6, 6))
            sheet.save(source)
            result = package_tileset(source, root / "tiles", "floor", columns=2, rows=2,
                                     tile_size=(2, 2), margin=1, padding=1, layout="orthogonal",
                                     transition_masks=[0, 1, 2, 3])
            self.assertEqual(result["tile_count"], 4)
            self.assertEqual(Image.open(result["tile_paths"][0]).getpixel((0, 0)), (255, 0, 0, 255))
            self.assertEqual(Image.open(result["tile_paths"][2]).getpixel((0, 0)), (0, 255, 0, 255))
            metadata = json.loads(Path(result["metadata"]).read_text())
            self.assertEqual(metadata["tile_size"], [2, 2])
            self.assertEqual(metadata["margin"], 1)
            self.assertEqual(metadata["padding"], 1)
            self.assertEqual(metadata["layout"], "orthogonal")
            self.assertEqual(metadata["transition_rules"]["3"], "floor_003")
            self.assertEqual(metadata["tiles"][0]["alpha_coverage"], 1.0)
            self.assertEqual(metadata["edges"][0]["mean_absolute_difference"], 0.0)
            self.assertEqual(Image.open(result["atlas"]).size, (4, 4))

    def test_rejects_bad_dimensions_layout_and_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sheet.png"
            Image.new("RGBA", (8, 8)).save(source)
            with self.assertRaisesRegex(ValueError, "dimensions"):
                package_tileset(source, root / "bad", "floor", columns=2, rows=2,
                                tile_size=(3, 3), margin=0, padding=0, layout="orthogonal")
            with self.assertRaisesRegex(ValueError, "layout"):
                package_tileset(source, root / "bad", "floor", columns=2, rows=2,
                                tile_size=(4, 4), margin=0, padding=0, layout="hex")
            with self.assertRaisesRegex(ValueError, "Transition masks"):
                package_tileset(source, root / "bad", "floor", columns=2, rows=2,
                                tile_size=(4, 4), margin=0, padding=0, layout="orthogonal",
                                transition_masks=[0, 0, 2, 3])
            package_tileset(source, root / "tiles", "floor", columns=2, rows=2,
                            tile_size=(4, 4), margin=0, padding=0, layout="isometric")
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                package_tileset(source, root / "tiles", "floor", columns=2, rows=2,
                                tile_size=(4, 4), margin=0, padding=0, layout="isometric")


if __name__ == "__main__":
    unittest.main()
