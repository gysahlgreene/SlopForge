import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopforge.unity_ui import apply_sprite_settings


class UnityUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "Assets/UI").mkdir(parents=True)
        (self.root / "ProjectSettings").mkdir()
        (self.root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
        self.image = self.root / "Assets/UI/panel.png"
        self.image.write_bytes(b"png")
        self.metadata = self.root / "Assets/UI/panel_sprite_settings.json"
        self.metadata.write_text('{}\n')

    def tearDown(self):
        self.temp.cleanup()

    def test_unity_apply_sets_sprite_settings_and_optional_sliced_image_prefab(self):
        captured = {}

        def run(command, **kwargs):
            class_name = command[-1].split(".")[0]
            script = self.root / "Assets/Editor" / f"{class_name}.cs"
            captured["script"] = script.read_text()
            captured["command"] = command

        with patch("slopforge.unity_ui.unity_cli", return_value="/unity"), \
                patch("slopforge.unity_ui.subprocess.run", side_effect=run):
            apply_sprite_settings(self.root, self.image, self.metadata, border=(8, 9, 10, 11),
                                  pivot=(0.5, 0.5), pixels_per_unit=100, prefab=True)
        code = captured["script"]
        self.assertIn("TextureImporterType.Sprite", code)
        self.assertIn("ReadTextureSettings(settings)", code)
        self.assertIn("settings.spriteMeshType = SpriteMeshType.FullRect", code)
        self.assertIn("new Vector4(8, 9, 10, 11)", code)
        self.assertIn("PrefabUtility.SaveAsPrefabAsset", code)
        self.assertIn("Image, UnityEngine.UI", code)
        self.assertIn("panel.prefab", code)

    def test_unity_apply_rejects_paths_outside_the_project(self):
        with self.assertRaisesRegex(ValueError, "inside the Unity project"):
            apply_sprite_settings(self.root, self.root.parent / "outside.png", self.metadata,
                                  border=(0, 0, 0, 0), pivot=(0.5, 0.5), pixels_per_unit=100)


if __name__ == "__main__":
    unittest.main()
