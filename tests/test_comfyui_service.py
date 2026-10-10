import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from slopforge.backends.comfyui import ComfyUIClient, comfy_environment, backend_provenance
from slopforge.config import load_project
from slopforge.paths import comfy_backend, comfy_home


class Response:
    def __init__(self, body=b"{}"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class ComfyUIServiceTests(unittest.TestCase):
    def test_backend_provenance_uses_exposed_facts_or_unavailable(self):
        facts = backend_provenance({"system": {"comfyui_version": "0.3.1"},
                                    "devices": [{"name": "NVIDIA GPU"}]}, queried=True)
        self.assertEqual(facts["provider"], {"status": "known", "value": "ComfyUI"})
        self.assertEqual(facts["version"], {"status": "known", "value": "0.3.1"})
        self.assertEqual(facts["device"], {"status": "known", "value": ["NVIDIA GPU"]})
        self.assertEqual(facts["model_weights"]["status"], "unavailable")
        self.assertEqual(facts["custom_node_revisions"]["status"], "unavailable")
        absent = backend_provenance({}, queried=False)
        self.assertEqual(absent["version"]["status"], "not_recorded")
        self.assertEqual(absent["device"]["status"], "not_recorded")

    def test_local_and_remote_backend_selection_does_not_select_compute_profile(self):
        config = {"asset_pipeline": {"tools": {"comfy_url": "http://127.0.0.1:8188", "comfy_backend": "auto"}}}
        self.assertEqual(comfy_backend(config), "local")
        config["asset_pipeline"]["tools"]["comfy_url"] = "http://127.0.0.2:8188"
        self.assertEqual(comfy_backend(config), "local")
        config["asset_pipeline"]["tools"]["comfy_url"] = "http://gpu.example:8188"
        self.assertEqual(comfy_backend(config), "remote")
        with patch.dict("os.environ", {"SLOPFORGE_COMFYUI_BACKEND": "local"}):
            self.assertEqual(comfy_backend(config), "local")

    def test_remote_configuration_does_not_require_comfyui_home(self):
        config = {"asset_pipeline": {"tools": {"comfy_url": "http://gpu.example:8188", "comfy_home": None}}}
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(comfy_home(config))

    def test_subprocess_environment_omits_comfy_home_for_http_backend(self):
        config = {"asset_pipeline": {"tools": {"comfy_url": "http://gpu.example:8188",
                                                  "comfy_backend": "auto", "comfy_home": None},
                                      "selected_compute_profile": "h100"}}
        with patch.dict("os.environ", {"COMFYUI_HOME": "/remote/path/that/is/not/local"}):
            environment = comfy_environment(config)
        self.assertEqual(environment["COMFYUI_URL"], "http://gpu.example:8188")
        self.assertEqual(environment["SLOPFORGE_COMFYUI_BACKEND"], "remote")
        self.assertEqual(environment["SLOPFORGE_COMPUTE_PROFILE"], "h100")
        self.assertNotIn("COMFYUI_HOME", environment)

    def test_compute_profile_overrides_workflow_independent_of_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ai").mkdir()
            (root / "ai/project.yaml").write_text(
                "project: {name: test}\nasset_pipeline:\n  active_style: plain\n"
                "  workflows: {image: base.json}\n  compute_profiles:\n"
                "    fast:\n      workflows: {image: fast.json}\n      tools: {comfy_url: 'http://wrong.example:8188', hunyuan_checkpoint: test.safetensors}\n"
            )
            with patch.dict("os.environ", {"COMFYUI_URL": "http://gpu.example:8188",
                                            "SLOPFORGE_COMPUTE_PROFILE": "fast"}, clear=True):
                config = load_project(root)
        self.assertEqual(config["asset_pipeline"]["workflows"]["image"], "fast.json")
        self.assertEqual(config["asset_pipeline"]["selected_compute_profile"], "fast")
        self.assertEqual(comfy_backend(config), "remote")
        self.assertEqual(config["asset_pipeline"]["tools"]["comfy_url"], "http://gpu.example:8188")
        self.assertEqual(config["asset_pipeline"]["tools"]["hunyuan_checkpoint"], "test.safetensors")

    def test_remote_urls_use_the_same_health_and_node_api(self):
        calls = []

        def open_request(request, timeout):
            calls.append((request.full_url, timeout))
            return Response(b'{"KSampler": {}}')

        client = ComfyUIClient("http://gpu.example:8188")
        with patch("slopforge.backends.comfyui.urlopen", open_request):
            self.assertEqual(client.node_types(), {"KSampler": {}})
        self.assertEqual(calls[0][0], "http://gpu.example:8188/object_info")

    def test_upload_uses_comfyui_multipart_api(self):
        captured = []

        def open_request(request, timeout):
            captured.append(request)
            return Response(b'{"name":"input.png","subfolder":"slopforge","type":"input"}')

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            image.write_bytes(b"png bytes")
            client = ComfyUIClient("http://remote:8188")
            with patch("slopforge.backends.comfyui.urlopen", open_request):
                result = client.upload_input(image, "slopforge")

        request = captured[0]
        self.assertEqual(result["name"], "input.png")
        self.assertEqual(request.full_url, "http://remote:8188/upload/image")
        self.assertIn(b'name="image"; filename="source.png"', request.data)
        self.assertIn(b"png bytes", request.data)
        self.assertIn(b'name="subfolder"', request.data)

    def test_output_download_uses_view_for_non_image_files(self):
        client = ComfyUIClient("http://remote:8188")
        captured = []

        def open_request(request, timeout):
            captured.append(request.full_url)
            return Response(b"glb data")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "model.glb"
            with patch("slopforge.backends.comfyui.urlopen", open_request):
                client.download_output({"filename": "model.glb", "subfolder": "models", "type": "output"}, destination)
            self.assertEqual(destination.read_bytes(), b"glb data")
        self.assertEqual(captured, ["http://remote:8188/view?filename=model.glb&subfolder=models&type=output"])

    def test_failed_prompt_exposes_node_error(self):
        def open_request(request, timeout):
            return Response(b'{"node_errors":{"4":{"errors":[{"message":"missing custom node"}]}}}')

        with patch("slopforge.backends.comfyui.urlopen", open_request):
            with self.assertRaisesRegex(RuntimeError, "missing custom node"):
                ComfyUIClient("http://localhost:8188").queue_workflow({})

    def test_workflow_validation_reports_missing_node_before_queueing(self):
        calls = []

        def open_request(request, timeout):
            calls.append(request.full_url)
            return Response(b"{}")

        with patch("slopforge.backends.comfyui.urlopen", open_request):
            with self.assertRaisesRegex(RuntimeError, "missing workflow node classes: CustomNode"):
                ComfyUIClient("http://remote:8188").queue_workflow({"1": {"class_type": "CustomNode", "inputs": {}}})
        self.assertEqual(calls, ["http://remote:8188/object_info"])

    def test_workflow_validation_reports_model_choices(self):
        body = json.dumps({"UNETLoader": {"input": {"required": {
            "unet_name": [["available.safetensors"], {}]}}}}).encode()

        with patch("slopforge.backends.comfyui.urlopen", lambda request, timeout: Response(body)):
            with self.assertRaisesRegex(RuntimeError, "UNETLoader.unet_name: missing.safetensors"):
                ComfyUIClient("http://remote:8188").validate_workflow({"1": {
                    "class_type": "UNETLoader", "inputs": {"unet_name": "missing.safetensors"}}})

    def test_transparency_mask_cannot_feed_foreground_crop_before_network_or_queue(self):
        workflow = {
            "image": {"class_type": "LoadImage", "inputs": {"image": "narrow.png"}},
            "crop": {"class_type": "ImageCropToMask", "inputs": {"masks": ["image", 1]}},
        }
        with patch("slopforge.backends.comfyui.urlopen") as request:
            with self.assertRaisesRegex(RuntimeError, "crop.*InvertMask"):
                ComfyUIClient("http://remote:8188").queue_workflow(workflow)
        request.assert_not_called()

    def test_explicit_foreground_mask_passes_validation(self):
        workflow = {
            "image": {"class_type": "LoadImage", "inputs": {"image": "narrow.png"}},
            "foreground": {"class_type": "InvertMask", "inputs": {"mask": ["image", 1]}},
            "crop": {"class_type": "ImageCropToMask", "inputs": {"masks": ["foreground", 0]}},
        }
        info = {node["class_type"]: {} for node in workflow.values()}
        self.assertEqual(ComfyUIClient("http://remote:8188").validate_workflow(workflow, info), info)

    def test_workflow_validation_checks_background_removal_model_choices(self):
        body = json.dumps({"LoadBackgroundRemovalModel": {"input": {"required": {
            "bg_removal_name": [["birefnet.safetensors"], {}]}}}}).encode()

        with patch("slopforge.backends.comfyui.urlopen", lambda request, timeout: Response(body)):
            with self.assertRaisesRegex(RuntimeError, "LoadBackgroundRemovalModel.bg_removal_name: missing.safetensors"):
                ComfyUIClient("http://remote:8188").validate_workflow({"1": {
                    "class_type": "LoadBackgroundRemovalModel",
                    "inputs": {"bg_removal_name": "missing.safetensors"}}})

    def test_history_waits_until_generation_is_complete(self):
        client = ComfyUIClient("http://remote:8188")
        client.history = Mock(side_effect=[
            {"status": {"completed": False}, "outputs": {"raw": {}}},
            {"status": {"completed": True}, "outputs": {"final": {}}},
        ])
        with patch("slopforge.backends.comfyui.time.sleep"):
            result = client.wait_for_completion("prompt", timeout=2)
        self.assertIn("final", result["outputs"])
        self.assertEqual(client.history.call_count, 2)


if __name__ == "__main__":
    unittest.main()
