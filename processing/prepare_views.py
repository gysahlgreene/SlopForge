#!/usr/bin/env python3
"""Frame generated object views for multi-view 3D conditioning and measure their agreement.

Pixal3D's multi-view rig expects square views on black, the same scale in every view, with the
object spanning about 1/1.1 of the frame at its widest. Each view is cut out, brought to one object
height (an eye-level turn does not change it), then all views share one scale.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PAD = 1.1
OPPOSITE = (("front", "back"), ("left", "right"))


def frame_views(cutouts, size=1024):
    """Map name -> RGBA cutout to name -> size² RGBA view, transparent around the object, at one scale."""
    boxes = {name: image.getchannel("A").getbbox() for name, image in cutouts.items()}
    empty = [name for name, box in boxes.items() if box is None]
    if empty:
        raise ValueError(f"Background removal left no object in the {', '.join(empty)} view")
    subjects = {name: cutouts[name].crop(box) for name, box in boxes.items()}
    height = max(item.height for item in subjects.values())
    subjects = {name: item.resize((max(1, round(item.width * height / item.height)), height), Image.Resampling.LANCZOS)
                for name, item in subjects.items()}
    scale = size / PAD / max(max(item.size) for item in subjects.values())
    framed = {}
    for name, item in subjects.items():
        item = item.resize((max(1, round(item.width * scale)), max(1, round(item.height * scale))),
                           Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.alpha_composite(item, ((size - item.width) // 2, (size - item.height) // 2))
        framed[name] = canvas
    return framed


def mirror_iou(framed):
    """Silhouette overlap of each opposite pair; on an eye-level orbit one view mirrors the other."""
    masks = {name: np.asarray(image.getchannel("A")) > 127 for name, image in framed.items()}
    result = {}
    for first, second in OPPOSITE:
        if first in masks and second in masks:
            a, b = masks[first], masks[second][:, ::-1]
            result[f"{first}_{second}"] = round(float((a & b).sum() / max((a | b).sum(), 1)), 4)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--view", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--size", type=int, default=1024)
    args = parser.parse_args()
    from rembg import remove

    cutouts = {}
    for spec in args.view:
        name, separator, path = spec.partition("=")
        if not separator or not Path(path).is_file():
            raise SystemExit(f"--view must be NAME=PATH of an existing image, got {spec!r}")
        cutouts[name] = remove(Image.open(path).convert("RGBA")).convert("RGBA")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    framed = frame_views(cutouts, args.size)
    for name, image in framed.items():
        target = args.output_dir / f"view_{name}.png"
        Image.alpha_composite(Image.new("RGBA", image.size, (0, 0, 0, 255)), image).convert("RGB").save(target)
        print(f"{name} view: {target}")
    args.report.write_text(json.dumps({"mirror_iou": mirror_iou(framed)}, indent=2) + "\n")


if __name__ == "__main__":
    main()
    # rembg's onnxruntime can abort in its own teardown at interpreter exit (SIGABRT, "recursive_mutex lock
    # failed"; 2 of 64 runs on macOS), after the outputs are written. Skip teardown once main() succeeds.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
