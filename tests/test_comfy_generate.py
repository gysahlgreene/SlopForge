import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from processing import comfy_generate
from processing.comfy_generate import find_save_node


def test_comfy_generation_selects_only_image_outputs():
    assert find_save_node({"1": {"class_type": "SaveVideo"}}) is None
    assert find_save_node({"1": {"class_type": "SaveImage"}}) == "1"


def test_effective_workflow_hash_is_after_all_image_bindings(monkeypatch):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        workflow_path = root / "workflow.json"
        workflow_path.write_text(json.dumps({
            "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
            "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
            "4": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "5": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
            "6": {"class_type": "Custom", "inputs": {"steps": 1, "strength": 0.5}},
        }))
        reference = root / "ref.png"
        reference.write_bytes(b"reference bytes")
        destination, metadata = root / "result.png", root / "generation.json"

        class Client:
            def __init__(self, _url): pass
            def upload_input(self, _path, _folder): return {"name": "random-upload.png", "subfolder": "tmp"}
            def queue_workflow(self, workflow):
                self.workflow = workflow
                return "prompt-1"
            def wait_for_completion(self, _prompt, timeout): return {"outputs": {}}
            def list_outputs(self, _history):
                return [{"filename": "out.png", "subfolder": "", "type": "output"}]
            def download_output(self, _item, path): Path(path).write_bytes(b"generated image")

        client = Client("http://comfy")
        monkeypatch.setattr(comfy_generate, "ComfyUIClient", lambda _url: client)
        monkeypatch.setattr(sys, "argv", ["comfy_generate.py", "--workflow", str(workflow_path),
            "--prompt", "bound prompt", "--negative", "bound negative", "--dest", str(destination),
            "--prefix", "incidental/output", "--seed", "17", "--metadata", str(metadata),
            "--references", json.dumps([{"path": str(reference), "strength": 0.7, "sha256": "ref-digest"}]),
            "--reference-inputs", json.dumps([{"image": {"node": "4", "input": "image"},
                                               "strength": {"node": "6", "input": "strength"}}]),
            "--workflow-inputs", json.dumps({"6": {"steps": 9}})])

        comfy_generate.main()
        saved = json.loads(metadata.read_text())
        assert saved["workflow_source_sha256"] != saved["workflow_effective_sha256"]
        assert saved["effective_bindings"]["uploaded_inputs"]["4.image"] == __import__("hashlib").sha256(b"reference bytes").hexdigest()
        assert "random-upload.png" not in json.dumps(saved["effective_bindings"])
        assert saved["outputs"][0]["sha256"] == __import__("hashlib").sha256(b"generated image").hexdigest()
