import tempfile
import unittest
from pathlib import Path

from slopforge.review import generate_review_board


class ReviewBoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "ai/assets/candidates/concept/badge").mkdir(parents=True)
        (self.root / "ai/assets/candidates/concept/badge/candidate.png").write_bytes(b"image")
        self.manifest = {"assets": {
            "recipe:pack": {"id": "pack-id", "name": "pack", "type": "recipe", "status": "partial",
                            "recipe_instance": {"stages": {"badge": {"asset_id": "badge-id", "status": "failed"}}}},
            "concept:badge": {"id": "badge-id", "name": "badge", "type": "concept", "status": "candidate",
                           "parent_id": "pack-id", "dependencies": [], "description": "Tiny concept",
                           "generator": {"workflow": "z-image.json", "model": "z_image_turbo", "seed": 5},
                           "candidates": {"selected": None, "items": [{"number": 1,
                               "path": "ai/assets/candidates/concept/badge/candidate.png", "status": "candidate",
                               "prompt": "<script>alert('x')</script>", "seed": 123,
                               "variation": {"silhouette": "wide <unsafe>"},
                               "generator": {"workflow": "z-image.json", "model": "turbo"}},
                               {"number": 2, "path": "missing.png", "status": "failed", "seed": 124}]}}}}

    def tearDown(self):
        self.temp.cleanup()

    def test_board_renders_candidates_missing_files_pack_links_provenance_and_safe_cli_actions(self):
        page = generate_review_board(self.root, self.manifest)
        html = page.read_text()
        self.assertIn('src="ai/assets/candidates/concept/badge/candidate.png"', html)
        self.assertIn("Missing file: missing.png", html)
        self.assertIn("pack", html)
        self.assertIn("z-image.json", html)
        self.assertIn("123", html)
        self.assertIn("silhouette", html)
        self.assertIn("wide &lt;unsafe&gt;", html)
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert('x')</script>", html)
        self.assertIn("approve badge 1", html)
        self.assertIn("reject badge 1", html)
        self.assertIn("generate concept badge", html)
        self.assertIn("inspect badge", html)

    def test_board_output_and_asset_paths_stay_inside_project(self):
        with self.assertRaisesRegex(ValueError, "within the project"):
            generate_review_board(self.root, self.manifest, "../outside.html")
        self.manifest["assets"]["concept:badge"]["candidates"]["items"][0]["path"] = "../../private.png"
        with self.assertRaisesRegex(ValueError, "within the project"):
            generate_review_board(self.root, self.manifest)

    def test_board_shows_model_material_previews_and_typed_outputs_with_missing_views(self):
        (self.root / "Assets/Robot").mkdir(parents=True)
        (self.root / "Assets/Robot/front.png").write_bytes(b"preview")
        self.manifest["assets"]["prop:robot"] = {
            "id": "robot-id", "name": "robot", "type": "prop", "status": "ready",
            "material_candidates": {"selected": None, "items": [{"number": 1, "status": "candidate",
                "outputs": {"preview_front": "Assets/Robot/front.png", "preview_side": "Assets/Robot/missing.png"}}]},
            "artifacts": {"model": {"type": "model.glb", "path": "Assets/Robot/robot.glb"}},
        }
        html = generate_review_board(self.root, self.manifest).read_text()
        self.assertIn("Material 1", html)
        self.assertIn('src="Assets/Robot/front.png"', html)
        self.assertIn("Missing file: Assets/Robot/missing.png", html)
        self.assertIn("robot.glb", html)


if __name__ == "__main__":
    unittest.main()
