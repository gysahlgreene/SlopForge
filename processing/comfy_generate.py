#!/usr/bin/env python3
import argparse
import json
import os
import tempfile
import sys
from pathlib import Path
from slopforge.backends.comfyui import ComfyUIClient

COMFY_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")

def write_metadata(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def find_save_node(workflow):
    for node_id, node in workflow.items():
        if node.get("class_type") == "SaveImage":
            return node_id
    return None

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workflow", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--negative", default="low quality, blurry, distorted, extra limbs, watermark, text")
    p.add_argument("--dest", required=True)
    p.add_argument("--prefix", default="generated/asset")
    p.add_argument("--seed", type=int)
    p.add_argument("--metadata", type=Path)
    args = p.parse_args()

    workflow_path = Path(args.workflow)
    if not workflow_path.exists():
        print(f"Workflow not found: {workflow_path}", file=sys.stderr)
        sys.exit(1)

    workflow = json.loads(workflow_path.read_text())

    # Try to find positive/negative CLIPTextEncode nodes.
    # This assumes your saved workflow contains one positive prompt node and one negative prompt node.
    pos_id = None
    neg_id = None

    clip_nodes = []
    for node_id, node in workflow.items():
        if node.get("class_type") == "CLIPTextEncode":
            clip_nodes.append(node_id)

    if len(clip_nodes) >= 1:
        pos_id = clip_nodes[0]
    if len(clip_nodes) >= 2:
        neg_id = clip_nodes[1]

    if pos_id is None:
        print("Could not find a CLIPTextEncode node for positive prompt.", file=sys.stderr)
        sys.exit(1)

    workflow[pos_id]["inputs"]["text"] = args.prompt

    if neg_id is not None:
        workflow[neg_id]["inputs"]["text"] = args.negative

    save_id = find_save_node(workflow)
    if save_id is None:
        print("Could not find SaveImage node in workflow.", file=sys.stderr)
        sys.exit(1)

    workflow[save_id]["inputs"]["filename_prefix"] = args.prefix
    samplers = [node for node in workflow.values() if node.get("class_type") == "KSampler"]
    seed = args.seed
    if seed is not None:
        for node in samplers:
            node.setdefault("inputs", {})["seed"] = seed
    elif samplers:
        seed = samplers[0].get("inputs", {}).get("seed")

    models = []
    for node in workflow.values():
        for key, value in node.get("inputs", {}).items():
            if isinstance(value, str) and value.lower().endswith((".safetensors", ".ckpt", ".gguf", ".onnx")):
                models.append(value)

    client = ComfyUIClient(COMFY_URL)
    try:
        prompt_id = client.queue_workflow(workflow)
        history = client.wait_for_completion(prompt_id, timeout=600)
    except Exception as exc:
        print(f"ComfyUI generation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    images = [item for item in client.list_outputs(history) if item["filename"].lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]

    if not images:
        print("No images found in ComfyUI output.", file=sys.stderr)
        sys.exit(1)

    dest = Path(args.dest)
    client.download_output(images[0], dest)

    if args.metadata:
        write_metadata(args.metadata, {"workflow": workflow_path.name, "model": models or None, "seed": seed, "prompt_id": prompt_id})

    print(dest)

if __name__ == "__main__":
    main()
