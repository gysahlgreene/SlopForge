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
    if asset_type.get("name") == "prop":
        basis = dict(identity_inputs or {})
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
                finish_stage(stage, "succeeded", [artifact])
            elif stage:
                finish_stage(stage, "failed", error=record.get("error", "Concept image generation failed"))
        except Exception as exc:
            record["error"] = str(exc)
            record["validation"]["errors"].append(str(exc))
            if stage and stage["status"] == "running":
                finish_stage(stage, "failed", error=record["error"])
        add_candidate(manifest, key, record)
        results.append(record)
        if execution:
            save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
    asset = manifest["assets"][key]
    if final_path is not None:
        asset.setdefault("outputs", {})["final_path"] = final_path.relative_to(root).as_posix()
    if not any(item["status"] == "candidate" for item in results):
        asset["status"] = "failed"
        if execution:
            finish_execution(execution, "failed")
            save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
        raise RuntimeError(f"No valid candidates generated for {name}; see manifest candidate errors")
    if execution:
        finish_execution(execution, "succeeded")
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
