import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from slopforge.backends.comfyui import ComfyUIClient


ROOT = Path(__file__).resolve().parents[1]
URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")


def require_flag(name):
    if os.environ.get(name) != "1":
        pytest.skip(f"set {name}=1 to run against a live ComfyUI service")


def test_live_comfyui_2d_generation_and_http_file_transfer():
    require_flag("SLOPFORGE_COMFYUI_INTEGRATION")
    client = ComfyUIClient(URL)
    stats = client.health()
    assert stats.get("system", {}).get("comfyui_version")

    workflow = json.loads((ROOT / "workflows/image_text2img_api.json").read_text())
    for node in workflow.values():
        if node.get("class_type") == "CLIPTextEncode":
            node["inputs"]["text"] = "A simple blue ceramic game potion bottle, isolated, clear silhouette"
        elif node.get("class_type") == "KSampler":
            node["inputs"]["seed"] = 7012026
        elif node.get("class_type") == "SaveImage":
            node["inputs"]["filename_prefix"] = "slopforge_integration/remote_2d"

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        uploaded_file = root / "upload_probe.png"
        Image.new("RGB", (8, 8), (20, 80, 160)).save(uploaded_file)
        uploaded = client.upload_file(uploaded_file, "slopforge_integration")
        restored_upload = root / "restored_upload.png"
        client.download_output({"filename": uploaded["name"], "subfolder": uploaded["subfolder"],
                                "type": uploaded["type"]}, restored_upload)
        assert restored_upload.read_bytes() == uploaded_file.read_bytes()

        prompt_id = client.queue_workflow(workflow)
        history = client.wait_for_completion(prompt_id, timeout=900)
        outputs = [item for item in client.list_outputs(history) if item["filename"].lower().endswith(".png")]
        assert outputs, "ComfyUI completed the image prompt without a PNG output"
        restored_image = root / "generated.png"
        client.download_output(outputs[0], restored_image)
        with Image.open(restored_image) as image:
            image.verify()


def test_live_h100_trellis_bf16_and_local_blender_pipeline():
    require_flag("SLOPFORGE_COMFYUI_3D_INTEGRATION")
    blender = os.environ.get("BLENDER_BIN", "/Applications/Blender.app/Contents/MacOS/Blender")
    if not Path(blender).is_file():
        pytest.skip("set BLENDER_BIN to run the full local Blender continuation")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        concept = ROOT / "img/power-relay-concept.png"
        output = root / "relay.glb"
        command = [sys.executable, str(ROOT / "processing/comfy_generate_3d.py"), "--image", str(concept),
                   "--name", "integration_relay", "--dest", str(output), "--workflow",
                   str(ROOT / "workflows/trellis2_image_to_model_h100_api.json"), "--seed", "7012026",
                   "--face-budget", "12000", "--blender", blender]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join((str(ROOT), environment.get("PYTHONPATH", "")))
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=7200)
        assert result.returncode == 0, result.stdout + "\n" + result.stderr
        assert output.is_file() and output.stat().st_size > 1024
        assert (root / "native_material/basecolor.png").is_file()
        assert (root / "native_material/metallic.png").is_file()
        assert (root / "native_material/roughness.png").is_file()
