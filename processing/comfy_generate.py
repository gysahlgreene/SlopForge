#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import tempfile
from pathlib import Path

from slopforge.backends.comfyui import ComfyUIClient, ComfyUIError
from slopforge.backends.comfyui import (
    backend_provenance,
    _write_failure_report,
)
from slopforge.provenance import (
    canonical_workflow_identity,
    file_sha256,
    workflow_sha256,
)
from slopforge.quality import apply_workflow_inputs
from slopforge.workflow_requirements import workflow_output_rights, workflow_requirements_identity

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

def bind_reference_inputs(client, workflow, references, slots):
    if len(references) > len(slots):
        raise ValueError(f"Workflow maps {len(slots)} reference_inputs for {len(references)} selected references")
    for index, reference in enumerate(references):
        slot = slots[index]
        for key in ("image", "strength"):
            target = slot.get(key)
            if target is None and key == "strength":
                continue
            if not isinstance(target, dict) or str(target.get("node")) not in workflow:
                raise ValueError(f"Reference workflow mapping {index + 1} has no valid {key} node/input")
            node = workflow[str(target["node"])]
            input_name = target.get("input")
            if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict) or input_name not in node["inputs"]:
                raise ValueError(f"Reference workflow mapping {index + 1} targets a missing node/input")
    used = []
    for index, reference in enumerate(references):
        slot = slots[index]
        uploaded = client.upload_input(reference["path"], "slopforge/references")
        if not uploaded.get("name"):
            raise ValueError(f"ComfyUI did not return an uploaded filename for reference {reference['path']}")
        image_name = "/".join(part for part in (uploaded.get("subfolder") or "", uploaded["name"]) if part)
        image_target = slot["image"]
        workflow[str(image_target["node"])]["inputs"][image_target["input"]] = image_name
        strength_target = slot.get("strength")
        if strength_target:
            workflow[str(strength_target["node"])]["inputs"][strength_target["input"]] = reference["strength"]
        provenance = {key: reference[key] for key in
                      ("library_entry_id", "category", "sha256", "expected_sha256", "source") if key in reference}
        content_hash = file_sha256(reference["path"]) if Path(reference["path"]).is_file() else None
        used.append({"path": reference.get("provenance_path", reference["path"]),
                     "strength": reference["strength"], "comfyui_input": image_name,
                     "workflow_slot": f"{image_target['node']}.{image_target['input']}",
                     **({"content_sha256": content_hash} if content_hash else {}), **provenance})
    return used

def apply_seed(workflow, seed):
    for node in workflow.values():
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        for key in ("seed", "noise_seed"):
            if key in inputs:
                inputs[key] = seed

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workflow", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--negative", default="low quality, blurry, distorted, extra limbs, watermark, text")
    p.add_argument("--dest", required=True)
    p.add_argument("--prefix", default="generated/asset")
    p.add_argument("--seed", type=int)
    p.add_argument("--metadata", type=Path)
    p.add_argument("--failure-report", help="Path to write atomic failure report on handled error")
    p.add_argument("--references", help="JSON array of approved reference paths and strengths")
    p.add_argument("--reference-inputs", help="JSON array mapping reference slots to workflow node inputs")
    p.add_argument("--workflow-inputs", help="JSON node/input overrides for the selected quality tier")
    p.add_argument("--quality", help="JSON quality tier and effective settings for provenance")
    args = p.parse_args()

    workflow_path = Path(args.workflow)
    if not workflow_path.exists():
        print(f"Workflow not found: {workflow_path}", file=sys.stderr)
        sys.exit(1)

    workflow = json.loads(workflow_path.read_text())
    source_workflow = json.loads(json.dumps(workflow))
    workflow_requirements = workflow_requirements_identity(workflow_path, workflow)
    if args.workflow_inputs:
        overrides = json.loads(args.workflow_inputs)
        apply_workflow_inputs(workflow, overrides)

    # Try to find positive/negative CLIPTextEncode nodes.
    # This assumes your saved workflow contains one positive prompt node and one negative prompt node.
    pos_id = None
    neg_id = None

    # Image-edit graphs (view generation) take their prompt in TextEncodeQwenImageEditPlus.prompt.
    prompt_inputs = {"CLIPTextEncode": "text", "TextEncodeQwenImageEditPlus": "prompt"}
    clip_nodes = []
    for node_id, node in workflow.items():
        if node.get("class_type") in prompt_inputs:
            clip_nodes.append(node_id)

    if len(clip_nodes) >= 1:
        pos_id = clip_nodes[0]
    if len(clip_nodes) >= 2:
        neg_id = clip_nodes[1]

    if pos_id is None:
        print("Could not find a CLIPTextEncode node for positive prompt.", file=sys.stderr)
        sys.exit(1)

    workflow[pos_id]["inputs"][prompt_inputs[workflow[pos_id]["class_type"]]] = args.prompt

    if neg_id is not None:
        workflow[neg_id]["inputs"][prompt_inputs[workflow[neg_id]["class_type"]]] = args.negative

    save_id = find_save_node(workflow)
    if save_id is None:
        print("Could not find SaveImage node in workflow.", file=sys.stderr)
        sys.exit(1)

    workflow[save_id]["inputs"]["filename_prefix"] = args.prefix
    seed = args.seed
    if seed is not None:
        apply_seed(workflow, seed)
    else:
        seed = next((node.get("inputs", {}).get(key) for node in workflow.values()
                     for key in ("seed", "noise_seed") if key in node.get("inputs", {})), None)

    models = []
    for node in workflow.values():
        for key, value in node.get("inputs", {}).items():
            if isinstance(value, str) and value.lower().endswith((".safetensors", ".ckpt", ".gguf", ".onnx")):
                models.append(value)

    client = ComfyUIClient(COMFY_URL)
    references_used = []
    try:
        if args.references:
            references = json.loads(args.references)
            reference_inputs = json.loads(args.reference_inputs or "[]")
            if not isinstance(references, list) or not isinstance(reference_inputs, list):
                raise ValueError("Reference paths and workflow input mappings must be JSON arrays")
            references_used = bind_reference_inputs(client, workflow, references, reference_inputs)
            if any("content_sha256" not in item for item in references_used):
                raise ValueError("A selected reference is missing local content and cannot be fingerprinted")
        prompt_id = client.queue_workflow(workflow)
        history = client.wait_for_completion(prompt_id, timeout=600)
    except ComfyUIError as exc:
        # Tag errors at the client/boundary that knows their category.
        # Never infer retryability from message text.
        if not exc.category:
            exc.category = "unknown"
        if args.failure_report:
            _write_failure_report(args.failure_report, error=exc)
        print(f"ComfyUI generation failed: {exc}", file=sys.stderr)
        # Preserve subprocess return behavior: exit non-zero.
        sys.exit(1)

    extensions = (".png", ".jpg", ".jpeg", ".webp")
    # Preview nodes return "temp" images; only a SaveImage result is the generated asset.
    outputs = [item for item in client.list_outputs(history)
               if item["type"] == "output" and item["filename"].lower().endswith(extensions)]

    if not outputs:
        print("No image outputs found in ComfyUI output.", file=sys.stderr)
        sys.exit(1)

    dest = Path(args.dest)
    client.download_output(outputs[0], dest)
    outputs = [{"index": 0, "source_filename": outputs[0]["filename"], "path": dest.name}]

    if args.metadata:
        quality = json.loads(args.quality) if args.quality else None
        uploaded_inputs = {item["workflow_slot"]: item["content_sha256"] for item in references_used}
        workflow_identity = canonical_workflow_identity(source_workflow, workflow, uploaded_inputs)
        bindings = {"prompt": args.prompt, "negative_prompt": args.negative, "seed": seed,
                    "workflow_inputs": json.loads(args.workflow_inputs) if args.workflow_inputs else {},
                    "uploaded_inputs": workflow_identity["bindings"],
                    "reference_strengths": [item["strength"] for item in references_used],
                    "quality": quality}
        graph_models = sorted(set(models))
        outputs = [{"index": 0, "source_filename": outputs[0]["source_filename"], "path": dest.name,
                    "sha256": file_sha256(dest), "kind": "image"}]
        write_metadata(args.metadata, {"workflow": workflow_path.name, "model": models or None, "seed": seed,
                                       "workflow_sha256": workflow_sha256(workflow_path),
                                       "workflow_source_sha256": workflow_identity["source_sha256"],
                                       "workflow_effective_sha256": workflow_identity["effective_sha256"],
                                       "effective_bindings": bindings,
                                       "backend": backend_provenance(queried=False),
                                       "model_filenames": [{"status": "known", "value": name} for name in graph_models],
                                       "workflow_requirements": workflow_requirements,
                                       "output_rights": workflow_output_rights(workflow_path, graph_models),
                                       "prompt_id": prompt_id, "output_kind": "image",
                                       "references_used": references_used,
                                       "outputs": outputs, "quality": quality})

    print(dest)

def _write_invocation_failure(error):
    try:
        report_index = sys.argv.index("--failure-report")
        report_path = sys.argv[report_index + 1]
    except (ValueError, IndexError):
        return
    if isinstance(error, ComfyUIError) and error.category:
        reported = error
    elif isinstance(error, KeyboardInterrupt):
        reported = ComfyUIError("Worker interrupted", category="interruption",
                                operation="worker", evidence={})
    else:
        reported = ComfyUIError(str(error) or type(error).__name__, category="unknown",
                                operation="worker", evidence={})
    _write_failure_report(report_path, error=reported)


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        _write_invocation_failure(exc)
        raise
