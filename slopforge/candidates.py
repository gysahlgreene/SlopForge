import json
import os
import secrets
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .manifest import (add_candidate, find_asset, start_execution, start_stage, begin_stage,
                       finish_stage, finish_execution)
from .manifest import save_manifest
from .provenance import generator_provenance, file_sha256
from .style import style_identity
from .taxonomy import output_path
from .validation import validate_image
from .failures import StageFailure, failure_record


def _record_downstream_not_run(execution, failure):
    names = ("conditioning_preparation", "mesh_workflow_execution", "material_generation",
             "material_map_acquisition", "material_assembly_export", "final_publication")
    execution["blocked_stages"] = [
        {"name": name, "attempt": None, "outcome": "not_run",
         "caused_by": {"stage": failure["stage"], "stage_id": failure.get("stage_id"),
                       "attempt": failure.get("attempt"), "category": failure["category"]},
         "reason": f"Not run because {failure['stage']} failed."}
        for name in names
    ]


def reject_candidate(manifest, asset_selector, number, reason=None):
    asset = find_asset(manifest, asset_selector)
    candidate = next((item for item in asset.get("candidates", {}).get("items", [])
                      if item.get("number") == number), None)
    if candidate is None or candidate.get("status") != "candidate":
        raise ValueError(f"Candidate {number} is not available to reject for {asset.get('name')}")
    if asset.get("candidates", {}).get("selected") == number or candidate.get("approval") == "approved":
        raise ValueError("Cannot reject an approved candidate")
    candidate["status"] = "rejected"
    candidate["review"] = {"status": "rejected", "at": datetime.now(timezone.utc).isoformat()}
    if reason:
        candidate["review"]["reason"] = reason
    return candidate


def generate_candidates(project_root, config, asset_type, style, name, description, count, manifest, key, backend_generate,
                        *, semantic_description=None, variations=None, identity_inputs=None):
    root = Path(project_root).resolve()
    final_path = output_path(root, config, asset_type, name)
    candidate_dir = root / config["asset_pipeline"]["candidate_root"] / asset_type["name"] / name
    existing = manifest["assets"][key].setdefault("candidates", {"items": [], "selected": None})["items"]
    if variations is not None and len(variations) != count:
        raise ValueError("Candidate count must match the number of deliberate variations")
    start = max((int(item["number"]) for item in existing), default=0) + 1
    asset = manifest["assets"][key]
    seeds = [secrets.randbits(32) for _ in range(count)]
    execution = None
    # Every 3D type's concepts get lineage, so recipe resume can prove an approved module's concepts unchanged.
    if identity_inputs is not None:
        basis = dict(identity_inputs)
        basis["candidate_attempts"] = [{"seed": seeds[index],
                                        "variation": variations[index] if variations is not None else None}
                                       for index in range(count)]
        execution = start_execution(asset, basis)
        save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
    results = []
    for offset, number in enumerate(range(start, start + count)):
        candidate_path = candidate_dir / f"candidate_{number:02d}.png"
        metadata_path = candidate_dir / f"candidate_{number:02d}.json"
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        seed = seeds[offset]
        variation = variations[len(results)] if variations is not None else None
        prompt = description
        if variation:
            prompt += "\nDESIGN VARIATION:\n" + "\n".join(f"- {key}: {value}" for key, value in variation.items())
        record = {"number": number, "path": candidate_path.relative_to(root).as_posix(), "prompt": prompt, "status": "failed", "seed": seed, "validation": {"status": "not_run", "errors": [], "warnings": [], "measured": {}}}
        if variation is not None:
            record["variation"] = dict(variation)
        record["description"] = description if semantic_description is None else semantic_description
        record["style"] = style_identity(style)
        stage = None
        failure = None
        interrupted = None
        if execution:
            stage = start_stage(execution, "concept_generation", number, [],
                                {"prompt": prompt, "variation": variation, "seed": seed}, {})
            save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
            begin_stage(stage)
            save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
        try:
            print(f"Generating {name} candidate {number} ({len(results) + 1}/{count})...", flush=True)
            backend_generate(prompt, candidate_path, seed, metadata_path)
            record["validation"] = validate_image(candidate_path, expected_format=asset_type.get("format", "PNG"), require_alpha=bool(asset_type.get("alpha_required", False)), report_path=candidate_path.relative_to(root))
            record["status"] = "candidate" if record["validation"]["status"] != "failed" else "failed"
            if record["status"] == "failed":
                failure = failure_record(StageFailure(
                    "processing_validation", "Concept image failed validation",
                    operation="validate_image", remedy="inspect the image validation report and correct the input",
                    stage="concept_generation", stage_id=stage.get("id") if stage else None,
                    evidence={"validation": record["validation"]}),
                    stage="concept_generation", stage_id=stage.get("id") if stage else None,
                    attempt=number, operation="validate_image")
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text())
                record["generator"] = generator_provenance(metadata.get("workflow"), metadata)
                asset = manifest["assets"][key]
                asset["generator"] = generator_provenance(metadata.get("workflow"), metadata)
            if execution and candidate_path.is_file() and not record.get("error"):
                artifact = {"id": f"concept-candidate:{number}", "type": "image.concept",
                            "path": candidate_path.relative_to(root).as_posix(), "sha256": file_sha256(candidate_path),
                            "stage": "concept_generation", "attempt": number, "derived_from": []}
                record.update({"execution_id": execution["id"], "stage_attempt": number, "artifact": artifact})
                if failure:
                    finish_stage(stage, "failed", [artifact], error="Concept image failed validation",
                                 failure=failure)
                else:
                    finish_stage(stage, "succeeded", [artifact])
            elif stage and stage["status"] == "running":
                finish_stage(stage, "failed", error=record.get("error", "Concept image generation failed"),
                             outputs=([{"id": f"concept-candidate:{number}", "type": "image.concept",
                                "path": candidate_path.relative_to(root).as_posix(),
                                "sha256": file_sha256(candidate_path), "stage": "concept_generation",
                                "attempt": number, "derived_from": []}] if candidate_path.is_file() else []),
                             failure=failure)
        except (Exception, KeyboardInterrupt) as exc:
            record["error"] = str(exc)
            record["validation"]["errors"].append(str(exc))
            failure = failure_record(exc, stage="concept_generation",
                stage_id=stage.get("id") if stage else None, attempt=number,
                operation=exc.operation if isinstance(exc, StageFailure) else "concept_generation")
            record["failure"] = failure
            if isinstance(exc, KeyboardInterrupt):
                interrupted = exc
            if stage and stage["status"] == "running":
                outputs = ([{"id": f"concept-candidate:{number}", "type": "image.concept",
                    "path": candidate_path.relative_to(root).as_posix(), "sha256": file_sha256(candidate_path),
                    "stage": "concept_generation", "attempt": number, "derived_from": []}]
                    if candidate_path.is_file() else [])
                finish_stage(stage, "failed", outputs, error=record["error"] or type(exc).__name__,
                             failure=failure)
        if failure:
            record["failure"] = failure
        add_candidate(manifest, key, record)
        results.append(record)
        # Persist each candidate so an interrupted run keeps the ones already generated.
        save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
        if interrupted:
            if execution:
                _record_downstream_not_run(execution, failure)
                finish_execution(execution, "failed", failure=failure)
                save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
            raise interrupted
        if failure:
            break
    asset = manifest["assets"][key]
    if final_path is not None:
        asset.setdefault("outputs", {})["final_path"] = final_path.relative_to(root).as_posix()
    if not any(item["status"] == "candidate" for item in results):
        asset["status"] = "failed"
        if execution:
            failure = next((item.get("failure") for item in results if item.get("failure")),
                           failure_record(RuntimeError("No valid candidates were generated"),
                                          stage="concept_generation", attempt=1,
                                          operation="candidate_generation"))
            _record_downstream_not_run(execution, failure)
            finish_execution(execution, "failed", failure=failure)
            save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
        raise RuntimeError(f"No valid candidates generated for {name}; see manifest candidate errors")
    if execution:
        finish_execution(execution, "succeeded")
        asset.pop("last_failure", None)
        save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
    return results


def approve_image_candidate(project_root, config, asset_type, manifest, key, number, force=False):
    root = Path(project_root).resolve()
    asset = manifest["assets"][key]
    candidate = next((item for item in asset.get("candidates", {}).get("items", []) if item["number"] == number), None)
    if candidate is None or candidate.get("status") != "candidate":
        raise ValueError(f"Candidate {number} is not a valid candidate for {asset['name']}")
    source = root / candidate["path"]
    destination = output_path(root, config, asset_type, asset["name"])
    if destination.exists() and not (force or config["asset_pipeline"].get("overwrite_existing")):
        raise FileExistsError(f"Output exists; pass --force to replace: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copy2(source, temporary)
        result = validate_image(temporary, expected_format=asset_type.get("format", "PNG"), require_alpha=bool(asset_type.get("alpha_required", False)), report_path=destination.relative_to(root))
        if result["status"] == "failed":
            raise ValueError("Candidate validation failed: " + "; ".join(result["errors"]))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    if asset_type.get("alpha_recommended") and not result["measured"].get("has_alpha", False):
        result["warnings"].append("alpha channel is recommended for this asset type")
        if result["status"] == "passed":
            result["status"] = "passed_with_warnings"
    candidate["approval"] = "approved"
    asset["candidates"]["selected"] = number
    asset["generator"] = dict(candidate.get("generator") or generator_provenance(None, {"seed": candidate.get("seed")}))
    asset["description"] = candidate.get("description", asset["description"])
    if candidate.get("style"):
        asset["style"] = candidate["style"]["name"]
        asset["style_version"] = candidate["style"]["version"]
    asset["outputs"]["image"] = destination.relative_to(root).as_posix()
    asset["validation"] = result
    asset["status"] = "ready" if result["status"] != "failed" else "failed"
    return result
