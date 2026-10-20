import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from processing import comfy_generate, comfy_generate_3d
from processing.prepare_views import PAD, frame_views, mirror_iou


def _box(width, height, canvas=400):
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    image.paste((200, 60, 40, 255), (10, 20, 10 + width, 20 + height))
    return image


def _extent(image):
    return image.getchannel("A").getbbox()


def test_views_share_one_object_height_and_one_scale():
    # The side was drawn at half the front's scale; framing must undo that before Pixal3D reads depth.
    framed = frame_views({"front": _box(200, 100), "left": _box(50, 50)}, size=1024)
    front, left = (_extent(framed[name]) for name in ("front", "left"))
    assert front[2] - front[0] == pytest.approx(1024 / PAD, abs=2)
    assert left[3] - left[1] == pytest.approx(front[3] - front[1], abs=2)
    assert left[2] - left[0] == pytest.approx((front[2] - front[0]) / 2, abs=2)
    assert all(image.size == (1024, 1024) and image.mode == "RGBA" for image in framed.values())


def test_mirrored_silhouettes_measure_whether_opposite_views_agree():
    asymmetric = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    asymmetric.paste((200, 60, 40, 255), (10, 20, 210, 120))
    asymmetric.paste((200, 60, 40, 255), (10, 120, 60, 300))  # an L shape
    mirrored = asymmetric.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    agree = mirror_iou(frame_views({"front": asymmetric, "back": mirrored}))
    disagree = mirror_iou(frame_views({"front": asymmetric, "back": asymmetric}))
    assert agree["front_back"] > 0.99 and disagree["front_back"] < 0.8
    assert mirror_iou(frame_views({"front": asymmetric})) == {}


def test_empty_view_cutout_stops_with_the_slot_name():
    with pytest.raises(ValueError, match="back view"):
        frame_views({"front": _box(20, 20), "back": Image.new("RGBA", (64, 64), (0, 0, 0, 0))})


def test_worker_binds_view_slots_and_records_their_hashes(tmp_path):
    path = tmp_path / "multiview.json"
    path.write_text(json.dumps({
        "view_front": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
        "view_back": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
        "image": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
    }))
    views = {"front": "ai3d/front.png", "back": "ai3d/back.png"}
    graph = comfy_generate_3d.load_model_workflow(path, "ai3d/concept.png", "relay", 7, 1000, views)
    assert [graph[node]["inputs"]["image"] for node in ("view_front", "view_back", "image")] == [
        "ai3d/front.png", "ai3d/back.png", "ai3d/concept.png"]
    _, uploaded = comfy_generate_3d._workflow_identity(
        json.loads(path.read_text()), graph,
        {"ai3d/concept.png": "c" * 64, "ai3d/front.png": "f" * 64, "ai3d/back.png": "b" * 64})
    assert uploaded == {"view_front.image": "f" * 64, "view_back.image": "b" * 64, "image.image": "c" * 64}
    with pytest.raises(ValueError, match="back view"):
        comfy_generate_3d.load_model_workflow(path, "ai3d/concept.png", "relay", 7, 1000, {"front": "ai3d/front.png"})


def test_image_edit_prompt_nodes_take_the_prompt_and_negative(monkeypatch, tmp_path):
    workflow_path = tmp_path / "views.json"
    workflow_path.write_text(json.dumps({
        "positive": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "old"}},
        "negative": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": ""}},
        "save": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}},
    }))
    queued = {}

    class Client:
        def __init__(self, _url): pass
        def queue_workflow(self, workflow):
            queued.update(workflow)
            return "prompt-1"
        def wait_for_completion(self, _prompt, timeout): return {"outputs": {}}
        def list_outputs(self, _history): return [{"filename": "out.png", "subfolder": "", "type": "output"}]
        def download_output(self, _item, path): Path(path).write_bytes(b"view")

    monkeypatch.setattr(comfy_generate, "ComfyUIClient", Client)
    monkeypatch.setattr(sys, "argv", ["comfy_generate.py", "--workflow", str(workflow_path), "--prompt", "back view",
                                      "--negative", "blurry", "--dest", str(tmp_path / "view.png"), "--seed", "3"])
    comfy_generate.main()
    assert (queued["positive"]["inputs"]["prompt"], queued["negative"]["inputs"]["prompt"]) == ("back view", "blurry")
