import contextlib
import io
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
from slopforge.ui import make_sprite_import_metadata


class UIPackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "game"
        (self.project / "Assets").mkdir(parents=True)
        init_project(self.project)

    def tearDown(self):
        self.temp.cleanup()

    def test_ui_recipe_contains_coherent_components_states_and_no_functional_copy(self):
        types = load_taxonomy(self.project)
        definition, children = load_recipe(self.project, "starter_ui_pack", types)
        self.assertEqual(definition["id"], "starter_ui_pack")
        ids = {child["id"] for child in children}
        self.assertTrue({"panel_landscape", "panel_portrait", "button_normal", "button_hover", "button_pressed", "button_disabled",
                         "tab_selected", "inventory_slot_selected", "health_bar", "tooltip", "portrait_frame"} <= ids)
        for child in children:
            prompt = child.get("generation_prompt", "").lower()
            self.assertIn("no text", prompt)
            self.assertNotIn("write ", prompt)

    def test_sprite_import_metadata_records_nine_slice_and_unity_defaults(self):
        metadata = make_sprite_import_metadata("Assets/UI/panel.png", (128, 64),
                                               border=(12, 8, 12, 8), pivot=(0.5, 0.5),
                                               pixels_per_unit=100)
        self.assertEqual(metadata["sprite_mode"], "single")
        self.assertEqual(metadata["border"], {"left": 12, "bottom": 8, "right": 12, "top": 8})
        self.assertEqual(metadata["pixels_per_unit"], 100)
        with self.assertRaisesRegex(ValueError, "exceed sprite dimensions"):
            make_sprite_import_metadata("panel.png", (20, 16), border=(12, 8, 12, 8))

    def test_cli_writes_import_metadata_as_typed_output_of_approved_ui_asset(self):
        image_path = self.project / "Assets/Art/Generated/UI/panel.png"
        Image.new("RGBA", (64, 64), "gray").save(image_path)
        manifest_path = self.project / "ai/assets/manifest.json"
        manifest = load_manifest(manifest_path)
        manifest["assets"]["ui:panel"] = {
            "id": "panel-id", "type": "ui", "name": "panel", "description": "UI panel", "status": "ready",
            "candidates": {"selected": 1, "items": [{"number": 1, "approval": "approved"}]},
            "outputs": {"image": "Assets/Art/Generated/UI/panel.png"}, "artifacts": {},
        }
        save_manifest(manifest_path, manifest)
        args = ["--project", str(self.project), "ui-meta", "panel", "--border", "8", "8", "8", "8"]
        self.assertEqual(parse_args(args).command, "ui-meta")
        with patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(main(args), 0)
        manifest = load_manifest(manifest_path)
        asset = manifest["assets"]["ui:panel"]
        artifact = asset["artifacts"]["unity.sprite_settings"]
        self.assertEqual(artifact["approval"]["status"], "approved")
        output_path = self.project / artifact["path"]
        self.assertEqual(json.loads(output_path.read_text())["border"]["left"], 8)


if __name__ == "__main__":
    unittest.main()
