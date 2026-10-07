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
from readiness_fixture import complete_measurements


class CharacterReadinessTests(unittest.TestCase):
    complete_measurements = staticmethod(complete_measurements)

    def test_cli_exposes_inspection_and_explicit_approval_commands(self):
        inspect = parse_args(["--project", "/tmp/game", "character", "readiness", "pilot"])
        approve = parse_args(["--project", "/tmp/game", "character", "approve-readiness", "pilot"])
        self.assertEqual(inspect.character_action, "readiness")
        self.assertEqual(inspect.source_output, "model")
        self.assertEqual(approve.character_action, "approve-readiness")

    def test_closed_humanoid_measurements_pass_without_a_still_image_score(self):
        report = classify_character_readiness({"measured": self.complete_measurements()})
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["approval"]["status"], "pending")
        self.assertIn("deformation", " ".join(report["limitations"]).lower())
        self.assertNotIn("image_score", report)

    def test_open_or_disconnected_mesh_needs_human_review(self):
        report = classify_character_readiness({"measured": self.complete_measurements(
            component_count=3, boundary_edge_count=8, nonmanifold_edge_count=8)})
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

    def test_incomplete_material_or_coordinate_report_fails_closed(self):
        measurements = self.complete_measurements()
        del measurements["mesh_without_uv_count"]
        report = classify_character_readiness({"measured": measurements})
        self.assertEqual(report["status"], "fail")
        self.assertIn("material and UV measurements are incomplete", report["reasons"])

    def test_incomplete_topology_report_fails_closed(self):
        measurements = self.complete_measurements()
        del measurements["component_count"]
        report = classify_character_readiness({"measured": measurements})
        self.assertEqual(report["status"], "fail")
        self.assertIn("geometry, coordinate, or review measurements are incomplete", report["reasons"])

    def test_malformed_measurements_return_failure_without_raising(self):
        for field, value in (("mesh_objects", "one"), ("face_count", None),
                             ("dimensions", ["wide", 1, 1]), ("dimensions", [True, 1, 1]),
                             ("dimensions", [10**1000, 1, 1]),
                             ("coordinate_system", {"up_axis": []}), ("rest_pose_status", []),
                             ("auxiliary_objects", [None])):
            with self.subTest(field=field, value=value):
                report = classify_character_readiness({"measured": self.complete_measurements(**{field: value})})
                self.assertEqual(report["status"], "fail")

    def test_legacy_or_forged_approved_reports_cannot_advance(self):
        legacy = {"status": "pass", "approval": {"status": "approved"}}
        self.assertFalse(readiness_allows_rigging(legacy))
        forged = dict(legacy, measured=self.complete_measurements(image_texture_count=0))
        self.assertFalse(readiness_allows_rigging(forged))

    def test_character_scale_uses_scene_units(self):
        measured = self.complete_measurements(dimensions=[70, 180, 50])
        measured["coordinate_system"]["scale_length"] = 0.01
        report = classify_character_readiness({"measured": measured})
        self.assertEqual(report["status"], "pass")
        for actual, expected in zip(report["checks"]["dimensions_meters"], [0.7, 1.8, 0.5]):
            self.assertAlmostEqual(actual, expected)

    def test_approval_rejects_incomplete_old_report_without_changing_it(self):
        readiness = {"status": "pass", "approval": {"status": "pending"}, "report_path": "readiness.json"}
        character = {"type": "character", "name": "pilot", "animation_readiness": readiness}
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "readiness.json"
            report.write_text(json.dumps(readiness))
            original = report.read_bytes()
            with self.assertRaisesRegex(ValueError, "run character readiness again"):
                approve_character_readiness(Path(directory), {"assets": {"character:pilot": character}}, "pilot")
            self.assertEqual(readiness["approval"]["status"], "pending")
            self.assertEqual(report.read_bytes(), original)

    def test_unreviewed_rest_pose_requires_human_review(self):
        report = classify_character_readiness({"measured": self.complete_measurements(
            rest_pose_status="visual_review_required")})
        self.assertEqual(report["status"], "needs_review")
        self.assertEqual(report["approval"]["status"], "pending")
        self.assertIn("rest pose and model orientation require human review", report["reasons"])

    def test_missing_texture_or_uncovered_mesh_fails(self):
        report = classify_character_readiness({"measured": self.complete_measurements(
            mesh_without_material_count=1, mesh_without_texture_count=1, missing_textures=["missing.png"])})
        self.assertEqual(report["status"], "fail")
        self.assertIn("1 mesh objects have no assigned material", report["reasons"])
        self.assertIn("1 mesh objects have no linked image texture", report["reasons"])
        self.assertIn("1 referenced texture files are missing", report["reasons"])

    def test_unapproved_readiness_cannot_advance_when_contract_fails(self):
        readiness = classify_character_readiness({"measured": self.complete_measurements(
            image_texture_count=0)})
        self.assertEqual(readiness["status"], "fail")
        readiness["approval"] = {"status": "approved"}
        self.assertFalse(readiness_allows_rigging(readiness))

    def test_every_mesh_needs_a_linked_texture(self):
        report = classify_character_readiness({"measured": self.complete_measurements(
            mesh_without_texture_count=1)})
        self.assertEqual(report["status"], "fail")

    def test_failed_contract_cannot_be_human_approved(self):
        character = {"type": "character", "name": "pilot", "animation_readiness":
                     classify_character_readiness({"measured": self.complete_measurements(image_texture_count=0)})}
        manifest = {"assets": {"character:pilot": character}}
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "readiness.json"
            character["animation_readiness"]["report_path"] = "readiness.json"
            report.write_text(json.dumps(character["animation_readiness"]))
            with self.assertRaisesRegex(ValueError, "cannot be approved"):
                approve_character_readiness(Path(directory), manifest, "pilot")

    def test_rigging_requires_accepted_readiness_report(self):
        self.assertFalse(readiness_allows_rigging({"status": "pass", "approval": {"status": "pending"}}))
        self.assertFalse(readiness_allows_rigging({"status": "fail", "approval": {"status": "approved"}}))
        for status in ("pass", "needs_review"):
            self.assertTrue(readiness_allows_rigging({"status": status, "approval": {"status": "approved"},
                                                     "measured": self.complete_measurements()}))

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
            blender_result = {"measured": self.complete_measurements(), "animation_readiness": {
                "status": "pass", "approval": {"status": "approved"}, "measured": {}}}

            def inspect(command, **kwargs):
                Path(command[-2]).write_text(json.dumps(blender_result))

            with patch("slopforge.character_readiness.blender_executable", return_value="blender"), \
                    patch("slopforge.character_readiness.subprocess.run", side_effect=inspect):
                result = run_character_readiness(root, {"asset_pipeline": {
                    "output_root": "Assets/Art/Generated",
                    "model_budgets": {"character_faces": 60000},
                }}, manifest, "pilot")

            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["approval"]["status"], "pending")
            self.assertEqual(result["measured"], blender_result["measured"])
            self.assertEqual(result["source"]["sha256"], hashlib.sha256(model.read_bytes()).hexdigest())
            self.assertTrue((root / result["report_path"]).is_file())
            self.assertEqual(character["pipeline_status"]["model_generation_status"], "ready")
            self.assertEqual(character["pipeline_status"]["animation_readiness_status"], "pass")
            self.assertEqual(character["pipeline_status"]["rigging_status"], "not_started")

    def test_failed_inspection_preserves_previous_report_and_approval(self):
        for failure in ("missing_report", "changed_source"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "model.glb"
                source.write_bytes(b"original source")
                report = root / "Assets/Characters/pilot/Readiness/report.json"
                report.parent.mkdir(parents=True)
                previous = classify_character_readiness({"measured": self.complete_measurements()})
                previous["approval"] = {"status": "approved"}
                report.write_text(json.dumps(previous))
                original_report = report.read_bytes()
                character = {"id": "character:pilot", "name": "pilot", "type": "character",
                             "animation_readiness": previous, "artifacts": {"model": {
                                 "id": "model", "path": "model.glb", "type": "model.glb",
                                 "status": "ready", "approval": {"status": "approved"}}}}

                def inspect(command, **kwargs):
                    if failure == "changed_source":
                        Path(command[-2]).write_text(json.dumps({"measured": self.complete_measurements()}))
                        source.write_bytes(b"changed during inspection")

                with patch("slopforge.character_readiness.blender_executable", return_value="blender"), \
                     patch("slopforge.character_readiness.subprocess.run", side_effect=inspect):
                    with self.assertRaisesRegex(RuntimeError, "without creating|changed during"):
                        run_character_readiness(root, {"asset_pipeline": {"output_root": "Assets"}},
                                                {"assets": {"character:pilot": character}}, "pilot")
                self.assertEqual(report.read_bytes(), original_report)
                self.assertIs(character["animation_readiness"], previous)
                self.assertEqual(previous["approval"]["status"], "approved")

    def test_needs_review_report_requires_explicit_approval(self):
        character = {"type": "character", "name": "pilot", "animation_readiness": {
            "status": "needs_review", "approval": {"status": "pending"},
            "measured": self.complete_measurements(rest_pose_status="visual_review_required")}}
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
