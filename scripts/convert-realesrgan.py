#!/usr/bin/env python3
"""Convert Real-ESRGAN's official RealESRGAN_x4plus.pth to the RealESRGAN_x4plus.safetensors the tiling upscale
graph loads (workflows/image_upscale_esrgan_api.json), so the installed file has a documented source and terms.

The source is xinntao's release v0.1.0 (BSD-3-Clause). The conversion keeps the release's EMA weights (`params_ema`)
unchanged and writes them without pickle; both files' sha256 are pinned here and in the workflow's sidecar.
Usage: convert-realesrgan.py <RealESRGAN_x4plus.pth> <RealESRGAN_x4plus.safetensors>
Needs torch and safetensors (ComfyUI's Python has both). docs/COMFYUI.md, Models and workflows.
"""
import hashlib
import sys

SOURCE_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
SOURCE_SHA256 = "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1"  # 67,040,989 bytes, 2026-10-27
CONVERTED_SHA256 = "37f9a931c215f040aa6d50f711f2cb115f713c46df1d0d6469a8bd7bfe9a60bb"  # 66,857,836 bytes


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    source, out = sys.argv[1:3]
    if sha256(source) != SOURCE_SHA256:
        sys.exit(f"{source} is not the release file ({SOURCE_URL}); download that one")
    import torch
    from safetensors.torch import save_file
    state = torch.load(source, map_location="cpu", weights_only=True)  # tensors only: no code runs from the file
    weights = state["params_ema"] if "params_ema" in state else state
    save_file({name: tensor.contiguous() for name, tensor in weights.items()}, out)
    digest = sha256(out)
    if CONVERTED_SHA256 and digest != CONVERTED_SHA256:
        sys.exit(f"{out} has sha256 {digest}, not the recorded {CONVERTED_SHA256}: a different torch or safetensors "
                 "wrote it differently; check its tensors equal the release's before using it")
    print(f"{out}: sha256 {digest}")


if __name__ == "__main__":
    main()
