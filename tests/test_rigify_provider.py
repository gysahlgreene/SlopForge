import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from slopforge.character_rigging import rigify_character, welding_tolerance
from slopforge.cli import parse_args
from readiness_fixture import complete_measurements
from slopforge.manifest import new_record, register_artifact


class RigifyProviderTests(unittest.TestCase):
    def _approve_readiness(self):
        artifact = self.manifest["assets"]["character:pilot"]["artifacts"]["model"]
        source = self.root / artifact["path"]
        self.manifest["assets"]["character:pilot"]["animation_readiness"] = {
            "measured": complete_measurements(),
            "status": "pass", "approval": {"status": "approved"}, "source_output": "model",
            "source": {"artifact_id": artifact["id"], "path": artifact["path"],
                       "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        source = self.root / "Assets/Characters/pilot/model.glb"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"glTF fixture")
        character = new_record("character", "pilot", "Pilot", {"name": "default", "version": 1},
                              {"strategy": "text_only"})
        self.manifest = {"assets": {"character:pilot": character}}
        register_artifact(self.manifest, "character:pilot", "model", "model.glb",
                          "Assets/Characters/pilot/model.glb", status="ready", approval_status="approved")
        self.config = {"asset_pipeline": {"output_root": "Assets/Art/Generated", "tools": {"blender": "/fake/blender"}}}

    def tearDown(self):
        self.temp.cleanup()

    def test_weld_tolerance_scales_with_model_units_without_changing_shape(self):
        self.assertAlmostEqual(welding_tolerance((0, 0, 0), (2, 1, 0.5)), 0.00002)

    def test_cli_selects_the_rigify_provider_and_source_artifact(self):
        args = parse_args(["--project", str(self.root), "character", "rig", "pilot",
                           "--source-output", "model"])
        self.assertEqual((args.command, args.character_action, args.name, args.source_output),
                         ("character", "rig", "pilot", "model"))

    def test_real_provider_adapter_records_pending_rig_and_pose_artifacts(self):
        self._approve_readiness()
        def fake_blender(command, check):
            request = json.loads(Path(command[-1]).read_text())
            Path(request["rigged_model"]).parent.mkdir(parents=True, exist_ok=True)
            Path(request["rigged_model"]).write_bytes(b"FBX fixture")
            evidence = {}
            for pose, filename in request["evidence"].items():
                path = Path(filename)
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (4, 4), (80, 90, 100)).save(path)
                evidence[pose] = path.relative_to(self.root).as_posix()
            result = {"status": "complete", "provider": {"name": "Blender Rigify", "version": "5.1.0",
                                   "source": "https://docs.blender.org/manual/en/5.1/addons/rigging/rigify/",
                                   "license": "GPL-2.0-or-later"},
                      "rigged_model": Path(request["rigged_model"]).relative_to(self.root).as_posix(),
                      "evidence": evidence, "skeleton_mapping": {"DEF-spine": "DEF-spine"},
                      "deformation_evidence": {"leg_lift": {"max_vertex_displacement": 0.25}},
                      "mesh_repair": {"weld_tolerance": 0.00001, "meshes": [{"merged_vertices": 10, "boundary_edges": 0, "nonmanifold_edges": 0}]}}
            Path(request["report"]).write_text(json.dumps(result))

        with patch("slopforge.character_rigging.subprocess.run", side_effect=fake_blender) as run:
            output = rigify_character(self.root, self.config, self.manifest, "character:pilot")
        run.assert_called_once()
        asset = self.manifest["assets"]["character:pilot"]
        self.assertEqual(output["status"], "review_required")
        self.assertEqual(asset["artifacts"]["rig"]["approval"]["status"], "pending")
        self.assertEqual(asset["artifacts"]["rig"]["provenance"]["license"], "GPL-2.0-or-later")
        self.assertEqual(len([key for key in asset["artifacts"] if key.startswith("rig_pose.")]), 6)
        self.assertEqual(asset["rigging"]["deformation_evidence"]["leg_lift"]["max_vertex_displacement"], 0.25)
        self.assertEqual(asset["rigging"]["mesh_repair"]["meshes"][0]["merged_vertices"], 10)

    def test_failed_provider_report_is_actionable_and_cleans_its_partial_files(self):
        self._approve_readiness()
        def failed_blender(command, check):
            request = json.loads(Path(command[-1]).read_text())
            Path(request["rigged_model"]).parent.mkdir(parents=True, exist_ok=True)
            Path(request["rigged_model"]).write_bytes(b"partial")
            Path(request["report"]).write_text(json.dumps({"status": "failed", "error": "no weights were produced"}))

        with patch("slopforge.character_rigging.subprocess.run", side_effect=failed_blender):
            with self.assertRaisesRegex(RuntimeError, "no weights were produced"):
                rigify_character(self.root, self.config, self.manifest, "character:pilot")
        output = self.root / "Assets/Art/Generated/Characters/pilot/Rigging"
        self.assertFalse((output / "pilot_rigged.fbx").exists())
        self.assertFalse(any((output / "Review").glob("*.png")))


if __name__ == "__main__":
    unittest.main()
