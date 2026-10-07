import tempfile
import hashlib
from PIL import Image
import unittest
from pathlib import Path
from unittest.mock import patch

from slopforge.character_rigging import (record_rigging_result, resolve_rigging_source,
    run_character_rigging, classify_skintokens_structure, approve_deformation, skintokens_character)
from slopforge.manifest import new_record, register_artifact
from readiness_fixture import complete_measurements


class CharacterRiggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = {"assets": {}}
        character = new_record("character", "pilot", "Pilot", {"name": "default", "version": 1},
                              {"strategy": "text_only"})
        self.manifest["assets"]["character:pilot"] = character
        source = self.root / "Assets/Characters/pilot/model.glb"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"glTF")
        register_artifact(self.manifest, "character:pilot", "model", "model.glb",
                          "Assets/Characters/pilot/model.glb", status="ready", approval_status="approved")
        character["animation_readiness"] = {
            "measured": complete_measurements(),
            "status": "pass", "approval": {"status": "approved"}, "source_output": "model",
            "source": {"artifact_id": "model", "path": "Assets/Characters/pilot/model.glb",
                       "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}
        self.result = {
            "provider": {"name": "sample", "version": "1.2", "source": "https://example.test/provider",
                         "license": "MIT"},
            "source_output": "model",
            "rigged_model": "Assets/Characters/pilot/rigged.fbx",
            "evidence": {"t_pose": "Assets/Characters/pilot/review/t_pose.png"},
            "skeleton_mapping": {"hips": "pelvis", "left_upper_arm": "upperarm_l"},
            "unity_humanoid_mapping": {"Hips": "pelvis", "RightHand": "hand_r"},
        }
        (self.root / self.result["rigged_model"]).parent.mkdir(parents=True, exist_ok=True)
        (self.root / self.result["rigged_model"]).write_bytes(b"FBX")
        (self.root / self.result["evidence"]["t_pose"]).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (2, 2), (0, 0, 0, 255)).save(self.root / self.result["evidence"]["t_pose"])

    def tearDown(self):
        self.temp.cleanup()

    def test_rig_result_is_typed_provenance_aware_and_pending_review(self):
        report = record_rigging_result(self.root, self.manifest, "character:pilot", self.result)
        character = self.manifest["assets"]["character:pilot"]
        rig = character["artifacts"]["rig"]
        pose = character["artifacts"]["rig_pose.t_pose"]

        self.assertEqual(report["status"], "review_required")
        self.assertEqual(rig["type"], "model.rigged")
        self.assertEqual(rig["approval"]["status"], "pending")
        self.assertEqual(rig["derived_from"], [{"asset_id": character["id"], "output_id": "model"}])
        self.assertEqual(rig["provenance"]["license"], "MIT")
        self.assertEqual(pose["type"], "image.rig_evidence")
        self.assertEqual(pose["approval"]["status"], "pending")
        self.assertEqual(character["rigging"]["skeleton_mapping"]["hips"], "pelvis")
        self.assertEqual(character["rigging"]["unity_humanoid_mapping"]["RightHand"], "hand_r")
        self.assertIn("raised_arms", report["missing_recommended_poses"])

    def test_rejects_unknown_source_and_paths_outside_project(self):
        result = dict(self.result, source_output="missing")
        with self.assertRaisesRegex(ValueError, "source output"):
            record_rigging_result(self.root, self.manifest, "character:pilot", result)

        result = dict(self.result, rigged_model="../outside.fbx")
        with self.assertRaisesRegex(ValueError, "project-relative"):
            record_rigging_result(self.root, self.manifest, "character:pilot", result)

    def test_requires_provider_license_and_existing_nonempty_exports(self):
        result = dict(self.result, provider={"name": "sample", "version": "1.2", "source": "https://example.test"})
        with self.assertRaisesRegex(ValueError, "license"):
            record_rigging_result(self.root, self.manifest, "character:pilot", result)

        result = dict(self.result, rigged_model="Assets/Characters/pilot/missing.fbx")
        with self.assertRaisesRegex(ValueError, "missing or empty"):
            record_rigging_result(self.root, self.manifest, "character:pilot", result)

    def test_rigging_source_must_be_an_approved_contained_model_artifact(self):
        path = resolve_rigging_source(self.root, self.manifest, "character:pilot", "model")
        self.assertEqual(path, self.root.resolve() / "Assets/Characters/pilot/model.glb")
        self.assertTrue(path.is_file())

        artifact = self.manifest["assets"]["character:pilot"]["artifacts"]["model"]
        artifact["approval"]["status"] = "pending"
        with self.assertRaisesRegex(ValueError, "approved"):
            resolve_rigging_source(self.root, self.manifest, "character:pilot", "model")

    def test_rigging_source_requires_accepted_animation_readiness(self):
        character = self.manifest["assets"]["character:pilot"]
        character["animation_readiness"].update({"status": "needs_review", "approval": {"status": "pending"}})
        with self.assertRaisesRegex(ValueError, "animation-readiness"):
            resolve_rigging_source(self.root, self.manifest, "character:pilot", "model")
        character["animation_readiness"]["approval"]["status"] = "approved"
        self.assertEqual(resolve_rigging_source(self.root, self.manifest, "character:pilot", "model"),
                         self.root.resolve() / "Assets/Characters/pilot/model.glb")

    def test_rigging_readiness_must_match_selected_model_and_content(self):
        normalized = self.root / "Assets/Characters/pilot/normalized.glb"
        normalized.write_bytes(b"normalized model")
        register_artifact(self.manifest, "character:pilot", "normalized_model", "model.glb",
                          "Assets/Characters/pilot/normalized.glb", status="ready", approval_status="approved")
        with self.assertRaisesRegex(ValueError, "readiness.*source"):
            resolve_rigging_source(self.root, self.manifest, "character:pilot", "normalized_model")

        source = self.root / "Assets/Characters/pilot/model.glb"
        source.write_bytes(b"changed after readiness")
        with self.assertRaisesRegex(ValueError, "readiness.*source"):
            resolve_rigging_source(self.root, self.manifest, "character:pilot", "model")

    def test_skintokens_requires_the_approved_normalized_model(self):
        with self.assertRaisesRegex(ValueError, "normalized_model"):
            skintokens_character(self.root, {"asset_pipeline": {}}, self.manifest, "character:pilot")

    def test_unknown_configured_provider_fails_with_available_provider(self):
        config = {"asset_pipeline": {"character_rigging_provider": "unknown_provider"}}
        with self.assertRaisesRegex(ValueError, "available provider: blender_rigify"):
            run_character_rigging(self.root, config, self.manifest, "character:pilot")

    def test_skintokens_structure_requires_all_measured_gates(self):
        good = {"armature_count": 1, "skinned_component_count": 3,
                "unclassified_objects": [], "unweighted_vertices": 0,
                "weight_sum_min": 0.9999, "weight_sum_max": 1.0001,
                "max_influences": 4, "bind_pose_count": 28,
                "material_coverage": {"base_color": 1.0}}
        self.assertEqual(classify_skintokens_structure(good)["status"], "pass")
        for field, value in (("armature_count", 0), ("unclassified_objects", ["Mystery"]),
                             ("unweighted_vertices", 1), ("weight_sum_min", 0.8),
                             ("weight_sum_max", 1.2), ("max_influences", 5),
                             ("bind_pose_count", 0), ("skinned_component_count", 0)):
            bad = dict(good, **{field: value})
            self.assertEqual(classify_skintokens_structure(bad)["status"], "fail", field)
        self.assertEqual(classify_skintokens_structure(dict(good, material_coverage={"base_color": 0}))["status"], "fail")
        self.assertEqual(classify_skintokens_structure(dict(good, material_coverage={"base_color": 0.5}))["status"], "fail")

    def test_deformation_approval_requires_explicit_confirmation_and_complete_evidence(self):
        record_rigging_result(self.root, self.manifest, "character:pilot", self.result)
        character = self.manifest["assets"]["character:pilot"]
        character["rigging"]["structural_report"] = {"status": "pass"}
        with self.assertRaisesRegex(ValueError, "confirmation"):
            approve_deformation(self.root, self.manifest, "character:pilot", confirmed=False)
        with self.assertRaisesRegex(ValueError, "canonical"):
            approve_deformation(self.root, self.manifest, "character:pilot", confirmed=True)
        self.assertEqual(character["artifacts"]["rig"]["approval"]["status"], "pending")

    def test_skintokens_registers_only_postprocessed_fbx(self):
        config = {"asset_pipeline": {"character_rigging_provider": "skintokens",
                 "output_root": "Assets/Generated", "tools": {}}}
        with self.assertRaisesRegex(ValueError, "normalized"):
            run_character_rigging(self.root, config, self.manifest, "character:pilot")
        normalized = self.root / "Assets/Characters/pilot/normalized.glb"
        normalized.write_bytes(b"glTF")
        register_artifact(self.manifest, "character:pilot", "normalized_model", "model.glb",
                          "Assets/Characters/pilot/normalized.glb", status="ready", approval_status="approved")
        character = self.manifest["assets"]["character:pilot"]
        character["animation_readiness"] = {
            "measured": complete_measurements(),
            "status": "pass", "approval": {"status": "approved"}, "source_output": "normalized_model",
            "source": {"artifact_id": "normalized_model", "path": "Assets/Characters/pilot/normalized.glb",
                       "sha256": hashlib.sha256(normalized.read_bytes()).hexdigest()}}
        character["normalization"] = {"approval": {"status": "approved"}}
        def inference(_config, _source, output, *, seed):
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_bytes(b"raw glb")
            return {"revision": "rev", "checkpoint_id": "ckpt", "checkpoint_sha256": "a" * 64,
                    "output_sha256": "b" * 64, "seed": seed, "settings": {}}
        def blender(command, **_kwargs):
            request = __import__("json").loads(Path(command[-1]).read_text())
            self.assertEqual(request["checkpoint_sha256"], "a" * 64)
            Path(request["rigged_model"]).write_bytes(b"FBX")
            for path in request["evidence"].values():
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGBA", (2, 2), (0, 0, 0, 255)).save(path)
            Image.new("RGBA", (14, 2), (0, 0, 0, 255)).save(request["contact_sheet"])
            Path(request["report"]).write_text(__import__("json").dumps({
                "status": "complete", "armature_count": 1, "skinned_component_count": 1,
                "unclassified_objects": [], "unweighted_vertices": 0, "weight_sum_min": 1,
                "weight_sum_max": 1, "max_influences": 4, "bind_pose_count": 28,
                "material_coverage": {"base_color": 1.0}, "semantic_mapping": {"hips": "bone_0"},
                "deformation_evidence": {pose: {"max_vertex_displacement": 0.1}
                                         for pose in request["evidence"]}}))
        with patch("slopforge.character_rigging.run_skintokens_inference", side_effect=inference), \
             patch("slopforge.character_rigging.blender_executable", return_value="blender"), \
             patch("slopforge.character_rigging.subprocess.run", side_effect=blender):
            result = run_character_rigging(self.root, config, self.manifest, "character:pilot",
                                           source_output="normalized_model")
        character = self.manifest["assets"]["character:pilot"]
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(character["artifacts"]["rig"]["path"].split(".")[-1], "fbx")
        self.assertEqual(character["pipeline_status"]["deformation_status"], "needs_review")
        self.assertEqual(character["artifacts"]["rig"]["approval"]["status"], "pending")
        self.assertEqual(character["artifacts"]["rig"]["validation"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
