import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopforge.unity_tiles import create_tile_assets


class UnityTilesTests(unittest.TestCase):
    def test_unity_tile_builder_creates_scriptable_tiles_with_sprite_and_collider(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets/Tiles").mkdir(parents=True)
            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
            image = root / "Assets/Tiles/tile_000.png"
            image.write_bytes(b"png")
            output = root / "Assets/Tiles/Unity"

            def run(command, **kwargs):
                script = next((root / "Assets/Editor").glob("SlopForgeTileBuilder_*.cs"))
                code = script.read_text()
                self.assertIn("using UnityEngine.Tilemaps;", code)
                self.assertIn("tile.colliderType = Tile.ColliderType.Grid", code)
                self.assertIn("tile.sprite = sprite", code)
                (output / "tile_000.asset").write_text("tile")

            with patch("slopforge.unity_tiles.unity_cli", return_value="/unity"), \
                    patch("slopforge.unity_tiles.subprocess.run", side_effect=run):
                result = create_tile_assets(root, [image], output, collider="grid", pixels_per_unit=64)
            self.assertEqual(result, [(output / "tile_000.asset").resolve()])

    def test_unity_tile_builder_rejects_external_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
            external = root.parent / "external-tile.png"
            external.write_bytes(b"png")
            with self.assertRaisesRegex(ValueError, "inside the Unity project"):
                create_tile_assets(root, [external], root / "Assets/Tiles", collider="none", pixels_per_unit=100)
            external.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
