#!/usr/bin/env python3

import argparse
import json
import re
import shutil
import sys
import os
import tempfile
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
try:
    from .comfy_status import prompt_failure
except ImportError:
    from comfy_status import prompt_failure


COMFY_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_ROOT = Path(os.environ.get("COMFYUI_HOME", Path.home() / "ComfyUI")).expanduser()
COMFY_INPUT = COMFY_ROOT / "input"
COMFY_OUTPUT = COMFY_ROOT / "output"

CHECKPOINT = "hunyuan3d-dit-v2_fp16.safetensors"


def api(method, path, payload=None):
    body = None
    headers = {}

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(
        COMFY_URL + path,
        data=body,
        headers=headers,
        method=method,
    )

    with urlopen(req, timeout=60) as response:
        raw = response.read()

    if not raw:
        return {}

    return json.loads(raw.decode("utf-8"))


def safe_name(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value)
    return value.strip("_")


def find_glb(value):
    if isinstance(value, dict):
        filename = value.get("filename")

        if isinstance(filename, str) and filename.lower().endswith(".glb"):
            return value

        for child in value.values():
            found = find_glb(child)
            if found:
                return found

    elif isinstance(value, list):
        for child in value:
            found = find_glb(child)
            if found:
                return found

    return None


def make_workflow(image_name, asset_name, checkpoint=CHECKPOINT, seed=None):
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {
                "image": image_name
            }
        },
        "2": {
            "class_type": "ImageOnlyCheckpointLoader",
            "inputs": {
                "ckpt_name": checkpoint
            }
        },
        "3": {
            "class_type": "CLIPVisionEncode",
            "inputs": {
                "clip_vision": ["2", 1],
                "image": ["1", 0],
                "crop": "none"
            }
        },
        "4": {
            "class_type": "Hunyuan3Dv2Conditioning",
            "inputs": {
                "clip_vision_output": ["3", 0]
            }
        },
        "5": {
            "class_type": "EmptyLatentHunyuan3Dv2",
            "inputs": {
                "resolution": 3072,
                "batch_size": 1
            }
        },
        "6": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {
                "model": ["2", 0],
                "shift": 1.0,
                "sampling": "flow"
            }
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed if seed is not None else int(time.time_ns() % 9223372036854775807),
                "steps": 20,
                "cfg": 8.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["6", 0],
                "positive": ["4", 0],
                "negative": ["4", 1],
                "latent_image": ["5", 0]
            }
        },
        "8": {
            "class_type": "VAEDecodeHunyuan3D",
            "inputs": {
                "samples": ["7", 0],
                "vae": ["2", 2],
                "num_chunks": 8000,
                "octree_resolution": 256
            }
        },
        "9": {
            "class_type": "VoxelToMesh",
            "inputs": {
                "voxel": ["8", 0],
                "algorithm": "surface net",
                "threshold": 0.6
            }
        },
        "10": {
            "class_type": "SaveGLB",
            "inputs": {
                "mesh": ["9", 0],
                "filename_prefix": f"generated_models/{asset_name}"
            }
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--checkpoint", default=CHECKPOINT)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args()

    src = Path(args.image).expanduser().resolve()

    if not src.exists():
        print(f"Input image does not exist: {src}", file=sys.stderr)
        sys.exit(1)

    name = safe_name(args.name)

    if not name:
        print("Invalid asset name.", file=sys.stderr)
        sys.exit(1)

    # Check ComfyUI first.
    try:
        api("GET", "/system_stats")
    except Exception as exc:
        print(f"ComfyUI is not reachable at {COMFY_URL}: {exc}", file=sys.stderr)
        sys.exit(1)

    input_dir = COMFY_INPUT / "ai3d"
    input_dir.mkdir(parents=True, exist_ok=True)

    input_filename = f"{name}_concept.png"
    input_path = input_dir / input_filename

    shutil.copy2(src, input_path)

    comfy_image_name = f"ai3d/{input_filename}"

    seed = args.seed if args.seed is not None else int(time.time_ns() % 9223372036854775807)
    workflow = make_workflow(comfy_image_name, name, args.checkpoint, seed)

    result = api(
        "POST",
        "/prompt",
        {
            "prompt": workflow,
            "client_id": str(uuid.uuid4())
        },
    )

    prompt_id = result.get("prompt_id")

    if not prompt_id:
        print("ComfyUI did not return a prompt_id:", file=sys.stderr)
        print(json.dumps(result, indent=2), file=sys.stderr)
        sys.exit(1)

    print(f"Queued 3D generation: {prompt_id}", flush=True)

    deadline = time.time() + 3600

    while time.time() < deadline:
        time.sleep(2)

        history = api("GET", f"/history/{prompt_id}")

        if prompt_id not in history:
            continue

        entry = history[prompt_id]

        failure = prompt_failure(entry)
        if failure:
            print(failure, file=sys.stderr)
            sys.exit(1)

        glb = find_glb(entry.get("outputs", {}))

        if glb:
            source = (
                COMFY_OUTPUT
                / glb.get("subfolder", "")
                / glb["filename"]
            )

            if not source.exists():
                print(f"ComfyUI reported GLB but file is missing: {source}", file=sys.stderr)
                sys.exit(1)

            dest = Path(args.dest).expanduser().resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy2(source, dest)

            if args.metadata:
                args.metadata.parent.mkdir(parents=True, exist_ok=True)
                temporary = args.metadata.with_name(f".{args.metadata.name}.tmp")
                temporary.write_text(json.dumps({"workflow": "hunyuan3d_image_to_model_api", "model": args.checkpoint, "seed": seed, "prompt_id": prompt_id}, indent=2) + "\n")
                temporary.replace(args.metadata)

            print(f"GLB: {dest}")
            return

        status = entry.get("status", {})

        if status.get("completed"):
            print("ComfyUI finished but no GLB was produced.", file=sys.stderr)
            print(json.dumps(entry, indent=2), file=sys.stderr)
            sys.exit(1)

    print("Timed out waiting for Hunyuan3D.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
