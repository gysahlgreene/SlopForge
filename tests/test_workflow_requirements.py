import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import yaml

from slopforge.doctor import run_doctor
from slopforge.initializer import init_project
from slopforge.workflow_requirements import (
    load_workflow_requirements,
    requirements_path,
    validate_workflow_requirements,
    workflow_requirements_identity,
)


class WorkflowRequirementsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workflow_path = Path(self.temp.name) / "sample.json"
        self.workflow = {
            "1": {"class_type": "LoadImage", "inputs": {}},
            "2": {"class_type": "UNETLoader", "inputs": {"unet_name": "model.safetensors"}},
        }
        self.workflow_path.write_text(json.dumps(self.workflow))
        self.manifest = {
            "schema_version": 1,
            "id": "test.image",
            "version": 1,
            "capabilities": ["image_generation"],
            "workflow_sha256": hashlib.sha256(self.workflow_path.read_bytes()).hexdigest(),
            "nodes": [
                {"class": "LoadImage", "source": "ComfyUI", "revision": "unknown"},
                {"class": "UNETLoader", "source": "ComfyUI", "revision": "unknown"},
            ],
            "models": [{"name": "model.safetensors", "source": "https://models.example/model",
                        "license": "unverified", "license_source": "https://models.example/license",
                        "sha256": "unknown"}],
            "inputs": [{"name": "image", "type": "image"}],
            "outputs": [{"name": "image", "type": "image/png"}],
            "profiles": ["default"],
            "tested_on": [{"profile": "default", "backend": "comfyui"}],
            "estimated_resource_class": "unknown",
        }

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self, manifest=None):
        path = requirements_path(self.workflow_path)
        path.write_text(yaml.safe_dump(manifest or self.manifest, sort_keys=False))
        return path

    def test_loads_adjacent_manifest_and_validates_graph_declarations(self):
        self.write_manifest()
        loaded = load_workflow_requirements(self.workflow_path)
        self.assertEqual(loaded["id"], "test.image")
        self.assertEqual(validate_workflow_requirements(self.workflow_path, self.workflow, loaded), [])

    def test_every_bundled_api_workflow_has_a_consistent_sidecar(self):
        from slopforge.paths import tool_root

        workflow_dir = tool_root() / "workflows"
        for path in workflow_dir.glob("*.json"):
            with self.subTest(workflow=path.name):
                manifest = load_workflow_requirements(path)
                self.assertIsNotNone(manifest)
                workflow = json.loads(path.read_text())
                self.assertEqual(validate_workflow_requirements(path, workflow, manifest), [])

    def test_legacy_workflow_without_sidecar_returns_unknown(self):
        self.assertFalse(requirements_path(self.workflow_path).exists())
        self.assertIsNone(load_workflow_requirements(self.workflow_path))

    def test_manifest_must_declare_every_graph_node_and_model(self):
        self.manifest["nodes"] = self.manifest["nodes"][:1]
        self.manifest["models"] = []
        self.write_manifest()
        loaded = load_workflow_requirements(self.workflow_path)
        problems = validate_workflow_requirements(self.workflow_path, self.workflow, loaded)
        self.assertTrue(any("UNETLoader" in problem for problem in problems))
        self.assertTrue(any("model.safetensors" in problem for problem in problems))

    def test_background_removal_checkpoint_is_a_declared_model_dependency(self):
        self.workflow["3"] = {"class_type": "LoadBackgroundRemovalModel",
                               "inputs": {"bg_removal_name": "birefnet.safetensors"}}
        self.workflow_path.write_text(json.dumps(self.workflow))
        self.manifest["workflow_sha256"] = hashlib.sha256(self.workflow_path.read_bytes()).hexdigest()
        self.manifest["nodes"].append({"class": "LoadBackgroundRemovalModel", "source": "ComfyUI",
                                        "revision": "unknown"})
        self.manifest["models"].append({"name": "birefnet.safetensors", "source": "ComfyUI",
                                         "license": "unverified", "license_source": "unverified",
                                         "sha256": "unknown"})
        self.write_manifest()
        loaded = load_workflow_requirements(self.workflow_path)
        self.assertEqual(validate_workflow_requirements(self.workflow_path, self.workflow, loaded), [])

    def test_workflow_hash_mismatch_invalidates_stale_sidecar(self):
        self.manifest["workflow_sha256"] = "0" * 64
        self.write_manifest()
        loaded = load_workflow_requirements(self.workflow_path)
        self.assertTrue(any("workflow_sha256" in problem
                            for problem in validate_workflow_requirements(self.workflow_path, self.workflow, loaded)))

    def test_identity_reports_sidecar_id_and_version_without_paths(self):
        self.write_manifest()
        self.assertEqual(workflow_requirements_identity(self.workflow_path, self.workflow),
                         {"id": "test.image", "version": 1, "schema_version": 1})

    def test_legacy_identity_is_explicitly_unknown(self):
        self.assertEqual(workflow_requirements_identity(self.workflow_path), {"status": "unknown"})

    def test_rejects_invalid_manifest_shape(self):
        self.write_manifest({"schema_version": 1, "id": "broken", "version": "one"})
        with self.assertRaisesRegex(ValueError, "version"):
            load_workflow_requirements(self.workflow_path)

    def test_doctor_reports_requirements_unknown_for_legacy_override(self):
        root, output = self.make_project_with_override()
        with redirect_stdout(output), patch("slopforge.doctor.ComfyUIClient.health", side_effect=OSError("offline")):
            result = run_doctor(root)
        self.assertEqual(result, 0)
        self.assertIn("WARN Workflow requirements — unknown", output.getvalue())

    def test_doctor_reports_override_manifest_and_unverified_backend_versions(self):
        root, output = self.make_project_with_override()
        override = root / "ai/workflows/sample.json"
        manifest = self.manifest.copy()
        manifest["workflow_sha256"] = hashlib.sha256(override.read_bytes()).hexdigest()
        requirements_path(override).write_text(yaml.safe_dump(manifest, sort_keys=False))
        node_info = {
            "LoadImage": {},
            "UNETLoader": {"input": {"required": {"unet_name": [["model.safetensors"], {}]}}},
        }
        for class_name in ("CLIPVisionEncode", "Hunyuan3Dv2Conditioning", "EmptyLatentHunyuan3Dv2",
                           "KSampler", "VAEDecodeHunyuan3D", "VoxelToMesh", "SaveGLB"):
            node_info[class_name] = {}
        node_info["ImageOnlyCheckpointLoader"] = {
            "input": {"required": {"ckpt_name": [["hunyuan3d-dit-v2_fp16.safetensors"], {}]}}
        }
        stats = {"system": {"comfyui_version": "0.0-test"}, "devices": []}
        with redirect_stdout(output), patch("slopforge.doctor.ComfyUIClient.health", return_value=stats), \
                patch("slopforge.doctor.ComfyUIClient.node_types", return_value=node_info):
            result = run_doctor(root)
        self.assertEqual(result, 0, output.getvalue())
        self.assertIn("PASS Workflow requirements — test.image v1", output.getvalue())
        self.assertIn("WARN Workflow dependency versions", output.getvalue())
        self.assertIn("model hash unknown", output.getvalue())

    def test_doctor_fails_when_requirement_node_is_missing_from_backend(self):
        root, output = self.make_project_with_override()
        override = root / "ai/workflows/sample.json"
        manifest = self.manifest.copy()
        manifest["workflow_sha256"] = hashlib.sha256(override.read_bytes()).hexdigest()
        requirements_path(override).write_text(yaml.safe_dump(manifest, sort_keys=False))
        with redirect_stdout(output), patch("slopforge.doctor.ComfyUIClient.health", return_value={"system": {}, "devices": []}), \
                patch("slopforge.doctor.ComfyUIClient.node_types", return_value={}):
            result = run_doctor(root)
        self.assertEqual(result, 1)
        self.assertIn("FAIL Workflow node capabilities", output.getvalue())
        self.assertIn("LoadImage", output.getvalue())

    def test_doctor_reports_unknown_inline_hunyuan_requirements_and_checks_checkpoint(self):
        root, output = self.make_project_with_override()
        node_info = {"LoadImage": {}, "UNETLoader": {"input": {"required": {
            "unet_name": [["model.safetensors"], {}]}}}}
        classes = ("CLIPVisionEncode", "Hunyuan3Dv2Conditioning", "EmptyLatentHunyuan3Dv2",
                   "KSampler", "VAEDecodeHunyuan3D", "VoxelToMesh", "SaveGLB")
        node_info.update({name: {} for name in classes})
        node_info["ImageOnlyCheckpointLoader"] = {"input": {"required": {
            "ckpt_name": [["other.safetensors"], {}]}}}
        with redirect_stdout(output), \
                patch("slopforge.doctor.ComfyUIClient.health", return_value={"system": {}, "devices": []}), \
                patch("slopforge.doctor.ComfyUIClient.node_types", return_value=node_info):
            result = run_doctor(root)
        self.assertEqual(result, 1)
        self.assertIn("WARN Model workflow requirements — unknown", output.getvalue())
        self.assertIn("FAIL Model workflow model choices", output.getvalue())
        self.assertIn("hunyuan3d-dit-v2_fp16.safetensors", output.getvalue())

    def make_project_with_override(self):
        root = Path(self.temp.name) / "project"
        (root / "Assets").mkdir(parents=True)
        init_project(root)
        (root / "ai/workflows").mkdir(parents=True, exist_ok=True)
        workflow_path = root / "ai/workflows/sample.json"
        workflow_path.write_text(json.dumps(self.workflow))
        project_config = """project: {name: Test, engine: unity}
asset_pipeline:
  active_style: default
  workflows: {image: sample.json}
"""
        (root / "ai/project.yaml").write_text(project_config)
        output = StringIO()
        return root, output


if __name__ == "__main__":
    unittest.main()
