import tempfile
import unittest
from pathlib import Path

from slopforge.config import load_project
from slopforge.initializer import init_project
from slopforge.pipelines.model import material_candidate_paths, model_paths
from slopforge.recipes import load_recipe
from slopforge.style import build_prompt, load_style
from slopforge.taxonomy import load_taxonomy


class CharacterRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "game"
        (self.root / "Assets").mkdir(parents=True)
        init_project(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_character_model_is_a_typed_asset_and_recipe_child(self):
        types = load_taxonomy(self.root)
        definition, children = load_recipe(self.root, "character_3d_pack", types)
        self.assertEqual(types["character"]["pipeline"], "model")
        self.assertEqual(types["character"]["face_budget"], "character_faces")
        self.assertEqual([child["id"] for child in children], ["character"])
        self.assertEqual(children[0]["type"], "character")
        self.assertIsNone(children[0].get("generation_prompt"))
        config = load_project(self.root)
        prompt = build_prompt(load_style(self.root, config), types["character"],
                              "Lunar scout in navy and white EVA armor")
        self.assertIn("neutral A-pose", prompt)
        self.assertIn("Lunar scout in navy and white EVA armor", prompt)

    def test_character_rigging_provider_has_an_explicit_default(self):
        config = load_project(self.root)
        self.assertEqual(config["asset_pipeline"]["character_rigging_provider"], "blender_rigify")

    def test_character_model_outputs_use_character_paths(self):
        config = load_project(self.root)
        character = load_taxonomy(self.root)["character"]

        paths = model_paths(self.root, config, "moon_scout", character)
        candidate = material_candidate_paths(self.root, config, "moon_scout", 1, character)

        self.assertEqual(paths["glb"].relative_to(self.root.resolve()).as_posix(),
                         "Assets/Art/Generated/Characters/moon_scout/Source/moon_scout.glb")
        self.assertEqual(candidate["directory"].relative_to(self.root).as_posix(),
                         "ai/assets/candidates/character/moon_scout/material_01")


if __name__ == "__main__":
    unittest.main()
