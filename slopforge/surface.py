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

from .backends.comfyui import ComfyUIClient, ComfyUIError, python_executable
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


def _cheapest_path(cost):
    """Column index per row of the cheapest top-to-bottom path through cost (rows x columns), moving at most one
    column per row."""
    total = cost.copy()
    for row in range(1, len(total)):
        previous = total[row - 1]
        total[row] += np.minimum(np.minimum(np.r_[np.inf, previous[:-1]], previous), np.r_[previous[1:], np.inf])
    path = [int(np.argmin(total[-1]))]
    for row in range(len(total) - 2, -1, -1):
        column = path[-1]
        low, high = max(column - 1, 0), min(column + 2, total.shape[1])
        path.append(low + int(np.argmin(total[row, low:high])))
    return path[::-1]


def _cover_seam(image, band):
    """Roll image by half its width, so it wraps left to right but has a seam down its middle, then cover that seam
    with the unrolled image's own middle, joined along a least-difference path on each side."""
    w = image.shape[1]
    rolled = np.roll(image, w // 2, 1)
    difference = ((image - rolled) ** 2).sum(2)
    keep = np.zeros(difference.shape, bool)
    width = int(band * w)
    for start, stop in ((w // 2 - width, w // 2 - 4), (w // 2 + 4, w // 2 + width)):
        for row, offset in enumerate(_cheapest_path(difference[:, start:stop])):
            column = start + offset
            if start < w // 2:
                keep[row, column:w // 2] = True
            else:
                keep[row, w // 2:column] = True
    soft = np.asarray(Image.fromarray((keep * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5))) / 255.0
    return image * soft[..., None] + rolled * (1 - soft[..., None])


def cut_seams(image, band=0.12):
    """A tiling copy of image whose every pixel is the source's own: seamless left to right first, then top to
    bottom. Covering both seams of a fully rolled image at once ran the source's own edges out to the tile's edges
    inside the bands, leaving a short seam there."""
    across = _cover_seam(image, band)
    return np.transpose(_cover_seam(np.transpose(across, (1, 0, 2)), band), (1, 0, 2))


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
    saved = [item for item in client.list_outputs(entry) if item["type"] == "output"]  # not preview temp images
    if not saved:
        raise ComfyUIError(f"{resolved.name} finished without saving an image", category="inference",
                           operation="surface")
    client.download_output(saved[0], out)
    return {"workflow": resolved.name, "workflow_sha256": file_sha256(resolved), "prompt_id": prompt_id}


def make_tiling_material(root, config, source, prompt, out_dir, seed=7, seams="cut"):
    """A seamless 2048 tile from a generated surface, and its derived maps; returns paths and provenance.

    seams="cut" joins the half-rolled image along least-difference paths and keeps every original pixel; it made
    the approved prototype's ground and bark. seams="repaint" lets the image model repaint the seam cross from the
    surface's prompt, for patterned surfaces such as dressed stone; on meadow grass it repainted a darker, busier
    cross that showed as bands every repeat (2026-10-23 live run). RealESRGAN's upscale is mixed 35% with a plain
    Lanczos resize: alone it smeared fine speckle into paint-like strokes. Broad brightness drift is flattened, so
    tiles don't show as light and dark squares.
    """
    if seams not in ("cut", "repaint"):
        raise ValueError(f"Tiling seams must be cut or repaint, got {seams!r}")
    root, out_dir = Path(root), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = ComfyUIClient(comfy_url(config))
    provenance = {"source_sha256": file_sha256(source), "seams": seams}
    with Image.open(source) as image:
        original = np.asarray(image.convert("RGB"))
    h, w = original.shape[:2]
    with tempfile.TemporaryDirectory(prefix="slopforge-surface-") as scratch:
        scratch = Path(scratch)
        if seams == "cut":
            seamless = cut_seams(original.astype(np.float64))
        else:
            rolled = np.roll(np.roll(original, h // 2, 0), w // 2, 1)
            band = w // 8
            mask = np.zeros((h, w), np.uint8)
            mask[:, w // 2 - band:w // 2 + band] = 255
            mask[h // 2 - band:h // 2 + band, :] = 255
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
