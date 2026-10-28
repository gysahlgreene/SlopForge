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
        assert saved["output_rights"] == [{"source": "workflow.json", "status": "unknown",
                                           "reason": "workflow.json has no requirements sidecar naming its models"}]


def test_downloads_saved_output_not_a_preview(monkeypatch, tmp_path):
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(json.dumps({
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
    }))
    downloaded = []

    class Client:
        def queue_workflow(self, _workflow): return "prompt-1"
        def wait_for_completion(self, _prompt, timeout): return {"outputs": {}}
        def list_outputs(self, _history):
            return [{"filename": "preview.png", "subfolder": "", "type": "temp"},
                    {"filename": "saved.png", "subfolder": "", "type": "output"}]
        def download_output(self, item, path):
            downloaded.append(item["filename"])
            Path(path).write_bytes(b"image")

    monkeypatch.setattr(comfy_generate, "ComfyUIClient", lambda _url: Client())
    monkeypatch.setattr(sys, "argv", ["comfy_generate.py", "--workflow", str(workflow_path),
                                      "--prompt", "p", "--dest", str(tmp_path / "result.png")])
    comfy_generate.main()
    assert downloaded == ["saved.png"]


def _video_run(monkeypatch, tmp_path, outputs):
    """The worker in its video mode (B5) against a fake ComfyUI client; returns the client and the paths."""
    workflow_path = tmp_path / "video.json"
    workflow_path.write_text(json.dumps({
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
        "3": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
        "4": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 1}},
        "5": {"class_type": "SaveImage", "inputs": {"filename_prefix": "preview"}},
        "6": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "old", "format": "mp4"}},
    }))
    start = tmp_path / "start.png"
    start.write_bytes(b"start frame")
    paths = {"dest": tmp_path / "walk.mp4", "metadata": tmp_path / "generation.json",
             "report": tmp_path / "failure.json"}

    class Client:
        def __init__(self, _url): self.uploads = []
        def upload_input(self, path, _folder):
            self.uploads.append(Path(path).name)
            return {"name": "uploaded-start.png", "subfolder": "slopforge"}
        def queue_workflow(self, workflow):
            self.workflow = workflow
            return "prompt-9"
        def wait_for_completion(self, _prompt, timeout):
            self.timeout = timeout
            return {"outputs": {}}
        def list_outputs(self, _history): return outputs
        def download_output(self, item, path): Path(path).write_bytes(b"generated video")

    client = Client("http://comfy")
    monkeypatch.setattr(comfy_generate, "ComfyUIClient", lambda _url: client)
    monkeypatch.setattr(sys, "argv", ["comfy_generate.py", "--workflow", str(workflow_path), "--output", "video",
                                      "--image", str(start), "--timeout", "3600", "--prompt", "walk", "--negative",
                                      "turning", "--dest", str(paths["dest"]), "--prefix", "video/wolf", "--seed", "7",
                                      "--metadata", str(paths["metadata"]), "--failure-report", str(paths["report"])])
    return client, paths


def test_video_mode_binds_the_start_image_saves_the_video_and_waits_longer(monkeypatch, tmp_path):
    client, paths = _video_run(monkeypatch, tmp_path, [
        {"filename": "preview.png", "subfolder": "", "type": "output"},
        {"filename": "wolf_00001_.mp4", "subfolder": "video", "type": "output"}])
    comfy_generate.main()
    graph = client.workflow
    assert graph["3"]["inputs"]["image"] == "slopforge/uploaded-start.png" and client.uploads == ["start.png"]
    assert graph["6"]["inputs"]["filename_prefix"] == "video/wolf" and graph["4"]["inputs"]["noise_seed"] == 7
    assert graph["1"]["inputs"]["text"] == "walk" and graph["2"]["inputs"]["text"] == "turning"
    assert client.timeout == 3600 and paths["dest"].read_bytes() == b"generated video"
    saved = json.loads(paths["metadata"].read_text())
    assert saved["output_kind"] == "video" and saved["outputs"][0]["kind"] == "video"
    assert saved["outputs"][0]["source_filename"] == "wolf_00001_.mp4"
    digest = __import__("hashlib").sha256(b"start frame").hexdigest()
    assert saved["effective_bindings"]["uploaded_inputs"]["3.image"] == digest


def test_a_video_run_that_returns_no_video_is_a_retryable_refusal(monkeypatch, tmp_path):
    from slopforge.failures import StageFailure, failure_record
    _, paths = _video_run(monkeypatch, tmp_path, [{"filename": "preview.png", "subfolder": "", "type": "output"}])
    try:
        comfy_generate.main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("a run without a video must fail")
    report = json.loads(paths["report"].read_text())
    assert report["category"] == "candidate_quality"
    validation = report["evidence"]["validation"]
    assert validation["failure_codes"] == ["video_refused"] and validation["artifact_kind"] == "video"
    failure = failure_record(StageFailure(report["category"], report["message"], operation=report["operation"],
                                          remedy="generate the next seed", evidence=report["evidence"]),
                             stage="video_generation", attempt=1, operation="video_generation")
    assert failure["retryable"]
