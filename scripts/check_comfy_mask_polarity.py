"""Run with ComfyUI's Python: python check_comfy_mask_polarity.py [ComfyUI directory]."""

import json
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "ComfyUI"
sys.path.insert(0, str(root))

import numpy as np
from PIL import Image

import folder_paths
from nodes import LoadImage
from comfy_extras.nodes_images import ImageCropToMask
from comfy_extras.nodes_mask import InvertMask


def crop(image, mask):
    return ImageCropToMask.execute(image, mask, 128, 128, 1.1, 0, "#000000").result[0]


results = []
with tempfile.TemporaryDirectory(dir=folder_paths.get_input_directory()) as directory:
    for label, width, alpha in [("narrow", 20, True), ("broad", 80, True), ("rgb", 20, False)]:
        pixels = np.zeros((128, 128, 4), dtype=np.uint8)
        left = (128 - width) // 2
        pixels[16:112, left:left + width] = (230, 200, 150, 255)
        path = Path(directory) / (label + ".png")
        Image.fromarray(pixels if alpha else pixels[:, :, :3]).save(path)
        image, transparency = LoadImage().load_image(str(path))
        if alpha:
            assert transparency[0, 0, 0] == 1, "LoadImage transparency convention changed"
            assert transparency[0, 64, 64] == 0, "Opaque subject must have zero transparency"
        foreground = InvertMask.execute(transparency).result[0]
        corrected = crop(image, foreground)
        brightness = float((corrected.max(dim=-1).values > 0.3).float().mean())
        assert brightness > 0.05, f"{label}: conditioning crop erased the subject"
        assert float(corrected[..., 0].max()) > 0.85, f"{label}: crop lost source colors"
        results.append({"input": label, "corrected_bright_fraction": brightness,
                        "direct_mask_bright_fraction": float((crop(image, transparency)
                            .max(dim=-1).values > 0.3).float().mean())})

print(json.dumps({"status": "passed", "cases": results}, indent=2))
