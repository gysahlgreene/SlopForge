import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopforge.character_normalization import approve_character_normalization, normalize_character


def complete_report():
    return {"status": "pass", "uv_status": "pass", "warnings": [],
            "channels": {"base_color": "baked", "roughness": "absent", "metallic": "absent", "normal": "absent"},
            "components": [{"source": "Body", "output": "Normalized_Body",
                            "source_vertices": 8, "source_faces": 6,
                            "source_materials": ["Paint"],
                            "source_material_assignments": [{"slot": 0, "material": "Paint", "face_count": 6}],
                            "output_vertices": 8, "output_faces": 6,
                            "textures": {"base_color": "component_0_base_color.png"}}]}


class CharacterNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "Assets/Characters/pilot/model.glb"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"approved source")
        self.config = {"asset_pipeline": {"output_root": "Assets/Art/Generated",
                                          "model_budgets": {"character_faces": 60000}}}
        self.character = {"id": "character:pilot", "name": "pilot", "type": "character",
                          "artifacts": {"model": {"id": "model", "type": "model.glb",
                                                   "path": "Assets/Characters/pilot/model.glb", "status": "ready",
                                                   "approval": {"status": "approved"}}},
                          "animation_readiness": {"status": "pass", "approval": {"status": "approved"},
                                                  "source_output": "model", "source": {
                                                      "artifact_id": "model", "path": "Assets/Characters/pilot/model.glb",
                                                      "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()}}}
        self.manifest = {"assets": {"character:pilot": self.character}}

    def test_rejects_unapproved_non_model_missing_and_unsafe_inputs(self):
        original = hashlib.sha256(self.source.read_bytes()).hexdigest()
        cases = [({"approval": {"status": "pending"}}, None),
                 ({"type": "image.png"}, None),
                 ({"path": "Assets/Characters/pilot/missing.glb"}, None),
                 ({}, "../outside")]
        for artifact_change, output_root in cases:
            with self.subTest(artifact_change=artifact_change, output_root=output_root):
                manifest = copy.deepcopy(self.manifest)
                manifest["assets"]["character:pilot"]["artifacts"]["model"].update(artifact_change)
                config = copy.deepcopy(self.config)
                if output_root:
                    config["asset_pipeline"]["output_root"] = output_root
                with self.assertRaises((ValueError, FileNotFoundError)):
                    normalize_character(self.root, config, manifest, "pilot")
                self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original)
        candidate = self.root / "Assets/Art/Generated/Characters/pilot/Normalization/model.glb"
        candidate.parent.mkdir(parents=True)
        candidate.write_bytes(b"existing candidate")
        with self.assertRaises(FileExistsError):
            normalize_character(self.root, self.config, self.manifest, "pilot")
        self.assertEqual(candidate.read_bytes(), b"existing candidate")
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original)

    def test_rejects_stale_readiness_source_path_or_hash(self):
        original = hashlib.sha256(self.source.read_bytes()).hexdigest()
        for change in ({"path": "Assets/Characters/other/model.glb"}, {"sha256": "0" * 64}):
            with self.subTest(change=change):
                manifest = copy.deepcopy(self.manifest)
                manifest["assets"]["character:pilot"]["animation_readiness"]["source"].update(change)
                with self.assertRaises(ValueError):
                    normalize_character(self.root, self.config, manifest, "pilot")
                self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original)
        self.source.write_bytes(b"changed after readiness")
        with self.assertRaises(ValueError):
            normalize_character(self.root, self.config, self.manifest, "pilot")

    def test_rejects_incomplete_blender_report_before_registering(self):
        reports = ({"status": "pass", "uv_status": "pass", "channels": {"base_color": "baked"},
                    "components": [{"source": "Body", "output": "Body"}]},
                   {"status": "pass", "uv_status": "pass", "channels": {key: "absent" for key in
                    ("base_color", "roughness", "metallic", "normal")}, "components": []})
        for report in reports:
            with self.subTest(report=report):
                manifest = copy.deepcopy(self.manifest)
                def blender(command, **_):
                    request = json.loads(Path(command[-1]).read_text())
                    Path(request["output"]).write_bytes(b"normalized")
                    Path(request["report"]).write_text(json.dumps(report))

                with patch("slopforge.character_normalization.blender_executable", return_value="blender"), \
                     patch("slopforge.character_normalization.subprocess.run", side_effect=blender):
                    with self.assertRaises(ValueError):
                        normalize_character(self.root, self.config, manifest, "pilot")
                self.assertNotIn("normalized_model", manifest["assets"]["character:pilot"]["artifacts"])

    def test_approval_rejects_incomplete_report(self):
        output = self.root / "normalized.glb"
        output.write_bytes(b"normalized")
        self.character["artifacts"]["normalized_model"] = {"path": "normalized.glb", "approval": {"status": "pending"}}
        self.character["normalization"] = {"report_path": "report.json"}
        for report in ({"status": "pass", "uv_status": "pass", "channels": {"base_color": "baked"},
                        "components": [{"source": "Body", "output": "Body"}]},
                       {"status": "pass", "uv_status": "pass", "channels": {key: "absent" for key in
                        ("base_color", "roughness", "metallic", "normal")}, "components": []}):
            with self.subTest(report=report):
                report["normalized"] = {"sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
                (self.root / "report.json").write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    approve_character_normalization(self.root, self.manifest, "pilot")
                self.assertEqual(self.character["artifacts"]["normalized_model"]["approval"]["status"], "pending")

    def test_success_stays_pending_until_explicit_approval(self):
        def blender(command, **_):
            request = json.loads(Path(command[-1]).read_text())
            Path(request["output"]).parent.mkdir(parents=True, exist_ok=True)
            Path(request["output"]).write_bytes(b"normalized")
            (Path(request["output"]).parent / "component_0_base_color.png").write_bytes(b"PNG data")
            Path(request["report"]).write_text(json.dumps(complete_report()))

        with patch("slopforge.character_normalization.blender_executable", return_value="blender"), \
             patch("slopforge.character_normalization.subprocess.run", side_effect=blender):
            result = normalize_character(self.root, self.config, self.manifest, "pilot")
        artifact = self.character["artifacts"]["normalized_model"]
        self.assertEqual(artifact["approval"]["status"], "pending")
        self.assertEqual(result["source"]["sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        approve_character_normalization(self.root, self.manifest, "pilot")
        self.assertEqual(artifact["approval"]["status"], "approved")
        self.assertEqual(artifact["status"], "ready")

    def test_rejects_malformed_component_evidence_at_recording_and_approval(self):
        variants = []
        for change in ({"source_faces": 0}, {"output_vertices": 0},
                       {"source_material_assignments": [{"slot": 0, "material": "Paint", "face_count": 5}]},
                       {"textures": {}}, {"textures": {"base_color": "missing.png"}},
                       {"textures": {"base_color": "empty.png"}}):
            report = complete_report()
            report["components"][0].update(change)
            variants.append(report)
        optional = complete_report()
        optional["channels"]["roughness"] = "baked"
        variants.append(optional)
        optional = complete_report()
        optional["components"][0]["textures"]["roughness"] = "component_0_base_color.png"
        variants.append(optional)
        for report in variants:
            with self.subTest(report=report):
                shutil.rmtree(self.root / "Assets/Art/Generated/Characters/pilot/Normalization", ignore_errors=True)
                manifest = copy.deepcopy(self.manifest)

                def blender(command, **_):
                    request = json.loads(Path(command[-1]).read_text())
                    output = Path(request["output"])
                    output.write_bytes(b"normalized")
                    (output.parent / "component_0_base_color.png").write_bytes(b"PNG data")
                    (output.parent / "empty.png").write_bytes(b"")
                    Path(request["report"]).write_text(json.dumps(report))

                with patch("slopforge.character_normalization.blender_executable", return_value="blender"), \
                     patch("slopforge.character_normalization.subprocess.run", side_effect=blender):
                    with self.assertRaises(ValueError):
                        normalize_character(self.root, self.config, manifest, "pilot")
                self.assertNotIn("normalized_model", manifest["assets"]["character:pilot"]["artifacts"])

                output = self.root / "normalized.glb"
                output.write_bytes(b"normalized")
                (self.root / "component_0_base_color.png").write_bytes(b"PNG data")
                (self.root / "empty.png").write_bytes(b"")
                saved = copy.deepcopy(report)
                saved["normalized"] = {"sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
                (self.root / "report.json").write_text(json.dumps(saved))
                character = manifest["assets"]["character:pilot"]
                character["artifacts"]["normalized_model"] = {"path": "normalized.glb", "approval": {"status": "pending"}}
                character["normalization"] = {"report_path": "report.json"}
                with self.assertRaises(ValueError):
                    approve_character_normalization(self.root, manifest, "pilot")
                self.assertEqual(character["artifacts"]["normalized_model"]["approval"]["status"], "pending")

    def test_approval_rejects_failed_geometry_or_bake(self):
        report_path = self.root / "report.json"
        for report in ({"status": "fail", "uv_status": "pass", "channels": {"base_color": "baked"}},
                       {"status": "pass", "uv_status": "fail", "channels": {"base_color": "baked"}},
                       {"status": "pass", "uv_status": "pass", "channels": {"base_color": "failed"}}):
            report_path.write_text(json.dumps(report))
            self.character["normalization"] = {"status": report["status"], "report_path": "report.json"}
            self.character["artifacts"]["normalized_model"] = {"approval": {"status": "pending"}}
            with self.assertRaises(ValueError):
                approve_character_normalization(self.root, self.manifest, "pilot")
