#!/usr/bin/env python3
"""Assemble blender/render_turntable.py frames into a looping GIF.

Usage: turntable_gif.py <frames_dir> <out.gif> [--size 360] [--ms 80] [--colors 255]
"""
import argparse
from pathlib import Path

from PIL import Image


def build(frames_dir, out, size=360, ms=80, colors=255):
    paths = sorted(Path(frames_dir).glob("frame_*.png"))
    if not paths:
        raise SystemExit(f"No frame_*.png files in {frames_dir}")
    frames = [Image.open(path).convert("RGB").resize((size, size), Image.LANCZOS) for path in paths]
    # One shared palette, sampled across the loop, avoids per-frame flicker and keeps every frame's colours.
    sample = frames[::max(1, len(frames) // 8)]
    montage = Image.new("RGB", (size * len(sample), size))
    for index, frame in enumerate(sample):
        montage.paste(frame, (index * size, 0))
    palette = montage.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    quantized = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(out, save_all=True, append_images=quantized[1:], duration=ms, loop=0, optimize=True)
    return len(frames)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("frames_dir")
    parser.add_argument("out")
    parser.add_argument("--size", type=int, default=360)
    parser.add_argument("--ms", type=int, default=80)
    parser.add_argument("--colors", type=int, default=255, help="palette size; fewer colours make smaller files")
    args = parser.parse_args()
    print(f"{build(args.frames_dir, args.out, args.size, args.ms, args.colors)} frames -> {args.out}")


if __name__ == "__main__":
    main()
