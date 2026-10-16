import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from slopforge.character_quality import (classify_character_source_findings,
    create_character_source_review, approve_character_source_review,
    reject_character_source_review, is_character_source_review_current,
    require_current_character_source_approval)
from slopforge.cli import parse_args


class CharacterSourceQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.asset = {"id": "character-id", "name": "pilot", "type": "character",
                      "status": "ready", "artifacts": {},
                      "conditioning": {"strategy": "single_image", "references_used": ["input.png"]}}
        (self.root / "Assets/Characters/pilot").mkdir(parents=True)
        self._file("Assets/Characters/pilot/model.glb", b"glTF" + (12).to_bytes(4, "little") + (2).to_bytes(4, "little"))
        self.asset["artifacts"]["model"] = self._artifact("model", "model.glb", "Assets/Characters/pilot/model.glb")
        for view in ("front", "side", "rear", "three_quarter"):
            path = f"Assets/Characters/pilot/{view}.png"
            self._image(path)
            self.asset["artifacts"][f"preview_{view}"] = self._artifact(f"preview.{view}", f"preview.{view}", path)
        self._image("Assets/Characters/pilot/normal.png")
        self.asset["artifacts"]["normal"] = self._artifact("normal", "texture.normal", "Assets/Characters/pilot/normal.png")
        inspection_path = "Assets/Characters/pilot/inspection.json"
        inspection = {"status": "passed_with_warnings", "measured": {
            "component_details": [{"object_name": "Body", "component_index": 0, "vertex_count": 4,
                                   "face_count": 1, "bounds_min": [0, 0, 0], "bounds_max": [1, 1, 1]}],
            "topology_diagnostics": [{"object_name": "Body", "component_index": 0, "kind": "boundary_edge",
                                      "source_vertex_indices": [0, 1], "positions": [[0, 0, 0], [1, 0, 0]]}]}}
        self._file(inspection_path, json.dumps(inspection).encode())
        self.asset["artifacts"]["inspection"] = self._artifact("inspection", "inspection.json", inspection_path)
        self.manifest = {"assets": {"character:pilot": self.asset}}
        self._image("input.png")
        self.concepts = {}
        for view in ("front", "left", "rear"):
            path = f"ai/concepts/{view}.png"
            self._image(path)
            self.concepts[view] = path

    def tearDown(self):
        self.temp.cleanup()

    def _file(self, relative, contents):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def _image(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4), (120, 80, 60)).save(path)
        return path

    def _artifact(self, artifact_id, artifact_type, path):
        return {"id": artifact_id, "type": artifact_type, "path": path, "status": "ready",
                "approval": {"status": "approved"}}

    def _regions(self):
        self._image("ai/concepts/helmet-crop.png")
        self._image("Assets/Characters/pilot/helmet-closeup.png")
        return [{"name": "helmet", "concept_crop": "ai/concepts/helmet-crop.png",
                 "model_closeup": "Assets/Characters/pilot/helmet-closeup.png"}]

    def test_source_review_records_exact_hashes_and_four_views(self):
        result = create_character_source_review(self.root, self.manifest, "pilot", self.concepts, self._regions())
        self.assertEqual(result["status"], "ready_for_review")
        self.assertEqual(set(result["previews"]), {"front", "side", "rear", "three_quarter"})
        self.assertEqual(result["source_artifact"]["sha256"], __import__("hashlib").sha256(
            (self.root / "Assets/Characters/pilot/model.glb").read_bytes()).hexdigest())
        self.assertTrue(result["sha256"])
        self.assertIn("dependency_model_and_node_license_terms", result["unknowns"])
        self.assertTrue(all(finding["classification"] == "unclassified" for finding in result["findings"]))
        report = self.root / result["report_path"]
        self.assertEqual(json.loads(report.read_text())["id"], result["id"])
        self.assertNotIn("decisions", result)

    def test_single_image_route_and_missing_concepts_stay_incomplete(self):
        incomplete = dict(self.concepts)
        incomplete.pop("left")
        result = create_character_source_review(self.root, self.manifest, "pilot", incomplete, self._regions())
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["conditioning"]["route"], "single_image")
        self.assertIn("concept_views.left", result["missing"])
        self.assertNotIn("decisions", result)
        for view in ("side", "rear", "three_quarter"):
            self.asset["artifacts"].pop(f"preview_{view}")
        result = create_character_source_review(self.root, self.manifest, "pilot", self.concepts, self._regions())
        self.assertTrue({"previews.side", "previews.rear", "previews.three_quarter"}.issubset(result["missing"]))
        self.asset["artifacts"].pop("normal")
        result = create_character_source_review(self.root, self.manifest, "pilot", self.concepts, self._regions())
        self.assertIn("material_artifacts", result["missing"])

    def test_rejects_missing_or_unsafe_source_review_paths(self):
        with self.assertRaisesRegex(ValueError, "project-relative"):
            create_character_source_review(self.root, self.manifest, "pilot", {**self.concepts, "front": "../escape.png"}, self._regions())
        outside = self.root.parent / "outside-review.png"
        self._image("ai/concepts/invalid.png")
        (self.root / "ai/concepts/link.png").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "within the project"):
            create_character_source_review(self.root, self.manifest, "pilot",
                {**self.concepts, "front": "ai/concepts/link.png"}, self._regions())
        self._file("ai/concepts/corrupt.png", b"not an image")
        with self.assertRaisesRegex(ValueError, "valid image"):
            create_character_source_review(self.root, self.manifest, "pilot",
                {**self.concepts, "front": "ai/concepts/corrupt.png"}, self._regions())
        result = create_character_source_review(self.root, self.manifest, "pilot",
            {**self.concepts, "rear": "ai/concepts/missing.png"}, self._regions())
        self.assertIn("concept_views.rear", result["missing"])
        (self.root / "Assets/Characters/pilot/model.glb").write_bytes(b"invalid model")
        with self.assertRaisesRegex(ValueError, "invalid .glb header"):
            create_character_source_review(self.root, self.manifest, "pilot", self.concepts, self._regions())

    def test_critical_regions_require_matching_concept_and_model_closeups(self):
        regions = [{"name": "helmet", "concept_crop": "ai/concepts/helmet-crop.png"}]
        self._image(regions[0]["concept_crop"])
        result = create_character_source_review(self.root, self.manifest, "pilot", self.concepts, regions)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("critical_regions.helmet.model_closeup", result["missing"])

    def test_findings_start_unclassified_and_only_accept_valid_classifications(self):
        result = create_character_source_review(self.root, self.manifest, "pilot", self.concepts, self._regions())
        finding = result["findings"][0]
        self.assertEqual(finding["classification"], "unclassified")
        report_bytes = (self.root / result["report_path"]).read_bytes()
        with self.assertRaisesRegex(ValueError, "classification"):
            classify_character_source_findings(self.root, self.manifest, "pilot", result["id"],
                                                {finding["id"]: "approved"})
        with self.assertRaisesRegex(ValueError, "Unknown finding"):
            classify_character_source_findings(self.root, self.manifest, "pilot", result["id"],
                                                {"missing": "intentional"})
        classified = classify_character_source_findings(self.root, self.manifest, "pilot", result["id"],
                                                         {finding["id"]: "intentional"})
        self.assertEqual(classified["findings"][0]["classification_history"][-1]["classification"], "intentional")
        again = classify_character_source_findings(self.root, self.manifest, "pilot", result["id"],
                                                    {finding["id"]: "unresolved"})
        self.assertEqual(len(again["findings"][0]["classification_history"]), 2)
        self.assertEqual((self.root / result["report_path"]).read_bytes(), report_bytes)

    def test_source_review_and_classification_cli_commands_parse_repeated_inputs(self):
        args = parse_args(["character", "source-review", "pilot", "--concept-view", "front=f.png",
                           "--concept-view", "left=l.png", "--concept-view", "rear=r.png",
                           "--critical-region", "helmet", "--concept-crop", "helmet=c.png",
                           "--model-closeup", "helmet=m.png"])
        self.assertEqual(args.character_action, "source-review")
        self.assertEqual(len(args.concept_view), 3)
        classified = parse_args(["character", "classify-source", "pilot", "review-id",
                                 "--finding", "finding-id=intentional"])
        self.assertEqual(classified.character_action, "classify-source")
        approved = parse_args(["character", "approve-source", "pilot", "review-id", "--confirm"])
        self.assertTrue(approved.confirm)
        rejected = parse_args(["character", "reject-source", "pilot", "review-id", "--reason", "missing glove geometry"])
        self.assertEqual(rejected.reason, "missing glove geometry")

    def test_source_approval_requires_complete_review_and_classification(self):
        result = create_character_source_review(self.root, self.manifest, "pilot", {"front": self.concepts["front"]}, self._regions())
        with self.assertRaisesRegex(ValueError, "complete"):
            approve_character_source_review(self.root, self.manifest, "pilot", result["id"])
        result = create_character_source_review(self.root, self.manifest, "pilot", self.concepts, self._regions())
        with self.assertRaisesRegex(ValueError, "classified"):
            approve_character_source_review(self.root, self.manifest, "pilot", result["id"])
        classifications = {finding["id"]: "intentional" for finding in result["findings"]}
        classify_character_source_findings(self.root, self.manifest, "pilot", result["id"], classifications)
        approved = approve_character_source_review(self.root, self.manifest, "pilot", result["id"], approved_by="reviewer")
        self.assertEqual(approved["decisions"][-1]["decision"], "approved")
        self.assertEqual(approved["decisions"][-1]["reviewed_sha256"], approved["sha256"])
        self.assertEqual(self.asset["status"], "ready")
        self.assertNotIn("material_approval", self.asset)
        rejected = reject_character_source_review(self.root, self.manifest, "pilot", result["id"], "Geometry misses the shoulder form")
        self.assertEqual(rejected["decisions"][-1]["reason"], "Geometry misses the shoulder form")
        with self.assertRaisesRegex(ValueError, "rejected"):
            require_current_character_source_approval(self.root, self.asset, "model")

    def test_source_approval_stales_after_any_reviewed_input_changes(self):
        paths = ["Assets/Characters/pilot/model.glb", self.concepts["front"],
                 "Assets/Characters/pilot/front.png", "Assets/Characters/pilot/normal.png",
                 "Assets/Characters/pilot/inspection.json"]
        for relative in paths:
            with self.subTest(path=relative):
                result = create_character_source_review(self.root, self.manifest, "pilot", self.concepts, self._regions())
                classify_character_source_findings(self.root, self.manifest, "pilot", result["id"],
                    {finding["id"]: "intentional" for finding in result["findings"]})
                approve_character_source_review(self.root, self.manifest, "pilot", result["id"])
                self.assertTrue(is_character_source_review_current(self.root, result))
                target = self.root / relative
                if target.suffix == ".png":
                    Image.new("RGB", (4, 4), (2, 4, 8)).save(target)
                elif target.suffix == ".json":
                    report = json.loads(target.read_text())
                    report["changed"] = True
                    target.write_text(json.dumps(report))
                else:
                    target.write_bytes(target.read_bytes() + b"changed")
                self.assertFalse(is_character_source_review_current(self.root, result))


if __name__ == "__main__":
    unittest.main()
