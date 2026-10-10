#!/usr/bin/env python3

import argparse
import json
import re
import shutil
import subprocess
import sys
import os
import struct
import time
import zlib
from contextlib import contextmanager
from pathlib import Path
from slopforge.backends.comfyui import ComfyUIClient
from slopforge.backends.blender import blender_environment
from slopforge.provenance import workflow_sha256, file_sha256, canonical_workflow_identity
from slopforge.backends.comfyui import backend_provenance
from slopforge.quality import apply_workflow_inputs
from slopforge.workflow_requirements import workflow_requirements_identity
from slopforge.validation import validate_image
from slopforge.manifest import (load_manifest, save_manifest, find_asset, begin_stage,
                                start_stage, finish_stage)


COMFY_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
CHECKPOINT = "hunyuan3d-dit-v2_fp16.safetensors"


def _journal_execution(context):
    if not isinstance(context, dict) or not all(context.get(key) for key in
            ("manifest_path", "asset_selector", "execution_id", "project_root")):
        return None
    manifest = load_manifest(context["manifest_path"])
    asset = find_asset(manifest, context["asset_selector"])
    execution = next((item for item in asset.get("executions", [])
                      if item.get("id") == context["execution_id"]), None)
    return None if execution is None else (context, manifest, execution)


@contextmanager
def _journal_stage(context, name, attempt, settings, provenance=None):
    state = _journal_execution(context)
    if state is None:
        yield
        return
    context, manifest, execution = state
    stage = next((item for item in reversed(execution.get("stages", []))
                  if item["name"] == name and item["attempt"] == attempt
                  and item["status"] in {"pending", "running"}), None)
    if stage is None:
        stage = start_stage(execution, name, attempt, context.get("upstream_artifacts", []), settings, provenance or {})
        save_manifest(context["manifest_path"], manifest)
    if stage["status"] == "pending":
        begin_stage(stage)
        save_manifest(context["manifest_path"], manifest)
    try:
        yield stage
    except Exception as exc:
        finish_stage(stage, "failed", error=str(exc) or type(exc).__name__)
        save_manifest(context["manifest_path"], manifest)
        raise


def _journal_finish(context, stage, outputs):
    if stage is None:
        return
    state = _journal_execution(context)
    if state is None:
        return
    context, manifest, execution = state
    current = next((item for item in execution["stages"] if item is stage), None)
    if current is None:
        current = next(item for item in reversed(execution["stages"])
                       if item["name"] == stage["name"] and item["attempt"] == stage["attempt"])
    root = Path(context["project_root"]).resolve()
    refs = []
    for index, (path, kind) in enumerate(outputs):
        path = Path(path).resolve()
        refs.append({"id": f"{execution['id']}:{current['name']}:{current['attempt']}:{index}",
                     "type": kind, "path": path.relative_to(root).as_posix(),
                     "sha256": file_sha256(path), "stage": current["name"],
                     "attempt": current["attempt"],
                     "derived_from": [{"artifact_id": parent["id"], "sha256": parent["sha256"]}
                                      for parent in current.get("inputs", [])]})
    finish_stage(current, "succeeded", refs)
    save_manifest(context["manifest_path"], manifest)


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


def copy_generated_maps(outputs, destination, client=None, *, baked_normal=None):
    client = client or ComfyUIClient(COMFY_URL)
    textures = {}
    for key in ("basecolor", "roughness", "metallic"):
        images = outputs.get("save_" + key, {}).get("images", [])
        if not images:
            raise ValueError(f"Textured model workflow did not produce its {key} map")
        item = images[0]
        target = destination / "native_material" / f"{key}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        client.download_output(item, target)
        textures[key] = target.relative_to(destination).as_posix()
    normal = destination / "native_material" / "normal.png"
    normal.parent.mkdir(parents=True, exist_ok=True)
    normal_images = outputs.get("save_normal", {}).get("images", [])
    if normal_images:
        client.download_output(normal_images[0], normal)
    elif baked_normal is not None:
        shutil.copy2(baked_normal, normal)
    else:
        # ponytail: neutral normal for legacy workflows without a source mesh or normal output.
        write_flat_normal(normal)
    textures["normal"] = normal.relative_to(destination).as_posix()
    return textures


def copy_conditioning_image(outputs, destination, client):
    images = outputs.get("save_conditioning", {}).get("images", [])
    if not images:
        raise ValueError("Model workflow did not produce its conditioning image")
    target = destination / "conditioning.png"
    client.download_output(images[0], target)
    validation = validate_image(target, report_path=target.name)
    if validation["status"] == "failed":
        raise ValueError("Invalid conditioning image: " + "; ".join(validation["errors"]))
    return target.name


def write_flat_normal(normal):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixel = zlib.compress(b"\x00\x80\x80\xff")
    normal.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b""))


def run_model_workflow(workflow, client):
    prompt_id = client.queue_workflow(workflow)
    print(f"Queued 3D generation: {prompt_id}", flush=True)
    return client.wait_for_completion(prompt_id), prompt_id


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
    parser.add_argument("--voxel-resolution", type=int, default=256,
                        help="Voxel remesh resolution used before reducing a generated shape")
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--workflow-inputs", help="JSON node/input overrides for the selected quality tier")
    parser.add_argument("--quality", help="JSON quality tier and effective settings for provenance")
    parser.add_argument("--journal-context", help="Optional prop manifest journal context JSON")
    args = parser.parse_args()
    if args.face_budget <= 0:
        parser.error("--face-budget must be positive")
    if args.voxel_resolution <= 0:
        parser.error("--voxel-resolution must be positive")

    src = Path(args.image).expanduser().resolve()

    if not src.exists():
        print(f"Input image does not exist: {src}", file=sys.stderr)
        sys.exit(1)

    name = safe_name(args.name)

    if not name:
        print("Invalid asset name.", file=sys.stderr)
        sys.exit(1)

    workflow_requirements = {"status": "unknown"}
    source_workflow = None
    if args.workflow:
        declared_workflow = json.loads(args.workflow.read_text())
        source_workflow = json.loads(json.dumps(declared_workflow))
        workflow_requirements = workflow_requirements_identity(args.workflow, declared_workflow)

    client = ComfyUIClient(COMFY_URL)
    try:
        health = client.health()
    except Exception as exc:
        print(f"ComfyUI is not reachable at {COMFY_URL}: {exc}", file=sys.stderr)
        sys.exit(1)

    uploaded = client.upload_input(src, "ai3d")
    comfy_image_name = f"{uploaded.get('subfolder', 'ai3d')}/{uploaded['name']}"

    seed = args.seed if args.seed is not None else int(time.time_ns() % 9223372036854775807)
    workflow = (load_model_workflow(args.workflow, comfy_image_name, name, seed, args.face_budget)
                if args.workflow else make_workflow(comfy_image_name, name, args.checkpoint, seed))
    if args.workflow_inputs:
        apply_workflow_inputs(workflow, json.loads(args.workflow_inputs))
    source_content_hash = file_sha256(src)
    dest = Path(args.dest).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shape_prompt_id = None
    journal = json.loads(args.journal_context) if args.journal_context else None
    journal_attempt = (journal or {}).get("attempt", 1)
    if "prepared_mesh" in workflow:
        if args.blender is None:
            raise ValueError("This model workflow requires --blender for mesh reduction and UV preparation")
        raw_workflow = {key: node for key, node in workflow.items()
                        if not key.startswith("save") or key == "save_raw"}
        print("Mesh stage: generating the detailed shape...", flush=True)
        with _journal_stage(journal, "mesh_workflow_execution", journal_attempt,
                            {"phase": "raw_shape", "seed": seed},
                            {"backend": backend_provenance(health, queried=True)}) as stage:
            entry, shape_prompt_id = run_model_workflow(raw_workflow, client)
            _journal_finish(journal, stage, [])
        raw = find_glb(entry["outputs"].get("save_raw", {}))
        if not raw:
            raise ValueError("Model workflow did not produce its raw mesh")
        raw_path = dest.with_name(dest.stem + "_untextured.glb")
        with _journal_stage(journal, "mesh_output_acquisition", journal_attempt,
                            {"phase": "raw_shape"}) as stage:
            client.download_output(raw, raw_path)
            _journal_finish(journal, stage, [(raw_path, "mesh.raw")])
        prepared = dest.with_name(f"{name}_{seed}_prepared.glb")
        print("Mesh stage: Blender reduction and UV preparation...", flush=True)
        script = Path(__file__).resolve().parents[1] / "blender" / "prepare_model.py"
        with _journal_stage(journal, "mesh_preparation", journal_attempt,
                            {"face_budget": args.face_budget, "voxel_resolution": args.voxel_resolution}):
            subprocess.run([str(args.blender), "--background", "--python-exit-code", "1", "--python", str(script), "--", str(raw_path),
                            str(prepared), str(dest.with_name("native_mesh.blend")), "--face-budget", str(args.face_budget),
                            "--voxel-resolution", str(args.voxel_resolution), "--mesh-only"],
                           check=True, env=blender_environment())
            if not prepared.is_file():
                raise RuntimeError("Blender did not produce the prepared mesh")
            state = _journal_execution(journal)
            if state:
                _, manifest, execution = state
                current = execution["stages"][-1]
                _journal_finish(journal, current, [(prepared, "mesh.prepared")])
        prepared_upload = client.upload_input(prepared, "3d")
        workflow["prepared_mesh"]["inputs"]["model_file"] = f"{prepared_upload.get('subfolder', '3d')}/{prepared_upload['name']}"
        prepared_content_hash = file_sha256(prepared)
        del workflow["save_raw"]
        print("Material stage: generating and baking mesh-aware PBR textures...", flush=True)

    with _journal_stage(journal, "material_generation", journal_attempt,
                        {"seed": seed, "workflow": args.workflow.name if args.workflow else "hunyuan3d"},
                        {"backend": backend_provenance(health, queried=True)}) as stage:
        entry, prompt_id = run_model_workflow(workflow, client)
        _journal_finish(journal, stage, [])
    glb = find_glb(entry["outputs"].get("save", {})) if args.workflow else find_glb(entry["outputs"])
    if not glb:
        raise ValueError("ComfyUI finished but no final GLB was produced")
    with _journal_stage(journal, "mesh_output_acquisition", journal_attempt + 1,
                        {"phase": "material_outputs"}) as stage:
        client.download_output(glb, dest)
        textured = any(node.get("class_type") == "ApplyTextureToMesh" for node in workflow.values())
        textures = copy_generated_maps(entry["outputs"], dest.parent, client) if textured else {}
        conditioning_image = (copy_conditioning_image(entry["outputs"], dest.parent, client)
                              if "save_conditioning" in workflow else None)
        acquired = [(dest, "mesh.final")] + [(dest.parent / path, f"texture.{name}")
                                              for name, path in textures.items()]
        if conditioning_image:
            acquired.append((dest.parent / conditioning_image, "image.conditioning"))
        _journal_finish(journal, stage, acquired)
    models = sorted({value for node in workflow.values() for value in node.get("inputs", {}).values()
                     if isinstance(value, str) and value.endswith(".safetensors")})
    if args.metadata:
        args.metadata.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.metadata.with_name(f".{args.metadata.name}.tmp")
        workflow_digest = workflow_sha256(args.workflow) if args.workflow else None
        uploaded_inputs = {}
        for node_id, node in workflow.items():
            inputs = node.get("inputs", {})
            if node.get("class_type") == "LoadImage" and inputs.get("image") == comfy_image_name:
                uploaded_inputs[f"{node_id}.image"] = source_content_hash
            elif node.get("class_type") in {"LoadImage", "LoadMesh"} and "prepared_upload" in locals():
                if inputs.get("image") == f"{prepared_upload.get('subfolder', '3d')}/{prepared_upload['name']}" or \
                        inputs.get("model_file") == f"{prepared_upload.get('subfolder', '3d')}/{prepared_upload['name']}":
                    slot = "image" if "image" in inputs else "model_file"
                    uploaded_inputs[f"{node_id}.{slot}"] = prepared_content_hash
        identity = canonical_workflow_identity(source_workflow or workflow, workflow, uploaded_inputs)
        model_filenames = sorted({value for node in workflow.values() for value in node.get("inputs", {}).values()
                                  if isinstance(value, str) and value.endswith((".safetensors", ".ckpt", ".gguf", ".onnx"))})
        output_records = [{"path": dest.name, "sha256": file_sha256(dest), "kind": "mesh"}]
        if "raw_path" in locals() and raw_path.is_file():
            output_records.append({"path": raw_path.name, "sha256": file_sha256(raw_path), "kind": "mesh.raw"})
        if "prepared" in locals() and prepared.is_file():
            output_records.append({"path": prepared.name, "sha256": file_sha256(prepared), "kind": "mesh.prepared"})
        for key, relative in textures.items():
            target = dest.parent / relative
            output_records.append({"path": Path(relative).as_posix(), "sha256": file_sha256(target), "kind": f"texture.{key}"})
        if conditioning_image:
            target = dest.parent / conditioning_image
            output_records.append({"path": conditioning_image, "sha256": file_sha256(target), "kind": "conditioning_image"})
        remesh = next((node["inputs"] for node in workflow.values()
                       if node.get("class_type") == "RemeshMesh"), None)
        unwrap = next((node["inputs"] for node in workflow.values()
                       if node.get("class_type") == "UnwrapMesh"), None)
        mesh_preparation = {"face_budget": args.face_budget, "budget_unit": "triangles"}
        if remesh is not None:
            mesh_preparation.update({"method": "native_udf_remesh" if remesh.get("sign_mode") == "udf"
                                     else "native_signed_remesh", "resolution": remesh.get("resolution")})
        else:
            mesh_preparation.update({"method": "preserve_closed_or_remesh",
                                     "voxel_resolution": args.voxel_resolution})
        if unwrap is not None:
            mesh_preparation["uv_unwrap"] = unwrap.get("segmenter")
            mesh_preparation["uv_resolution"] = unwrap.get("resolution")
            mesh_preparation["padding"] = unwrap.get("padding")
        temporary.write_text(json.dumps({"workflow": args.workflow.name if args.workflow else "hunyuan3d_image_to_model_api",
                                        "model": models if args.workflow else args.checkpoint, "seed": seed,
                                        "workflow_sha256": workflow_digest,
                                        "workflow_source_sha256": workflow_digest,
                                        "workflow_source": ({"status": "known", "value": workflow_digest}
                                            if workflow_digest else {"status": "unavailable",
                                                "reason": "Hunyuan workflow is synthesized in the worker; no source file exists"}),
                                        "workflow_effective_sha256": identity["effective_sha256"],
                                        "effective_bindings": {"uploaded_inputs": identity["bindings"],
                                            "workflow_inputs": json.loads(args.workflow_inputs) if args.workflow_inputs else {},
                                            "seed": seed, "face_budget": args.face_budget,
                                            "voxel_resolution": args.voxel_resolution,
                                            "source_image_sha256": source_content_hash},
                                        "backend": backend_provenance(health, queried=True),
                                        "provenance": {"model_weights": backend_provenance(health, queried=True)["model_weights"],
                                            "custom_node_revisions": backend_provenance(health, queried=True)["custom_node_revisions"]},
                                        "model_filenames": [{"status": "known", "value": value} for value in model_filenames],
                                        "outputs": output_records,
                                        "workflow_requirements": workflow_requirements,
                                        "mesh_preparation": mesh_preparation,
                                        "prompt_id": prompt_id, "shape_prompt_id": shape_prompt_id,
                                        "textured": textured, "textures": textures,
                                        "conditioning_image": conditioning_image,
                                        "normal_source": "workflow" if entry["outputs"].get("save_normal", {}).get("images") else
                                                         "neutral_placeholder",
                                        "quality": json.loads(args.quality) if args.quality else None}, indent=2) + "\n")
        temporary.replace(args.metadata)
    print(f"GLB: {dest}")


if __name__ == "__main__":
    main()
