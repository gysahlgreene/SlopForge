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
import zlib
from contextlib import contextmanager
from pathlib import Path
from slopforge.backends.comfyui import ComfyUIClient, ComfyUIError
from slopforge.backends.blender import blender_environment
from slopforge.provenance import workflow_sha256, file_sha256, canonical_workflow_identity
from slopforge.backends.comfyui import backend_provenance, _write_failure_report
from slopforge.quality import apply_workflow_inputs
from slopforge.providers import BUILTIN_RIGHTS
from slopforge.workflow_requirements import workflow_output_rights, workflow_requirements_identity
from slopforge.validation import validate_image
from slopforge.manifest import (load_manifest, save_manifest, find_asset, begin_stage,
                                start_stage, finish_stage)
from slopforge.failures import StageFailure, failure_record


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
def _journal_stage(context, name, attempt, settings, provenance=None, *, inputs=None):
    state = _journal_execution(context)
    if state is None:
        yield
        return
    context, manifest, execution = state
    stages = execution.get("stages")
    if not isinstance(stages, list) or not all(isinstance(item, dict) for item in stages):
        raise ValueError("Execution stages are malformed; worker journal attribution stopped")
    ids = [item["id"] for item in stages if "id" in item]
    if (not all(isinstance(item, str) and item for item in ids) or len(ids) != len(set(ids))):
        raise ValueError("Execution stage IDs are malformed or ambiguous")
    if name == "mesh_workflow_execution":
        stage_id = context.get("stage_id")
        matches = [item for item in stages if item.get("id") == stage_id]
        if (not stage_id or len(matches) != 1 or matches[0].get("name") != name or
                matches[0].get("attempt") != attempt or matches[0].get("status") != "running"):
            raise ValueError("Parent mesh stage handle is missing or ambiguous")
        stage = matches[0]
    else:
        stage = start_stage(execution, name, attempt,
                            context.get("upstream_artifacts", []) if inputs is None else inputs,
                            settings, provenance or {})
        save_manifest(context["manifest_path"], manifest)
    if name == "mesh_workflow_execution":
        stage.setdefault("provenance", {}).update(provenance or {})
        save_manifest(context["manifest_path"], manifest)
    if stage["status"] == "pending":
        begin_stage(stage)
        save_manifest(context["manifest_path"], manifest)
    try:
        yield stage
    except (Exception, KeyboardInterrupt) as exc:
        if isinstance(exc, ComfyUIError) and exc.category:
            reported = StageFailure(
                exc.category, str(exc), operation=exc.operation or name,
                remedy="inspect the retained stage evidence and resolve the reported boundary",
                stage=name, stage_id=stage["id"], evidence=exc.evidence)
        elif isinstance(exc, KeyboardInterrupt):
            reported = StageFailure(
                "interruption", str(exc) or "Worker interrupted", operation=name,
                remedy="inspect retained state and explicitly resume; remote inference may still be running",
                stage=name, stage_id=stage["id"])
        else:
            reported = exc
        failure = failure_record(
            reported, stage=name, stage_id=stage["id"], attempt=attempt,
            operation=(reported.operation if isinstance(reported, StageFailure) else name))
        finish_stage(stage, "failed", error=str(exc) or type(exc).__name__, failure=failure)
        save_manifest(context["manifest_path"], manifest)
        if reported is not exc:
            raise reported from exc
        raise


def _journal_finish(context, stage, outputs):
    if stage is None:
        return []
    state = _journal_execution(context)
    if state is None:
        return
    context, manifest, execution = state
    stages = execution.get("stages")
    if not isinstance(stages, list) or not all(isinstance(item, dict) for item in stages):
        raise ValueError("Execution stages are malformed; worker journal attribution stopped")
    ids = [item["id"] for item in stages if "id" in item]
    if (not all(isinstance(item, str) and item for item in ids) or len(ids) != len(set(ids))):
        raise ValueError("Execution stage IDs are malformed or ambiguous")
    if stage.get("id"):
        matches = [item for item in stages if item.get("id") == stage["id"]]
    else:
        matches = [item for item in stages if item.get("name") == stage.get("name")
                   and item.get("attempt") == stage.get("attempt")]
    if len(matches) != 1:
        raise ValueError("Worker stage handle is missing or ambiguous")
    current = matches[0]
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
    return refs


def _workflow_identity(source, effective, images, prepared_name=None, prepared_hash=None):
    """images maps each uploaded image name (source concept and any views) to its content hash."""
    uploaded = {}
    for node_id, node in effective.items():
        inputs = node.get("inputs", {})
        if node.get("class_type") == "LoadImage" and inputs.get("image") in images:
            uploaded[f"{node_id}.image"] = images[inputs["image"]]
        # Bound by uploaded name, not loader class: the bundled graphs load it with Load3DAdvanced.
        elif prepared_name and inputs.get("model_file") == prepared_name:
            uploaded[f"{node_id}.model_file"] = prepared_hash
    return canonical_workflow_identity(source or effective, effective, uploaded), uploaded


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


VIEW_SLOTS = ("front", "left", "back", "right")


def load_model_workflow(path, image_name, asset_name, seed, face_budget, views=None):
    """views maps a multi-view slot to its uploaded image; LoadImage nodes named view_<slot> take it."""
    workflow = json.loads(Path(path).read_text())
    views = views or {}
    sampler_index = 0
    for node_id, node in workflow.items():
        inputs = node.setdefault("inputs", {})
        kind = node.get("class_type")
        if kind == "LoadImage" and node_id.startswith("view_"):
            slot = node_id.removeprefix("view_")
            if slot not in views:
                raise ValueError(f"Model workflow {Path(path).name} needs a {slot} view (node {node_id}); "
                                 "configure workflows.views so conditioning preparation generates it")
            inputs["image"] = views[slot]
        elif kind == "LoadImage":
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


def project_concept(args, dest, textures):
    """Project the front concept onto the base color; the voxel bake is kept beside it."""
    basecolor = dest.parent / textures["basecolor"]
    voxel = basecolor.with_name("basecolor_voxel.png")
    shutil.copy2(basecolor, voxel)
    request = dest.parent / "concept_projection_request.json"
    report = dest.parent / "concept_projection.json"
    request.write_text(json.dumps({"model": str(dest), "basecolor": str(voxel), "concept": str(args.image),
                                   "output": str(basecolor), "report": str(report)}))
    result = subprocess.run([str(args.blender), "--background", "--python-exit-code", "1", "--python",
                             str(Path(__file__).resolve().parents[1] / "blender/project_concept.py"), "--", str(request)],
                            capture_output=True, text=True)
    if result.returncode != 0 or not report.is_file():
        raise ValueError("Concept projection failed: " + (result.stdout + result.stderr)[-2000:])
    projection = json.loads(report.read_text())
    if projection["status"] == "skipped":
        shutil.copy2(voxel, basecolor)
    print(f"Concept projection {projection['status']}: aspect error {projection.get('aspect_error')}")
    return {**projection, "voxel_basecolor": voxel.relative_to(dest.parent).as_posix()}


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


def run_model_workflow(workflow, client, *args, memory_retry=True):
    prompt_id = client.queue_workflow(workflow)
    print(f"Queued 3D generation: {prompt_id}", flush=True)
    try:
        return client.wait_for_completion(prompt_id), prompt_id
    except ComfyUIError as exc:
        # A remote out-of-memory failure is the cache of earlier jobs, not this one: a texture bake failed holding
        # 77 GiB after seven back-to-back approvals, and passed once ComfyUI freed its memory (2026-10-23).
        if (memory_retry and (exc.evidence or {}).get("remote_terminal") is True
                and "out of memory" in str(exc).lower()):
            print("ComfyUI ran out of GPU memory; freeing its cache and queueing once more", flush=True)
            client.free_memory()
            return run_model_workflow(workflow, client, *args, memory_retry=False)
        # Tag at known boundary (execution → inference); never infer
        # retryability from message text.
        exc.category = exc.category or "inference"
        evidence = exc.evidence if isinstance(exc.evidence, dict) else {}
        evidence = {**evidence, "prompt_id": prompt_id}
        if evidence.get("remote_terminal") is not True:
            evidence["outcome_unknown"] = True
        exc.evidence = evidence
        raise
    except Exception as exc:
        raise ComfyUIError(
            f"Could not validate ComfyUI history for prompt {prompt_id}: {exc}",
            category="inference", operation="wait_for_completion",
            evidence={"prompt_id": prompt_id, "outcome_unknown": True}) from exc


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
    parser.add_argument("--project-concept", action="store_true",
                        help="Project the front concept onto camera-facing base color (character concepts)")
    parser.add_argument("--remove-hidden-faces", action="store_true",
                        help="delete the faces no ray from outside reaches before the reduction (blender/mesh_cleanup.py)")
    parser.add_argument("--require-manifold", action="store_true",
                        help="Make the mesh manifold (characters must be closed to rig): local repair, voxel repair as fallback")
    parser.add_argument("--view", action="append", default=[], metavar="SLOT=PATH",
                        help="Framed view for a multi-view workflow slot (front, left, back, right)")
    parser.add_argument("--workflow-inputs", help="JSON node/input overrides for the selected quality tier")
    parser.add_argument("--quality", help="JSON quality tier and effective settings for provenance")
    parser.add_argument("--journal-context", help="Optional prop manifest journal context JSON")
    parser.add_argument("--failure-report", help="Path to write atomic failure report on handled error")
    args = parser.parse_args()
    if args.face_budget <= 0:
        parser.error("--face-budget must be positive")
    if args.voxel_resolution <= 0:
        parser.error("--voxel-resolution must be positive")
    view_paths = {}
    for spec in args.view:
        slot, separator, path = spec.partition("=")
        if not separator or slot not in VIEW_SLOTS or slot in view_paths or not Path(path).is_file():
            parser.error(f"--view must be a unique SLOT=PATH of an existing image with SLOT in {VIEW_SLOTS}, got {spec!r}")
        view_paths[slot] = Path(path).resolve()

    src = Path(args.image).expanduser().resolve()

    if not src.exists():
        print(f"Input image does not exist: {src}", file=sys.stderr)
        sys.exit(1)

    if args.workflow and validate_image(src, expected_format=None, require_alpha=True)["status"] == "failed":
        # The model graphs crop to the concept's alpha and remove no background: an opaque concept is rebuilt with
        # its backdrop, as a card or box around the object (2026-10-24 weapon graph A/B, docs/WORKFLOWS.md).
        print(f"Model workflows need the concept cut-out with transparency (slopforge.surface.make_cutout); "
              f"{src.name} has no alpha channel", file=sys.stderr)
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
        health = client.health(retry_window=120)
    except ComfyUIError as exc:
        # Tag at known boundary (health → environment).
        if not exc.category:
            exc.category = "environment"
        if args.failure_report:
            _write_failure_report(args.failure_report, error=exc)
        print(f"ComfyUI is not reachable at {COMFY_URL}: {exc}", file=sys.stderr)
        sys.exit(1)

    uploaded = client.upload_input(src, "ai3d")
    comfy_image_name = f"{uploaded.get('subfolder', 'ai3d')}/{uploaded['name']}"
    source_content_hash = file_sha256(src)
    image_hashes = {comfy_image_name: source_content_hash}
    comfy_views = {}
    for slot, path in view_paths.items():
        uploaded_view = client.upload_input(path, "ai3d")
        comfy_views[slot] = f"{uploaded_view.get('subfolder', 'ai3d')}/{uploaded_view['name']}"
        image_hashes[comfy_views[slot]] = file_sha256(path)

    seed = args.seed if args.seed is not None else int(time.time_ns() % 9223372036854775807)
    workflow = (load_model_workflow(args.workflow, comfy_image_name, name, seed, args.face_budget, comfy_views)
                if args.workflow else make_workflow(comfy_image_name, name, args.checkpoint, seed))
    if args.workflow_inputs:
        apply_workflow_inputs(workflow, json.loads(args.workflow_inputs))
    if "normal_bake" in workflow and "maps" in workflow:  # keep the normal bake at the color bake's tier resolution
        workflow["normal_bake"]["inputs"]["resolution"] = workflow["maps"]["inputs"]["texture_size"]
    # The rights in what each sub-stage makes: the models the effective graph loads (after overrides), and Blender
    # where it reduces or projects. The legacy inline Hunyuan3D graph has no sidecar: its terms are unread.
    graph_models = sorted({value for node in workflow.values() for value in node.get("inputs", {}).values()
                           if isinstance(value, str) and value.endswith((".safetensors", ".ckpt", ".gguf", ".onnx"))})
    model_rights = workflow_output_rights(args.workflow, graph_models) if args.workflow else [
        {"source": "legacy Hunyuan3D 2.0 graph", "status": "unknown",
         "reason": "the inline graph has no requirements sidecar; Tencent's community licence was not checked for "
                   "this use"}]
    blender_rights = [{"source": "blender", **BUILTIN_RIGHTS["blender"]}]
    dest = Path(args.dest).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shape_prompt_id = None
    journal = json.loads(args.journal_context) if args.journal_context else None
    journal_attempt = (journal or {}).get("attempt", 1)
    if "prepared_mesh" in workflow:
        if args.blender is None:
            raise ValueError("This model workflow requires --blender for mesh reduction and UV preparation")
        raw_workflow = {key: node for key, node in workflow.items()
                        if not key.startswith("save") or key in {"save_raw", "save_detail"}}
        raw_identity, raw_bindings = _workflow_identity(source_workflow, raw_workflow, image_hashes)
        source_hash = workflow_sha256(args.workflow) if args.workflow else None
        raw_provenance = {
            "workflow_source_sha256": ({"status": "known", "value": source_hash} if source_hash else
                {"status": "unavailable", "reason": "Hunyuan workflow is synthesized; no source file exists"}),
            "workflow_effective_sha256": {"status": "known", "value": raw_identity["effective_sha256"]},
            "effective_bindings": {"uploaded_inputs": raw_bindings},
        }
        print("Mesh stage: generating the detailed shape...", flush=True)
        with _journal_stage(journal, "mesh_workflow_execution", journal_attempt,
                            {"phase": "raw_shape", "seed": seed},
                            {"backend": backend_provenance(health, queried=True), **raw_provenance,
                             "output_rights": model_rights}) as stage:
            entry, shape_prompt_id = run_model_workflow(raw_workflow, client)
            raw = find_glb(entry["outputs"].get("save_raw", {}))
            if not raw:
                raise ValueError("Model workflow did not produce its raw mesh")
        raw_path = dest.with_name(dest.stem + "_untextured.glb")
        detail = find_glb(entry["outputs"].get("save_detail", {}))
        detail_path = dest.with_name(dest.stem + "_detail.glb") if detail else None
        baked_normal = dest.with_name(dest.stem + "_normal_mikktspace.png") if detail else None
        with _journal_stage(journal, "mesh_raw_acquisition", journal_attempt,
                            {"phase": "raw_shape"}, {"output_rights": model_rights}) as stage:
            client.download_output(raw, raw_path)
            if detail:
                client.download_output(detail, detail_path)
            raw_refs = _journal_finish(journal, stage, [(raw_path, "mesh.raw")] +
                                       ([(detail_path, "mesh.detail")] if detail else []))
        prepared = dest.with_name(f"{name}_{seed}_prepared.glb")
        print("Mesh stage: Blender reduction and UV preparation...", flush=True)
        script = Path(__file__).resolve().parents[1] / "blender" / "prepare_model.py"
        # Blender reduces the full-detail shape where the graph's own reduction is midpoint DecimateMesh, which made a
        # pistol's flat steel wavy and rounded its edges; Blender's collapse decimation of the same shape kept them
        # and removes inner shells before the budget is spent (2026-10-24, docs/QUALITY-TIERS.md). The character
        # graph's crease-preserving QEM reduction is kept: its manifold repair and rigging were tuned on it.
        midpoint = any(node.get("class_type") == "DecimateMesh" and node["inputs"].get("placement_mode") == "midpoint"
                       for node in workflow.values())
        source_kind, source_path = ("mesh.detail", detail_path) if detail and midpoint else ("mesh.raw", raw_path)
        with _journal_stage(journal, "mesh_preparation", journal_attempt,
                            {"face_budget": args.face_budget, "voxel_resolution": args.voxel_resolution,
                             "source": source_kind,
                             **({"remove_hidden_faces": True} if args.remove_hidden_faces else {})},
                            {"output_rights": blender_rights},
                            inputs=None if raw_refs is None else [ref for ref in raw_refs if ref["type"] == source_kind]):
            subprocess.run([str(args.blender), "--background", "--python-exit-code", "1", "--python", str(script), "--", str(source_path),
                            str(prepared), str(dest.with_name("native_mesh.blend")), "--face-budget", str(args.face_budget),
                            "--voxel-resolution", str(args.voxel_resolution), "--mesh-only",
                            # The graph already ran a UDF remesh; Blender's voxel remesh would erase thin parts.
                            *(["--no-voxel-repair"] if "shape_remesh" in workflow and not args.require_manifold else []),
                            # Manifold types try a local repair first; voxel repair only runs if it fails.
                            *(["--local-repair"] if args.require_manifold else []),
                            # The budget and the texture go to what a player can see (docs/MATERIALS.md, Geometry and maps)
                            *(["--remove-hidden-faces"] if args.remove_hidden_faces else []),
                            # Normals are baked in Blender (MikkTSpace, as Blender and Unity shade) from the
                            # full-detail remesh; ComfyUI's bake uses Lengyel tangents and speckles when shaded.
                            *(["--detail-mesh", str(detail_path), "--normal-output", str(baked_normal),
                               "--texture-size", str(workflow.get("maps", {}).get("inputs", {}).get("texture_size", 2048))]
                              if detail else [])],
                           check=True, env=blender_environment())
            if not prepared.is_file():
                raise RuntimeError("Blender did not produce the prepared mesh")
            state = _journal_execution(journal)
            if state:
                _, manifest, execution = state
                current = execution["stages"][-1]
                prepared_refs = _journal_finish(journal, current, [(prepared, "mesh.prepared")])
        prepared_upload = client.upload_input(prepared, "3d")
        workflow["prepared_mesh"]["inputs"]["model_file"] = f"{prepared_upload.get('subfolder', '3d')}/{prepared_upload['name']}"
        prepared_content_hash = file_sha256(prepared)
        del workflow["save_raw"]
        print("Material stage: generating and baking mesh-aware PBR textures...", flush=True)

    material_inputs = prepared_refs if "prepared_refs" in locals() else (journal or {}).get("upstream_artifacts", [])
    prepared_name = (f"{prepared_upload.get('subfolder', '3d')}/{prepared_upload['name']}"
                     if "prepared_upload" in locals() else None)
    identity, uploaded_inputs = _workflow_identity(source_workflow, workflow, image_hashes,
        prepared_name, prepared_content_hash if "prepared_content_hash" in locals() else None)
    source_hash = workflow_sha256(args.workflow) if args.workflow else None
    material_provenance = {
        "workflow_source_sha256": ({"status": "known", "value": source_hash} if source_hash else
            {"status": "unavailable", "reason": "Hunyuan workflow is synthesized; no source file exists"}),
        "workflow_effective_sha256": {"status": "known", "value": identity["effective_sha256"]},
        "effective_bindings": {"uploaded_inputs": uploaded_inputs},
    }
    with _journal_stage(journal, "material_generation", journal_attempt,
                        {"seed": seed, "workflow": args.workflow.name if args.workflow else "hunyuan3d"},
                        {"backend": backend_provenance(health, queried=True), **material_provenance,
                         "output_rights": model_rights},
                        inputs=material_inputs) as stage:
        entry, prompt_id = run_model_workflow(workflow, client)
        glb = find_glb(entry["outputs"].get("save", {})) if args.workflow else find_glb(entry["outputs"])
        if not glb:
            raise ValueError("ComfyUI finished but no final GLB was produced")
        _journal_finish(journal, stage, [])
    with _journal_stage(journal, "mesh_output_acquisition", journal_attempt,
                        {"phase": "material_outputs"},
                        {"output_rights": model_rights + (blender_rights if args.project_concept else [])},
                        inputs=material_inputs) as stage:
        client.download_output(glb, dest)
        textured = any(node.get("class_type") == "ApplyTextureToMesh" for node in workflow.values())
        mikktspace = locals().get("baked_normal")
        mikktspace = mikktspace if mikktspace is not None and Path(mikktspace).is_file() else None
        textures = copy_generated_maps(entry["outputs"], dest.parent, client, baked_normal=mikktspace) if textured else {}
        projection = None
        if args.project_concept and textures:
            projection = project_concept(args, dest, textures)
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
        model_filenames = sorted({value for node in workflow.values() for value in node.get("inputs", {}).values()
                                  if isinstance(value, str) and value.endswith((".safetensors", ".ckpt", ".gguf", ".onnx"))})
        output_records = [{"path": dest.name, "sha256": file_sha256(dest), "kind": "mesh"}]
        if "raw_path" in locals() and raw_path.is_file():
            output_records.append({"path": raw_path.name, "sha256": file_sha256(raw_path), "kind": "mesh.raw"})
        if locals().get("detail_path") and detail_path.is_file():
            output_records.append({"path": detail_path.name, "sha256": file_sha256(detail_path), "kind": "mesh.detail"})
        if "prepared" in locals() and prepared.is_file():
            output_records.append({"path": prepared.name, "sha256": file_sha256(prepared), "kind": "mesh.prepared"})
        for key, relative in textures.items():
            target = dest.parent / relative
            output_records.append({"path": Path(relative).as_posix(), "sha256": file_sha256(target), "kind": f"texture.{key}"})
        if conditioning_image:
            target = dest.parent / conditioning_image
            output_records.append({"path": conditioning_image, "sha256": file_sha256(target), "kind": "conditioning_image"})
        if projection and projection.get("voxel_basecolor"):
            output_records.append({"path": projection["voxel_basecolor"],
                                   "sha256": file_sha256(dest.parent / projection["voxel_basecolor"]),
                                   "kind": "texture.basecolor_voxel"})
        remesh = next((node["inputs"] for node in workflow.values()
                       if node.get("class_type") == "RemeshMesh"), None)
        unwrap = next((node["inputs"] for node in workflow.values()
                       if node.get("class_type") == "UnwrapMesh"), None)
        mesh_preparation = {"face_budget": args.face_budget, "budget_unit": "triangles",
                            **({"source": source_kind} if "source_kind" in locals() else {})}
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
                                            "source_image_sha256": source_content_hash,
                                            **({"view_sha256": {slot: image_hashes[name] for slot, name in comfy_views.items()}}
                                               if comfy_views else {})},
                                        "backend": backend_provenance(health, queried=True),
                                        "provenance": {"model_weights": backend_provenance(health, queried=True)["model_weights"],
                                            "custom_node_revisions": backend_provenance(health, queried=True)["custom_node_revisions"]},
                                        "model_filenames": [{"status": "known", "value": value} for value in model_filenames],
                                        "outputs": output_records,
                                        "workflow_requirements": workflow_requirements,
                                        "output_rights": model_rights,
                                        "mesh_preparation": mesh_preparation,
                                        "prompt_id": prompt_id, "shape_prompt_id": shape_prompt_id,
                                        "textured": textured, "textures": textures,
                                        "conditioning_image": conditioning_image,
                                        "basecolor_source": ("voxel_with_front_concept_projection"
                                                             if projection and projection["status"] == "projected"
                                                             else "voxel") if textures else None,
                                        "concept_projection": projection,
                                        "normal_source": "workflow" if entry["outputs"].get("save_normal", {}).get("images") else
                                                         "blender_mikktspace_bake" if mikktspace else
                                                         "neutral_placeholder",
                                        "quality": json.loads(args.quality) if args.quality else None}, indent=2) + "\n")
        temporary.replace(args.metadata)
    print(f"GLB: {dest}")


def _write_invocation_failure(error):
    try:
        report_index = sys.argv.index("--failure-report")
        report_path = sys.argv[report_index + 1]
    except (ValueError, IndexError):
        return
    if isinstance(error, (ComfyUIError, StageFailure)):
        reported = error
    elif isinstance(error, KeyboardInterrupt):
        reported = StageFailure("interruption", "Worker interrupted", operation="worker",
            remedy="inspect retained state and explicitly resume; remote inference may still be running")
    else:
        reported = StageFailure("unknown", str(error) or type(error).__name__, operation="worker",
            remedy="inspect the retained worker output and identify the failing boundary")
    _write_failure_report(report_path, error=reported)


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        _write_invocation_failure(exc)
        raise
