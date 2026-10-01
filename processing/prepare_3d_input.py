#!/usr/bin/env python3

import argparse
from pathlib import Path

from PIL import Image
from rembg import remove


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--cutout", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--size", type=int, default=1024)
    args = parser.parse_args()

    src = Path(args.input).expanduser().resolve()
    cutout_path = Path(args.cutout).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not src.exists():
        raise SystemExit(f"Input image missing: {src}")

    cutout_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Removing background: {src}")

    image = Image.open(src).convert("RGBA")
    cutout = remove(image).convert("RGBA")

    cutout.save(cutout_path)

    alpha = cutout.getchannel("A")
    bbox = alpha.getbbox()

    if bbox is None:
        raise SystemExit("Background removal produced an empty image.")

    subject = cutout.crop(bbox)

    canvas_size = args.size

    # Keep some breathing room around the object.
    target_size = int(canvas_size * 0.78)

    scale = min(
        target_size / subject.width,
        target_size / subject.height,
    )

    new_width = max(1, round(subject.width * scale))
    new_height = max(1, round(subject.height * scale))

    subject = subject.resize(
        (new_width, new_height),
        Image.Resampling.LANCZOS,
    )

    # IMPORTANT:
    # Hunyuan's ComfyUI workflow consumes RGB, not the alpha mask.
    # Therefore we explicitly bake the isolated object onto pure white.
    canvas = Image.new(
        "RGBA",
        (canvas_size, canvas_size),
        (255, 255, 255, 255),
    )

    x = (canvas_size - new_width) // 2
    y = (canvas_size - new_height) // 2

    canvas.alpha_composite(subject, (x, y))

    rgb = canvas.convert("RGB")
    rgb.save(output_path, quality=100)

    print(f"Transparent cutout: {cutout_path}")
    print(f"3D input:          {output_path}")


if __name__ == "__main__":
    main()
