#!/usr/bin/env python3

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


METAL_WORDS = {
    "metal", "metallic", "steel", "iron", "brass", "copper",
    "gold", "silver", "chrome", "aluminium", "aluminum",
    "titanium", "bronze"
}

SMOOTH_WORDS = {
    "glass", "crystal", "gem", "polished", "glossy",
    "chrome", "ceramic"
}

ROUGH_WORDS = {
    "stone", "rock", "wood", "cloth", "fabric",
    "leather", "concrete", "rust", "rough"
}


def contains_any(text, words):
    text = text.lower()
    return any(word in text for word in words)


def save_gray(array, path):
    image = Image.fromarray(
        np.clip(array * 255.0, 0, 255).astype(np.uint8),
        mode="L",
    )
    image.save(path)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--basecolor", required=True)
    parser.add_argument("--prompt", required=True)

    parser.add_argument("--normal", required=True)
    parser.add_argument("--roughness", required=True)
    parser.add_argument("--metallic", required=True)
    parser.add_argument("--emission", required=True)

    args = parser.parse_args()

    base_path = Path(args.basecolor).resolve()

    if not base_path.exists():
        raise SystemExit(f"Base color missing: {base_path}")

    for value in (
        args.normal,
        args.roughness,
        args.metallic,
        args.emission,
    ):
        Path(value).resolve().parent.mkdir(parents=True, exist_ok=True)

    image = Image.open(base_path).convert("RGB")

    rgb = np.asarray(image).astype(np.float32) / 255.0

    # ---------- HEIGHT / NORMAL ----------

    gray_image = image.convert("L").filter(
        ImageFilter.GaussianBlur(radius=1.5)
    )

    gray = np.asarray(gray_image).astype(np.float32) / 255.0

    dy, dx = np.gradient(gray)

    strength = 2.5

    nx = -dx * strength
    ny = -dy * strength
    nz = np.ones_like(gray)

    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    length = np.maximum(length, 1e-8)

    normal = np.stack(
        (
            nx / length,
            -ny / length,
            nz / length,
        ),
        axis=-1,
    )

    normal = normal * 0.5 + 0.5

    Image.fromarray(
        np.clip(normal * 255.0, 0, 255).astype(np.uint8),
        mode="RGB",
    ).save(args.normal)

    # ---------- MATERIAL HEURISTICS ----------

    prompt = args.prompt.lower()

    if contains_any(prompt, SMOOTH_WORDS):
        base_roughness = 0.22
    elif contains_any(prompt, ROUGH_WORDS):
        base_roughness = 0.70
    else:
        base_roughness = 0.42

    if contains_any(prompt, METAL_WORDS):
        base_metallic = 0.85
    else:
        base_metallic = 0.05

    # Slight roughness variation derived from texture detail.
    roughness = np.clip(
        base_roughness + ((0.5 - gray) * 0.18),
        0.06,
        0.95,
    )

    metallic = np.full_like(
        gray,
        base_metallic,
        dtype=np.float32,
    )

    save_gray(roughness, args.roughness)
    save_gray(metallic, args.metallic)

    # ---------- EMISSION ----------

    hsv = np.asarray(image.convert("HSV")).astype(np.float32)

    saturation = hsv[:, :, 1] / 255.0
    value = hsv[:, :, 2] / 255.0

    # Bright + colourful portions of the AI texture become emissive.
    mask = np.clip(
        ((saturation - 0.35) / 0.45)
        * ((value - 0.45) / 0.45),
        0.0,
        1.0,
    )

    mask = np.power(mask, 1.5)

    emission = rgb * mask[:, :, None]

    Image.fromarray(
        np.clip(emission * 255.0, 0, 255).astype(np.uint8),
        mode="RGB",
    ).save(args.emission)

    print(f"Base color: {base_path}")
    print(f"Normal:     {Path(args.normal).resolve()}")
    print(f"Roughness:  {Path(args.roughness).resolve()}")
    print(f"Metallic:   {Path(args.metallic).resolve()}")
    print(f"Emission:   {Path(args.emission).resolve()}")


if __name__ == "__main__":
    main()
