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
from PIL import Image


def close_mask(mask, alpha, share=0.03):
    """A part's mask with its narrow gaps closed (a dilation then an erosion by `share` of the object's longer
    side), holes filled, and kept on the object. SAM's lid mask stopped at the iron band across a chest's lid, and
    OmniPart then left the band and the lid's ends with the body (2026-10-25)."""
    rows, cols = np.nonzero(alpha)
    radius = max(1, round(share * max(np.ptp(rows) + 1, np.ptp(cols) + 1))) if len(rows) else 1
    grown = np.pad(np.asarray(mask, bool), radius + 1)
    for _ in range(radius):  # a square element (rows, then columns) keeps straight edges straight
        grown = grown | np.roll(grown, 1, 0) | np.roll(grown, -1, 0)
        grown = grown | np.roll(grown, 1, 1) | np.roll(grown, -1, 1)
    for _ in range(radius):
        grown = grown & np.roll(grown, 1, 0) & np.roll(grown, -1, 0)
        grown = grown & np.roll(grown, 1, 1) & np.roll(grown, -1, 1)
    closed = grown[radius + 1:-radius - 1, radius + 1:-radius - 1]
    # holes: background not reachable from the border
    outside = np.zeros(closed.shape, bool)
    outside[0, :], outside[-1, :], outside[:, 0], outside[:, -1] = ~closed[0, :], ~closed[-1, :], ~closed[:, 0], ~closed[:, -1]
    while True:
        grown = outside | (np.roll(outside, 1, 0) | np.roll(outside, -1, 0) | np.roll(outside, 1, 1) | np.roll(outside, -1, 1)) & ~closed
        if (grown == outside).all():
            break
        outside = grown
    return (closed | ~outside) & np.asarray(alpha, bool)


def choose_mask(masks, scores, box, alpha):
    """Of SAM's candidate masks for a declared box, the one that fills the box's object pixels without spilling
    out of it: fill (share of the object inside the box the mask covers) minus twice the spill (share of the mask
    outside the box), SAM's score breaking ties. SAM's single best answer for a chest's lid box was the two iron
    band arcs on it, 5% of the chest (2026-10-25); a tight trigger box must not take the guard or the frame.
    Returns (index, report): each candidate's score, fill and spill."""
    x0, y0, x1, y1 = (int(round(value)) for value in box)
    inside = np.zeros(alpha.shape, bool)
    inside[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)] = True
    object_in_box = max(int((alpha & inside).sum()), 1)
    report, best = [], None
    for index, (mask, score) in enumerate(zip(masks, scores)):
        mask = np.asarray(mask, bool) & alpha
        total = max(int(mask.sum()), 1)
        fill = float((mask & inside).sum()) / object_in_box
        spill = float((mask & ~inside).sum()) / total
        report.append({"score": round(float(score), 4), "fill": round(fill, 4), "spill": round(spill, 4)})
        key = (round(fill - 2 * spill, 3), float(score))
        if best is None or key > best[0]:
            best = (key, index)
    return best[1], report


def grid_points(alpha, box, n=3):
    """n x n prompt points over a box (20% to 80% of its width and height), each moved to the nearest object pixel
    inside the box. SAM's answers for a box alone were each one row of a chest lid's planks (fill 0.04 at best,
    2026-10-25); with these points as well it took the dome (0.65), a pistol's trigger rose from 0.13 to 0.49 and its
    slide held at 0.70 (fill minus twice the spill)."""
    x0, y0, x1, y1 = (int(round(value)) for value in box)
    inside = np.zeros(alpha.shape, bool)
    inside[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)] = True
    ys, xs = np.nonzero(alpha & inside)
    if not len(xs):
        return []
    points = []
    for fy in np.linspace(0.2, 0.8, n):
        for fx in np.linspace(0.2, 0.8, n):
            tx, ty = x0 + fx * (x1 - x0), y0 + fy * (y1 - y0)
            nearest = int(np.argmin((xs - tx) ** 2 + (ys - ty) ** 2))
            points.append([int(xs[nearest]), int(ys[nearest])])
    return points


def ground(model, processor, image, text, device):
    """The box Florence-2 detects for the part's description, or None.

    Open-vocabulary detection, not phrase grounding: on a lantern concept, grounding "glass globe" or "carrying ring"
    also boxed the whole lantern, while detection boxed just the globe, the ring and the wire guard (2026-10-24).
    """
    import torch
    task = "<OPEN_VOCABULARY_DETECTION>"
    inputs = processor(text=task + text, images=image, return_tensors="pt").to(device, torch.float16)
    ids = model.generate(**inputs, max_new_tokens=256, num_beams=3, do_sample=False)
    decoded = processor.batch_decode(ids, skip_special_tokens=False)[0]
    boxes = processor.post_process_generation(decoded, task=task, image_size=image.size)[task].get("bboxes") or []
    return [float(value) for value in boxes[0]] if boxes else None


def run(request):
    import torch
    from transformers import AutoProcessor, Florence2ForConditionalGeneration, Sam2Model, Sam2Processor
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
            candidates, scores = [], []
            points = grid_points(alpha, box)
            # SAM's three answers to the box alone, then to the box with points on the object inside it: a lid of
            # planks and iron bands is one region to the second prompt and a single plank row to the first
            for prompt in ({"input_boxes": [[box]]},
                           *([{"input_boxes": [[box]], "input_points": [[points]], "input_labels": [[[1] * len(points)]]}]
                             if points else [])):
                inputs = sam_processor(images=image, return_tensors="pt", **prompt).to(device)
                with torch.no_grad():
                    outputs = sam(**inputs, multimask_output=True)
                masks = sam_processor.post_process_masks(outputs.pred_masks.cpu(), inputs["original_sizes"])[0]
                candidates.extend(np.asarray(masks).reshape(-1, image.size[1], image.size[0]) > 0.5)
                scores.extend(outputs.iou_scores.flatten().tolist())
            chosen, choices = choose_mask(list(candidates), scores, box, alpha)
            mask = close_mask(candidates[chosen], alpha)  # a part lies on the object, a strap does not split it
            entry.update({"score": round(float(scores[chosen]), 4), "pixels": int(mask.sum()),
                          "share": round(float(mask.sum() / max(alpha.sum(), 1)), 4),
                          "candidate": chosen, "prompt": "box" if chosen < 3 else "box and points",
                          "candidates": choices})
            Image.fromarray((mask * 255).astype(np.uint8)).save(out / f"{part['name']}.png")
            entry["mask"] = f"{part['name']}.png"
        report["parts"][part["name"]] = entry
    (out / "masks.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    print(json.dumps(run(json.loads(Path(sys.argv[1]).read_text()))))
