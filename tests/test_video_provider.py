"""B5's video provider: Wan 2.2 image-to-video in ComfyUI behind the same worker as images, in its video mode."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from slopforge.backends import comfyui
from slopforge.failures import StageFailure

ROOT = Path(__file__).resolve().parents[1]


def config():
    return {"asset_pipeline": {"tools": {"asset_python": sys.executable}, "workflows": {}, "quality_settings": {},
                               "selected_quality_tier": "normal", "selected_compute_profile": "h100",
                               "comfy_url": "http://127.0.0.1:8188"}}


def test_generate_video_runs_the_worker_in_its_video_mode(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(comfyui.subprocess, "run", lambda command, **_: calls.append(command)
                        or subprocess.CompletedProcess(command, 0))
    start = tmp_path / "start.png"
    comfyui.generate_video(tmp_path, config(), ROOT / "workflows/video_wan22_i2v_api.json", "walk", "turning",
                           start, tmp_path / "walk.mp4", 7, tmp_path / "walk.json",
                           workflow_inputs={"10": {"length": 121}}, timeout=3600)
    command = calls[0]
    assert command[1].endswith("processing/comfy_generate.py")
    option = lambda name: command[command.index(name) + 1]
    assert option("--output") == "video" and option("--image") == str(start) and option("--timeout") == "3600"
    assert option("--prompt") == "walk" and option("--negative") == "turning" and option("--seed") == "7"
    assert json.loads(option("--workflow-inputs")) == {"10": {"length": 121}}


def test_a_refused_video_raises_its_retryable_failure(monkeypatch, tmp_path):
    def run(command, **_):
        report = command[command.index("--failure-report") + 1]
        Path(report).write_text(json.dumps({"version": "v1", "category": "candidate_quality", "operation":
                                            "video_generation", "message": "no video", "exception_type": "ComfyUIError",
                                            "evidence": {"validation": {"failure_codes": ["video_refused"]}}}))
        return subprocess.CompletedProcess(command, 1)
    monkeypatch.setattr(comfyui.subprocess, "run", run)
    with pytest.raises(StageFailure) as caught:
        comfyui.generate_video(tmp_path, config(), ROOT / "workflows/video_wan22_i2v_api.json", "walk", "", tmp_path /
                               "start.png", tmp_path / "walk.mp4", 1, tmp_path / "walk.json")
    assert caught.value.category == "candidate_quality"
    assert caught.value.evidence["validation"]["failure_codes"] == ["video_refused"]
