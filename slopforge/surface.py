"""Approval-time processing for natural-environment images.

- ``cutout``: a plant or foliage image on white becomes a tightly cropped RGBA cut-out, for cards in Unity.
- ``tiling_material``: a generated surface becomes a seamless 2048 x 2048 tile with derived normal, roughness and
  height maps, for terrain layers and bark.

Both were built for the natural-environment prototype (2026-10-23, docs/media/natural-showcase-2026-10).
"""
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .backends.comfyui import ComfyUIClient, python_executable
from .paths import comfy_url, resolve_workflow, tool_root
from .provenance import file_sha256

TILE_SIZE = 2048
SEAMLESS_WORKFLOW = "image_seamless_inpaint_api.json"
UPSCALE_WORKFLOW = "image_upscale_esrgan_api.json"


def make_cutout(root, config, source, destination):
    """Remove the background with the 3D input tool's rembg step, then crop to the visible pixels."""
    with tempfile.TemporaryDirectory(prefix="slopforge-cutout-") as scratch:
        cut, flat = Path(scratch) / "cutout.png", Path(scratch) / "input.png"
        subprocess.run([python_executable(root, config), str(tool_root() / "processing/prepare_3d_input.py"),
                        "--input", str(source), "--cutout", str(cut), "--output", str(flat)],
                       check=True, stdout=subprocess.DEVNULL)
        with Image.open(cut) as image:
            image = image.convert("RGBA")
            box = image.getchannel("A").point(lambda a: 255 if a > 20 else 0).getbbox()
            if box is None:
                raise ValueError(f"Background removal left nothing visible in {Path(source).name}")
            image.crop(box).save(destination)
            return image.crop(box).size


def blur(array, radius):
    """Gaussian blur by FFT, which wraps around, so maps derived from a tile still tile."""
    height, width = array.shape
    fy, fx = np.fft.fftfreq(height)[:, None], np.fft.fftfreq(width)[None, :]
    return np.real(np.fft.ifft2(np.fft.fft2(array) * np.exp(-2 * (np.pi * radius) ** 2 * (fx ** 2 + fy ** 2))))


def resize_tiling(array, size, pad):
    """Resize a tile that is wrap-padded by pad texels on each side to size, keeping its edges continuous.

    A plain resize clamps at the edges, so the outermost texels of an 8x enlargement each copy their own side and
    no longer meet: a faint seam.
    """
    inner = array.shape[0] - 2 * pad
    scaled = round(size * array.shape[0] / inner)
    offset = round(size * pad / inner)
    big = np.asarray(Image.fromarray(array).resize((scaled, scaled), Image.LANCZOS))
    return big[offset:offset + size, offset:offset + size].astype(np.float64)


def derive_maps(rgb, out_dir):
    """Height, normal (OpenGL, as Unity expects), roughness and a lightly cavity-darkened base colour from a tile."""
    scale = rgb.shape[0] / 1024
    luminance = rgb @ [0.2126, 0.7152, 0.0722]
    height = blur(luminance, 1.0 * scale) - blur(luminance, 40 * scale)  # dark joints recessed, broad shading removed
    height = (height - height.min()) / (np.ptp(height) + 1e-6)
    gy, gx = np.gradient(np.pad(height, 1, mode="wrap"))
    gx, gy = gx[1:-1, 1:-1], gy[1:-1, 1:-1]
    strength = 4.0 * scale
    normal = np.dstack([-gx * strength, gy * strength, np.ones_like(gx)])
    normal /= np.linalg.norm(normal, axis=2, keepdims=True)
    cavity = np.clip((blur(height, 2 * scale) - blur(height, 12 * scale)) * 2.5 + 1, 0.8, 1.0)
    roughness = np.clip(0.88 - 0.18 * (height - 0.5), 0.6, 0.98)
    paths = {name: Path(out_dir) / f"{name}.png" for name in ("basecolor", "normal", "roughness", "height")}
    Image.fromarray((np.clip(rgb * cavity[..., None], 0, 1) * 255).astype(np.uint8)).save(paths["basecolor"])
    Image.fromarray(((normal * 0.5 + 0.5) * 255).astype(np.uint8)).save(paths["normal"])
    Image.fromarray((roughness * 255).astype(np.uint8)).save(paths["roughness"])
    Image.fromarray((height * 255).astype(np.uint8)).save(paths["height"])
    return paths


def _run(client, root, workflow_path, image, bind, out, prompt=None, seed=None):
    """Upload image, bind it into a workflow graph, run it, and download its first output to out."""
    resolved = resolve_workflow(root, workflow_path)
    graph = json.loads(resolved.read_text())
    uploaded = client.upload_input(image, "slopforge/surface")
    graph[bind]["inputs"]["image"] = "/".join(part for part in (uploaded.get("subfolder") or "", uploaded["name"]) if part)
    for node in graph.values():
        if prompt is not None and node.get("class_type") == "CLIPTextEncode":
            node["inputs"]["text"] = prompt
        if seed is not None and "seed" in node.get("inputs", {}):
            node["inputs"]["seed"] = seed
    prompt_id = client.queue_workflow(graph)
    entry = client.wait_for_completion(prompt_id, timeout=900)
    client.download_output(client.list_outputs(entry)[0], out)
    return {"workflow": resolved.name, "workflow_sha256": file_sha256(resolved), "prompt_id": prompt_id}


def make_tiling_material(root, config, source, prompt, out_dir, seed=7):
    """A seamless 2048 tile from a generated surface, and its derived maps; returns paths and provenance.

    The image is rolled by half so its seams cross the middle; the image model repaints that cross with the
    surface's own prompt, keeping every other pixel. RealESRGAN's upscale is mixed 35% with a plain Lanczos
    resize: alone it smeared fine speckle into paint-like strokes. Broad brightness drift is flattened, so tiles
    don't show as light and dark squares.
    """
    root, out_dir = Path(root), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = ComfyUIClient(comfy_url(config))
    provenance = {"source_sha256": file_sha256(source)}
    with Image.open(source) as image:
        original = np.asarray(image.convert("RGB"))
    h, w = original.shape[:2]
    rolled = np.roll(np.roll(original, h // 2, 0), w // 2, 1)
    band = w // 8
    mask = np.zeros((h, w), np.uint8)
    mask[:, w // 2 - band:w // 2 + band] = 255
    mask[h // 2 - band:h // 2 + band, :] = 255
    with tempfile.TemporaryDirectory(prefix="slopforge-surface-") as scratch:
        scratch = Path(scratch)
        Image.fromarray(np.dstack([rolled, 255 - mask])).save(scratch / "seam_input.png")
        provenance["seamless"] = _run(client, root, SEAMLESS_WORKFLOW, scratch / "seam_input.png", "seam_source",
                                      scratch / "painted.png", prompt=prompt, seed=seed)
        with Image.open(scratch / "painted.png") as image:
            painted = np.asarray(image.convert("RGB").resize((w, h))).astype(np.float64)
        soft = np.asarray(Image.fromarray(mask).filter(ImageFilter.GaussianBlur(6))).astype(np.float64)[..., None] / 255
        seamless = painted * soft + rolled.astype(np.float64) * (1 - soft)
        pad = 64
        Image.fromarray(np.pad(seamless.round().astype(np.uint8), ((pad, pad), (pad, pad), (0, 0)), mode="wrap")).save(
            scratch / "upscale_input.png")
        provenance["upscale"] = _run(client, root, UPSCALE_WORKFLOW, scratch / "upscale_input.png", "upscale_source",
                                     scratch / "upscaled.png")
        with Image.open(scratch / "upscaled.png") as image:
            big = np.asarray(image.convert("RGB"))
    esrgan = resize_tiling(big, TILE_SIZE, pad * big.shape[0] // (h + 2 * pad))
    lanczos = resize_tiling(np.pad(seamless.round().astype(np.uint8), ((pad, pad), (pad, pad), (0, 0)), mode="wrap"),
                            TILE_SIZE, pad)
    tile = esrgan * 0.35 + lanczos * 0.65
    luminance = tile @ [0.2126, 0.7152, 0.0722]
    gain = 1 + 0.8 * (luminance.mean() / np.maximum(blur(luminance, TILE_SIZE / 10), 1) - 1)
    tile = np.clip(tile * gain[..., None], 0, 255) / 255
    paths = derive_maps(tile, out_dir)
    provenance["maps"] = {name: file_sha256(path) for name, path in paths.items()}
    return paths, provenance
