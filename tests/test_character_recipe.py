import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from slopforge.config import load_project
from slopforge.initializer import init_project
from slopforge.pipelines.model import _native_material_candidate, material_candidate_paths, model_paths
from slopforge.recipes import load_recipe
from slopforge.recipes import run_recipe
from slopforge.manifest import load_manifest
from slopforge.style import build_prompt, load_style
from slopforge.taxonomy import load_taxonomy
from slopforge.validation import validate_model_outputs


class CharacterRecipeTests(unittest.TestCase):
    def test_character_recipe_uses_the_concept_candidate_budget(self):
        config = load_project(self.root)
        config["asset_pipeline"]["quality_tiers"]["normal"]["defaults"] = {
            "image_candidates": 4, "model_candidates": 2}
        manifest = load_manifest(self.root / "ai/assets/manifest.json")
        def image_backend(_root, _config, _workflow, _prompt, destination, _prefix, seed, metadata):
            Image.new("RGB", (32, 32), "gray").save(destination)
            metadata.write_text('{"model":"fixture"}')
        with patch("slopforge.pipelines.model.generate_image", side_effect=image_backend):
            run_recipe(self.root, config, load_style(self.root, config), load_taxonomy(self.root), manifest,
                       "character_3d_pack", quality_tier="normal")
        character = next(asset for asset in manifest["assets"].values() if asset["type"] == "character")
        self.assertEqual(len(character["candidates"]["items"]), 4)

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
        self.assertEqual(types["character"]["voxel_resolution"], 120)
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
        self.assertEqual(character["max_components"], 64)
        self.assertEqual(character["max_boundary_edges"], 0)

    def test_fragmented_character_mesh_exceeds_its_component_budget(self):
        result = validate_model_outputs(
            {}, {"measured": {"component_count": 1189}},
            max_components=64,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("component count 1189 exceeds budget 64", result["errors"])

    def test_nonmanifold_character_mesh_exceeds_its_topology_budget(self):
        result = validate_model_outputs(
            {}, {"measured": {"nonmanifold_edge_count": 4168}},
            max_nonmanifold_edges=0,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("non-manifold edge count 4168 exceeds budget 0", result["errors"])

    def test_open_character_mesh_exceeds_its_boundary_budget(self):
        result = validate_model_outputs(
            {}, {"measured": {"boundary_edge_count": 549}},
            max_boundary_edges=0,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("boundary edge count 549 exceeds budget 0", result["errors"])

    def test_character_topology_budgets_fail_closed_without_inspection_metrics(self):
        result = validate_model_outputs(
            {}, {"measured": {}}, max_components=64, max_nonmanifold_edges=0,
            max_boundary_edges=0,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("component count was not measured", result["errors"])
        self.assertIn("non-manifold edge count was not measured", result["errors"])
        self.assertIn("boundary edge count was not measured", result["errors"])

    def test_native_character_candidate_fails_when_fragmented_mesh_exceeds_budget(self):
        config = load_project(self.root)
        character = load_taxonomy(self.root)["character"]
        asset = {"name": "scout", "source": {"glb": "scout.glb", "processed_mesh": "processed.blend"},
                 "description": "Lunar scout"}
        (self.root / "scout.glb").write_bytes(b"glb")
        texture_names = {key: f"{key}.png" for key in ("basecolor", "normal", "roughness", "metallic")}
        for filename in texture_names.values():
            Image.new("RGB", (8, 8), "gray").save(self.root / filename)

        def process_model(_root, _config, _source, fbx, blend, _textures, _budget, **options):
            fbx.write_bytes(b"fbx")
            blend.write_bytes(b"blend")
            preview_dir = Path(options["preview_dir"])
            preview_dir.mkdir(parents=True, exist_ok=True)
            for view in ("front", "side", "rear"):
                Image.new("RGB", (8, 8), "gray").save(preview_dir / f"scout_{view}.png")

        with patch("slopforge.pipelines.model.process_model", side_effect=process_model), \
                patch("slopforge.pipelines.model.inspect_model", return_value={
                    "status": "passed_with_warnings", "errors": [], "warnings": [],
                    "measured": {"face_count": 100, "component_count": 1189,
                                 "nonmanifold_edge_count": 4168, "boundary_edge_count": 549}}):
            result = _native_material_candidate(
                self.root, config, character, asset, 1, {"textures": texture_names})

        self.assertEqual(result["status"], "failed")
        self.assertIn("component count 1189 exceeds budget 64", result["validation"]["errors"])
        self.assertIn("non-manifold edge count 4168 exceeds budget 0", result["validation"]["errors"])
        self.assertIn("boundary edge count 549 exceeds budget 0", result["validation"]["errors"])


if __name__ == "__main__":
    unittest.main()
