import json
import math
import copy
import os
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from PIL import Image, ImageStat

from ..backends.blender import inspect_model, process_model
from ..backends.comfyui import generate_image, generate_model, python_executable, workflow_mask_errors
from ..backends.omnipart import generate_part_model
from ..backends.hybrid import MAX_OPEN_PART_STRETCH, generate_hybrid_parts
from ..config import select_quality_tier, workflow_node_inputs
from ..candidates import generate_candidates
from ..conditioning import ensure_supported, resolve_conditioning
from ..failures import StageFailure, candidate_quality_rejection, failure_record, should_retry
from ..manifest import (save_manifest, load_manifest, start_execution, start_stage, begin_stage,
                        finish_stage, finish_execution, record_reuse_decision, execution_identity)
from ..paths import blender_executable, resolve_workflow, tool_root
from ..providers import (NOTICES_FILE, combine_rights, lineage_rights, merge_rights, require_shippable,
                         rights_of, write_notices)
from ..provenance import generator_provenance, file_sha256, tool_sha256
from ..open_state import hinged_part, open_choice, open_paths, prepare_open_conditioning
from .reuse import _valid_sha256, artifact_integrity, stage_reuse_decision
from ..style import build_prompt, style_identity
from ..taxonomy import load_taxonomy, output_path
from ..unity_material import (apply_glass, build_unity_material, derive_emission, emitter_colour_mask, glass_material_path,
                              finish_word, make_metallic_gloss, match_concept_colours, match_metal_lightness,
                              unity_cli, zero_metallic, concept_part_colours)
from ..emitters import concept_emitter_mask, project_to_texture
from ..unity_weapon import build_weapon_prefab
from ..unity_playmode import verify_play_mode
from ..kit_material import kit_texture, match_hue, match_roughness
from ..parts import check_part_masks, check_slide_scale, make_part_masks, part_settings
from ..validation import (MIN_EMISSIVE_FRACTION, apply_concept_colour, apply_concept_silhouette, apply_declared_emitter,
                          apply_hybrid_alignment, apply_mesh_folds, apply_part_coverage, apply_part_fit,
                          apply_part_penetration, apply_visible_backfaces,
                          apply_concept_fit, apply_declared_glass, apply_declared_nonmetal, apply_module_footprint,
                          apply_module_stretch, apply_moving_parts, apply_thin_features, apply_weapon_orientation,
                          concept_colour_fidelity, concept_thin_recall,
                          is_placeholder_normal, measure_material_maps, validate_image,
                          validate_model_outputs)


def _artifact_ref(root, path, artifact_id, kind, stage, attempt, derived_from=()):
    path = Path(path)
    return {"id": artifact_id, "type": kind, "path": path.resolve().relative_to(Path(root).resolve()).as_posix(),
            "sha256": file_sha256(path), "stage": stage, "attempt": attempt,
            "derived_from": [{"artifact_id": item["id"], "sha256": item["sha256"]}
                             for item in derived_from]}


def _persist_reload(root, pipeline, manifest):
    path = Path(root) / pipeline["manifest"]
    from .. import SCHEMA_VERSION
    manifest.setdefault("schema_version", SCHEMA_VERSION)
    save_manifest(path, manifest)
    return _reload_manifest(root, pipeline, manifest)


def _reload_manifest(root, pipeline, manifest):
    latest = load_manifest(Path(root) / pipeline["manifest"])
    assets = manifest.setdefault("assets", {})
    latest_assets = latest.get("assets", {})
    for key in list(assets):
        if key not in latest_assets:
            del assets[key]
    for key, latest_asset in latest_assets.items():
        if key in assets:
            assets[key].clear()
            assets[key].update(latest_asset)
        else:
            assets[key] = latest_asset
    manifest.update({key: value for key, value in latest.items() if key != "assets"})
    manifest["assets"] = assets
    return manifest


def _execution_stage(asset, execution_id, name=None, attempt=None, *, stage_id=None):
    executions = asset.get("executions")
    if not isinstance(executions, list) or not all(isinstance(item, dict) for item in executions):
        raise ValueError("Execution history is malformed; stage attribution is ambiguous")
    matches = [item for item in executions if item.get("id") == execution_id]
    if len(matches) != 1:
        raise ValueError("Execution identity is missing or ambiguous; stage attribution stopped")
    execution = matches[0]
    stages = execution.get("stages")
    if not isinstance(stages, list) or not all(isinstance(item, dict) for item in stages):
        raise ValueError("Execution stages are malformed; stage attribution is ambiguous")
    ids = []
    for item in stages:
        if (not isinstance(item.get("name"), str) or not item["name"] or
                type(item.get("attempt")) is not int or item["attempt"] < 1):
            raise ValueError("Execution stage identity is malformed; stage attribution is ambiguous")
        if "id" in item:
            if not isinstance(item["id"], str) or not item["id"]:
                raise ValueError("Execution stage ID is malformed; stage attribution is ambiguous")
            ids.append(item["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Execution stage IDs are duplicated; stage attribution is ambiguous")
    if stage_id is not None:
        candidates = [item for item in stages if item.get("id") == stage_id]
        if (len(candidates) != 1 or (name is not None and candidates[0]["name"] != name) or
                (attempt is not None and candidates[0]["attempt"] != attempt)):
            raise ValueError("Stage ID is missing, mismatched, or ambiguous")
        return execution, candidates[0]
    if name is None or type(attempt) is not int:
        raise ValueError("Stage lookup requires an exact ID or a name and attempt")
    candidates = [item for item in stages if item["name"] == name and item["attempt"] == attempt]
    if len(candidates) != 1:
        raise ValueError("Legacy stage name/attempt lookup is missing or ambiguous")
    return execution, candidates[0]


def _execution_chain(asset, execution_id):
    executions = asset.get("executions")
    if not isinstance(executions, list) or not all(isinstance(item, dict) for item in executions):
        raise ValueError("Execution history is malformed; resume accounting is ambiguous")
    ids = [item.get("id") for item in executions]
    if not all(isinstance(item, str) and item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("Execution IDs are malformed or duplicated; resume accounting is ambiguous")
    by_id = dict(zip(ids, executions))
    chain, seen = [], set()
    current_id = execution_id
    while current_id is not None:
        if current_id in seen or current_id not in by_id:
            raise ValueError("Execution parent chain is missing or cyclic; resume accounting stopped")
        seen.add(current_id)
        current = by_id[current_id]
        stages = current.get("stages")
        if not isinstance(stages, list) or not all(isinstance(item, dict) for item in stages):
            raise ValueError("Execution stages are malformed; resume accounting stopped")
        stage_ids = [item["id"] for item in stages if "id" in item]
        if (not all(isinstance(item, str) and item for item in stage_ids) or
                len(stage_ids) != len(set(stage_ids))):
            raise ValueError("Execution stage IDs are malformed or duplicated; resume accounting stopped")
        chain.append(current)
        current_id = current.get("parent_execution_id")
    return list(reversed(chain))


def _unknown_outcome_prompts(execution):
    stages = execution.get("stages")
    if not isinstance(stages, list) or not all(isinstance(item, dict) for item in stages):
        raise ValueError("Cannot resume: failure history is malformed")
    prompts = []
    for stage in stages:
        failure = stage.get("failure")
        if failure is None:
            continue
        if (not isinstance(failure, dict) or "evidence" not in failure or
                not isinstance(failure["evidence"], dict)):
            raise ValueError("Cannot resume: failure evidence is malformed")
        evidence = failure["evidence"]
        if "outcome_unknown" in evidence and not isinstance(evidence["outcome_unknown"], bool):
            raise ValueError("Cannot resume: remote outcome evidence is malformed")
        if evidence.get("outcome_unknown") is True:
            prompt_id = evidence.get("prompt_id")
            if isinstance(prompt_id, str) and prompt_id:
                prompts.append(prompt_id)
            else:
                prompts.append("unknown prompt ID")
    return prompts


def _resolve_interrupted_prior(asset, execution, root, pipeline, manifest):
    """Mark unresolved running work on *execution* as terminal interruption before reuse.

    *execution* is a prior that survived from the previous run and still has
    ``status == 'running'`` because the process died before it could finish.
    ``status = 'running'`` is an incomplete terminal state – the manifest cannot
    be trusted to reflect the real outcome.

    For every stage that is still ``status == 'running'``:

    * Terminate the stage with ``category == 'interruption'`` and record the exact
      ``stage_id`` of that stage.
    * Record evidence that completion was *not* persisted, together with the
      recovery detection timestamp and the unknown original termination time /
      cause.
    * Any *previously* succeeded stages and their artifacts are preserved
      untouched.

    After all stages are classified, mark the *execution* itself as ``failed``
    with a matching ``interruption`` failure.

    Returns ``None`` on success.  Returns the ``{execution_id, unresolved_stage_name}``
    dict when the unresolved stage is mesh-related and carries evidence that a
    remote prompt may have been accepted (``outcome_unknown``) – the caller must
    stop resume and surface an actionable service-inspection message before any
    new inference submission.
    """
    from slopforge.manifest import finish_stage, finish_execution
    unresolved = [
        stage for stage in execution.get("stages", [])
        if isinstance(stage, dict) and stage.get("status") == "running"
    ]
    if not unresolved and execution.get("status") != "running":
        return None

    mesh_stages = {"mesh_workflow_execution"}
    mesh_worker_stages = {
        "mesh_raw_acquisition", "mesh_preparation", "material_generation",
        "mesh_output_acquisition",
    }
    pending_remote = next(
        (stage for stage in unresolved
         if (stage.get("name") in mesh_stages or stage.get("name") in mesh_worker_stages)
         and stage.get("started_at") is not None),
        None)

    now = datetime.now(timezone.utc).isoformat()
    for stage in unresolved:
        execution_failure = failure_record(
            RuntimeError("Process terminated while stage was running; completion not persisted"),
            stage=stage["name"],
            stage_id=stage.get("id"),
            attempt=stage.get("attempt"),
            operation=(stage.get("operation", stage["name"])),
        )
        execution_failure["category"] = "interruption"
        execution_failure["evidence"] = {
            "completion_not_persisted": True,
            "recovery_detected_at": now,
            "unknown_original_termination_time": True,
            "unknown_original_termination_cause": True,
        }
        prior_evidence = (stage.get("failure") or {}).get("evidence", {})
        execution_failure["evidence"]["outcome_unknown"] = (
            stage is pending_remote or prior_evidence.get("outcome_unknown") is True
        )
        prompt_id = prior_evidence.get("prompt_id")
        if isinstance(prompt_id, str) and prompt_id:
            execution_failure["evidence"]["prompt_id"] = prompt_id
        execution_failure["message"] = (
            f"Stage '{stage['name']}' (id={stage.get('id')}) was still running when the prior "
            "process died; inference completion cannot be trusted."
        )
        execution_failure["remedy"] = (
            "inspect the service state after restart and verify inference outcomes "
            "before submitting new work."
        )
        finish_stage(stage, "failed",
                     error="Process terminated while stage was running; completion not persisted",
                     failure=execution_failure)

    failed_on = "unknown"
    for stage in unresolved:
        if stage.get("name") in mesh_stages or stage.get("name") in mesh_worker_stages:
            failed_on = stage["name"]
            break

    exec_failure = failure_record(
        RuntimeError("Prior execution terminated without completion; stages marked as interruption"),
        stage=failed_on, attempt=None, operation="model_approval",
    )
    exec_failure["category"] = "interruption"
    exec_failure["evidence"] = {
        "completion_not_persisted": True,
        "recovery_detected_at": now,
        "unknown_original_termination_time": True,
        "unknown_original_termination_cause": True,
    }
    exec_failure["message"] = (
        "Prior execution was still running on restart; inferred interruption."
    )
    exec_failure["remedy"] = (
        "inspect the service state after restart and verify inference outcomes "
        "before submitting new work."
    )
    finish_execution(execution, "failed", failure=exec_failure)
    root = Path(root)  # normalize to Path
    _persist_reload(root, pipeline, manifest)
    if pending_remote:
        return {"execution_id": execution["id"], "unresolved_stage_name": pending_remote["name"]}
    return None


def _partial_worker_output(execution):
    stages = execution.get("stages")
    if not isinstance(stages, list) or not all(isinstance(item, dict) for item in stages):
        raise ValueError("Cannot resume: worker stage history is malformed")
    ids = [item["id"] for item in stages if "id" in item]
    if (not all(isinstance(item, str) and item for item in ids) or len(ids) != len(set(ids)) or
            any(not isinstance(item.get("name"), str) or type(item.get("attempt")) is not int or
                item["attempt"] < 1 for item in stages)):
        raise ValueError("Cannot resume: worker stage identity is malformed or ambiguous")
    failed_mesh_attempts = {item["attempt"] for item in stages
                            if item["name"] == "mesh_workflow_execution" and item.get("status") == "failed"}
    worker_stages = {"mesh_raw_acquisition", "mesh_preparation", "material_generation",
                     "mesh_output_acquisition"}
    return next((item for item in stages if item["name"] in worker_stages and
                 item["attempt"] in failed_mesh_attempts and item.get("status") == "succeeded"), None)


def _record_blocked_stages(execution, pipeline, failure):
    if pipeline["workflows"].get("model"):
        order = ["mesh_raw_acquisition", "mesh_preparation", "material_generation",
                 "mesh_output_acquisition", "material_map_acquisition",
                 "material_assembly_export", "final_publication"]
    else:
        order = ["material_generation", "material_map_acquisition",
                 "material_assembly_export", "final_publication"]
    failed = failure.get("stage")
    if failed in order:
        order = order[order.index(failed) + 1:]
    elif failed not in {"model_approval", "conditioning_preparation", "mesh_workflow_execution"}:
        return
    completed = {stage.get("name") for stage in execution.get("stages", [])
                 if isinstance(stage, dict) and stage.get("status") == "succeeded"}
    execution["blocked_stages"] = [
        {"name": name, "attempt": None, "outcome": "not_run",
         "caused_by": {"stage": failed, "stage_id": failure.get("stage_id"),
                       "attempt": failure.get("attempt"), "category": failure.get("category")},
         "reason": f"Not run because {failed} failed."}
        for name in order if name not in completed
    ]


def _mesh_slot_history(asset, execution_id, scope_sha256, budget):
    slots, slot_executions, rejected = {}, {}, set()
    stages_by_id = {}
    for execution in _execution_chain(asset, execution_id):
        for stage in execution["stages"]:
            sid = stage.get("id")
            if sid:
                if sid in stages_by_id:
                    raise ValueError(
                        "Stage ID is duplicated across execution chain; retry accounting ambiguity")
                stages_by_id[sid] = stage
            slot = stage.get("attempt_slot")
            if slot is None:
                if stage.get("name") == "mesh_workflow_execution" and stage.get("status") != "succeeded":
                    raise ValueError(
                        "Cannot resume: legacy mesh attempt has no retry-slot accounting; "
                        "start a fresh execution to avoid exceeding the candidate budget")
                continue
            if (not isinstance(slot, dict) or not _valid_sha256(slot.get("scope_sha256")) or
                    type(slot.get("seed_index")) is not int or slot["seed_index"] < 0 or
                    not isinstance(slot.get("origin_execution_id"), str) or
                    not slot["origin_execution_id"]):
                raise ValueError("Mesh attempt slot is malformed; resume accounting stopped")
            if slot["scope_sha256"] != scope_sha256:
                continue
            index = slot["seed_index"]
            if index >= budget:
                raise ValueError("Mesh attempt slot exceeds its configured budget")
            previous = slots.get(index)
            if previous and previous.get("id") != stage.get("id"):
                adopted = stage.get("adopted_from")
                resumed = (execution.get("parent_execution_id") == slot_executions[index]["id"] and
                           slot.get("origin_execution_id") == slot_executions[index]["id"])
                if not ((isinstance(adopted, dict) and adopted.get("stage_id") == previous.get("id") and
                         slot == previous.get("attempt_slot")) or resumed):
                    raise ValueError("Mesh attempt slot accounting is duplicated or ambiguous")
            slots[index] = stage
            slot_executions[index] = execution
    for execution in _execution_chain(asset, execution_id):
        decisions = execution.get("retry_decisions", [])
        if not isinstance(decisions, list) or not all(isinstance(item, dict) for item in decisions):
            raise ValueError("Retry decisions are malformed; resume accounting stopped")
        for decision in decisions:
            category = decision.get("category")
            action = decision.get("action")
            next_seed = decision.get("next_seed_index")
            if (decision.get("scope") != "mesh" or
                    not _valid_sha256(decision.get("scope_sha256")) or
                    decision.get("stage") != "mesh_workflow_execution" or
                    not isinstance(decision.get("stage_id"), str) or not decision["stage_id"] or
                    type(decision.get("attempt")) is not int or decision["attempt"] < 1 or
                    type(decision.get("used")) is not int or decision["used"] < 1 or
                    type(decision.get("limit")) is not int or decision["limit"] < 1 or
                    decision["used"] > decision["limit"] or
                    not isinstance(category, str) or
                    category not in {"configuration", "environment", "inference",
                                     "candidate_quality", "processing_validation",
                                     "interruption", "unknown"} or
                    not isinstance(action, str) or
                    action not in {"next_candidate", "stop", "exhausted"} or
                    (next_seed is not None and (type(next_seed) is not int or next_seed < 0))):
                raise ValueError("Retry decision is malformed; resume accounting stopped")
            if ((category == "candidate_quality" and action not in {"next_candidate", "exhausted"}) or
                    (category != "candidate_quality" and action != "stop") or
                    (action == "next_candidate" and
                     (next_seed is None or next_seed >= decision["limit"] or
                      decision["used"] >= decision["limit"])) or
                    (action != "next_candidate" and next_seed is not None) or
                    (action == "exhausted" and decision["used"] != decision["limit"])):
                raise ValueError("Retry decision action contradicts its accounting; resume accounting stopped")
            if decision["scope_sha256"] != scope_sha256:
                continue
            if decision["limit"] != budget:
                raise ValueError("Retry decision budget contradicts its mesh scope; resume accounting stopped")
            stage = stages_by_id.get(decision["stage_id"])
            if stage is None:
                raise ValueError("Retry decision refers to a missing stage; resume accounting stopped")
            if (stage.get("name") != decision["stage"] or
                    type(stage.get("attempt")) is not int or
                    stage.get("attempt") != decision["attempt"]):
                raise ValueError("Retry decision refers to a contradictory stage; resume accounting stopped")
            slot = stage.get("attempt_slot")
            if not isinstance(slot, dict) or slot.get("scope_sha256") != scope_sha256:
                raise ValueError("Retry decision does not match its mesh slot")
            if category == "candidate_quality":
                if (type(slot.get("seed_index")) is not int or
                        decision["used"] != slot["seed_index"] + 1 or
                        (action == "next_candidate" and next_seed != slot["seed_index"] + 1)):
                    raise ValueError("Retry decision does not match its mesh slot accounting")
                rejected.add(slot["seed_index"])
            elif type(slot.get("seed_index")) is not int or decision["used"] != slot["seed_index"] + 1:
                raise ValueError("Retry decision does not match its mesh slot accounting")
    return slots, rejected


def _stage_record_shape(stage):
    if (not isinstance(stage, dict) or
            not isinstance(stage.get("name"), str) or not stage["name"] or
            type(stage.get("attempt")) is not int or stage["attempt"] < 1 or
            not isinstance(stage.get("status"), str) or
            stage["status"] not in {"pending", "running", "succeeded", "failed"} or
            not isinstance(stage.get("settings"), dict) or
            not isinstance(stage.get("inputs"), list) or
            not isinstance(stage.get("outputs"), list)):
        return False
    for reference in stage["inputs"]:
        if (not isinstance(reference, dict) or
                not isinstance(reference.get("id"), str) or not reference["id"] or
                not _valid_sha256(reference.get("sha256"))):
            return False
    for reference in stage["outputs"]:
        parents = reference.get("derived_from") if isinstance(reference, dict) else None
        if (not isinstance(reference, dict) or
                any(not isinstance(reference.get(field), str) or not reference[field]
                    for field in ("id", "type", "path", "sha256", "stage")) or
                not _valid_sha256(reference["sha256"]) or
                type(reference.get("attempt")) is not int or
                reference["attempt"] < 1 or not isinstance(parents, list) or
                not all(isinstance(parent, dict) and isinstance(parent.get("artifact_id"), str)
                        and parent["artifact_id"] and _valid_sha256(parent.get("sha256"))
                        for parent in parents)):
            return False
    return True


def prop_child_reuse_decision(project_root, asset, child_stage, child, config):
    reasons = []
    candidate_records = asset.get("candidates")
    candidates = candidate_records.get("items") if isinstance(candidate_records, dict) else None
    executions = asset.get("executions")
    if not isinstance(candidates, list) or not all(isinstance(item, dict) for item in candidates):
        return {"reusable": False, "reasons": ["prop child candidate records are missing or malformed"]}
    if (not isinstance(executions, list) or not all(isinstance(item, dict) for item in executions) or
            any(not isinstance(item.get("id"), str) or not item["id"] or
                not isinstance(item.get("status"), str) or
                item["status"] not in {"running", "succeeded", "failed"} or
                not isinstance(item.get("identity_inputs"), dict) or
                not isinstance(item.get("stages"), list) for item in executions)):
        return {"reusable": False, "reasons": ["prop child execution records are missing or malformed"]}
    execution_ids = child_stage.get("candidate_execution_ids")
    if not isinstance(execution_ids, list) or not execution_ids:
        return {"reusable": False, "reasons": ["prop child candidate execution identity is unknown"]}
    selected_candidates = [item for item in candidates if item.get("execution_id") in execution_ids]
    if not selected_candidates or any(item.get("status") != "candidate" or not item.get("artifact")
                                       for item in selected_candidates):
        return {"reusable": False, "reasons": ["prop child candidate set is incomplete"]}
    exec_matches = [e for e in executions
                    if isinstance(e, dict) and e.get("id") == execution_ids[0]]
    if len(exec_matches) > 1:
        return {"reusable": False, "reasons": ["candidate execution identity is ambiguous"]}
    if not exec_matches:
        return {"reusable": False, "reasons": ["candidate execution is missing"]}
    execution = exec_matches[0]
    candidate = selected_candidates[0]
    identity = (execution or {}).get("identity_inputs")
    if not isinstance(identity, dict):
        reasons.append("prop child execution identity is missing or malformed")
        identity = {}
    attempts = identity.get("candidate_attempts") if isinstance(identity, dict) else None
    if not isinstance(attempts, list) or not all(isinstance(item, dict) for item in attempts):
        reasons.append("prop child candidate attempt identities are missing or malformed")
        attempts = []
    if len(execution_ids) != 1 or len(selected_candidates) != len(attempts):
        reasons.append("prop child candidate set changed or is incomplete")
    if not execution or execution.get("status") != "succeeded":
        reasons.append("candidate execution is missing or incomplete")
    expected_description = child.get("description", asset.get("description"))
    expected_prompt = child.get("requested_generation_prompt", child.get("generation_prompt"))
    if not isinstance(expected_prompt, str) or not expected_prompt:
        reasons.append("prop child requested prompt is unknown")
    if identity.get("brief") != expected_description:
        reasons.append("prop child brief changed")
    if identity.get("generation_prompt") != expected_prompt:
        reasons.append("prop child prompt changed")
    if (not identity.get("style") or not child.get("requested_style_identity") or
            identity.get("style") != child.get("requested_style_identity")):
        reasons.append("prop child style identity changed or is unknown")
    if (not identity.get("conditioning") or not child.get("requested_conditioning") or
            identity.get("conditioning") != child.get("requested_conditioning")):
        reasons.append("prop child conditioning or references changed or are unknown")
    expected_count = child.get("count", config.get("asset_pipeline", {}).get("defaults", {}).get("image_candidates"))
    variations = child.get("variations", [None] * expected_count) if expected_count is not None else None
    if (not isinstance(attempts, list) or expected_count is None or len(attempts) != expected_count or
            len(attempts) != len(selected_candidates) or
            [item.get("variation") for item in attempts] != variations):
        reasons.append("prop child candidate count or variations changed")
    pipeline = config.get("asset_pipeline", {})
    workflow = child.get("requested_image_workflow", pipeline.get("workflows", {}).get("image"))
    if workflow:
        workflow_path = resolve_workflow(project_root, workflow)
        expected_workflow = {"identifier": Path(workflow).name,
                             "sha256": file_sha256(workflow_path) if workflow_path.is_file() else None,
                             "configured_inputs": workflow_node_inputs(config, "image", Path(workflow).name)}
        if identity.get("workflow") != expected_workflow:
            reasons.append("prop child workflow identity changed or is unknown")
    if "quality" not in identity:
        reasons.append("prop child quality identity is unknown")
    else:
        expected_quality = {"tier": pipeline.get("selected_quality_tier", "normal"),
                            "settings": pipeline.get("quality_settings", {})}
        if identity["quality"] != expected_quality:
            reasons.append("prop child quality settings changed")
    for index, candidate in enumerate(selected_candidates):
        artifact = candidate.get("artifact")
        if candidate.get("execution_id") != (execution or {}).get("id") or not isinstance(artifact, dict):
            reasons.append("candidate provenance is unknown or belongs to another execution")
            continue
        attempt = artifact.get("attempt")
        if (not isinstance(artifact.get("id"), str) or not artifact["id"] or
                not isinstance(artifact.get("type"), str) or not artifact["type"] or
                isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1 or
                not isinstance(artifact.get("path"), str) or candidate.get("path") != artifact.get("path") or
                not isinstance(artifact.get("sha256"), str) or not artifact["sha256"]):
            reasons.append("candidate artifact identity is incomplete or inconsistent")
            continue
        intact, reason = artifact_integrity(project_root, artifact)
        if not intact:
            reasons.append(reason)
        execution_stages = (execution or {}).get("stages", [])
        if not isinstance(execution_stages, list):
            reasons.append("candidate execution stages are missing or malformed")
            continue
        if not all(_stage_record_shape(stage) for stage in execution_stages):
            reasons.append("candidate execution stages are missing or malformed")
            continue
        target_stages = [item for item in execution_stages
                         if item.get("name") == artifact.get("stage")]
        if any(type(item.get("attempt")) is not int or item["attempt"] < 1
               for item in target_stages):
            reasons.append("candidate stage identity is malformed")
            continue
        matches = [item for item in target_stages if item.get("attempt") == attempt]
        if len(matches) != 1:
            reasons.append("candidate stage is missing or ambiguous")
            continue
        stage = matches[0]
        attempt_identity = attempts[index] if index < len(attempts) else {}
        settings = stage.get("settings")
        if not isinstance(settings, dict):
            reasons.append("candidate stage settings are missing or malformed")
            continue
        variation = attempt_identity.get("variation")
        if variation is not None and not isinstance(variation, dict):
            reasons.append("candidate variation identity is malformed")
            continue
        expected_stage_prompt = expected_prompt
        if variation and isinstance(expected_prompt, str):
            expected_stage_prompt += "\nDESIGN VARIATION:\n" + "\n".join(
                f"- {key}: {value}" for key, value in variation.items())
        if (type(attempt_identity.get("seed")) is not int or
                attempt_identity.get("seed") != settings.get("seed") or
                variation != settings.get("variation") or
                settings.get("prompt") != expected_stage_prompt):
            reasons.append("candidate stage settings differ from execution identity or current request")
        stage_outputs = stage.get("outputs")
        if not isinstance(stage_outputs, list):
            reasons.append("candidate stage outputs are missing or malformed")
            continue
        if not all(isinstance(o, dict) for o in stage_outputs):
            reasons.append("candidate stage outputs are missing or malformed")
            continue
        output_matches = [out for out in stage_outputs
                          if out.get("id") == artifact["id"]]
        if len(output_matches) != 1:
            reasons.append("candidate artifact is missing or ambiguous in recorded stage outputs")
            continue
        output = output_matches[0]
        identity_fields = ("id", "type", "stage", "attempt", "path", "sha256")
        if any(output.get(field) != artifact.get(field) for field in identity_fields):
            reasons.append("candidate artifact identity differs from recorded stage output")
            continue
        decision = stage_reuse_decision(project_root, stage, inputs=[], settings=stage.get("settings", {}))
        if not decision["reusable"]:
            reasons.extend(decision["reasons"])
    return {"reusable": not reasons, "reasons": reasons}


def processed_mesh_reuse_decision(project_root, asset, source_mesh, processing_settings):
    executions = asset.get("executions", [])
    malformed = {"reusable": False,
                 "reasons": ["malformed processed-mesh provenance: authoritative records are malformed"]}
    if not isinstance(executions, list) or not all(isinstance(item, dict) for item in executions):
        return malformed
    stage_lists = [execution.get("stages") for execution in executions]
    if not all(isinstance(stages, list) for stages in stage_lists):
        return malformed
    stages = [stage for records in stage_lists for stage in records]
    if not all(isinstance(stage, dict) for stage in stages):
        return malformed
    artifact_lists = [(stage, field, stage.get(field)) for stage in stages
                      for field in ("inputs", "outputs")]
    if not all(isinstance(records, list) for _, _, records in artifact_lists):
        return malformed
    artifacts = [(field, item) for _, field, records in artifact_lists for item in records]
    if not all(isinstance(item, dict) for _, item in artifacts):
        return malformed
    parent_lists = [(item, item.get("derived_from", [])) for _, item in artifacts]
    if not all(isinstance(parents, list) for _, parents in parent_lists):
        return malformed
    parents = [parent for _, records in parent_lists for parent in records]
    if not all(isinstance(parent, dict) for parent in parents):
        return malformed
    if (any("id" not in execution for execution in executions)
            or any("name" not in stage or "attempt" not in stage for stage in stages)
            or any("id" not in item or "sha256" not in item for _, item in artifacts)
            or any(field == "outputs" and any(key not in item for key in
                                                  ("type", "path", "stage", "attempt"))
                   for field, item in artifacts)
            or any("artifact_id" not in parent or "sha256" not in parent for parent in parents)):
        return malformed
    if (any(not isinstance(execution["id"], str) or not execution["id"] for execution in executions)
            or any(not isinstance(stage["name"], str) or type(stage["attempt"]) is not int
                   or stage["attempt"] < 1 for stage in stages)
            or any(not isinstance(item["id"], str) or not item["id"] or not _valid_sha256(item["sha256"])
                   for _, item in artifacts)
            or any(field == "outputs" and (
                       not isinstance(item["type"], str) or not item["type"]
                       or not isinstance(item["path"], str) or not item["path"]
                       or not isinstance(item["stage"], str)
                       or type(item["attempt"]) is not int or item["attempt"] < 1)
                   for field, item in artifacts)
            or any(not isinstance(parent["artifact_id"], str) or not parent["artifact_id"]
                   or not _valid_sha256(parent["sha256"])
                   for parent in parents)):
        return malformed
    execution_ids = [execution["id"] for execution in executions]
    if len(set(execution_ids)) != len(execution_ids):
        return {"reusable": False,
                "reasons": ["ambiguous processed-mesh provenance: duplicate execution identity"]}
    # Step 1: Collect ALL stages with matching name and attempt across executions
    # to verify unique and unambiguous provenance.
    target_names = {"mesh_preparation", "material_assembly_export"}
    by_name_attempt = {}
    for execution in executions:
        exec_stages = execution.get("stages", [])
        for stage in exec_stages:
            if stage.get("name") not in target_names:
                continue
            key = (stage.get("name"), stage.get("attempt"))
            by_name_attempt.setdefault(key, []).append(stage)

    # Require exactly one matching stage per (name, attempt) to avoid ambiguous provenance.
    ambiguous_keys = [key for key, stages in by_name_attempt.items() if len(stages) > 1]
    if ambiguous_keys:
        return {"reusable": False,
                "reasons": ["ambiguous processed-mesh provenance: duplicate stage identity "
                             + ", ".join(f"{s[0]}:{s[1]}" for s in ambiguous_keys)]}

    for execution in executions:
        for stage in execution.get("stages", []):
            if stage.get("name") not in target_names:
                continue
            output_ids = [item["id"] for item in stage.get("outputs", []) if "id" in item]
            if any(output_ids[i] == output_ids[j]
                   for i in range(len(output_ids)) for j in range(i + 1, len(output_ids))):
                return {"reusable": False,
                        "reasons": ["ambiguous processed-mesh provenance: duplicate output identity"]}

    source_record = asset.get("source", {})
    if not isinstance(source_record, dict):
        return malformed
    if (not isinstance(source_mesh, dict) or not isinstance(source_mesh.get("id"), str)
            or not source_mesh["id"] or not _valid_sha256(source_mesh.get("sha256"))):
        return {"reusable": False, "reasons": ["source mesh identity is malformed"]}
    processed_path = source_record.get("processed_mesh")
    if not isinstance(processed_path, str) or not processed_path:
        return {"reusable": False, "reasons": ["processed mesh path is unknown"]}

    # Step 2: Find the unique matching stage that is succeeded.
    for execution in reversed(executions):
        exec_stages = execution.get("stages", [])
        for stage in exec_stages:
            if stage.get("name") not in target_names:
                continue
            if stage.get("status") != "succeeded" or stage.get("settings") != processing_settings:
                continue
            stage_inputs = stage.get("inputs", [])
            source_identity = (source_mesh.get("id"), source_mesh.get("sha256"))
            if not any((item.get("id"), item.get("sha256")) == source_identity or
                       any((parent.get("artifact_id"), parent.get("sha256")) == source_identity
                           for parent in item.get("derived_from", []) if isinstance(parent, dict))
                       for item in stage_inputs if isinstance(item, dict)):
                continue
            source_ok, source_reason = artifact_integrity(project_root, source_mesh)
            if not source_ok:
                return {"reusable": False, "reasons": [f"source mesh {source_reason}"]}
            stage_outs = stage.get("outputs", [])
            expected_type = "mesh.prepared" if stage.get("name") == "mesh_preparation" else "mesh.processed"
            prepared_matches = [item for item in stage_outs
                                if item.get("type") == expected_type and item.get("path") == processed_path]
            if len(prepared_matches) > 1:
                return {"reusable": False,
                        "reasons": ["ambiguous processed-mesh output: multiple artifacts match the required path"]}
            if not prepared_matches:
                continue
            prepared = prepared_matches[0]
            output_matches = [o for o in stage_outs if o.get("id") == prepared.get("id")]
            if len(output_matches) != 1:
                return {"reusable": False,
                        "reasons": ["ambiguous processed-mesh output: duplicate artifact ID "
                                     f"{prepared.get('id')!r} found in {len(output_matches)} outputs"]}
            # Validate that the output's recorded attempt matches the containing stage.
            if (type(prepared.get("attempt")) is not int or
                    prepared.get("attempt") != stage.get("attempt")):
                return {"reusable": False,
                        "reasons": [f"output attempt {prepared.get('attempt')} does not match "
                                     f"stage attempt {stage.get('attempt')} at {processed_path}"]}
            # Validate that the output's recorded stage matches the containing stage name.
            # An output claiming a different stage is not reliably attributable to this stage.
            if (not isinstance(prepared.get("stage"), str) or
                    prepared.get("stage") != stage.get("name")):
                return {"reusable": False,
                        "reasons": [f"output stage {prepared.get('stage')!r} does not match "
                                     f"containing stage {stage.get('name')!r}"]}
            derived = prepared.get("derived_from", [])
            input_identities = {(item.get("id"), item.get("sha256")) for item in stage_inputs}
            derived_identities = {(item.get("artifact_id"), item.get("sha256")) for item in derived}
            if (not input_identities or len(input_identities) != len(stage_inputs) or
                    any(not isinstance(item_id, str) or not item_id or
                        not isinstance(digest, str) or not digest
                        for item_id, digest in input_identities) or
                    len(derived_identities) != len(derived) or
                    derived_identities != input_identities):
                return {"reusable": False,
                        "reasons": ["processed-mesh lineage does not exactly match recorded stage inputs"]}
            intact, reason = artifact_integrity(project_root, prepared)
            if intact:
                return {"reusable": True, "reasons": []}
            return {"reusable": False, "reasons": [reason]}
    return {"reusable": False, "reasons": ["no matching processed mesh lineage and settings"]}


def _adopt_stage(context, name, attempt, inputs, settings):
    prior = (context or {}).get("reuse_execution")
    if not prior:
        return None
    # Collect ALL matching stages first, require exactly one
    stages = prior.get("stages", [])
    if not isinstance(stages, list) or not all(_stage_record_shape(stage) for stage in stages):
        return None
    targets = [stage for stage in stages if stage.get("name") == name]
    if any(isinstance(stage.get("attempt"), bool) or
           not isinstance(stage.get("attempt"), int) or stage["attempt"] < 1
           for stage in targets):
        return None
    matching = [stage for stage in targets if stage.get("attempt") == attempt]
    if len(matching) != 1:
        return None  # 0 or >1 matches → ambiguous or missing
    old = matching[0]
    decision = (stage_reuse_decision(context["root"], old, inputs=inputs, settings=settings)
                if old else {"reusable": False, "reasons": [f"missing {name} stage"]})
    if name == "mesh_workflow_execution" and decision["reusable"]:
        worker_stages = [stage for stage in prior.get("stages", [])
                         if stage.get("attempt") == attempt and stage.get("name") in {
                             "mesh_raw_acquisition", "mesh_preparation", "material_generation",
                             "mesh_output_acquisition"}]
        for worker_stage in worker_stages:
            outputs = [item for item in worker_stage.get("outputs", [])
                       if worker_stage.get("name") != "material_generation" or
                       item.get("type", "").startswith("texture.")]
            if not outputs:
                continue
            if worker_stage.get("status") != "succeeded":
                decision["reusable"] = False
                decision["reasons"].append(f"worker stage {worker_stage.get('name')} is incomplete")
                continue
            worker_decision = stage_reuse_decision(
                context["root"], worker_stage, inputs=worker_stage.get("inputs", []),
                settings=worker_stage.get("settings", {}))
            if not worker_decision["reusable"]:
                decision["reusable"] = False
                decision["reasons"].extend(worker_decision["reasons"])
            for output in outputs:
                intact, reason = artifact_integrity(context["root"], output)
                if not intact:
                    decision["reusable"] = False
                    decision["reasons"].append(reason)
    executions = context["manifest"]["assets"][context["key"]].get("executions")
    if not isinstance(executions, list) or not all(isinstance(item, dict) for item in executions):
        return None
    current = [item for item in executions if item.get("id") == context["execution_id"]]
    if len(current) != 1:
        return None
    execution = current[0]
    record = record_reuse_decision(execution, name, old["attempt"] if old else None,
                                   execution_identity({"inputs": inputs, "settings": settings}), decision)
    record["source_execution_id"] = prior["id"]
    if not decision["reusable"]:
        _persist_reload(context["root"], context["pipeline"], context["manifest"])
        return None
    stage = start_stage(execution, name, attempt, inputs, settings, copy.deepcopy(old.get("provenance", {})))
    if old.get("attempt_slot"):
        stage["attempt_slot"] = copy.deepcopy(old["attempt_slot"])
    stage["adopted_from"] = {"execution_id": prior["id"], "stage_id": old.get("id")}
    begin_stage(stage)
    finish_stage(stage, "succeeded", copy.deepcopy(old["outputs"]))
    _persist_reload(context["root"], context["pipeline"], context["manifest"])
    return stage["outputs"]


def _lineage_start(context, name, attempt, inputs, settings, *, parents=None):
    if not context:
        return None
    asset = context["manifest"]["assets"][context["key"]]
    execution = next(item for item in asset["executions"] if item["id"] == context["execution_id"])
    stage = start_stage(execution, name, attempt, list(inputs if parents is None else parents), settings, {})
    save_manifest(Path(context["root"]) / context["pipeline"]["manifest"], context["manifest"])
    begin_stage(stage)
    _persist_reload(context["root"], context["pipeline"], context["manifest"])
    asset = context["manifest"]["assets"][context["key"]]
    context.setdefault("_stage_handles", {})[(name, attempt)] = stage["id"]
    return _execution_stage(asset, context["execution_id"], name, attempt,
                            stage_id=stage["id"])[1]


def _lineage_finish(context, name, attempt, outputs, *, error=None, failure=None, stage_id=None):
    if not context:
        return []
    asset = context["manifest"]["assets"][context["key"]]
    handles = context.get("_stage_handles", {})
    stage_id = stage_id or handles.get((name, attempt))
    execution, stage = _execution_stage(asset, context["execution_id"], name, attempt,
                                        stage_id=stage_id)
    refs = []
    root = context["root"]
    parents = stage.get("inputs", [])
    for index, (path, kind) in enumerate(outputs):
        path = Path(path)
        if path.is_file():
            refs.append(_artifact_ref(root, path, f"{execution['id']}:{name}:{attempt}:{index}",
                                      kind, name, attempt, parents))
    failure = failure or (failure_record(
        error, stage=name, stage_id=stage["id"], attempt=attempt,
        operation=error.operation if isinstance(error, StageFailure) else name)
        if error is not None else None)
    if failure is not None and failure.get("stage_id") is None:
        failure = {**failure, "stage_id": stage["id"]}
    finish_stage(stage, "failed" if error is not None else "succeeded", refs,
                 error=(str(error) or type(error).__name__) if error is not None else None,
                 failure=failure)
    handles.pop((name, attempt), None)
    _persist_reload(context["root"], context["pipeline"], context["manifest"])
    return refs


def _validation_failure(validation, *, stage, attempt):
    if not isinstance(validation, dict) or validation.get("status") != "failed":
        return None
    retryable = candidate_quality_rejection(validation)
    if retryable:
        remedy = "generate another mesh candidate within the configured budget"
    elif validation.get("failure_codes") == ["module_stretch"]:
        remedy = "approve a concept closer to the module's proportions"  # the stretch comes from the concept
    else:
        remedy = "inspect the validation report and correct the deterministic failure"
    failure = StageFailure(
        "candidate_quality" if retryable else "processing_validation",
        "Candidate failed validation" + (f" ({', '.join(validation['failure_codes'])})"
                                         if validation.get("failure_codes") else ""),
        operation="validate_model_outputs",
        remedy=remedy,
        stage=stage,
        evidence={"validation": validation},
    )
    return failure_record(failure, stage=stage, attempt=attempt,
                          operation="validate_model_outputs")


def _candidate_failure(candidate, *, attempt):
    failure = candidate.get("failure") if isinstance(candidate, dict) else None
    if isinstance(failure, dict):
        return failure
    validation = candidate.get("validation") if isinstance(candidate, dict) else None
    failure = _validation_failure(validation, stage="material_assembly_export", attempt=attempt)
    if failure is not None:
        return failure
    message = candidate.get("error") if isinstance(candidate, dict) else None
    return failure_record(RuntimeError(message or "Candidate failed without a validation report"),
                          stage="material_assembly_export", attempt=attempt,
                          operation="candidate_validation")


def _recorded_rights(metadata_paths):
    """The rights each ComfyUI run's worker recorded in its metadata; a run that recorded none is unknown."""
    entries = []
    for path in metadata_paths:
        info = json.loads(path.read_text()) if path.is_file() else {}
        recorded = info.get("output_rights")
        for entry in recorded if isinstance(recorded, list) else [
                {"source": path.name, "status": "unknown", "reason": "its worker recorded no output rights"}]:
            if entry not in entries:
                entries.append(entry)
    return entries


def _lineage_provenance(context, name, attempt, facts):
    if not context:
        return
    asset = context["manifest"]["assets"][context["key"]]
    stage_id = context.get("_stage_handles", {}).get((name, attempt))
    _, stage = _execution_stage(asset, context["execution_id"], name, attempt,
                                stage_id=stage_id)
    stage["provenance"].update(facts)


_MATERIAL_ARTIFACT_TYPES = {
    "surface": "surface.swatch", "fbx": "mesh.fbx", "blend": "project.blend",
    "basecolor": "texture.basecolor", "normal": "texture.normal", "roughness": "texture.roughness",
    "metallic": "texture.metallic", "metallic_gloss": "texture.metallic_gloss",
    "emission": "texture.emission", "preview_front": "preview.front", "preview_side": "preview.side",
    "preview_rear": "preview.rear", "preview_three_quarter": "preview.three_quarter",
    "validation": "validation.json",
}


def _material_artifact_refs(root, paths, execution_id, attempt, upstream):
    refs = []
    for key, kind in _MATERIAL_ARTIFACT_TYPES.items():
        path = paths[key]
        if path.is_file():
            refs.append(_artifact_ref(root, path, f"{execution_id}:material:{attempt}:{key}", kind,
                                      "material_assembly_export", attempt, upstream))
    return refs


def model_paths(project_root, config, name, asset_type="prop"):
    directory = output_path(project_root, config, asset_type, name)
    source, materials, previews = directory / "Source", directory / "Materials", directory / "Previews"
    return {"directory": directory, "concept": source / "concept.png", "cutout": source / "concept_cutout.png",
            "input_3d": source / "concept_3d_input.png", "glb": source / f"{name}.glb",
            "surface": materials / f"{name}_surface_source.png",
            "fbx": directory / f"{name}.fbx", "blend": directory / f"{name}_preview.blend",
            "basecolor": materials / f"{name}_basecolor.png", "normal": materials / f"{name}_normal.png",
            "roughness": materials / f"{name}_roughness.png", "metallic": materials / f"{name}_metallic.png",
            "metallic_gloss": materials / f"{name}_metallic_gloss.png",
            "unity_material": materials / f"{name}_preview_PBR.mat",
            "unity_glass_material": glass_material_path(materials / f"{name}_preview_PBR.mat"),
            "emission": materials / f"{name}_emission.png", "preview_front": previews / f"{name}_front.png",
            "preview_side": previews / f"{name}_side.png", "preview_rear": previews / f"{name}_rear.png",
            "preview_three_quarter": previews / f"{name}_three_quarter.png",
            "processed_mesh": source / "processed_mesh.blend",
            "validation": directory / "validation.json"}


def material_candidate_paths(project_root, config, name, number, asset_type="prop"):
    asset_type_name = asset_type if isinstance(asset_type, str) else asset_type.get("name", "prop")
    directory = Path(project_root) / config["asset_pipeline"]["candidate_root"] / asset_type_name / name / f"material_{number:02d}"
    materials, previews = directory / "Materials", directory / "Previews"
    return {"directory": directory, "surface": directory / "surface_source.png",
            "fbx": directory / f"{name}.fbx", "blend": directory / f"{name}_preview.blend",
            "basecolor": materials / f"{name}_basecolor.png", "normal": materials / f"{name}_normal.png",
            "roughness": materials / f"{name}_roughness.png", "metallic": materials / f"{name}_metallic.png",
            "metallic_gloss": materials / f"{name}_metallic_gloss.png",
            "emission": materials / f"{name}_emission.png", "preview_front": previews / f"{name}_front.png",
            "preview_side": previews / f"{name}_side.png", "preview_rear": previews / f"{name}_rear.png",
            "preview_three_quarter": previews / f"{name}_three_quarter.png",
            "validation": directory / "validation.json", "generator": directory / "generation.json"}


def _relative_outputs(root, paths, keys):
    return {key: paths[key].relative_to(root).as_posix() for key in keys}


def _generate_material_candidate(root, config, asset_type, asset, number, prompt, stage_mesh, lineage=None, seed=None):
    paths = material_candidate_paths(root, config, asset["name"], number, asset_type)
    paths["directory"].mkdir(parents=True, exist_ok=True)
    paths["basecolor"].parent.mkdir(parents=True, exist_ok=True)
    candidate = {"number": number, "prompt": prompt, "status": "failed", "kind": "surface_swatch",
                 "seed": seed if seed is not None else secrets.randbits(32), "path": paths["surface"].relative_to(root).as_posix(),
                 "validation": {"status": "not_run", "errors": [], "warnings": [], "measured": {}}}
    pipeline = config["asset_pipeline"]
    material_started = map_started = assembly_started = False
    candidate["artifacts"] = []
    previous = (lineage or {}).get("prior_candidate")
    previous_attempts = previous.get("stage_attempts", {}) if previous else {}
    candidate["stage_attempts"] = {}
    try:
        workflow = pipeline["workflows"].get("image")
        if not workflow:
            raise ValueError("Configure asset_pipeline.workflows.image in ai/project.yaml")
        metadata_path = paths["generator"]
        material_inputs = (lineage or {}).get("material_inputs", (lineage or {}).get("upstream", []))
        material_settings = {"prompt": prompt, "seed": candidate["seed"],
                             "workflow_sha256": file_sha256(resolve_workflow(root, workflow)),
                             "configured_inputs": workflow_node_inputs(config, "image", Path(workflow).name)}
        material_attempt = previous_attempts.get("material_generation", previous["number"]) if previous else number
        material_refs = _adopt_stage(lineage, "material_generation", material_attempt,
                                     material_inputs, material_settings)
        if material_refs is not None:
            candidate["stage_attempts"]["material_generation"] = material_attempt
            metadata_ref = next((item for item in material_refs if item["type"] == "generation.metadata"), None)
            info = json.loads((root / metadata_ref["path"]).read_text()) if metadata_ref else {}
            candidate["generator"] = copy.deepcopy((previous or {}).get("generator") or
                                                     generator_provenance(info.get("workflow"), info))
            candidate["artifacts"].extend(material_refs)
            surface_ref = next(item for item in material_refs if item["type"] == "surface.swatch")
            paths["surface"] = root / surface_ref["path"]
            candidate["path"] = surface_ref["path"]
        else:
            _lineage_start(lineage, "material_generation", number, (), material_settings,
                           parents=material_inputs)
            material_started = bool(lineage)
            generate_image(root, config, resolve_workflow(root, workflow), prompt, paths["surface"],
                           f"slopforge/prop/{asset['name']}/material_{candidate['seed']}",
                           candidate["seed"], metadata_path)
            material_check = validate_image(paths["surface"], expected_format="PNG",
                                            report_path=paths["surface"].relative_to(root))
            if material_check["status"] == "failed":
                raise ValueError("Surface material validation failed: " + "; ".join(material_check["errors"]))
            info = json.loads(metadata_path.read_text()) if metadata_path.is_file() else {}
            candidate["generator"] = generator_provenance(info.get("workflow"), info)
        if material_started:
            missing = lambda fact: {"status": "not_recorded", "reason": f"Image worker did not record {fact}"}
            _lineage_provenance(lineage, "material_generation", number, {
                "workflow": {"status": "known", "value": info.get("workflow") or workflow},
                "workflow_source_sha256": ({"status": "known", "value": info["workflow_source_sha256"]}
                    if info.get("workflow_source_sha256") else missing("source workflow hash")),
                "workflow_effective_sha256": ({"status": "known", "value": info["workflow_effective_sha256"]}
                    if info.get("workflow_effective_sha256") else missing("effective workflow hash")),
                "effective_bindings": ({"status": "known", "value": info["effective_bindings"]}
                    if "effective_bindings" in info else missing("effective bindings")),
                "backend": ({"status": "known", "value": info["backend"]}
                    if "backend" in info else missing("backend identity")),
                "model": ({"status": "known", "value": info["model"]}
                    if "model" in info else missing("model identity")),
                **({"output_rights": info["output_rights"]} if isinstance(info.get("output_rights"), list) else {}),
            })
            material_refs = _lineage_finish(lineage, "material_generation", number,
                [(paths["surface"], "surface.swatch"), (metadata_path, "generation.metadata")])
            candidate["artifacts"].extend(material_refs)
            material_started = False
            candidate["stage_attempts"]["material_generation"] = number

        python = python_executable(root, config)
        surface_ref = [item for item in material_refs if item["type"] == "surface.swatch"]
        map_settings = {"map_prompt": prompt,
                        "tool_sha256": tool_sha256(tool_root() / "processing/make_pbr_maps.py")}
        map_attempt = previous_attempts.get("material_map_acquisition", previous["number"]) if previous else number
        map_keys = ("basecolor", "normal", "roughness", "metallic", "metallic_gloss", "emission")
        # The swatch bake overwrites the maps it is given, so the map stage's tiles live apart from them.
        tiles = {key: paths["directory"] / "Tiles" / paths[key].name for key in map_keys}
        map_refs = _adopt_stage(lineage, "material_map_acquisition", map_attempt, surface_ref, map_settings)
        if map_refs is not None:
            candidate["stage_attempts"]["material_map_acquisition"] = map_attempt
            candidate["artifacts"].extend(map_refs)
            for key in map_keys:
                reference = next((item for item in map_refs if item["type"] == _MATERIAL_ARTIFACT_TYPES[key]), None)
                if reference:
                    tiles[key] = root / reference["path"]
        else:
            _lineage_start(lineage, "material_map_acquisition", number, (), map_settings, parents=surface_ref)
            _lineage_provenance(lineage, "material_map_acquisition", number, {"output_rights": []})
            map_started = bool(lineage)
            tiles["basecolor"].parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([python, str(tool_root() / "processing/make_pbr_maps.py"), "--basecolor", str(paths["surface"]),
                            "--prompt", prompt,
                            "--normal", str(tiles["normal"]), "--roughness", str(tiles["roughness"]),
                            "--metallic", str(tiles["metallic"]), "--emission", str(tiles["emission"])], check=True)
            shutil.copy2(paths["surface"], tiles["basecolor"])
            make_metallic_gloss(tiles["metallic"], tiles["roughness"], tiles["metallic_gloss"])
        if map_started:
            map_refs = _lineage_finish(lineage, "material_map_acquisition", number,
                [(tiles[key], _MATERIAL_ARTIFACT_TYPES[key]) for key in map_keys])
            candidate["artifacts"].extend(map_refs)
            map_started = False
            candidate["stage_attempts"]["material_map_acquisition"] = number
        face_budget = _face_budget(pipeline, asset_type, asset)
        textures = [paths[key] for key in ("basecolor", "normal", "roughness", "metallic", "emission")]
        assembly_inputs = [*map_refs, *(lineage or {}).get("assembly_inputs", [])]
        assembly_settings = {"material_scale": float(pipeline.get("material_scale", 3.0)),
                             "face_budget": face_budget,
                             "processing_tool_sha256": tool_sha256(tool_root() / "blender/prepare_model.py"),
                             **_placement(asset)}
        assembly_attempt = previous_attempts.get("material_assembly_export", previous["number"]) if previous else number
        assembly_refs = _adopt_stage(lineage, "material_assembly_export", assembly_attempt,
                                     assembly_inputs, assembly_settings)
        if assembly_refs is not None:
            candidate["artifacts"].extend(assembly_refs)
            candidate["stage_attempts"]["material_assembly_export"] = assembly_attempt
            candidate["outputs"] = copy.deepcopy((previous or {}).get("outputs", {}))
            for key, artifact_type in _MATERIAL_ARTIFACT_TYPES.items():
                reference = next((item for item in [*assembly_refs, *map_refs, *material_refs]
                                  if item["type"] == artifact_type), None)
                if reference:
                    candidate["outputs"][key] = reference["path"]
            validation_ref = next((item for item in assembly_refs if item["type"] == "validation.json"), None)
            if validation_ref:
                candidate["validation"] = json.loads((root / validation_ref["path"]).read_text())
            else:
                candidate["validation"] = copy.deepcopy((previous or {}).get("validation", {}))
            candidate["status"] = "candidate" if candidate["validation"].get("status") != "failed" else "failed"
            return candidate
        mesh_path = root / asset["source"]["processed_mesh"]
        _lineage_start(lineage, "material_assembly_export", number, (),
                       assembly_settings, parents=assembly_inputs)
        _lineage_provenance(lineage, "material_assembly_export", number, {"output_rights": rights_of(config, "blender")})
        assembly_started = bool(lineage)
        for key in map_keys:
            if key != "metallic_gloss" and tiles[key].is_file() and tiles[key].resolve() != paths[key].resolve():
                shutil.copy2(tiles[key], paths[key])
        process_model(root, config, root / asset["source"]["glb"], paths["fbx"], paths["blend"], textures,
                      _reduction_budget(face_budget, asset, asset_type), surface_source=paths["surface"],
                      preview_dir=paths["preview_front"].parent,
                      material_scale=float(pipeline.get("material_scale", 3.0)),
                      stage_mesh=mesh_path,
                      reuse_stage_mesh=bool((lineage or {}).get("processed_mesh_reusable")),
                      target_size=asset.get("target_size"), pivot=asset.get("pivot"),
                      arm_thickness=asset.get("arm_thickness"))
        make_metallic_gloss(paths["metallic"], paths["roughness"], paths["metallic_gloss"])
        inspection = inspect_model(root, config, paths["blend"], paths["validation"], face_budget,
                                   real_scale=bool(asset.get("target_size")))
        check_paths = {key: paths[key] for key in
                        ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss", "emission",
                        "preview_front", "preview_side", "preview_rear", "preview_three_quarter")}
        candidate["validation"] = validate_model_outputs(check_paths, inspection, face_budget, root,
            max_components=asset_type.get("max_components"),
            max_nonmanifold_edges=asset_type.get("max_nonmanifold_edges"),
            max_boundary_edges=asset_type.get("max_boundary_edges"), min_uv_area=asset_type.get("min_uv_area"))
        paths["validation"].write_text(json.dumps(candidate["validation"], indent=2) + "\n")
        candidate["status"] = "candidate" if candidate["validation"]["status"] != "failed" else "failed"
        candidate["failure"] = _validation_failure(candidate["validation"],
                                                    stage="material_assembly_export", attempt=number)
        candidate["outputs"] = _relative_outputs(root, paths, check_paths)
        candidate["generator"].update({"workflow": info.get("workflow") or candidate["generator"].get("workflow") or workflow,
                                        "seed": candidate["seed"]})
        if assembly_started:
            assembly_outputs = [(paths[key], _MATERIAL_ARTIFACT_TYPES[key]) for key in
                                ("fbx", "blend", "preview_front", "preview_side", "preview_rear",
                                 "preview_three_quarter", "validation", *map_keys)]
            if mesh_path.is_file():
                assembly_outputs.append((mesh_path, "mesh.processed"))
            candidate["artifacts"].extend(_lineage_finish(lineage, "material_assembly_export", number,
                assembly_outputs,
                error=candidate["failure"]["message"] if candidate["failure"] else None,
                failure=candidate["failure"]))
            assembly_started = False
            candidate["stage_attempts"]["material_assembly_export"] = number
    except (Exception, KeyboardInterrupt) as exc:
        failure_stage = ("material_assembly_export" if assembly_started else
                         "material_map_acquisition" if map_started else "material_generation")
        candidate["failure"] = failure_record(
            exc, stage=failure_stage, attempt=number,
            operation=exc.operation if isinstance(exc, StageFailure) else failure_stage)
        if material_started:
            _lineage_finish(lineage, "material_generation", number, [], error=exc,
                            failure=candidate["failure"])
        if map_started:
            _lineage_finish(lineage, "material_map_acquisition", number, [], error=exc,
                            failure=candidate["failure"])
        if assembly_started:
            _lineage_finish(lineage, "material_assembly_export", number, [], error=exc,
                            failure=candidate["failure"])
        candidate["error"] = str(exc)
        candidate["validation"]["errors"].append(str(exc))
        if isinstance(exc, KeyboardInterrupt):
            raise
    return candidate


def _native_material_candidate(root, config, context, asset_type, asset, number, mesh_info, lineage=None):
    paths = material_candidate_paths(root, config, asset["name"], number, asset_type)
    paths["basecolor"].parent.mkdir(parents=True, exist_ok=True)
    mesh_path = root / asset["source"]["glb"]
    artifacts = []
    _lineage_start(context, "material_generation", number, (),
                   {"workflow": "mesh_pbr", "seed": mesh_info.get("seed")},
                   parents=(lineage or {}).get("material_inputs", (lineage or {}).get("upstream", [])))
    # The mesh stage's maps, copied and resized: their rights travel with them, no provider is added.
    _lineage_provenance(context, "material_generation", number, {"output_rights": []})
    if mesh_info.get("conditioning_image"):
        shutil.copy2(mesh_path.parent / mesh_info["conditioning_image"], paths["directory"] / "conditioning.png")
        mesh_info = {**mesh_info, "conditioning_image": "conditioning.png"}
    for key in ("basecolor", "normal", "roughness", "metallic"):
        shutil.copy2(mesh_path.parent / mesh_info["textures"][key], paths[key])
    if asset.get("texture_size"):
        _fit_texture_size({key: paths[key] for key in ("basecolor", "normal", "roughness", "metallic")},
                          asset["texture_size"])
    declared = concept_part_colours(asset.get("materials") or [], asset.get("parts") or [],
                                    (lineage or {}).get("part_masks"), (lineage or {}).get("concept_cutout"))
    declares_metal = any(item.get("class") == "metal" for item in declared)
    generator_metallic = None
    if declared and not declares_metal:
        # Declared non-metals are dielectrics (metallic 0); TRELLIS.2 decoded a glossy glaze at 0.3-0.6 (2026-10-20).
        with Image.open(paths["metallic"]) as image:
            generator_metallic = ImageStat.Stat(image.convert("L")).mean[0] / 255
            Image.new("RGB", image.size).save(paths["metallic"])
    coloured_nonmetals = [match for match, _glow in _emitter_targets(declared, "nonmetal").values() if match]
    nonmetal_fraction = (zero_metallic(paths["basecolor"], paths["metallic"], coloured_nonmetals)
                         if declares_metal and coloured_nonmetals else None)
    kit = kit_texture(root, context["manifest"], asset) if asset.get("kit_material") else None
    kit_settings = {}
    if kit:
        kit_settings = {"kit_texture_sha256": file_sha256(kit), "kit_hue_shift": match_hue(paths["basecolor"], kit)}
    kit_roughness = (asset.get("kit_material") or {}).get("roughness")
    if kit_roughness is not None:
        match_roughness(paths["roughness"], kit_roughness)
        kit_settings["kit_roughness"] = kit_roughness
    glass = [match for match, _glow in _emitter_targets(declared, "glass").values()]
    glass_fraction = apply_glass(paths["basecolor"], paths["roughness"], paths["metallic"], glass) if glass else None
    metal_gain = colour_transfer = None
    cutout = (lineage or {}).get("concept_cutout")
    # A held weapon's views search the full turn: TRELLIS.2 can rebuild it facing the other way (concept_view.py).
    turn = {"full_turn": True} if asset.get("pivot") == "grip" else {}
    transfer = bool(asset_type.get("concept_colour_transfer"))
    if (declares_metal or transfer) and cutout and Path(cutout).is_file():
        # The base colour and metallic maps seen from the concept's side: metal drawn lighter than decoded is
        # brightened (match_metal_lightness), and a type that opts in has its non-metal colours shifted towards the
        # concept's (match_concept_colours).
        views = {name: _concept_view(root, config, cutout, mesh_path, paths, name, min_iou=0.8, uv=False, **turn,
                                     **({"basecolor": str(paths["metallic"])} if name == "material_metallic" else {}))
                 for name in ("material_base", "material_metallic")}
        if all(view.get("status") == "rendered" for view in views.values()):
            arrays = [np.asarray(Image.open(path).convert("RGBA"), dtype=float) for path in
                      (cutout, paths["directory"] / "material_base_base.png",
                       paths["directory"] / "material_metallic_base.png")]
            if declares_metal:
                metal_gain = round(match_metal_lightness(paths["basecolor"], paths["metallic"], *arrays), 3)
            if transfer:
                # the parts route's textures are dark all over, so lightness moves the whole way to the concept's
                colour_transfer = match_concept_colours(paths["basecolor"], paths["metallic"], *arrays,
                                                        **({"lightness_share": 1.0} if mesh_info.get("part_model") == "omnipart" else {}))
    make_metallic_gloss(paths["metallic"], paths["roughness"], paths["metallic_gloss"])
    shutil.copy2(paths["basecolor"], paths["surface"])
    emissive_fraction = projection = None
    targets = sorted(set(_emitter_targets(declared).values()), key=str)
    if targets:
        projected, projection = _project_concept_emitters(root, config, (lineage or {}).get("concept_cutout"),
                                                          mesh_path, paths, targets)
        emissive_fraction = derive_emission(paths["basecolor"], paths["emission"], targets, extra_masks=projected)
    else:
        with Image.open(paths["basecolor"]) as image:
            Image.new("RGB", image.size, (0, 0, 0)).save(paths["emission"])
    paths["generator"].write_text(json.dumps(mesh_info, indent=2) + "\n")
    material_refs = _lineage_finish(context, "material_generation", number,
        [(paths[key], _MATERIAL_ARTIFACT_TYPES[key]) for key in
         ("surface", "basecolor", "normal", "roughness", "metallic", "metallic_gloss", "emission")]
        + [(paths["generator"], "generation.metadata")])
    artifacts.extend(material_refs)
    budget = _face_budget(config["asset_pipeline"], asset_type, asset)
    textures = [paths[key] for key in ("basecolor", "normal", "roughness", "metallic", "emission")]
    assembly_inputs = [*material_refs, *(lineage or {}).get("assembly_inputs", [])]
    _lineage_start(lineage, "material_assembly_export", number, (),
                   {"preserve_uvs": True, "face_budget": budget, **_placement(asset), **kit_settings},
                   parents=assembly_inputs)
    _lineage_provenance(lineage, "material_assembly_export", number, {"output_rights": rights_of(config, "blender")})
    grip = next((part for part in asset.get("parts") or [] if part["kind"] == "grip"), None)
    masks = (lineage or {}).get("part_masks")
    held = asset.get("pivot") == "grip"
    declared = [part for part in asset.get("parts") or [] if part["kind"] in ("hinge", "slide")]
    # A held weapon, or any asset with a moving part (a chest's lid), is framed from its concept: the masks go to the
    # final pass to split a cut weapon's parts, or to measure how much of each mask a generated part covers
    # (part_coverage). The grip mask and the full-turn search are the held weapon's alone.
    framed = held or bool(declared)
    moving = [(part["name"], part["kind"], Path(masks) / f"{part['name']}.png") for part in declared] if framed and masks else []
    parts_json = mesh_path.parent / "parts/parts.json" if mesh_info.get("part_model") else None
    process_model(root, config, mesh_path, paths["fbx"], paths["blend"], textures, budget,
                  preview_dir=paths["preview_front"].parent, preserve_uvs=True,
                  stage_mesh=root / asset["source"]["processed_mesh"], target_size=asset.get("target_size"),
                  pivot=asset.get("pivot"), arm_thickness=asset.get("arm_thickness"),
                  concept=(lineage or {}).get("concept_cutout") if framed else None,
                  grip_mask=Path(masks) / f"{grip['name']}.png" if held and grip and masks else None, parts=moving,
                  parts_json=parts_json, anchors={part["name"]: part["anchor"] for part in declared if part.get("anchor")},
                  motions={part["name"]: (part["axis"], float(part["min"]), float(part["max"])) for part in declared
                           if part.get("axis") is not None})
    inspection = inspect_model(root, config, paths["blend"], paths["validation"], budget,
                               real_scale=bool(asset.get("target_size")))
    keys = ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss", "emission",
            "preview_front", "preview_side", "preview_rear", "preview_three_quarter")
    validation = validate_model_outputs({key: paths[key] for key in keys}, inspection, budget, root,
        max_components=asset_type.get("max_components"),
        max_nonmanifold_edges=asset_type.get("max_nonmanifold_edges"),
        max_boundary_edges=asset_type.get("max_boundary_edges"), min_uv_area=asset_type.get("min_uv_area"))
    if asset_type.get("concept_projection"):
        validation = apply_concept_silhouette(validation, mesh_info.get("concept_projection"))
    maps = measure_material_maps({key: paths[key] for key in ("basecolor", "roughness", "metallic")})
    if declares_metal or generator_metallic is not None:  # the brief explains the metallic map
        maps["warnings"] = [item for item in maps["warnings"] if not item.startswith("metallic map is")]
    if generator_metallic is not None:
        maps["maps"]["metallic"]["generator_mean"] = round(generator_metallic, 4)
    validation.setdefault("measured", {})["material_maps"] = maps["maps"]
    validation["warnings"] = [*validation.get("warnings", []), *maps["warnings"]]
    if maps["warnings"] and validation["status"] == "passed":
        validation["status"] = "passed_with_warnings"
    if emissive_fraction is not None:
        validation = apply_declared_emitter(validation, emissive_fraction)
    if glass_fraction is not None:
        validation = apply_declared_glass(validation, glass_fraction)
    if nonmetal_fraction is not None:
        validation = apply_declared_nonmetal(validation, nonmetal_fraction)
    if metal_gain is not None:
        validation.setdefault("measured", {})["metal_lightness_gain"] = metal_gain
    if colour_transfer is not None:
        validation.setdefault("measured", {})["concept_colour_transfer"] = colour_transfer
    if held:
        validation = apply_weapon_orientation(validation)
    if moving:
        validation = apply_moving_parts(validation, [name for name, _kind, _mask in moving])
    validation = apply_mesh_folds(validation, validation.get("measured", {}).get("folded_edge_share"),
                                  float(asset_type.get("max_folded_edge_share", 0.1)))
    hybrid_info = mesh_info.get("hybrid") or {}
    # OmniPart decides labels where the mask did not vote: faces the concept's view did not see, or a dropped mask
    decisive = not ((hybrid_info.get("view") or {}).get("through") and not hybrid_info.get("masks_dropped"))
    validation = apply_hybrid_alignment(validation, hybrid_info.get("alignment_error"),
                                        float(asset_type.get("max_hybrid_alignment_error", 0.03)), decisive=decisive)
    validation = apply_part_fit(validation, (mesh_info.get("open_state") or {}).get("close"), MAX_OPEN_PART_STRETCH)
    if mesh_info.get("part_model"):
        validation = apply_part_coverage(validation, validation.get("measured", {}).get("part_coverage") or {},
                                         asset.get("parts") or [], asset_type.get("min_part_coverage", 0.55))
        validation = apply_part_penetration(validation, validation.get("measured", {}).get("part_penetration") or {},
                                            asset.get("parts") or [], float(asset_type.get("max_part_penetration", 0.02)))
        validation = apply_visible_backfaces(validation, validation.get("measured", {}).get("visible_backfaces"),
                                             float(asset_type.get("max_visible_backfaces", 0.01)))
    validation = apply_module_footprint(validation, validation.get("measured", {}).get("footprint_quadrants"),
                                        asset.get("footprint"))
    validation = apply_module_stretch(validation, validation.get("measured", {}).get("axis_stretch"),
                                      asset.get("max_stretch"))
    with Image.open(paths["basecolor"]) as image:
        validation.setdefault("measured", {})["texture_size"] = list(image.size)
    colour_limits = (asset_type.get("max_concept_hue_difference"), asset_type.get("min_concept_chroma_ratio"),
                     asset_type.get("max_concept_darkened_share"), asset_type.get("max_concept_desaturated_share"))
    min_fit = asset_type.get("min_concept_fit")
    cutout = (lineage or {}).get("concept_cutout")
    if (any(limit is not None for limit in colour_limits) or min_fit is not None) and cutout and Path(cutout).is_file():
        # The atlas also holds hidden insides and bases, so compare what the concept shows (2026-10-21 jug: atlas
        # saturation 0.42 of the concept's, 0.83 from the concept's side). 0.8 fits the concept's side; jugs fit 0.86.
        view = _concept_view(root, config, cutout, mesh_path, paths, "concept_colour", min_iou=0.8, uv=False, **turn)
        rendered = paths["directory"] / "concept_colour_base.png" if view.get("status") == "rendered" else None
        if any(limit is not None for limit in colour_limits):
            validation = apply_concept_colour(validation, concept_colour_fidelity(cutout, paths["basecolor"], rendered,
                                                                                  view), *colour_limits)
        if min_fit is not None:
            validation = apply_concept_fit(validation, view, min_fit)
        if rendered is not None:  # recorded for every model; enforced where the type declares a minimum
            validation = apply_thin_features(validation, concept_thin_recall(cutout, rendered),
                                             asset_type.get("min_concept_thin_recall"))
    paths["validation"].write_text(json.dumps(validation, indent=2) + "\n")
    failure = _validation_failure(validation, stage="material_assembly_export", attempt=number)
    assembly_outputs = [(paths[key], _MATERIAL_ARTIFACT_TYPES[key]) for key in
                        ("fbx", "blend", "preview_front", "preview_side", "preview_rear",
                         "preview_three_quarter", "validation")]
    artifacts.extend(_lineage_finish(
        lineage, "material_assembly_export", number, assembly_outputs,
        error=failure["message"] if failure else None, failure=failure))
    return {"number": number, "prompt": asset.get("generation_prompt", asset["description"]),
            "status": "candidate" if validation["status"] != "failed" else "failed",
            "kind": "mesh_pbr", "seed": mesh_info.get("seed"),
            "normal_source": mesh_info.get("normal_source", "unknown"),
            "emission_source": "declared_emissive_mask" if emissive_fraction is not None else "none",
            **({"emission_projection": projection} if projection else {}),
            "metallic_source": ("declared_nonmetal" if generator_metallic is not None else
                                "generator_with_declared_nonmetals" if nonmetal_fraction is not None else "generator"),
            **({"glass_source": "declared_glass_mask"} if glass_fraction is not None else {}),
            "path": paths["surface"].relative_to(root).as_posix(), "validation": validation,
            "generator": generator_provenance(mesh_info.get("workflow"), mesh_info),
            "outputs": _relative_outputs(root, paths, keys), "artifacts": artifacts,
            "failure": failure}


# Views workflow prompts per Pixal3D multi-view slot (2026-10-20, relay and crate on the H100). Pixal3D's
# orbit sits at eye level: the angle LoRA's "eye-level" kept the concept's raised camera and tilted the
# reconstruction, while "low-angle" from the raised three-quarter concept gave a level front. Its side views
# stopped 45-60 degrees short, so the sides use a plain instruction; Pixal3D's left slot is the object's
# left side, which a viewer at the front sees on the right.
_SIDE_VIEW = ("Move the camera 90 degrees to the {turn} around the object and look straight at the side that was "
              "on the {turn} of the image: an exact side profile view at the same eye level and distance; same "
              "object, same materials, plain light-grey background.")
VIEW_PROMPTS = {"front": "<sks> front view low-angle shot medium shot",
                "left": _SIDE_VIEW.format(turn="right"),
                "back": "<sks> back view eye-level shot medium shot",
                "right": _SIDE_VIEW.format(turn="left")}


def model_view_slots(root, workflow):
    """Multi-view slots a model graph conditions on: its LoadImage nodes named view_<slot>."""
    graph = json.loads(resolve_workflow(root, workflow).read_text())
    return [slot for slot in VIEW_PROMPTS if graph.get(f"view_{slot}", {}).get("class_type") == "LoadImage"]


# On an eye-level orbit opposite views have mirrored silhouettes. On 2026-10-20 sets that reconstructed
# cleanly scored at least 0.956 per pair; a three-quarter front, short side turns and a depth that drifted
# between sides scored 0.71-0.81 and gave tilted, doubled or tapered meshes.
VIEW_MIN_MIRROR_IOU = 0.9
VIEW_ATTEMPTS = 3


def _generate_views(root, config, python, concept, directory, slots, settings, execution_id, concept_artifact):
    """Conditioning views from the approved concept, as hashed artifacts of the conditioning stage.

    The front is generated from the concept; the other slots from that eye-level front, the LoRA's
    reference pose (from the three-quarter concept the back came out about 30 degrees off), with the
    concept prompt so unseen sides follow the brief instead of the editor's guess. A set whose opposite
    views disagree is regenerated with the next seeds and kept on disk. Like the cutout, every output
    derives from the stage input, the approved concept; reuse requires that. Returns (refs, attempts).
    """
    workflow = config["asset_pipeline"]["workflows"]["views"]
    order = ["front"] + [item for item in slots if item != "front"]
    attempts = []
    for attempt in range(1, settings["attempts"] + 1):
        folder = directory / f"attempt_{attempt}"
        folder.mkdir(parents=True, exist_ok=True)
        raw = {}
        for index, slot in enumerate(order):
            raw[slot] = folder / f"view_{slot}_raw.png"
            generate_image(root, config, workflow, settings["prompts"][slot], raw[slot],
                           f"slopforge/views/{execution_id}/{attempt}/{slot}",
                           settings["seed"] + 10 * (attempt - 1) + index, raw[slot].with_suffix(".json"),
                           conditioning={"references": [{"path": Path(concept if slot == "front" else raw["front"])
                                                         .relative_to(root).as_posix(), "strength": 1.0}],
                                         "workflow_inputs": [{"image": {"node": "image", "input": "image"}}]})
        subprocess.run([python, str(tool_root() / "processing/prepare_views.py"), "--output-dir", str(folder),
                        "--report", str(folder / "views.json"), *[f"--view={slot}={raw[slot]}" for slot in slots]],
                       check=True)
        agreement = json.loads((folder / "views.json").read_text())["mirror_iou"]
        attempts.append({"attempt": attempt, "seed": settings["seed"] + 10 * (attempt - 1),
                         "directory": folder.relative_to(root).as_posix(), "mirror_iou": agreement})
        if all(value >= settings["min_mirror_iou"] for value in agreement.values()):
            break
    else:
        raise StageFailure(
            "candidate_quality", f"Generated views disagree in all {len(attempts)} attempts (mirrored silhouette "
            f"overlap below {settings['min_mirror_iou']}): " + "; ".join(
                f"attempt {item['attempt']}: {item['mirror_iou']}" for item in attempts),
            operation="view_generation", stage="conditioning_preparation",
            remedy="inspect the retained views; describe each side of the object in --image-prompt or choose "
                   "another concept, then approve again", evidence={"attempts": attempts})
    refs = []
    for slot in order:
        refs.append(_artifact_ref(root, raw[slot], f"view-raw-{slot}:{execution_id}", f"image.view_raw.{slot}",
                                  "conditioning_preparation", 1, [concept_artifact]))
    for slot in slots:
        path = folder / f"view_{slot}.png"
        check = validate_image(path, expected_format="PNG", report_path=path.relative_to(root))
        if check["status"] == "failed":
            raise ValueError(f"Prepared {slot} view validation failed: {check['errors']}")
        refs.append(_artifact_ref(root, path, f"view-{slot}:{execution_id}", f"image.view.{slot}",
                                  "conditioning_preparation", 1, [concept_artifact]))
    return refs, attempts


def _face_budget(pipeline, asset_type, asset, default=30000):
    """A kit module's declared face budget, else its asset type's: a flat floor tile need not spend a doorway's 60k
    faces (2026-10-22 kit: a 3 x 3 m floor used 59,988)."""
    budget = asset.get("face_budget") or pipeline.get("model_budgets", {}).get(asset_type.get("face_budget"), default)
    return int(budget) if budget is not None else None


def _removes_hidden_faces(asset_type, asset):
    """Whether the mesh stage deletes the faces no ray from outside reaches before it reduces (the type's
    remove_hidden_faces): not behind declared glass, which is seen through, nor on a type that needs a closed body."""
    if not asset_type.get("remove_hidden_faces") or asset_type.get("max_nonmanifold_edges") == 0:
        return False
    return not any(item.get("class") == "glass" for item in asset.get("materials") or [])


def _reduction_budget(face_budget, asset, asset_type=None):
    """The face count to reduce a mesh to. The final pass cuts a weapon's moving parts from the reduced mesh, and
    the cut adds faces (the bisect's splits, the caps, a barrel): 1,901 on a 30,000-face pistol (2026-10-24 run B2),
    so the reduction leaves room for them. A hybrid split (part_model: hybrid) is closed by the interfaces between
    its pieces instead, about four triangles per edge of each cut, added to both sides: 6,000 on the 2026-10-25
    pistol, so it leaves 15%."""
    # shortcut: fixed margins, measured on one pistol each; make them per-type settings if another asset overruns
    cut_later = any(part["kind"] in ("hinge", "slide") for part in asset.get("parts") or [])
    if not cut_later:
        return face_budget
    return int(face_budget * (0.85 if (asset_type or {}).get("part_model") == "hybrid" else 0.9))


def _fit_texture_size(maps, size):
    """Resize a kit module's generated maps to its declared texture size (a texture-memory budget)."""
    for path in maps.values():
        with Image.open(path) as image:
            if image.size != (size, size):
                image.resize((size, size), Image.LANCZOS).save(path)


def _placement(asset):
    """A kit module's declared size and pivot: they shape the assembled model, so they join its stage settings.
    Absent for other assets, whose settings (and so their identities) stay as before."""
    return {key: asset[key] for key in ("target_size", "pivot", "arm_thickness", "max_stretch", "texture_size")
            if asset.get(key)}


CONTROL_SLOT = {"image": {"node": "pose_image", "input": "image"}, "strength": {"node": "pose_control", "input": "strength"}}


def concept_route(config, asset_type, conditioning, shape_guide=None):
    """Concept workflow and conditioning for an asset type; generation and reuse checks share it.

    Asset types with pose_control use workflows.character_image when the profile configures it:
    prompts alone did not hold the pose (hands on hips, arms against the body), a skeleton does.
    A prop with a rendered shape guide uses workflows.guided_image, the same ControlNet graph, which reads the
    guide as depth. Either image's hash joins the conditioning identity, so changing it invalidates old concepts.
    """
    workflows = config["asset_pipeline"]["workflows"]
    if shape_guide:
        reference = {"path": str(shape_guide), "strength": SHAPE_GUIDE_STRENGTH, "category": "shape_guide",
                     "source": Path(shape_guide).name, "sha256": file_sha256(shape_guide)}
        return workflows["guided_image"], {**conditioning,
                                           "references": [reference] + conditioning["references"],
                                           "workflow_inputs": [CONTROL_SLOT] + conditioning["workflow_inputs"]}
    pose = asset_type.get("pose_control")
    if not pose or not workflows.get("character_image"):
        return workflows.get("image"), conditioning
    image = tool_root() / "workflows/inputs" / pose["image"]
    if not image.is_file():
        raise ValueError(f"pose_control image not found: {image}")
    reference = {"path": str(image), "strength": float(pose.get("strength", 1.0)), "category": "pose_control",
                 "source": f"workflows/inputs/{pose['image']}", "sha256": file_sha256(image)}
    return workflows["character_image"], {**conditioning,
                                          "references": [reference] + conditioning["references"],
                                          "workflow_inputs": [CONTROL_SLOT] + conditioning["workflow_inputs"]}


def _concept_view(root, config, cutout, mesh_path, paths, name, **options):
    """Render the candidate's base colour from the concept's fitted view (blender/concept_view.py); returns its report.

    The render is <candidate>/<name>_base.png; options (min_iou, uv) pass through to the script.
    """
    prefix, report = paths["directory"] / name, paths["directory"] / f"{name}.json"
    request = paths["directory"] / f"{name}_request.json"
    request.write_text(json.dumps({"model": str(mesh_path), "basecolor": str(paths["basecolor"]),
                                   "concept": str(cutout), "prefix": str(prefix), "report": str(report), **options}))
    result = subprocess.run([blender_executable(config, root), "--background", "--python-exit-code", "1", "--python",
                             str(tool_root() / "blender/concept_view.py"), "--", str(request)],
                            capture_output=True, text=True)
    view = (json.loads(report.read_text()) if report.is_file() else
            {"status": "failed", "error": (result.stdout + result.stderr)[-500:]})
    view.pop("traceback", None)
    return view


def _project_concept_emitters(root, config, cutout, mesh_path, paths, targets):
    """Declared emitters found in the approved concept, as texture masks for this candidate (slopforge/emitters.py).

    Colour matching on the bake still runs, so a skipped or failed projection only loses this addition; the
    report says why. Returns (masks or None, report). Only emitters declared with a colour are projected: the pale
    rule on a concept also takes stone highlights (live lantern, 2026-10-21: 90% of the projected texels were
    granite), while pale paper bakes pale enough for the colour rule on the bake.
    """
    if all(match is None for match, _glow in targets):
        return None, {"status": "skipped", "reason": "pale emitters use the colour rule on the bake only"}
    if cutout is None or not Path(cutout).is_file():
        return None, {"status": "skipped", "reason": "approved concept cutout is missing"}
    prefix = paths["directory"] / "concept_view"
    projection = _concept_view(root, config, cutout, mesh_path, paths, "concept_view")
    if projection.get("status") != "rendered":
        return None, projection
    uv_path = Path(f"{prefix}_uv.npy")
    try:
        concept = Image.open(cutout).convert("RGBA")
        flat = Image.alpha_composite(Image.new("RGBA", concept.size, (0, 0, 0, 255)), concept).convert("RGB")
        view, uv = Image.open(f"{prefix}_base.png").convert("RGBA"), np.load(uv_path)
        with Image.open(paths["basecolor"]) as image:
            size = image.size
        masks = [None if match is None else project_to_texture(concept, concept_emitter_mask(concept, match, np.asarray(
                     emitter_colour_mask(flat, match)) > 127), view, uv, size) for match, _glow in targets]
    finally:
        uv_path.unlink(missing_ok=True)  # 64 MB float pass; the base render and report stay as evidence
        Path(f"{prefix}_uv.exr").unlink(missing_ok=True)
    projection["texture_fractions"] = [None if mask is None else round(sum(mask.histogram()[128:]) / (size[0] * size[1]), 5)
                                       for mask in masks]
    return masks, projection


def _emitter_targets(materials, material_class="emissive"):
    """Declared regions of one class as colour-rule targets: region -> (match_rgb or None for pale, glow_rgb)."""
    rgb = lambda value: tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    return {item["region"]: (rgb(item["color"]), rgb(item["color"])) if item.get("color") else (None, (255, 178, 102))
            for item in materials or [] if item.get("class") == material_class}


def check_emitters_in_concept(materials, cutout):
    """Stop before mesh inference when a declared emitter is not visible in the approved concept.

    The texture bake follows the concept, so every seed would fail emitter_missing and spend the whole mesh
    budget (issue #62). The cutout goes onto black first: background removal keeps the backdrop colour under
    transparent pixels, which the pale-emitter rule would otherwise find.
    """
    targets = _emitter_targets(materials)
    if not targets:
        return
    with Image.open(cutout) as image:
        image = image.convert("RGBA")
        flat = Image.alpha_composite(Image.new("RGBA", image.size, (0, 0, 0, 255)), image).convert("RGB")
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "concept.png"
        flat.save(source)
        missing = [region for region, target in targets.items()
                   if derive_emission(source, Path(temporary) / "emission.png", [target]) < MIN_EMISSIVE_FRACTION]
    if missing:
        raise StageFailure(
            "configuration", f"Declared emissive region(s) {', '.join(missing)} are not visible in the approved concept, "
            "so the texture bake cannot contain them", operation="emitter_preflight",
            remedy="check each emissive#rrggbb colour against the concept, or approve a concept that shows the emitter "
                   "as a flat opaque surface")


# Concept canvases (Z-Image buckets). On 2026-10-20 a "taller than wide" crate brief drew 0 of 6 crates taller than
# wide on the square canvas and 6 of 6 on portrait with the proportion stated first (docs/media/concept-adherence-2026-10).
# wide: long objects such as weapons, drawn side-on (2.4:1).
CONCEPT_ASPECTS = {"square": (1024, 1024), "portrait": (896, 1152), "landscape": (1152, 896), "wide": (1536, 640)}
SHAPE_GUIDES = ("cylinder", "box")
# Stump concepts, 2026-10-22 (docs/media/concept-proportion-2026-10): at 0.5 most trunks stayed taller than wide;
# at 0.8 the concept copied the primitive and lost the brief's roots.
SHAPE_GUIDE_STRENGTH = 0.65


def parse_target_size(spec):
    """'-,-,3.2' -> [None, None, 3.2]: a real size in metres per axis (x, y, z up); '-' keeps that axis in proportion."""
    parts = str(spec).split(",")
    if len(parts) != 3:
        raise ValueError(f"--target-size needs three sizes in metres, such as -,-,3.2; got {spec!r}")
    try:
        sizes = [None if part.strip() == "-" else float(part) for part in parts]
    except ValueError:
        raise ValueError(f"--target-size sizes are metres or '-', such as -,-,3.2; got {spec!r}") from None
    if all(size is None for size in sizes):
        raise ValueError("--target-size needs at least one size; '-' keeps an axis in proportion")
    if any(size is not None and not (math.isfinite(size) and size > 0) for size in sizes):
        raise ValueError(f"--target-size sizes must be positive, got {spec!r}")
    return sizes


def parse_shape_guide(spec):
    """'cylinder:0.5' -> ('cylinder', 0.5): a primitive envelope and its height divided by its width."""
    shape, _, ratio = spec.partition(":")
    if shape not in SHAPE_GUIDES:
        raise ValueError(f"--shape-guide must name cylinder or box, such as cylinder:0.5; got {spec!r}")
    try:
        ratio = float(ratio)
    except ValueError:
        raise ValueError(f"--shape-guide needs the envelope's height divided by width, such as cylinder:0.5; "
                         f"got {spec!r}") from None
    if not 0.2 <= ratio <= 5:
        raise ValueError(f"--shape-guide height divided by width must be between 0.2 and 5, got {ratio:g}")
    return shape, ratio


def _latent_node(graph, workflow_name):
    latent = next((node_id for node_id, node in graph.items() if "Latent" in node.get("class_type", "")
                   and {"width", "height"} <= node.get("inputs", {}).keys()), None)
    if latent is None:
        raise ValueError(f"Concept workflow {workflow_name} has no latent image size for --aspect to set")
    return latent


def _render_shape_guide(root, config, destination, shape, ratio, width, height):
    result = subprocess.run([blender_executable(config, root), "--background", "--python-exit-code", "1", "--python",
                             str(tool_root() / "blender/shape_guide.py"), "--", str(destination), str(width),
                             str(height), shape, str(ratio)], capture_output=True, text=True)
    if result.returncode or not destination.is_file():
        raise RuntimeError(f"Shape guide render failed: {(result.stdout + result.stderr)[-500:]}")


def _shape_guide_image(root, config, asset_type, name, guide, aspect):
    """Render the declared shape guide on the concept canvas, under the asset's candidates; returns its path."""
    if asset_type.get("prompt_mode") == "character":
        raise ValueError("A shape guide applies to prop concepts; character concepts follow their pose skeleton")
    workflow = config["asset_pipeline"]["workflows"].get("guided_image")
    if not workflow:
        raise ValueError("--shape-guide needs asset_pipeline.workflows.guided_image, a concept graph with a ControlNet "
                         "image input (the h100 profiles set image_character_pose_api.json)")
    if aspect:
        width, height = CONCEPT_ASPECTS[aspect]
    else:
        path = resolve_workflow(root, workflow)
        graph = json.loads(path.read_text())
        latent = _latent_node(graph, path.name)
        canvas = {**graph[latent]["inputs"], **workflow_node_inputs(config, "image", path.name).get(latent, {})}
        width, height = canvas["width"], canvas["height"]
    shape, ratio = guide
    destination = (root / config["asset_pipeline"]["candidate_root"] / asset_type["name"] / name /
                   f"shape_guide_{shape}_{ratio:g}_{width}x{height}.png")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _render_shape_guide(root, config, destination, shape, ratio, width, height)
    return destination


def _with_concept_aspect(config, asset_type, workflow_path, aspect):
    """Config whose concept workflow renders on this canvas, set like a quality tier's node inputs so the
    concept identity records it; later stages keep the unchanged config."""
    if aspect not in CONCEPT_ASPECTS:
        raise ValueError(f"Concept aspect must be one of {', '.join(CONCEPT_ASPECTS)}, got {aspect!r}")
    if asset_type.get("prompt_mode") == "character":
        raise ValueError("--aspect applies to prop concepts; character concepts follow their pose skeleton's canvas")
    latent = _latent_node(json.loads(workflow_path.read_text()), workflow_path.name)
    width, height = CONCEPT_ASPECTS[aspect]
    result = copy.deepcopy(config)
    by_workflow = (result["asset_pipeline"].setdefault("quality_settings", {}).setdefault("workflow_inputs", {})
                   .setdefault("image", {}))
    inputs = by_workflow.setdefault(workflow_path.name, copy.deepcopy(by_workflow.get("*", {})))
    inputs[latent] = {**inputs.get(latent, {}), "width": width, "height": height}
    return result


def generate(project_root, config, asset_type, style, name, description, count, manifest, key, *, generation_prompt=None,
             reference_paths=None, reference_categories=None, reference_entries=None, variations=None, aspect=None,
             shape_guide=None):
    root = Path(project_root).resolve()
    conditioning = resolve_conditioning(root, config, style, reference_paths=reference_paths,
                                        reference_categories=reference_categories, reference_entries=reference_entries)
    ensure_supported(conditioning)
    pipeline = config["asset_pipeline"]
    workflow = pipeline["workflows"].get("image")
    if not workflow:
        raise ValueError("Configure asset_pipeline.workflows.image in ai/project.yaml")
    aspect = aspect or asset_type.get("aspect")
    guide_path = _shape_guide_image(root, config, asset_type, name, shape_guide, aspect) if shape_guide else None
    workflow, conditioning = concept_route(config, asset_type, conditioning, guide_path)
    workflow_path = resolve_workflow(root, workflow)
    if aspect:
        config = _with_concept_aspect(config, asset_type, workflow_path, aspect)
        pipeline = config["asset_pipeline"]
    prompt = generation_prompt or build_prompt(style, asset_type, description)
    conditioning_args = {"conditioning": conditioning} if conditioning["references"] else {}

    def backend(prompt_text, destination, seed, metadata):
        return generate_image(root, config, workflow_path, prompt_text, destination,
                              f"slopforge/{asset_type['name']}/{name}/concept_{seed}", seed, metadata,
                              **conditioning_args)

    result = generate_candidates(root, config, asset_type, style, name, prompt, count, manifest, key, backend,
                                 semantic_description=description, variations=variations,
                                 identity_inputs={"asset_type": asset_type.get("name"), "brief": description,
                                     "generation_prompt": prompt, "style": style_identity(style),
                                     "workflow": {"identifier": Path(workflow).name,
                                         "sha256": file_sha256(workflow_path) if workflow_path.is_file() else None,
                                         "configured_inputs": workflow_node_inputs(config, "image", Path(workflow).name)},
                                     "quality": {"tier": pipeline.get("selected_quality_tier", "normal"),
                                         "settings": pipeline.get("quality_settings", {})},
                                     "conditioning": {"strategy": conditioning["strategy"],
                                         "references": [{"sha256": item.get("sha256"), "strength": item.get("strength")}
                                                        for item in conditioning.get("references", [])]}})
    record = manifest["assets"][key]
    record["description"] = description
    record["generation_prompt"] = prompt
    record["conditioning"] = {"strategy": conditioning["strategy"], "references_used": conditioning["references"]}
    record["generator"]["workflow"] = str(workflow)
    return result


def _style_matches_selected_concept(asset, style):
    number = asset.get("candidates", {}).get("selected")
    candidate = next((item for item in asset.get("candidates", {}).get("items", []) if item["number"] == number), None)
    expected = candidate.get("style") if candidate else None
    return (expected == style_identity(style) if expected else
            (asset.get("style"), asset.get("style_version")) == (style["name"], style["version"]))


def retexture(project_root, config, asset_type, style, manifest, key, *, material_prompt=None, count=1):
    root = Path(project_root).resolve()
    asset = manifest["assets"][key]
    items = asset.get("material_candidates", {}).get("items", [])
    if items and items[-1].get("kind") == "mesh_pbr":
        raise ValueError("This model has mesh-generated PBR regions. Surface-swatch retexturing would replace them; generate a revised concept to change its material design.")
    if not _style_matches_selected_concept(asset, style):
        raise ValueError("Concept style has changed; restore the original style or generate a new concept")
    paths = model_paths(root, config, asset["name"], asset_type)
    if not paths["glb"].is_file():
        raise ValueError("No generated mesh exists; approve a concept candidate first")
    asset.setdefault("source", {})["processed_mesh"] = paths["processed_mesh"].relative_to(root).as_posix()
    if count < 1:
        raise ValueError("Texture candidate count must be at least 1")
    pipeline = config["asset_pipeline"]
    workflow = pipeline["workflows"]["image"]
    workflow_path = resolve_workflow(root, workflow)
    prompt = material_prompt or build_prompt(style, asset_type, asset["description"], mode="material")
    existing = asset.setdefault("material_candidates", {"items": [], "selected": None})["items"]
    start = max((int(item["number"]) for item in existing), default=0) + 1
    seeds = [secrets.randbits(32) for _ in range(count)]
    selected_number = asset.get("material_candidates", {}).get("selected")
    selected_candidate = next((item for item in asset.get("material_candidates", {}).get("items", [])
                               if item["number"] == selected_number), None)
    parent_execution = next((execution for execution in asset.get("executions", [])
                             if selected_candidate and execution["id"] == selected_candidate.get("execution_id")), None)
    mesh_ref = next((artifact for stage in reversed(parent_execution.get("stages", []) if parent_execution else [])
                     for artifact in reversed(stage.get("outputs", []))
                     if artifact["type"] in {"mesh.glb", "mesh.raw", "mesh.final"}), None)
    processing_settings = {"face_budget": _face_budget(pipeline, asset_type, asset),
                           "material_scale": float(pipeline.get("material_scale", 3.0)),
                           "processing_tool_sha256": tool_sha256(tool_root() / "blender/prepare_model.py")}
    processed_reuse = processed_mesh_reuse_decision(root, asset, mesh_ref, processing_settings) \
        if mesh_ref else {"reusable": False, "reasons": ["source mesh lineage is unknown"]}
    concept_ref = asset.get("source", {}).get("concept_artifact")
    upstream = ([concept_ref] if concept_ref else []) + ([mesh_ref] if mesh_ref else [])
    execution = start_execution(asset, {"asset_type": asset.get("type"), "brief": asset.get("description"),
        "mesh_sha256": mesh_ref.get("sha256") if mesh_ref else file_sha256(paths["glb"]),
        "material_prompt": prompt, "material_scale": config["asset_pipeline"].get("material_scale", 3.0),
        "quality": config["asset_pipeline"].get("quality_settings", {}), "seeds": seeds,
        "workflow": {"identifier": Path(workflow).name, "sha256": file_sha256(workflow_path),
                     "configured_inputs": workflow_node_inputs(config, "image", Path(workflow).name)}},
        parent_execution_id=parent_execution.get("id") if parent_execution else None)
    lineage = {"root": root, "pipeline": config["asset_pipeline"], "manifest": manifest, "key": key,
               "execution_id": execution["id"], "upstream": upstream,
               "processed_mesh_reusable": processed_reuse["reusable"]}
    results = []
    try:
        for index, number in enumerate(range(start, start + count)):
            candidate = _generate_material_candidate(root, config, asset_type, asset, number, prompt,
                paths["processed_mesh"], lineage=lineage, seed=seeds[index])
            asset = manifest["assets"][key]
            existing = asset.setdefault("material_candidates", {"items": [], "selected": None})["items"]
            execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
            if not candidate.get("artifacts"):
                candidate["artifacts"] = _material_artifact_refs(root,
                    material_candidate_paths(root, config, asset["name"], number, asset_type),
                    execution["id"], number, upstream)
            candidate.update({"execution_id": execution["id"], "stage_attempt": number,
                              "mesh_source": paths["glb"].relative_to(root).as_posix(),
                              "mesh_attempt": mesh_ref.get("attempt") if mesh_ref else None,
                              "upstream_artifacts": upstream})
            existing.append(candidate)
            results.append(candidate)
        if any(item["status"] == "candidate" for item in results):
            finish_execution(execution, "succeeded")
        else:
            failure = _candidate_failure(results[-1], attempt=results[-1].get("stage_attempt", start))
            _record_blocked_stages(execution, pipeline, failure)
            finish_execution(execution, "failed", failure=failure)
        from .. import SCHEMA_VERSION
        manifest.setdefault("schema_version", SCHEMA_VERSION)
        save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
    except (Exception, KeyboardInterrupt) as exc:
        execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
        failure = next((stage.get("failure") for stage in execution.get("stages", [])
                        if stage.get("status") == "failed" and stage.get("failure")), None)
        for stage in execution.get("stages", []):
            if stage.get("status") == "running":
                failure = failure or failure_record(exc, stage=stage["name"], stage_id=stage.get("id"),
                    attempt=stage["attempt"], operation=(exc.operation if isinstance(exc, StageFailure)
                                                         else stage["name"]))
                finish_stage(stage, "failed", error=str(exc) or type(exc).__name__, failure=failure)
        failure = failure or execution.get("failure") or failure_record(
            exc, stage="material_generation", attempt=None,
            operation=exc.operation if isinstance(exc, StageFailure) else "retexture")
        if execution.get("status") == "running":
            _record_blocked_stages(execution, pipeline, failure)
            finish_execution(execution, "failed", failure=failure)
        save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
        raise
    return results


def approve_texture(project_root, config, manifest, key, number, force=False, *, asset_type="prop",
                    allow_placeholder_normal=False):
    root = Path(project_root).resolve()
    asset = manifest["assets"][key]
    candidate = next((item for item in asset.get("material_candidates", {}).get("items", [])
                      if item["number"] == number), None)
    if candidate is None or candidate.get("status") != "candidate":
        raise ValueError(f"Material candidate {number} is not valid for {asset['name']}")
    generator = asset.setdefault("generator", {})
    if not isinstance(generator.setdefault("workflow", {}), dict) or not isinstance(generator.setdefault("seed", {}), dict):
        # `generate` replaces the record with concept-stage provenance; this material belongs to the earlier mesh.
        raise ValueError(f"Concept candidates for {asset['name']} were regenerated after material {number} was made; "
                         "approve a concept again before publishing a material")
    try:
        unity_cli(root)
    except StageFailure as exc:
        asset["last_failure"] = failure_record(exc, stage="preflight", attempt=None,
                                               operation=exc.operation)
        save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
        raise
    paths = model_paths(root, config, asset["name"], asset_type)
    candidate_paths = material_candidate_paths(root, config, asset["name"], number, asset_type)
    candidate.setdefault("outputs", {})
    metallic = root / candidate["outputs"].get("metallic", candidate_paths["metallic"].relative_to(root).as_posix())
    roughness = root / candidate["outputs"].get("roughness", candidate_paths["roughness"].relative_to(root).as_posix())
    packed_ref = candidate["outputs"].get("metallic_gloss")
    packed = root / packed_ref if packed_ref else metallic.with_name(f"{asset['name']}_metallic_gloss.png")
    if not packed.is_file():
        make_metallic_gloss(metallic, roughness, packed)
    candidate["outputs"]["metallic_gloss"] = packed.relative_to(root).as_posix()
    final_keys = ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss", "emission",
                  "preview_front", "preview_side", "preview_rear", "preview_three_quarter")
    existing = [paths[name] for name in (*final_keys, "glb", "unity_material", "unity_glass_material") if paths[name].exists()]
    if existing and not (force or config["asset_pipeline"].get("overwrite_existing")):
        raise FileExistsError(f"Approved model outputs exist; pass --force to replace: {existing[0]}")
    sources = {name: root / candidate["outputs"][name] for name in final_keys}
    missing = [str(path) for path in sources.values() if not path.is_file() or not path.stat().st_size]
    if missing:
        raise ValueError("Material candidate output missing or empty: " + missing[0])
    if is_placeholder_normal(sources["normal"]):
        if not allow_placeholder_normal:
            raise ValueError(f"Material candidate {number} has a placeholder normal map ({sources['normal']}); "
                             "regenerate with a real normal map or pass --allow-placeholder-normal to waive")
        candidate["placeholder_normal_waived"] = True
    mesh_source = candidate.get("mesh_source") or asset.get("source", {}).get("glb")
    if not isinstance(mesh_source, str) or not (root / mesh_source).is_file():
        raise ValueError("Qualified material candidate has no retained source mesh")
    candidate_artifacts = candidate.get("artifacts", [])
    rights = _delivery_rights(root, asset, candidate_artifacts, mesh_source)
    try:
        require_shippable(rights, asset["name"], "approve-texture")
    except StageFailure as exc:
        asset["last_failure"] = failure_record(exc, stage="preflight", attempt=None, operation=exc.operation)
        save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
        raise
    pipeline = config["asset_pipeline"]
    execution = start_execution(asset, {
        "asset_type": asset.get("type"), "candidate_artifacts": [
            {"id": item["id"], "sha256": item["sha256"]} for item in candidate_artifacts],
        "publication_roles": ["surface", "fbx", "blend", "maps", "previews", "unity_material", "validation"],
    }, parent_execution_id=candidate.get("execution_id"))
    publication_stage = start_stage(execution, "final_publication", 1, candidate_artifacts,
                                    {"approval": "selected material candidate"},
                                    {"output_rights": [], "delivered_rights": rights})
    save_manifest(root / pipeline["manifest"], manifest)
    begin_stage(publication_stage)
    from .. import SCHEMA_VERSION
    manifest.setdefault("schema_version", SCHEMA_VERSION)
    save_manifest(root / pipeline["manifest"], manifest)
    publication_paths = [paths[name] for name in (*final_keys, "glb", "unity_material", "unity_glass_material", "validation")]
    publication_paths.append(paths["directory"] / NOTICES_FILE)
    publication_paths += [path.with_suffix(path.suffix + ".meta") for path in publication_paths]
    with tempfile.TemporaryDirectory(prefix="slopforge-texture-backup-") as backup_dir:
        backups = {}
        backups_complete = False
        try:
            for index, destination in enumerate(publication_paths):
                if destination.is_file():
                    backup = Path(backup_dir) / str(index)
                    shutil.copy2(destination, backup)
                    backups[destination] = backup
            backups_complete = True
            for name in final_keys:
                destination = paths[name]
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as handle:
                    temporary = Path(handle.name)
                try:
                    shutil.copy2(sources[name], temporary)
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
            if (root / mesh_source).resolve() != paths["glb"].resolve():
                paths["glb"].parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / mesh_source, paths["glb"])
            write_notices(paths["directory"], asset["name"], rights)
            type_record = load_taxonomy(root).get(asset.get("type") or asset_type) or {}  # asset_type is its name here
            # held weapons and types that deform (creatures, lit by probes) get no lightmap UVs
            unity_import = build_unity_material(root, paths["fbx"], paths["directory"] / "Materials" /
                                                f"{asset['name']}_preview_PBR.mat",
                                                {name: paths[name] for name in ("basecolor", "normal", "metallic_gloss", "emission")},
                                                lightmap_uvs=asset.get("pivot") != "grip"
                                                and type_record.get("lightmap_uvs", True))
            _require_stable_unity_identity(asset.get("unity_import"), unity_import)
            validation = dict(candidate["validation"])
            validation["measured"] = dict(validation.get("measured", {}))
            validation["measured"].update({name: paths[name].relative_to(root).as_posix() for name in final_keys})
            validation["measured"]["unity_material"] = paths["unity_material"].relative_to(root).as_posix()
            moving = [part for part in asset.get("parts") or [] if part["kind"] in ("hinge", "slide")]
            if moving or type_record.get("unity_prefab"):
                # A prefab a game can use: colliders, a Rigidbody, sockets, and for moving parts a clip each and a
                # motion check (unity_weapon). Types that opt in get one for static assets too.
                motion = build_weapon_prefab(root, asset["name"], paths["fbx"], moving,
                                             prefab=paths["directory"] / f"{asset['name']}.prefab",
                                             clip_folder=paths["directory"] / "Animations",
                                             render=paths["preview_front"].parent / f"{asset['name']}_motion.png",
                                             held=asset.get("pivot") == "grip", mass=float(type_record.get("mass", 1.0)),
                                             layer=type_record.get("unity_layer"))
                if motion["errors"]:
                    raise StageFailure("processing_validation",
                                       "weapon motion checks failed: " + "; ".join(motion["errors"]),
                                       operation="weapon_motion",
                                       remedy="check the part's declared axis, range and anchor against the published "
                                              "model: a hinge turns about the edge it is anchored on (a lid: @back-bottom, its seam)")
                validation["measured"]["weapon_motion"] = {key: value for key, value in motion.items()
                                                           if key != "errors"}
                # then the prefab is played: the Animator pulses each part and the Rigidbody settles on a floor
                validation["measured"]["play_mode"] = verify_play_mode(
                    root, motion["prefab"], moving, results=paths["directory"] / f"{asset['name']}_playmode.xml")
            paths["validation"].write_text(json.dumps(validation, indent=2) + "\n")
            outputs = _relative_outputs(root, paths, (*final_keys, "glb", "unity_material", "validation"))
            published = _published_artifacts(root, paths, candidate, execution["id"])
        except (Exception, KeyboardInterrupt) as exc:
            rollback_failure = None
            try:
                if backups_complete:
                    for destination in publication_paths:
                        if destination in backups:
                            shutil.copy2(backups[destination], destination)
                        else:
                            destination.unlink(missing_ok=True)
            except (Exception, KeyboardInterrupt) as rb_exc:
                rollback_failure = rb_exc
            primary_failure = failure_record(
                exc, stage="final_publication", stage_id=publication_stage["id"], attempt=1,
                operation=exc.operation if isinstance(exc, StageFailure) else "final_publication")
            if rollback_failure is not None:
                primary_failure["evidence"] = primary_failure.get("evidence") or {}
                primary_failure["evidence"]["rollback_failure"] = str(rollback_failure)
                primary_failure["evidence"]["rollback_partial"] = True
            finish_stage(publication_stage, "failed",
                         error=str(exc) or type(exc).__name__, failure=primary_failure)
            finish_execution(execution, "failed", failure=primary_failure)
            save_manifest(root / pipeline["manifest"], manifest)
            raise
    candidate["approval"] = "approved"
    asset["material_candidates"]["selected"] = number
    asset["material_prompt"] = candidate["prompt"]
    generator["material"] = candidate.get("generator")
    generator["workflow"]["material"] = (candidate.get("generator") or {}).get("workflow")
    generator["seed"]["material"] = candidate.get("seed")
    asset["outputs"] = outputs
    asset["validation"] = validation
    asset["status"] = "ready"
    asset["updated_at"] = datetime.now(timezone.utc).isoformat()
    finish_stage(publication_stage, "succeeded", published)
    finish_execution(execution, "succeeded")
    asset["published_artifacts"] = published
    asset["output_rights"] = rights  # what registered artifacts made from it (a rig, a clip) read
    asset["unity_import"] = {"logical_id": key, **unity_import}
    save_manifest(root / pipeline["manifest"], manifest)
    return validation


def _delivery_rights(root, asset, candidate_artifacts, mesh_source):
    """The weakest rights over the candidate's whole lineage and the GLB it ships, whose producer the candidate's
    lineage may bypass (the hybrid route's split surface; a retextured asset's published mesh)."""
    digest = file_sha256(root / mesh_source)
    mesh_refs = [output for execution in asset.get("executions") or [] if isinstance(execution, dict)
                 for stage in execution.get("stages") or [] if isinstance(stage, dict)
                 for output in stage.get("outputs") or [] if isinstance(output, dict)
                 and output.get("path") == mesh_source and output.get("sha256") == digest]
    rights = lineage_rights(asset, candidate_artifacts + mesh_refs)
    if mesh_refs:
        return rights
    return merge_rights(rights, combine_rights([{"source": mesh_source, "status": "unknown",
                                                 "reason": "no stage records producing the mesh it ships"}]))


def _require_stable_unity_identity(previous, current):
    """Republishing an asset must keep the Unity GUID at each path, or scene and prefab references break."""
    before = (previous or {}).get("assets", {})
    changed = sorted(role for role, entry in current["assets"].items()
                     if before.get(role, {}).get("path") == entry["path"] and before[role]["guid"] != entry["guid"])
    if changed:
        raise StageFailure("processing_validation",
                           f"Republishing changed the Unity GUID of the {', '.join(changed)}; references to the "
                           "previous asset would break", operation="unity_import",
                           remedy="restore the asset's .meta files from version control and approve again, "
                                  "or publish it under a new asset name")


def unity_preview(project_root, config, manifest, key, number, *, asset_type="prop"):
    """Import a material candidate into Unity and render it, without approving or publishing it."""
    root = Path(project_root).resolve()
    asset = manifest["assets"][key]
    candidate = next((item for item in asset.get("material_candidates", {}).get("items", [])
                      if item["number"] == number), None)
    if candidate is None or candidate.get("status") != "candidate":
        raise ValueError(f"Material candidate {number} is not valid for {asset['name']}")
    unity_cli(root)
    name = asset["name"]
    outputs = candidate.get("outputs", {})
    sources = {item: root / outputs[item] for item in ("fbx", "basecolor", "normal", "emission", "metallic", "roughness")
               if item in outputs}
    missing = [item for item in ("fbx", "basecolor", "normal", "emission", "metallic", "roughness")
               if item not in sources or not sources[item].is_file()]
    if missing:
        raise ValueError(f"Material candidate {number} is missing {', '.join(missing)}")
    candidate_dir = material_candidate_paths(root, config, name, number, asset_type)["directory"]
    # Outside the delivery folder, so a preview is never mistaken for a published asset.
    directory = root / config["asset_pipeline"]["output_root"] / "CandidatePreviews" / name / f"material_{number:02d}"
    (directory / "Materials").mkdir(parents=True, exist_ok=True)
    fbx = directory / f"{name}.fbx"
    shutil.copy2(sources["fbx"], fbx)
    maps = {}
    for item in ("basecolor", "normal", "emission"):
        maps[item] = directory / "Materials" / f"{name}_{item}.png"
        shutil.copy2(sources[item], maps[item])
    maps["metallic_gloss"] = directory / "Materials" / f"{name}_metallic_gloss.png"
    make_metallic_gloss(sources["metallic"], sources["roughness"], maps["metallic_gloss"])
    material = directory / "Materials" / f"{name}_preview_PBR.mat"
    render = candidate_dir / "unity_preview.png"
    record = {"status": "failed", "at": datetime.now(timezone.utc).isoformat(),
              "unity_version": (root / "ProjectSettings/ProjectVersion.txt").read_text().splitlines()[0].split(":")[-1].strip(),
              "inputs": {item: {"path": path.relative_to(root).as_posix(), "sha256": file_sha256(path)}
                         for item, path in sources.items()}}
    candidate["unity_preview"] = record
    try:
        build_unity_material(root, fbx, material, maps, render=render)
    except (Exception, KeyboardInterrupt) as exc:
        record["error"] = str(exc) or type(exc).__name__
        # Unreferenced copies under Assets/ would be imported again on the next Unity start.
        shutil.rmtree(directory, ignore_errors=True)
        directory.with_name(directory.name + ".meta").unlink(missing_ok=True)
        raise
    record.update({"status": "imported", "fbx": fbx.relative_to(root).as_posix(),
                   "material": material.relative_to(root).as_posix(),
                   "render": render.relative_to(root).as_posix() if render.is_file() else None})
    return record


def _published_artifacts(root, paths, candidate, execution_id):
    candidate_refs = candidate.get("artifacts", [])
    mesh_ref = next((item for item in candidate.get("upstream_artifacts", []) if item["type"].startswith("mesh.")), None)
    by_type = {}
    for item in candidate_refs:
        by_type.setdefault(item["type"], []).append(item)
    published = []
    output_types = {"surface": "surface.swatch", "fbx": "mesh.fbx", "blend": "project.blend",
                    "basecolor": "texture.basecolor", "normal": "texture.normal", "roughness": "texture.roughness",
                    "metallic": "texture.metallic", "metallic_gloss": "texture.metallic_gloss",
                    "emission": "texture.emission", "preview_front": "preview.front", "preview_side": "preview.side",
                    "preview_rear": "preview.rear", "preview_three_quarter": "preview.three_quarter",
                    "unity_material": "material.unity", "unity_glass_material": "material.unity_glass",
                    "validation": "validation.json", "glb": "mesh.glb"}
    for key_name, kind in output_types.items():
        path = paths[key_name]
        parents = by_type.get(kind, [])
        if key_name == "glb" and mesh_ref:
            parents = [mesh_ref]
        if key_name in ("unity_material", "unity_glass_material"):
            parents = [item for item in candidate_refs if item["type"].startswith("texture.")]
        if key_name == "validation":
            parents = candidate_refs
        if path.is_file():
            published.append(_artifact_ref(root, path, f"{execution_id}:published:{key_name}", kind,
                                           "final_publication", 1, parents))
    return published


def _part_sampler(asset_type):
    """OmniPart's sampler settings from the type (part_steps, part_cfg); part of the mesh identity on that route."""
    return {"steps": int(asset_type.get("part_steps", 25)), "cfg": float(asset_type.get("part_cfg", 7.5))}


def part_backend(asset_type, asset):
    """The part-level generator (asset type `part_model`) for a weapon that declares a hinge or slide, else None."""
    moving = any(part.get("kind") in ("hinge", "slide") for part in asset.get("parts") or [])
    return asset_type.get("part_model") if moving else None


def model_route(config, asset_type):
    """Config whose model workflow is the asset type's own graph when the profile provides it.

    Characters use workflows.character_model (sharp-feature remesh, inner shells dropped before QEM
    decimation). Swapping it in once, before any model work, keeps generation, provenance and reuse
    checks on the same workflow.
    """
    pipeline = config["asset_pipeline"]
    key = asset_type.get("model_workflow")
    if not key or not pipeline["workflows"].get(key):
        return config
    return {**config, "asset_pipeline": {**pipeline, "workflows": {**pipeline["workflows"],
                                                                     "model": pipeline["workflows"][key]}}}


def approve(project_root, config, asset_type, style, manifest, key, number, force=False, *,
            material_prompt=None, material_count=None, quality_tier=None, resume=False, open_number=None):
    root = Path(project_root).resolve()
    asset = manifest["assets"][key]
    candidate = next((item for item in asset.get("candidates", {}).get("items", []) if item["number"] == number), None)
    if candidate is None or candidate.get("status") != "candidate":
        raise ValueError(f"Candidate {number} is not valid for {asset['name']}")
    if candidate.get("open_of") is not None:
        raise ValueError(f"Candidate {number} is an open picture of candidate {candidate['open_of']}: approve "
                         f"{candidate['open_of']} with --open {number}")
    if open_number is not None:  # checked before the run starts; resume finds it in the execution's identity
        open_choice(asset, number, open_number)
    check_slide_scale(asset.get("parts") or [], asset.get("target_size"))
    candidate_quality = (candidate.get("generator") or {}).get("quality", {}).get("tier")
    config = select_quality_tier(config, quality_tier or candidate_quality or
                                 config["asset_pipeline"].get("selected_quality_tier", "normal"))
    pipeline = config["asset_pipeline"]
    config = model_route(config, asset_type)
    pipeline = config["asset_pipeline"]
    if pipeline["workflows"].get("model") and material_prompt:
        raise ValueError("The mesh-texturing workflow uses the selected concept's material design. Put the intended materials in --image-prompt; --material-prompt is for surface swatches.")
    expected_style = candidate.get("style")
    if ((expected_style and expected_style != style_identity(style)) or
            (not expected_style and (asset.get("style"), asset.get("style_version")) != (style["name"], style["version"]))):
        raise ValueError("Candidate style has changed; activate the original unchanged style pack or generate new candidates before 3D approval")
    conditioning = resolve_conditioning(root, config, style)
    ensure_supported(conditioning)
    workflow = pipeline["workflows"].get("model")
    view_slots = []
    if workflow:
        problems = workflow_mask_errors(json.loads(resolve_workflow(root, workflow).read_text()))
        if problems:
            raise ValueError("Invalid model workflow mask wiring: " + "; ".join(problems))
        view_slots = model_view_slots(root, workflow)
        if view_slots and "front" not in view_slots:  # the other views are generated from the front
            raise ValueError(f"Model workflow {Path(workflow).name} has view inputs but no view_front node")
        if view_slots and "back" not in view_slots and not {"left", "right"} <= set(view_slots):
            # View agreement is measured on opposite pairs; without one, any set would pass unchecked.
            raise ValueError(f"Model workflow {Path(workflow).name} needs an opposite view pair "
                             "(view_front and view_back, or view_left and view_right)")
        if view_slots and not pipeline["workflows"].get("views"):
            raise ValueError(f"Model workflow {Path(workflow).name} conditions on {', '.join(view_slots)} views; "
                             "set asset_pipeline.workflows.views (for example image_views_qwen_edit_api.json)")
    paths = model_paths(root, config, asset["name"], asset_type)
    existing = [path for name, path in paths.items() if name != "directory" and path.exists()]
    if existing and not (resume or force or config["asset_pipeline"].get("overwrite_existing")):
        raise FileExistsError(f"Model outputs exist; pass --force to replace: {existing[0]}")
    prompt = candidate.get("description", asset["description"])
    concept_workflow = pipeline["workflows"].get("image")
    material_prompt = material_prompt or build_prompt(style, asset_type, prompt, mode="material")
    material_count = material_count or int(pipeline["defaults"].get("material_candidates", 2))
    attempts = int(pipeline["defaults"].get("model_candidates", 1))
    if material_count < 1 or attempts < 1:
        raise ValueError("Material and model candidate budgets must be at least 1")
    mesh_seeds = [secrets.randbits(32) for _ in range(attempts)]
    material_seeds = [] if workflow else [secrets.randbits(32) for _ in range(attempts * material_count)]
    view_seed = secrets.randbits(32) if view_slots else None
    concept_path = root / candidate["path"]
    candidate_artifact = candidate.get("artifact")
    if candidate_artifact is None:
        candidate_artifact = {"id": f"legacy-concept:{number}", "type": "image.concept.legacy",
                              "path": candidate["path"], "sha256": file_sha256(concept_path),
                              "stage": "legacy_concept_selection", "attempt": number, "derived_from": []}
    intact, reason = artifact_integrity(root, candidate_artifact)
    if not intact:
        raise ValueError(f"Selected concept artifact is stale: {reason}")
    prior = None
    if resume:
        prior = next((item for item in reversed(asset.get("executions", []))
                      if item.get("status") in {"running", "failed"} and
                      item.get("identity_inputs", {}).get("selected_concept", {}).get("sha256") == candidate_artifact["sha256"]), None)
        if prior is None:
            raise ValueError("Cannot resume: no incomplete execution matches the selected concept")
        selected = prior["identity_inputs"].get("selected_concept", {})
        if selected.get("id") not in (None, candidate_artifact["id"]) or selected.get("number") not in (None, number):
            raise ValueError("Cannot resume: selected concept candidate identity changed")
        unknown_prompts = _unknown_outcome_prompts(prior)
        if unknown_prompts:
            raise ValueError("Cannot resume: remote inference outcome is unknown for " +
                             ", ".join(dict.fromkeys(unknown_prompts)) +
                             "; inspect the service state before submitting another generation")
        partial_worker = _partial_worker_output(prior)
        if partial_worker:
            raise ValueError(
                f"Cannot resume: partial worker output from {partial_worker['name']} is retained, "
                "but internal worker resume is unsupported; inspect it before resubmitting inference")
        resolved = _resolve_interrupted_prior(asset, prior, root, pipeline, manifest)
        if resolved is not None:
            stage_name = resolved["unresolved_stage_name"]
            stage_failure = next(
                (s.get("failure") for s in prior.get("stages", [])
                 if isinstance(s, dict) and s.get("name") == stage_name), None)
            evidence = (stage_failure or {}).get("evidence", {}) if isinstance(stage_failure, dict) else {}
            if evidence.get("outcome_unknown") is True:
                raise ValueError(
                    f"Cannot resume: remote inference outcome is unknown for {stage_name}; "
                    "inspect the service state before submitting another generation")
            raise ValueError(
                f"Cannot resume: unresolved {stage_name} may have accepted a remote prompt; "
                "inspect the service state before resubmitting inference")
        old_seeds = prior["identity_inputs"].get("mesh", {}).get("seeds")
        if not isinstance(old_seeds, list) or len(old_seeds) != attempts:
            raise ValueError("Cannot resume: mesh attempt seeds are missing or the attempt budget changed")
        mesh_seeds = old_seeds
        old_material_seeds = prior["identity_inputs"].get("material_seeds")
        if not workflow and (not isinstance(old_material_seeds, list) or len(old_material_seeds) != attempts * material_count):
            raise ValueError("Cannot resume: material seeds are missing or the candidate budget changed")
        material_seeds = old_material_seeds
        if view_slots:
            view_seed = prior["identity_inputs"].get("views", {}).get("seed")
            if type(view_seed) is not int:
                raise ValueError("Cannot resume: the multi-view seed is missing; approve without --resume")
        prior = copy.deepcopy(prior)
        recorded_open = (prior["identity_inputs"].get("open_concept") or {}).get("number")
        if open_number not in (None, recorded_open):
            raise ValueError("Cannot resume: the approved open picture changed; approve without --resume")
        open_number = recorded_open
    open_candidate = open_choice(asset, number, open_number) if open_number is not None else None
    if open_candidate and part_backend(asset_type, asset) != "hybrid":
        raise ValueError("An open picture is split by the hybrid parts route: set part_model: hybrid on the type")
    model_workflow_path = resolve_workflow(root, workflow) if workflow else None
    try:
        python = python_executable(root, config)
        if workflow:
            blender_executable(config, root)
    except (Exception, KeyboardInterrupt) as exc:
        asset["last_failure"] = failure_record(
            exc, stage="preflight", attempt=None,
            operation=exc.operation if isinstance(exc, StageFailure) else "model_preflight")
        save_manifest(root / pipeline["manifest"], manifest)
        if isinstance(exc, KeyboardInterrupt):
            raise
        failure = asset["last_failure"]
        raise StageFailure(failure["category"], failure["message"], operation=failure["operation"],
                           remedy=failure["remedy"], stage=failure["stage"],
                           stage_id=failure["stage_id"], evidence=failure["evidence"]) from exc
    execution = start_execution(asset, {
        "asset_type": asset_type.get("name"), "brief": candidate.get("description", asset.get("description")),
        "selected_concept": {"number": number, "id": candidate_artifact["id"], "sha256": candidate_artifact["sha256"]},
        **({"open_concept": {"number": open_number, "id": open_candidate["artifact"]["id"],
                             "sha256": open_candidate["artifact"]["sha256"]}} if open_candidate else {}),
        "workflows": {"concept": concept_workflow,
                      "material": {"identifier": Path(concept_workflow).name if concept_workflow else None,
                                   "sha256": (file_sha256(resolve_workflow(root, concept_workflow))
                                              if concept_workflow else None),
                                   "configured_inputs": (workflow_node_inputs(config, "image",
                                       Path(concept_workflow).name) if concept_workflow else {})},
                      "model": {"identifier": Path(workflow).name if workflow else "hunyuan3d_image_to_model_api",
                                "sha256": file_sha256(model_workflow_path) if model_workflow_path and model_workflow_path.is_file() else None,
                                "configured_inputs": workflow_node_inputs(config, "model", Path(workflow).name) if workflow else {}}},
        "quality": {"tier": pipeline.get("selected_quality_tier", "normal"),
                    "settings": pipeline.get("quality_settings", {})},
        "mesh": {"face_budget": _face_budget(pipeline, asset_type, asset, default=None),
                 "voxel_resolution": asset_type.get("voxel_resolution"), "seeds": mesh_seeds,
                 "checkpoint": pipeline.get("tools", {}).get("hunyuan_checkpoint")},
        "material_prompt": material_prompt, "material_count": material_count,
        "material_seeds": material_seeds,
        "material_scale": pipeline.get("material_scale", 3.0),
        **({"views": {"workflow": {"identifier": Path(pipeline["workflows"]["views"]).name,
                                   "sha256": file_sha256(resolve_workflow(root, pipeline["workflows"]["views"])),
                                   "configured_inputs": workflow_node_inputs(
                                       config, "image", Path(pipeline["workflows"]["views"]).name)},
                      "slots": view_slots, "seed": view_seed, "attempts": VIEW_ATTEMPTS,
                      "min_mirror_iou": VIEW_MIN_MIRROR_IOU,
                      "prompts": {slot: VIEW_PROMPTS[slot] if slot == "front" else
                                  f"{VIEW_PROMPTS[slot]}\nThe object, as designed from every side:\n"
                                  f"{candidate.get('prompt') or candidate.get('description', asset['description'])}"
                                  for slot in view_slots}}} if view_slots else {}),
    }, parent_execution_id=prior["id"] if prior else candidate.get("execution_id"))
    pipeline = config["asset_pipeline"]
    _persist_reload(root, pipeline, manifest)
    asset = manifest["assets"][key]
    execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
    candidate = next(item for item in asset["candidates"]["items"] if item["number"] == number)
    if open_candidate:
        open_candidate = next(item for item in asset["candidates"]["items"] if item["number"] == open_number)
    try:
        paths["concept"].parent.mkdir(parents=True, exist_ok=True)
        paths["basecolor"].parent.mkdir(parents=True, exist_ok=True)
        old_selected = asset.get("source", {}).get("concept_artifact") if prior else None
        old_parent = (old_selected or {}).get("derived_from", [])
        selected_intact = artifact_integrity(root, old_selected)[0] if old_selected else False
        if (selected_intact and old_parent == [{"artifact_id": candidate_artifact["id"],
                                                "sha256": candidate_artifact["sha256"]}]):
            selected_artifact = old_selected
        else:
            shutil.copy2(concept_path, paths["concept"])
            selected_artifact = _artifact_ref(root, paths["concept"], f"approved-concept:{execution['id']}",
                                              "image.concept.approved", "conditioning_preparation", 1,
                                              [candidate_artifact])
        open_artifact = None
        if open_candidate:  # the second concept: the same object open (docs/superpowers/specs, open-state props)
            open_path = paths["concept"].with_name("open_concept.png")
            old_open = (prior and (asset.get("source") or {}).get("open_concept_artifact")) or None
            if (old_open and artifact_integrity(root, old_open)[0] and old_open.get("derived_from") ==
                    [{"artifact_id": open_candidate["artifact"]["id"], "sha256": open_candidate["artifact"]["sha256"]}]):
                open_artifact = old_open
            else:
                shutil.copy2(root / open_candidate["path"], open_path)
                open_artifact = _artifact_ref(root, open_path, f"approved-open-concept:{execution['id']}",
                                              "image.concept.open.approved", "conditioning_preparation", 1,
                                              [open_candidate["artifact"]])
            open_candidate["approval"] = "approved"
        candidate["approval"] = "approved"
        asset["candidates"]["selected"] = number
        asset["status"] = "processing"
        asset["description"] = candidate.get("description", asset["description"])
        asset["style"], asset["style_version"] = style["name"], style["version"]
        asset["source"] = {"concept": paths["concept"].relative_to(root).as_posix(),
                           "concept_artifact": selected_artifact,
                           "concept_lineage": {"status": "known" if candidate.get("execution_id") else "unknown",
                               "reason": None if candidate.get("execution_id") else "legacy concept candidate has no execution record"},
                           **({"open_concept": open_artifact["path"], "open_concept_artifact": open_artifact,
                               "open_concept_number": open_number} if open_artifact else {})}
        _persist_reload(root, pipeline, manifest)
        asset = manifest["assets"][key]
        execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
    except (Exception, KeyboardInterrupt) as exc:
        _reload_manifest(root, pipeline, manifest)
        asset = manifest["assets"][key]
        execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
        failure = failure_record(exc, stage="model_approval", attempt=None,
            operation=exc.operation if isinstance(exc, StageFailure) else "selected_concept_setup")
        asset["last_failure"] = failure
        _record_blocked_stages(execution, pipeline, failure)
        finish_execution(execution, "failed", failure=failure)
        save_manifest(root / pipeline["manifest"], manifest)
        raise
    last_failure = None
    try:
        context = {"root": root, "pipeline": pipeline, "manifest": manifest, "key": key,
                   "execution_id": execution["id"], "reuse_execution": prior}
        # The background model is named in processing/background.py; a cut-out another model made is not reused
        # (rembg's default, BRIA RMBG-2.0, is non-commercial and made every cut-out until 2026-10-26)
        conditioning_settings = {"strategy": conditioning["strategy"], "tool": "prepare_3d_input.py",
                                 "background_sha256": file_sha256(tool_root() / "processing/background.py")}
        if view_slots:
            conditioning_settings["views"] = {**execution["identity_inputs"]["views"], "tool": "prepare_views.py"}
        if asset.get("parts"):
            conditioning_settings["parts"] = part_settings(config, asset["parts"])
        conditioning_inputs = [selected_artifact, *([open_artifact] if open_artifact else [])]
        conditioning_refs = _adopt_stage(context, "conditioning_preparation", 1,
                                         conditioning_inputs, conditioning_settings)
        if conditioning_refs is None:
            if prior:
                conditioning_dir = (root / pipeline["candidate_root"] / asset_type["name"] / asset["name"] /
                                    f"conditioning_{execution['id']}")
                conditioning_dir.mkdir(parents=True, exist_ok=True)
                paths["cutout"] = conditioning_dir / "concept_cutout.png"
                paths["input_3d"] = conditioning_dir / "concept_3d_input.png"
            asset = manifest["assets"][key]
            execution = next(item for item in asset["executions"] if item["id"] == context["execution_id"])
            stage = start_stage(execution, "conditioning_preparation", 1, conditioning_inputs,
                                conditioning_settings, {"concept_lineage": asset["source"]["concept_lineage"]})
            save_manifest(root / pipeline["manifest"], manifest)
            begin_stage(stage)
            _persist_reload(root, pipeline, manifest)
            asset = manifest["assets"][key]
            print("3D stage: background removal and isolated reconstruction input...", flush=True)
            subprocess.run([python, str(tool_root() / "processing/prepare_3d_input.py"), "--input", str(paths["concept"]),
                            "--cutout", str(paths["cutout"]), "--output", str(paths["input_3d"])], check=True)
            cutout_check = validate_image(paths["cutout"], expected_format="PNG", require_alpha=True, report_path=paths["cutout"].relative_to(root))
            input_check = validate_image(paths["input_3d"], expected_format="PNG", report_path=paths["input_3d"].relative_to(root))
            if cutout_check["status"] == "failed" or input_check["status"] == "failed":
                raise ValueError(f"Prepared concept validation failed: {cutout_check['errors'] + input_check['errors']}")
            conditioning_refs = [_artifact_ref(root, paths["cutout"], f"cutout:{execution['id']}",
                                             "image.cutout", "conditioning_preparation", 1, [selected_artifact]),
                                 _artifact_ref(root, paths["input_3d"], f"3d-input:{execution['id']}",
                                             "image.3d_input", "conditioning_preparation", 1, [selected_artifact])]
            if view_slots:
                print("3D stage: generating object views for multi-view conditioning...", flush=True)
                view_refs, view_attempts = _generate_views(
                    root, config, python, paths["concept"],
                    root / pipeline["candidate_root"] / asset_type["name"] / asset["name"] / f"views_{execution['id']}",
                    view_slots, conditioning_settings["views"], execution["id"], selected_artifact)
                conditioning_refs += view_refs
            if asset.get("parts"):
                print("3D stage: masking the declared parts on the concept...", flush=True)
                parts_dir = (root / pipeline["candidate_root"] / asset_type["name"] / asset["name"] /
                             f"parts_{execution['id']}")
                make_part_masks(config, paths["cutout"], asset["parts"], parts_dir)
                cutout_ref = next(item for item in conditioning_refs if item["type"] == "image.cutout")
                conditioning_refs += [
                    _artifact_ref(root, parts_dir / f"{part['name']}.png", f"part-mask-{part['name']}:{execution['id']}",
                                  "image.part_mask", "conditioning_preparation", 1, [cutout_ref])
                    for part in asset["parts"] if (parts_dir / f"{part['name']}.png").is_file()]
                conditioning_refs += [
                    _artifact_ref(root, parts_dir / "masks.json", f"part-masks:{execution['id']}", "data.part_masks",
                                  "conditioning_preparation", 1, [cutout_ref]),
                    _artifact_ref(root, parts_dir / "parts_overlay.png", f"part-overlay:{execution['id']}",
                                  "image.part_overlay", "conditioning_preparation", 1, [cutout_ref])]
            if open_artifact:
                print("3D stage: cutting out and masking the open picture...", flush=True)
                conditioning_refs += prepare_open_conditioning(
                    root, config, python, root / open_artifact["path"], paths["cutout"].parent, asset["parts"],
                    execution["id"], open_artifact, _artifact_ref)
            _, conditioning_stage = _execution_stage(asset, execution["id"], "conditioning_preparation", 1,
                                                      stage_id=stage["id"])
            if view_slots:
                conditioning_stage["provenance"]["view_attempts"] = view_attempts
            # BiRefNet's cut-outs, the views' graph (as its worker recorded it) and the part masks
            conditioning_stage["provenance"]["output_rights"] = (
                rights_of(config, "background_removal")
                + _recorded_rights([root / Path(item["path"]).with_suffix(".json") for item in conditioning_refs
                                    if item["type"].startswith("image.view_raw.")])
                + (rights_of(config, "part_masks") if asset.get("parts") else []))
            finish_stage(conditioning_stage, "succeeded", conditioning_refs)
            _persist_reload(root, pipeline, manifest)
        else:
            paths["cutout"] = root / next(item["path"] for item in conditioning_refs if item["type"] == "image.cutout")
            paths["input_3d"] = root / next(item["path"] for item in conditioning_refs if item["type"] == "image.3d_input")
        asset = manifest["assets"][key]
        conditioning_id = next((item.get("id") for item in execution["stages"]
                                if item["name"] == "conditioning_preparation" and item["attempt"] == 1), None)
        execution, conditioning_stage = _execution_stage(
            asset, execution["id"], "conditioning_preparation", 1, stage_id=conditioning_id)

        workflow = pipeline["workflows"].get("model")
        if workflow:  # declared emitters only drive the mesh-aware material stage
            check_emitters_in_concept(asset.get("materials"), paths["cutout"])
        if asset.get("parts"):  # a part missing from the concept would be missing from every mesh
            masks_ref = next(item for item in conditioning_refs if item["type"] == "data.part_masks")
            paths["part_masks"] = (root / masks_ref["path"]).parent
            check_part_masks(json.loads((root / masks_ref["path"]).read_text()), asset["parts"])
        # the mesh and its split come from the open picture when one is approved; the final pass still compares
        # with the closed concept (paths["cutout"], paths["part_masks"])
        mesh_paths = (open_paths(root, conditioning_refs, asset["parts"]) if open_artifact else
                      {"cutout": paths["cutout"], "input_3d": paths["input_3d"], "part_masks": paths.get("part_masks")})
        # generated with its part half open, faces the part shades are not hidden in play (OPEN3: the inside showed
        # holes where the removal had deleted them, 2026-10-26)
        removes_hidden = _removes_hidden_faces(asset_type, asset) and not open_artifact
        if asset.get("kit_material"):
            if not workflow:
                raise StageFailure("configuration", "A kit material is applied by the mesh-aware material stage",
                                   operation="kit_material_preflight",
                                   remedy="configure asset_pipeline.workflows.model (the h100 profiles set it)")
            kit_texture(root, manifest, asset)  # an unapproved kit texture stops here, before mesh inference
        print("3D stage: mesh and PBR generation..." if workflow else "3D stage: Hunyuan3D mesh generation...", flush=True)
        material_candidates = []
        viable = []
        attempt_errors = []
        failed_fast = False
        attempt_reports = asset.setdefault("model_attempts", [])
        next_attempt = (min(stage["attempt"] for stage in prior["stages"]
                            if stage["name"] == "mesh_workflow_execution")
                        if prior and any(stage["name"] == "mesh_workflow_execution" for stage in prior["stages"])
                        else max((int(item.get("number", 0)) for item in attempt_reports), default=0) + 1)
        next_material = max((int(item["number"]) for item in asset.get("material_candidates", {}).get("items", [])), default=0) + 1
        fresh_mesh_attempt = max(
            [int(item.get("number", 0)) for item in attempt_reports] +
            [stage["attempt"] for stage in (prior or {}).get("stages", []) if stage["name"] == "mesh_workflow_execution"],
            default=0) + 1
        if prior:
            prior_seeds = [stage.get("settings", {}).get("seed") for stage in prior["stages"]
                           if stage.get("name") == "mesh_workflow_execution" and stage.get("status") == "succeeded"]
            resume_offsets = []
            for seed in reversed(prior_seeds):
                offset = next((index for index, value in enumerate(mesh_seeds) if value == seed), None)
                if offset is not None and offset not in resume_offsets:
                    resume_offsets.append(offset)
            attempt_plan = [(next((stage["attempt"] for stage in reversed(prior["stages"])
                                  if stage.get("name") == "mesh_workflow_execution" and
                                  stage.get("status") == "succeeded" and
                                  stage.get("settings", {}).get("seed") == mesh_seeds[offset]), None), offset)
                            for offset in resume_offsets]
            attempt_plan.extend((None, offset) for offset in range(attempts) if offset not in resume_offsets)
        else:
            attempt_plan = [(next_attempt + offset, offset) for offset in range(attempts)]
        fresh_attempt_offset = 0
        budget_used = 0
        accounting_execution_id = execution["id"]  # the parent chain reaches the prior run
        for planned_attempt, offset in attempt_plan:
            attempt_number = planned_attempt if planned_attempt is not None else fresh_mesh_attempt + fresh_attempt_offset
            mesh_seed = mesh_seeds[offset]
            conditioning_refs = conditioning_stage["outputs"]
            mesh_inputs = [candidate_artifact, *conditioning_refs]
            mesh_quality = copy.deepcopy(execution["identity_inputs"]["quality"])
            mesh_quality.get("settings", {}).get("workflow_inputs", {}).pop("image", None)
            if not mesh_quality.get("settings", {}).get("workflow_inputs"):
                mesh_quality.get("settings", {}).pop("workflow_inputs", None)
            mesh_settings = {"seed": mesh_seed, "workflow": workflow or "hunyuan3d_image_to_model_api",
                             "workflow_identity": execution["identity_inputs"]["workflows"]["model"],
                             "quality": mesh_quality,
                             "face_budget": _face_budget(pipeline, asset_type, asset, default=None),
                             "voxel_resolution": asset_type.get("voxel_resolution"),
                             "checkpoint": pipeline.get("tools", {}).get("hunyuan_checkpoint")}
            if removes_hidden:  # only when set: existing assets keep their settings
                mesh_settings["remove_hidden_faces"] = True
                # prepare_model.py removes them in the mesh stage with mesh_cleanup.py (tool_sha256 covers both)
                mesh_settings["preparation_tool_sha256"] = tool_sha256(tool_root() / "blender/prepare_model.py")
            if part_backend(asset_type, asset):
                # Only on the part route: a None here would change every existing asset's mesh settings (review
                # 2026-10-25). A change of the part tools invalidates the stage.
                mesh_settings["part_model"] = part_backend(asset_type, asset)
                mesh_settings["part_tools_sha256"] = {
                    "part_model.py": tool_sha256(tool_root() / "processing/part_model.py"),
                    **({"hybrid_graph.py": tool_sha256(tool_root() / "blender/hybrid_graph.py"),
                        "hybrid_apply.py": tool_sha256(tool_root() / "blender/hybrid_apply.py"),
                        "part_split.py": file_sha256(tool_root() / "slopforge/part_split.py"),
                        "hybrid.py": file_sha256(tool_root() / "slopforge/backends/hybrid.py")}
                       if part_backend(asset_type, asset) == "hybrid" else
                       {"prepare_parts.py": tool_sha256(tool_root() / "blender/prepare_parts.py")})}
                mesh_settings["part_sampler"] = _part_sampler(asset_type)
            if open_artifact:  # the open part is closed in this stage (blender/close_part.py) within the bound
                mesh_settings["open_state"] = {"part": hinged_part(asset)["name"], "max_stretch": MAX_OPEN_PART_STRETCH,
                                               "close_tool_sha256": tool_sha256(tool_root() / "blender/close_part.py")}
            scope_sha256 = execution_identity({
                "inputs": [{"id": item["id"], "sha256": item["sha256"]} for item in mesh_inputs],
                "settings": {key: value for key, value in mesh_settings.items() if key != "seed"},
                "seeds": mesh_seeds, "budget": attempts,
            })
            slots, quality_rejections = _mesh_slot_history(
                manifest["assets"][key], accounting_execution_id, scope_sha256, attempts)
            if offset in quality_rejections:
                rejected_stage = slots[offset]
                chain_ids = {item["id"] for item in _execution_chain(
                    manifest["assets"][key], accounting_execution_id)}
                last_failure = rejected_stage.get("failure") or next((item.get("failure")
                    for item in reversed(manifest["assets"][key].get("model_attempts", []))
                    if item.get("execution_id") in chain_ids and
                    item.get("stage_attempt") == rejected_stage.get("attempt") and item.get("failure")),
                    last_failure)
                budget_used = max(budget_used, len(slots))
                continue
            used_attempts = len(slots) + (0 if offset in slots else 1)
            budget_used = max(budget_used, used_attempts)
            attempt_dir = root / pipeline["candidate_root"] / asset_type["name"] / asset["name"] / f"mesh_{attempt_number:02d}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            source_mesh, model_metadata = attempt_dir / f"{asset['name']}.glb", attempt_dir / "generation.json"
            stage_mesh = attempt_dir / "processed_mesh.blend"
            mesh_outputs = _adopt_stage(context, "mesh_workflow_execution", attempt_number,
                                        mesh_inputs, mesh_settings)
            if mesh_outputs is None:
                if prior:
                    attempt_number = fresh_mesh_attempt + fresh_attempt_offset
                    fresh_attempt_offset += 1
                    attempt_dir = (root / pipeline["candidate_root"] / asset_type["name"] / asset["name"] /
                                   f"mesh_{attempt_number:02d}")
                    attempt_dir.mkdir(parents=True, exist_ok=True)
                    source_mesh, model_metadata = attempt_dir / f"{asset['name']}.glb", attempt_dir / "generation.json"
                    stage_mesh = attempt_dir / "processed_mesh.blend"
                asset = manifest["assets"][key]
                execution = next(item for item in asset["executions"] if item["id"] == context["execution_id"])
                mesh_stage = start_stage(execution, "mesh_workflow_execution", attempt_number,
                                         mesh_inputs, mesh_settings,
                                         {"concept_lineage": asset["source"]["concept_lineage"]})
                mesh_stage["attempt_slot"] = {"scope_sha256": scope_sha256, "seed_index": offset,
                                               "origin_execution_id": prior["id"] if prior else execution["id"]}
                save_manifest(root / pipeline["manifest"], manifest)
                begin_stage(mesh_stage)
            else:
                _, mesh_stage = _execution_stage(manifest["assets"][key], execution["id"],
                    "mesh_workflow_execution", attempt_number)
                source_mesh = root / next(item["path"] for item in mesh_outputs if item["type"] == "mesh.glb")
                model_metadata = root / next(item["path"] for item in mesh_outputs if item["type"] == "generation.metadata")
            _persist_reload(root, pipeline, manifest)
            asset = manifest["assets"][key]
            execution, mesh_stage = _execution_stage(asset, execution["id"],
                "mesh_workflow_execution", attempt_number)
            mesh_stage_id = mesh_stage["id"]
            attempt_reports = asset.setdefault("model_attempts", [])
            journal_context = {"manifest_path": str(root / pipeline["manifest"]), "asset_selector": key,
                               "execution_id": execution["id"], "attempt": attempt_number,
                               "stage_id": mesh_stage_id,
                               "upstream_artifacts": [candidate_artifact, *conditioning_refs]}
            try:
                if mesh_outputs is None:
                    config["_journal_context"] = journal_context
                    if part_backend(asset_type, asset) == "omnipart":
                        # A weapon with moving parts: generated as parts (docs/WEAPONS.md, Moving parts)
                        materials = asset.get("materials") or []
                        generate_part_model(root, config, paths["cutout"], asset["name"], source_mesh, model_metadata,
                                            mesh_seed, asset["parts"], paths["part_masks"],
                                            _reduction_budget(_face_budget(pipeline, asset_type, asset), asset, asset_type),
                                            materials, finish_word(materials),
                                            texture_size=asset.get("texture_size") or asset_type.get("texture_size")
                                            or pipeline.get("texture_size", 2048), **_part_sampler(asset_type))
                    elif workflow:
                        budget = _reduction_budget(_face_budget(pipeline, asset_type, asset), asset, asset_type)
                        views = {item["type"].removeprefix("image.view."): root / item["path"]
                                 for item in conditioning_refs if item["type"].startswith("image.view.")}
                        generate_model(root, config, mesh_paths["cutout"], asset["name"], source_mesh, model_metadata,
                                       mesh_seed, budget, voxel_resolution=asset_type.get("voxel_resolution"),
                                       require_manifold=asset_type.get("max_nonmanifold_edges") == 0,
                                       remove_hidden_faces=removes_hidden,
                                       project_concept=asset_type.get("concept_projection") == "front",
                                       **({"views": views} if views else {}))
                    else:
                        generate_model(root, config, mesh_paths["input_3d"], asset["name"], source_mesh, model_metadata,
                                       mesh_seed)
                    if part_backend(asset_type, asset) == "hybrid":
                        # The generated surface, split by OmniPart's parts (docs/WEAPONS.md, Hybrid parts)
                        generate_hybrid_parts(root, config, mesh_paths["cutout"], source_mesh, model_metadata, mesh_seed,
                                              asset["parts"], mesh_paths["part_masks"],
                                              texture_size=asset.get("texture_size") or asset_type.get("texture_size")
                                              or pipeline.get("texture_size", 2048), **_part_sampler(asset_type),
                                              **({"open_part": hinged_part(asset)} if open_artifact else {}))
                    config.pop("_journal_context", None)
                _reload_manifest(root, pipeline, manifest)
                asset = manifest["assets"][key]
                execution, mesh_stage = _execution_stage(asset, execution["id"],
                    "mesh_workflow_execution", attempt_number, stage_id=mesh_stage_id)
                attempt_reports = asset.setdefault("model_attempts", [])
                mesh_info = json.loads(model_metadata.read_text())
                missing = lambda reason: {"status": "not_recorded", "reason": reason}
                backend = mesh_info.get("backend") or {}
                facts = mesh_info.get("provenance") or {}
                if mesh_outputs is None:
                    mesh_stage["provenance"].update({
                    "backend": {name: backend.get(name, missing(f"Worker did not record backend {name}"))
                                for name in ("provider", "version", "device")},
                    "model_weights": facts.get("model_weights", missing("Worker did not record exact model weights")),
                    "custom_node_revisions": facts.get("custom_node_revisions",
                        missing("Worker did not record custom-node revisions")),
                    "model_filenames": mesh_info.get("model_filenames", missing("Worker did not record configured model filenames")),
                    "workflow_source": mesh_info.get("workflow_source", missing("Worker did not record source workflow provenance")),
                    "workflow_effective_sha256": ({"status": "known", "value": mesh_info["workflow_effective_sha256"]}
                        if mesh_info.get("workflow_effective_sha256") else
                        missing("Worker did not record the effective workflow hash")),
                    "effective_bindings": mesh_info.get("effective_bindings", missing("Worker did not record effective bindings")),
                    # the worker's record of its models (and OmniPart's, on the part routes), and Blender's reduction
                    **({"output_rights": mesh_info["output_rights"] + rights_of(config, "blender")}
                       if isinstance(mesh_info.get("output_rights"), list) else {}),
                    })
            except KeyboardInterrupt as exc:
                config.pop("_journal_context", None)
                _reload_manifest(root, pipeline, manifest)
                asset = manifest["assets"][key]
                execution, mesh_stage = _execution_stage(asset, execution["id"],
                    "mesh_workflow_execution", attempt_number, stage_id=mesh_stage_id)
                failure = failure_record(exc, stage="mesh_workflow_execution", stage_id=mesh_stage_id,
                                         attempt=attempt_number,
                                         operation="mesh_workflow_execution")
                partial = []
                if source_mesh.is_file():
                    partial.append(_artifact_ref(root, source_mesh, f"mesh:{execution['id']}:{attempt_number}",
                        "mesh.glb", "mesh_workflow_execution", attempt_number, conditioning_refs))
                if mesh_stage["status"] == "running":
                    finish_stage(mesh_stage, "failed", partial, error=str(exc) or "Interrupted",
                                 failure=failure)
                elif "failure" not in mesh_stage:
                    mesh_stage["failure"] = failure
                attempt_reports.append({"number": attempt_number, "seed": mesh_seed,
                    "source": source_mesh.relative_to(root).as_posix() if source_mesh.is_file() else None,
                    "generation": model_metadata.relative_to(root).as_posix() if model_metadata.is_file() else None,
                    "failure": failure, "status": "interrupted",
                    "execution_id": execution["id"], "stage_attempt": attempt_number})
                finish_execution(execution, "failed", failure=failure)
                asset["status"] = "failed"
                _persist_reload(root, pipeline, manifest)
                raise
            except Exception as exc:
                config.pop("_journal_context", None)
                _reload_manifest(root, pipeline, manifest)
                asset = manifest["assets"][key]
                execution, mesh_stage = _execution_stage(asset, execution["id"],
                    "mesh_workflow_execution", attempt_number, stage_id=mesh_stage_id)
                reason = f"mesh generation failed: {exc}"
                failure = failure_record(exc, stage="mesh_workflow_execution", stage_id=mesh_stage_id,
                                         attempt=attempt_number,
                                         operation=(exc.operation if isinstance(exc, StageFailure)
                                                    else "mesh_workflow_execution"))
                last_failure = failure
                attempt_errors.append(reason)
                if mesh_stage["status"] == "running":
                    partial = []
                    if source_mesh.is_file():
                        partial.append(_artifact_ref(root, source_mesh, f"mesh:{execution['id']}:{attempt_number}",
                            "mesh.glb", "mesh_workflow_execution", attempt_number, conditioning_refs))
                    finish_stage(mesh_stage, "failed", partial, error=reason, failure=failure)
                elif "failure" not in mesh_stage:
                    mesh_stage["failure"] = failure
                attempt_reports.append({"number": attempt_number,
                                        "seed": mesh_seed,
                                        "source": source_mesh.relative_to(root).as_posix() if source_mesh.is_file() else None,
                                        "generation": model_metadata.relative_to(root).as_posix() if model_metadata.is_file() else None,
                                        "failure": failure, "status": "rejected", "error": reason,
                                        "execution_id": execution["id"], "stage_attempt": attempt_number})
                can_retry = should_retry(failure, used=used_attempts, limit=attempts)
                execution.setdefault("retry_decisions", []).append({
                    "scope": "mesh", "scope_sha256": scope_sha256,
                    "stage": "mesh_workflow_execution", "stage_id": mesh_stage_id,
                    "attempt": attempt_number, "category": failure["category"],
                    "used": used_attempts, "limit": attempts,
                    "action": "next_candidate" if can_retry else
                              "exhausted" if failure["category"] == "candidate_quality" else "stop",
                    "next_seed_index": offset + 1 if can_retry and offset + 1 < len(mesh_seeds) else None,
                })
                _persist_reload(root, pipeline, manifest)
                asset = manifest["assets"][key]
                execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
                if can_retry:
                    continue
                failed_fast = failure["category"] != "candidate_quality"
                break
            if mesh_outputs is None:
                mesh_outputs = [_artifact_ref(root, source_mesh, f"mesh:{execution['id']}:{attempt_number}",
                    "mesh.glb", "mesh_workflow_execution", attempt_number, conditioning_refs)]
                if model_metadata.is_file():
                    mesh_outputs.append(_artifact_ref(root, model_metadata, f"mesh-metadata:{execution['id']}:{attempt_number}",
                        "generation.metadata", "mesh_workflow_execution", attempt_number, conditioning_refs))
            if mesh_stage["status"] == "running":
                finish_stage(mesh_stage, "succeeded", mesh_outputs)
            _persist_reload(root, pipeline, manifest)
            asset = manifest["assets"][key]
            execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
            attempt_reports = asset.setdefault("model_attempts", [])
            asset["source"].update({"cutout": paths["cutout"].relative_to(root).as_posix(),
                                    "3d_input": paths["input_3d"].relative_to(root).as_posix(),
                                    "glb": source_mesh.relative_to(root).as_posix(),
                                    "processed_mesh": stage_mesh.relative_to(root).as_posix()})
            execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
            stage_outputs = [(stage_record, artifact) for stage_record in execution["stages"]
                             for artifact in stage_record.get("outputs", [])]
            mesh_artifact = next((artifact for stage_record, artifact in reversed(stage_outputs)
                                  if artifact["type"] in {"mesh.final", "mesh.glb", "mesh.raw"}), mesh_outputs[0])
            prepared_artifact = next((artifact for stage_record, artifact in reversed(stage_outputs)
                                      if artifact["type"] == "mesh.prepared"), None)
            texture_artifacts = [artifact for stage_record, artifact in stage_outputs
                                 if stage_record["attempt"] == attempt_number
                                 and artifact["type"].startswith("texture.")]
            upstream = [candidate_artifact, mesh_artifact]
            # The part route derives its maps from the generated parts and records no texture artifacts, so its
            # material stage descends from the mesh (review 2026-10-25: it had no parents at all).
            material_inputs = texture_artifacts if mesh_info.get("textured") and texture_artifacts else upstream
            assembly_inputs = [prepared_artifact or mesh_artifact]
            lineage = {"root": root, "pipeline": pipeline, "manifest": manifest, "key": key,
                       "execution_id": execution["id"], "attempt": attempt_number,
                       "upstream": upstream, "material_inputs": material_inputs,
                           "assembly_inputs": assembly_inputs, "reuse_execution": prior,
                       "concept_cutout": paths["cutout"], "part_masks": paths.get("part_masks")}
            previous_materials = ([item for item in asset.get("material_candidates", {}).get("items", [])
                                   if item.get("execution_id") == prior["id"] and
                                   item.get("mesh_attempt") == attempt_number] if prior else [])
            if mesh_info.get("textured"):
                start = next_material
                try:
                    generated = [_native_material_candidate(root, config, context, asset_type, asset, start, mesh_info,
                                                            lineage=lineage)]
                except Exception as exc:
                    reason = f"native material processing failed: {exc}"
                    asset = manifest["assets"][key]
                    execution, _ = _execution_stage(asset, context["execution_id"],
                        "mesh_workflow_execution", attempt_number, stage_id=mesh_stage_id)
                    local_stage_ids = {*context.get("_stage_handles", {}).values(),
                                       *lineage.get("_stage_handles", {}).values()}
                    running = [stage for stage in execution.get("stages", [])
                               if stage.get("status") == "running" and stage.get("id") in local_stage_ids]
                    if running:
                        stage = running[-1]
                        failure = failure_record(exc, stage=stage["name"], stage_id=stage["id"], attempt=stage["attempt"],
                                                 operation=(exc.operation if isinstance(exc, StageFailure)
                                                            else stage["name"]))
                        finish_stage(stage, "failed", error=reason, failure=failure)
                    else:
                        failure = failure_record(exc, stage="material_generation", attempt=start,
                                                 operation=(exc.operation if isinstance(exc, StageFailure)
                                                            else "material_generation"))
                    last_failure = failure
                    attempt_errors.append(reason)
                    asset.setdefault("model_attempts", []).append({"number": attempt_number,
                        "seed": mesh_seed, "source": source_mesh.relative_to(root).as_posix(),
                        "generation": model_metadata.relative_to(root).as_posix(),
                        "failure": failure, "status": "rejected", "error": reason,
                        "execution_id": execution["id"], "stage_attempt": attempt_number})
                    _persist_reload(root, pipeline, manifest)
                    failed_fast = True
                    break
            else:
                generated = []
                for index, number in enumerate(range(next_material, next_material + material_count)):
                    item = _generate_material_candidate(
                        root, config, asset_type, asset, number, material_prompt, stage_mesh,
                        lineage={**lineage, "prior_candidate": previous_materials[index]
                                 if index < len(previous_materials) else None},
                        seed=material_seeds[offset * material_count + index])
                    generated.append(item)
                    if item.get("status") != "candidate":
                        item["failure"] = _candidate_failure(
                            item, attempt=item.get("stage_attempt", item.get("number", attempt_number)))
                        break
            asset = manifest["assets"][key]
            execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
            attempt_reports = asset.setdefault("model_attempts", [])
            next_material += len(generated)
            for item in generated:
                item["mesh_source"] = source_mesh.relative_to(root).as_posix()
                item["mesh_attempt"] = attempt_number
                item["execution_id"] = execution["id"]
                item["stage_attempt"] = item.get("stage_attempts", {}).get("material_assembly_export", item["number"])
                item["upstream_artifacts"] = [*lineage["upstream"], *texture_artifacts]
                if not item.get("artifacts"):
                    candidate_paths = material_candidate_paths(root, config, asset["name"], item["number"], asset_type)
                    item["artifacts"] = _material_artifact_refs(root, candidate_paths, execution["id"],
                                                                  item["number"], lineage["upstream"])
            material_candidates.extend(generated)
            viable = [item for item in generated if item["status"] == "candidate"]
            failure = None
            if not viable:
                failures = [_candidate_failure(item, attempt=item.get("stage_attempt", item.get("number", attempt_number)))
                            for item in generated]
                if failures:
                    failure = failures[0]
                    last_failure = failure
                    for item, candidate_failure in zip(generated, failures):
                        item["failure"] = candidate_failure
                can_retry = bool(failures) and all(
                    should_retry(item, used=used_attempts, limit=attempts) for item in failures)
                if can_retry:
                    failed_fast = False
                else:
                    failed_fast = True
            attempt_reports.append({"number": attempt_number, "source": source_mesh.relative_to(root).as_posix(),
                                    "seed": mesh_seed,
                                    "generation": model_metadata.relative_to(root).as_posix(),
                                    "source_sha256": file_sha256(source_mesh),
                                    "input_sha256": file_sha256(mesh_paths["cutout"] if workflow else mesh_paths["input_3d"]),
                                    "status": "qualified" if viable else "rejected",
                                    "failure": failure,
                                    "execution_id": execution["id"], "stage_attempt": attempt_number,
                                    "materials": [{"number": item["number"], "status": item["status"],
                                                   "validation": item.get("validation")} for item in generated]})
            if failure:
                execution.setdefault("retry_decisions", []).append({
                    "scope": "mesh", "scope_sha256": scope_sha256,
                    "stage": "mesh_workflow_execution", "stage_id": mesh_stage_id,
                    "attempt": attempt_number, "category": failure["category"],
                    "used": used_attempts, "limit": attempts,
                    "action": "next_candidate" if can_retry else
                              "exhausted" if failure["category"] == "candidate_quality" else "stop",
                    "next_seed_index": offset + 1 if can_retry and offset + 1 < len(mesh_seeds) else None,
                })
            _persist_reload(root, pipeline, manifest)
            asset = manifest["assets"][key]
            execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
            attempt_reports = asset.setdefault("model_attempts", [])
            if viable:
                break
            if failed_fast:
                break
        previous = asset.get("material_candidates", {}).get("items", [])
        asset["material_candidates"] = {"items": previous + material_candidates, "selected": None}
        if not viable:
            # Keep the failed candidates: the error handler reloads the manifest from disk.
            _persist_reload(root, pipeline, manifest)
            asset = manifest["assets"][key]
            failures = [error for item in material_candidates for error in item.get("validation", {}).get("errors", [])]
            attempted = max(budget_used, sum(item.get("execution_id") == execution["id"]
                                             for item in attempt_reports))
            last_failure = last_failure or failure_record(
                RuntimeError("Candidate processing failed without a structured report"),
                stage="material_generation", attempt=max(attempted, 1), operation="model_approval")
            retry_state = "yes" if last_failure["retryable"] else "no"
            details = "; ".join(attempt_errors + failures) or last_failure["message"]
            message = last_failure["message"].removesuffix(f" — remedy: {last_failure['remedy']}")  # said once, last
            raise ValueError(
                f"No qualified model after {attempted} attempts "
                f"(stage={last_failure['stage']}, category={last_failure['category']}, "
                f"retryable={retry_state}, retry_budget={attempts}): "
                f"message={message}; {details}; remedy: {last_failure['remedy']}")
        first = viable[0]
        asset["conditioning"] = {"strategy": conditioning["strategy"], "references_used": conditioning["references"]}
        asset["generator"] = {"workflow": {"concept": concept_workflow, "mesh": mesh_info.get("workflow"),
                                             "material": (first.get("generator") or {}).get("workflow")},
                               "model": mesh_info.get("model"),
                               "seed": {"concept": candidate.get("seed"), "mesh": mesh_info.get("seed")},
                               "quality": mesh_info.get("quality") or (candidate.get("generator") or {}).get("quality"),
                               "model_attempts": attempt_reports}
        asset["material_prompt"] = first["prompt"]
        asset["validation"] = {"status": "not_run", "errors": [], "warnings": [
            "Choose a material candidate and approve it before using the Unity output."], "measured": {}}
        asset["status"] = "awaiting_texture_approval"
        asset["updated_at"] = datetime.now(timezone.utc).isoformat()
        execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
        finish_execution(execution, "succeeded")
        save_manifest(root / pipeline["manifest"], manifest)
        print("Material candidate previews:")
        for item in material_candidates:
            print(f"  {item['number']}: {item.get('outputs', {}).get('preview_front', item['path'])} ({item['status']})")
        return {"status": asset["status"], "material_candidates": material_candidates}
    except (Exception, KeyboardInterrupt) as exc:
        _reload_manifest(root, pipeline, manifest)
        asset = manifest["assets"][key]
        execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
        for stage in execution.get("stages", []):
            if stage["status"] == "running":
                failure = last_failure or failure_record(
                    exc, stage=stage["name"], stage_id=stage.get("id"),
                    attempt=stage["attempt"],
                    operation=exc.operation if isinstance(exc, StageFailure) else stage["name"])
                finish_stage(stage, "failed", error=str(exc) or type(exc).__name__, failure=failure)
                last_failure = last_failure or failure
        execution_failure = execution.get("failure") or next(
            (stage.get("failure") for stage in execution.get("stages", [])
             if stage.get("status") == "failed" and stage.get("failure")), last_failure)
        if execution.get("status") in {"running", "failed"}:
            execution_failure = execution_failure or failure_record(
                exc, stage="model_approval", attempt=None,
                operation=exc.operation if isinstance(exc, StageFailure) else "model_approval")
            _record_blocked_stages(execution, pipeline, execution_failure)
            if execution.get("status") == "running":
                finish_execution(execution, "failed", failure=execution_failure)
        asset["status"] = "failed"
        validation = asset.setdefault("validation", {})
        validation["status"] = "failed"
        validation.setdefault("errors", []).append(f"Pipeline stopped: {exc}")
        validation.setdefault("warnings", [])
        validation.setdefault("measured", {})
        save_manifest(root / pipeline["manifest"], manifest)
        raise
