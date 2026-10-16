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

    def test_board_pairs_character_concepts_with_model_views_and_source_review_evidence(self):
        (self.root / "concept.png").write_bytes(b"concept")
        (self.root / "model.png").write_bytes(b"model")
        self.manifest["assets"]["character:pilot"] = {"id": "pilot-id", "name": "pilot", "type": "character",
            "source_quality_reviews": [{"id": "review-1", "status": "ready_for_review",
                "report_path": "review.json", "concept_views": {"front": {"path": "concept.png"}},
                "previews": {"front": {"path": "model.png"}, "side": {"path": None}},
                "critical_regions": [{"name": "helmet", "concept_crop": {"path": "concept.png"},
                                      "model_closeup": {"path": "model.png"}}],
                "inspection": {"path": "inspection.json"}, "conditioning": {"route": "single_image"},
                "findings": [{"id": "boundary-1", "classification": "unclassified"}],
                "missing": [], "sha256": {"model": "abc"}}]}
        page = generate_review_board(self.root, self.manifest).read_text()
        self.assertIn("Source geometry review", page)
        self.assertIn("front concept", page)
        self.assertIn("front model", page)
        self.assertIn("single_image", page)
        self.assertIn("unclassified", page)
        self.assertIn("inspection.json", page)

    def test_board_renders_incomplete_review_without_inspection_and_shows_decision(self):
        self.manifest["assets"]["character:pilot"] = {"id": "pilot-id", "name": "pilot", "type": "character",
            "source_quality_reviews": [{"id": "incomplete", "status": "incomplete", "inspection": None,
                "missing": ["inspection"], "decisions": [{"decision": "rejected", "reason": "missing topology evidence"}]}]}
        page = generate_review_board(self.root, self.manifest).read_text()
        self.assertIn("Completeness:", page)
        self.assertIn("rejected: missing topology evidence", page)
        self.assertIn("stale or incomplete", page)
        self.assertIn("Inspection report missing", page)


if __name__ == "__main__":
    unittest.main()
