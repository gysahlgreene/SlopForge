import unittest
import json
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from slopforge.character_readiness import (
    approve_character_readiness,
    classify_character_readiness,
    readiness_allows_rigging,
    run_character_readiness,
)
from slopforge.cli import parse_args


class CharacterReadinessTests(unittest.TestCase):
    def test_cli_exposes_inspection_and_explicit_approval_commands(self):
        inspect = parse_args(["--project", "/tmp/game", "character", "readiness", "pilot"])
        approve = parse_args(["--project", "/tmp/game", "character", "approve-readiness", "pilot"])
        self.assertEqual(inspect.character_action, "readiness")
        self.assertEqual(inspect.source_output, "model")
        self.assertEqual(approve.character_action, "approve-readiness")

    def test_closed_humanoid_measurements_pass_without_a_still_image_score(self):
        report = classify_character_readiness({"measured": {
            "mesh_objects": 1, "vertex_count": 800, "face_count": 1400,
            "dimensions": [0.7, 1.8, 0.5], "transforms_applied": True,
            "component_count": 1, "boundary_edge_count": 0, "nonmanifold_edge_count": 0,
            "degenerate_face_count": 0, "zero_normal_count": 0, "face_budget": 60000,
        }})
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["approval"]["status"], "pending")
        self.assertIn("deformation", " ".join(report["limitations"]).lower())
        self.assertNotIn("image_score", report)

    def test_open_or_disconnected_mesh_needs_human_review(self):
        report = classify_character_readiness({"measured": {
            "mesh_objects": 1, "vertex_count": 800, "face_count": 1400,
            "dimensions": [0.7, 1.8, 0.5], "transforms_applied": True,
            "component_count": 3, "boundary_edge_count": 8, "nonmanifold_edge_count": 8,
            "degenerate_face_count": 0, "zero_normal_count": 0, "face_budget": 60000,
        }})
        self.assertEqual(report["status"], "needs_review")
        self.assertTrue(report["reasons"])

    def test_degenerate_generated_style_mesh_fails(self):
        report = classify_character_readiness({"measured": {
            "mesh_objects": 0, "vertex_count": 0, "face_count": 0,
            "dimensions": [0, 0, 0], "transforms_applied": False,
            "component_count": 0, "boundary_edge_count": 0, "nonmanifold_edge_count": 0,
            "degenerate_face_count": 0, "zero_normal_count": 0, "face_budget": 60000,
        }})
        self.assertEqual(report["status"], "fail")

    def test_rigging_requires_accepted_readiness_report(self):
        self.assertFalse(readiness_allows_rigging({"status": "pass", "approval": {"status": "pending"}}))
        self.assertFalse(readiness_allows_rigging({"status": "fail", "approval": {"status": "approved"}}))
        self.assertTrue(readiness_allows_rigging({"status": "pass", "approval": {"status": "approved"}}))
        self.assertTrue(readiness_allows_rigging({"status": "needs_review", "approval": {"status": "approved"}}))

    def test_blender_report_is_saved_and_pipeline_statuses_stay_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "Assets/Characters/pilot/model.glb"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"fixture")
            character = {"id": "character:pilot", "name": "pilot", "type": "character",
                         "status": "ready", "outputs": {}, "artifacts": {
                             "model": {"id": "model-id", "type": "model.glb", "path": "Assets/Characters/pilot/model.glb",
                                       "status": "ready", "approval": {"status": "approved"}}}}
            manifest = {"assets": {"character:pilot": character}}
            blender_result = {"measured": {
                "mesh_objects": 1, "vertex_count": 800, "face_count": 1400,
                "dimensions": [0.7, 1.8, 0.5], "transforms_applied": True,
                "component_count": 1, "boundary_edge_count": 0, "nonmanifold_edge_count": 0,
                "degenerate_face_count": 0, "zero_normal_count": 0, "face_budget": 60000,
            }}

            def inspect(command, **kwargs):
                Path(command[-2]).write_text(json.dumps(blender_result))

            with patch("slopforge.character_readiness.blender_executable", return_value="blender"), \
                    patch("slopforge.character_readiness.subprocess.run", side_effect=inspect):
                result = run_character_readiness(root, {"asset_pipeline": {
                    "output_root": "Assets/Art/Generated",
                    "model_budgets": {"character_faces": 60000},
                }}, manifest, "pilot")

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["source"]["sha256"], hashlib.sha256(model.read_bytes()).hexdigest())
            self.assertTrue((root / result["report_path"]).is_file())
            self.assertEqual(character["pipeline_status"]["model_generation_status"], "ready")
            self.assertEqual(character["pipeline_status"]["animation_readiness_status"], "pass")
            self.assertEqual(character["pipeline_status"]["rigging_status"], "not_started")

    def test_needs_review_report_requires_explicit_approval(self):
        character = {"type": "character", "name": "pilot", "animation_readiness": {
            "status": "needs_review", "approval": {"status": "pending"}}}
        manifest = {"assets": {"character:pilot": character}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readiness.json"
            path.write_text(json.dumps(character["animation_readiness"]))
            character["animation_readiness"]["report_path"] = "readiness.json"
            result = approve_character_readiness(Path(directory), manifest, "pilot")
            self.assertEqual(result["approval"]["status"], "approved")
            self.assertTrue(readiness_allows_rigging(result))


if __name__ == "__main__":
    unittest.main()
