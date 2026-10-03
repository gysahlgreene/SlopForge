#!/usr/bin/env python3

import argparse
import json
import re
import shutil
import subprocess
import sys
import os
import struct
import tempfile
import time
import uuid
import zlib
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


def load_model_workflow(path, image_name, asset_name, seed, face_budget):
    workflow = json.loads(Path(path).read_text())
    sampler_index = 0
    for node_id, node in workflow.items():
        inputs = node.setdefault("inputs", {})
        kind = node.get("class_type")
        if kind == "LoadImage":
            inputs["image"] = image_name
        elif kind == "KSampler":
            inputs["seed"] = (seed + sampler_index) % (2**64)
            sampler_index += 1
        elif kind == "DecimateMesh":
            inputs["target_face_count"] = face_budget
        elif kind in {"SaveGLB", "SaveImage"}:
            inputs["filename_prefix"] = f"generated_models/{asset_name}/{node_id}"
    return workflow


def copy_generated_maps(outputs, destination):
    textures = {}
    for key in ("basecolor", "roughness", "metallic"):
        images = outputs.get("save_" + key, {}).get("images", [])
        if not images:
            raise ValueError(f"Textured model workflow did not produce its {key} map")
        item = images[0]
        source = COMFY_OUTPUT / item.get("subfolder", "") / item["filename"]
        target = destination / "native_material" / f"{key}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        textures[key] = target.relative_to(destination).as_posix()
    normal = destination / "native_material" / "normal.png"
    normal.parent.mkdir(parents=True, exist_ok=True)
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixel = zlib.compress(b"\x00\x80\x80\xff")
    normal.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b""))
    textures["normal"] = normal.relative_to(destination).as_posix()
    return textures


def run_model_workflow(workflow):
    result = api("POST", "/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})
    if result.get("node_errors") or not result.get("prompt_id"):
        raise ValueError("ComfyUI rejected the model workflow: " + json.dumps(result))
    prompt_id = result["prompt_id"]
    print(f"Queued 3D generation: {prompt_id}", flush=True)
    deadline = time.monotonic() + 3600
    while time.monotonic() < deadline:
        time.sleep(2)
        entry = api("GET", f"/history/{prompt_id}").get(prompt_id)
        if not entry:
            continue
        failure = prompt_failure(entry)
        if failure:
            raise RuntimeError(failure)
        if entry.get("status", {}).get("completed"):
            return entry, prompt_id
    raise TimeoutError("Timed out waiting for 3D generation")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--checkpoint", default=CHECKPOINT)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--face-budget", type=int, default=30000)
    parser.add_argument("--blender", type=Path)
    args = parser.parse_args()
    if args.face_budget <= 0:
        parser.error("--face-budget must be positive")

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
    workflow = (load_model_workflow(args.workflow, comfy_image_name, name, seed, args.face_budget)
                if args.workflow else make_workflow(comfy_image_name, name, args.checkpoint, seed))
    dest = Path(args.dest).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shape_prompt_id = None
    if "prepared_mesh" in workflow:
        if args.blender is None:
            raise ValueError("This model workflow requires --blender for mesh reduction and UV preparation")
        raw_workflow = {key: node for key, node in workflow.items()
                        if not key.startswith("save") or key == "save_raw"}
        print("Mesh stage: generating the detailed shape...", flush=True)
        entry, shape_prompt_id = run_model_workflow(raw_workflow)
        raw = find_glb(entry["outputs"].get("save_raw", {}))
        if not raw:
            raise ValueError("Model workflow did not produce its raw mesh")
        raw_path = dest.with_name(dest.stem + "_untextured.glb")
        shutil.copy2(COMFY_OUTPUT / raw.get("subfolder", "") / raw["filename"], raw_path)
        prepared = COMFY_INPUT / "3d" / f"{name}_{seed}_prepared.glb"
        prepared.parent.mkdir(parents=True, exist_ok=True)
        print("Mesh stage: Blender reduction and UV preparation...", flush=True)
        script = Path(__file__).resolve().parents[1] / "blender" / "prepare_model.py"
        subprocess.run([str(args.blender), "--background", "--python", str(script), "--", str(raw_path),
                        str(prepared), str(dest.with_name("native_mesh.blend")), "--face-budget", str(args.face_budget),
                        "--mesh-only"], check=True)
        workflow["prepared_mesh"]["inputs"]["model_file"] = prepared.relative_to(COMFY_INPUT).as_posix()
        del workflow["save_raw"]
        print("Material stage: generating and baking mesh-aware PBR textures...", flush=True)

    entry, prompt_id = run_model_workflow(workflow)
    glb = find_glb(entry["outputs"].get("save", {})) if args.workflow else find_glb(entry["outputs"])
    if not glb:
        raise ValueError("ComfyUI finished but no final GLB was produced")
    source = COMFY_OUTPUT / glb.get("subfolder", "") / glb["filename"]
    shutil.copy2(source, dest)
    textured = any(node.get("class_type") == "ApplyTextureToMesh" for node in workflow.values())
    textures = copy_generated_maps(entry["outputs"], dest.parent) if textured else {}
    models = sorted({value for node in workflow.values() for value in node.get("inputs", {}).values()
                     if isinstance(value, str) and value.endswith(".safetensors")})
    if args.metadata:
        args.metadata.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.metadata.with_name(f".{args.metadata.name}.tmp")
        temporary.write_text(json.dumps({"workflow": args.workflow.name if args.workflow else "hunyuan3d_image_to_model_api",
                                        "model": models if args.workflow else args.checkpoint, "seed": seed,
                                        "prompt_id": prompt_id, "shape_prompt_id": shape_prompt_id,
                                        "textured": textured, "textures": textures}, indent=2) + "\n")
        temporary.replace(args.metadata)
    print(f"GLB: {dest}")


if __name__ == "__main__":
    main()
