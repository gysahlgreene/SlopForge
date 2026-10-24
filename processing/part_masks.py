#!/usr/bin/env python3
"""Mask each declared part of a concept: Florence-2 finds the part from its description, SAM 2.1 cuts its mask.

Usage: python part_masks.py request.json

request.json: {"image": concept cutout (RGBA), "out_dir": folder,
               "parts": [{"name": ..., "text": ..., "box": optional [x0, y0, x1, y1] as fractions of the image}],
               "florence": model id or path, "sam": model id or path}

A part's box, given at approval, is SAM's prompt. Without one, Florence-2 detects the part from its text, which is
unreliable on weapons: on 2026-10-24 it swapped a pistol's slide and grip and boxed whole swords, while boxes gave the
slide, the trigger, the grips and the pommel cleanly.

Writes <out_dir>/<name>.png (L, 255 inside the part) and <out_dir>/masks.json with each part's box, area and score.
Runs in its own environment (torch, transformers 5.20) on the GPU host, streamed there like the SkinTokens launcher.
Florence-2 is MIT and SAM 2.1 is Apache-2.0 (docs/WEAPONS.md, THIRD_PARTY_NOTICES.md).
"""
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoProcessor, Florence2ForConditionalGeneration, Sam2Model, Sam2Processor


def ground(model, processor, image, text, device):
    """The box Florence-2 detects for the part's description, or None.

    Open-vocabulary detection, not phrase grounding: on a lantern concept, grounding "glass globe" or "carrying ring"
    also boxed the whole lantern, while detection boxed just the globe, the ring and the wire guard (2026-10-24).
    """
    task = "<OPEN_VOCABULARY_DETECTION>"
    inputs = processor(text=task + text, images=image, return_tensors="pt").to(device, torch.float16)
    ids = model.generate(**inputs, max_new_tokens=256, num_beams=3, do_sample=False)
    decoded = processor.batch_decode(ids, skip_special_tokens=False)[0]
    boxes = processor.post_process_generation(decoded, task=task, image_size=image.size)[task].get("bboxes") or []
    return [float(value) for value in boxes[0]] if boxes else None


def run(request):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    rgba = Image.open(request["image"]).convert("RGBA")
    alpha = np.asarray(rgba)[..., 3] > 127
    # On white, as the concept was drawn: the cut-out's transparent pixels keep the backdrop's colour otherwise.
    image = Image.new("RGB", rgba.size, (255, 255, 255))
    image.paste(rgba, mask=rgba.getchannel("A"))
    if any("box" not in part for part in request["parts"]):
        florence_processor = AutoProcessor.from_pretrained(request["florence"])
        florence = Florence2ForConditionalGeneration.from_pretrained(request["florence"],
                                                                     torch_dtype=torch.float16).to(device)
    sam_processor = Sam2Processor.from_pretrained(request["sam"])
    sam = Sam2Model.from_pretrained(request["sam"]).to(device)
    out = Path(request["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    report = {"parts": {}, "image_size": list(image.size), "object_pixels": int(alpha.sum())}
    for part in request["parts"]:
        if "box" in part:
            width, height = image.size
            box = [part["box"][0] * width, part["box"][1] * height, part["box"][2] * width, part["box"][3] * height]
            source = "declared_box"
        else:
            box, source = ground(florence, florence_processor, image, part["text"], device), "detected"
        entry = {"text": part["text"], "box": box, "box_source": source}
        if box is not None:
            inputs = sam_processor(images=image, input_boxes=[[box]], return_tensors="pt").to(device)
            with torch.no_grad():
                outputs = sam(**inputs, multimask_output=False)
            mask = sam_processor.post_process_masks(outputs.pred_masks.cpu(), inputs["original_sizes"])[0]
            mask = np.asarray(mask).reshape(-1, image.size[1], image.size[0])[0] > 0.5
            mask &= alpha  # a part lies on the object
            entry.update({"score": round(float(outputs.iou_scores.flatten()[0]), 4), "pixels": int(mask.sum()),
                          "share": round(float(mask.sum() / max(alpha.sum(), 1)), 4)})
            Image.fromarray((mask * 255).astype(np.uint8)).save(out / f"{part['name']}.png")
            entry["mask"] = f"{part['name']}.png"
        report["parts"][part["name"]] = entry
    (out / "masks.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    print(json.dumps(run(json.loads(Path(sys.argv[1]).read_text()))))
