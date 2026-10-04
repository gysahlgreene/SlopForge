import tempfile
from PIL import Image
import unittest
from pathlib import Path

from slopforge.character_rigging import record_rigging_result, resolve_rigging_source, run_character_rigging
from slopforge.manifest import new_record, register_artifact


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
        self.result = {
            "provider": {"name": "sample", "version": "1.2", "source": "https://example.test/provider",
                         "license": "MIT"},
            "source_output": "model",
            "rigged_model": "Assets/Characters/pilot/rigged.fbx",
            "evidence": {"t_pose": "Assets/Characters/pilot/review/t_pose.png"},
            "skeleton_mapping": {"hips": "pelvis", "left_upper_arm": "upperarm_l"},
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

    def test_unknown_configured_provider_fails_with_available_provider(self):
        config = {"asset_pipeline": {"character_rigging_provider": "unknown_provider"}}
        with self.assertRaisesRegex(ValueError, "available provider: blender_rigify"):
            run_character_rigging(self.root, config, self.manifest, "character:pilot")


if __name__ == "__main__":
    unittest.main()
