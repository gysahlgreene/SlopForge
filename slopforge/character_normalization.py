"""Create reviewable normalized character geometry and baked materials."""

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .character_readiness import _character_asset, _project_file, _sha256_file, readiness_allows_rigging
from .manifest import register_artifact, set_artifact_approval
from .paths import blender_executable, tool_root


def _require_successful_report(report, directory):
    if not isinstance(report, dict):
        raise ValueError("Normalization report must be an object")
    channels = report.get("channels")
    components = report.get("components")
    if (report.get("status") != "pass" or report.get("uv_status") != "pass"
            or not isinstance(channels, dict)
            or set(channels) != {"base_color", "roughness", "metallic", "normal"}
            or channels["base_color"] != "baked"
            or any(value not in {"baked", "absent"} for value in channels.values())
            or not isinstance(components, list) or not components):
        raise ValueError("Normalization report has failed or incomplete geometry, components, or texture channels")
    referenced = {channel: 0 for channel in channels}
    for part in components:
        if (not isinstance(part, dict)
                or any(not isinstance(part.get(key), str) or not part[key]
                       for key in ("source", "output"))
                or any(type(part.get(key)) is not int or part[key] <= 0
                       for key in ("source_vertices", "source_faces", "output_vertices", "output_faces"))):
            raise ValueError("Normalization component has incomplete geometry counts")
        materials = part.get("source_materials")
        assignments = part.get("source_material_assignments")
        if (not isinstance(materials, list) or not isinstance(assignments, list) or not assignments
                or any(not isinstance(item, dict) or type(item.get("slot")) is not int
                       or item["slot"] < 0 or type(item.get("face_count")) is not int
                       or item["face_count"] <= 0 or (materials and item["slot"] >= len(materials))
                       or item.get("material") != (materials[item["slot"]] if materials else None)
                       for item in assignments)
                or len({item["slot"] for item in assignments}) != len(assignments)
                or sum(item["face_count"] for item in assignments) != part["source_faces"]):
            raise ValueError("Normalization component has invalid source material assignments")
        textures = part.get("textures")
        if not isinstance(textures, dict) or "base_color" not in textures or set(textures) - set(channels):
            raise ValueError("Normalization component has incomplete texture references")
        for channel, name in textures.items():
            if (not isinstance(name, str) or not name or name in {".", ".."}
                    or Path(name).name != name or "\\" in name):
                raise ValueError("Normalization texture must be a filename in the candidate directory")
            texture = (directory / name).resolve()
            if not texture.is_relative_to(directory.resolve()) or not texture.is_file() or not texture.stat().st_size:
                raise ValueError(f"Normalization texture is missing or empty: {name}")
            referenced[channel] += 1
    if any((status == "baked") != (referenced[channel] > 0) for channel, status in channels.items()):
        raise ValueError("Normalization channel statuses do not match component textures")


def normalize_character(project_root, config, manifest, character_selector, *, source_output="model"):
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)
    artifact = character.get("artifacts", {}).get(source_output)
    if (not artifact or artifact.get("status") != "ready"
            or artifact.get("approval", {}).get("status") != "approved"):
        raise ValueError("Normalization requires a ready approved source model")
    if artifact.get("type") not in {"model.glb", "model.fbx"}:
        raise ValueError("Normalization source must be a GLB or FBX model")
    if not readiness_allows_rigging(character.get("animation_readiness")):
        raise ValueError("Normalization requires an approved character-readiness report")
    if "normalized_model" in character.get("artifacts", {}):
        raise FileExistsError("A normalized model candidate is already recorded")
    _, source = _project_file(root, artifact.get("path"), "Normalization source")
    if not source.is_file() or not source.stat().st_size:
        raise FileNotFoundError(f"Normalization source is missing or empty: {artifact.get('path')}")
    source_hash = _sha256_file(source)
    readiness = character["animation_readiness"]
    if (readiness.get("source_output") != source_output
            or readiness.get("source") != {"artifact_id": artifact.get("id"),
                                           "path": artifact["path"], "sha256": source_hash}):
        raise ValueError("Approved character readiness does not match the selected source model")
    output_root, _ = _project_file(root, config["asset_pipeline"]["output_root"], "Output root")
    relative = Path(output_root) / "Characters" / character["name"] / "Normalization"
    _, directory = _project_file(root, relative.as_posix(), "Normalization output")
    output = directory / "model.glb"
    report_path = directory / "report.json"
    if directory.exists() and any(directory.iterdir()):
        raise FileExistsError(f"Normalization candidate directory already contains files: {directory}")
    existed = directory.exists()
    previous_files = set(directory.iterdir()) if existed else set()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as scratch:
            raw_report = Path(scratch) / "blender-report.json"
            request = Path(scratch) / "request.json"
            request.write_text(json.dumps({"source": str(source), "output": str(output),
                                           "report": str(raw_report),
                                           "face_budget": config["asset_pipeline"].get("model_budgets", {}).get("character_faces", 60000)}))
            subprocess.run([blender_executable(config, root), "--background", "--factory-startup",
                            "--python", str(tool_root() / "blender/normalize_character.py"),
                            "--", str(request)], check=True)
            if not output.is_file() or not output.stat().st_size or not raw_report.is_file():
                raise RuntimeError("Blender did not create a normalized model and report")
            report = json.loads(raw_report.read_text())
        _require_successful_report(report, directory)
        report.update({"source": {"artifact_id": artifact.get("id"), "path": artifact["path"], "sha256": source_hash},
                       "normalized": {"path": output.relative_to(root).as_posix(), "sha256": _sha256_file(output)},
                       "report_path": report_path.relative_to(root).as_posix(),
                       "approval": {"status": "pending"}})
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        register_artifact(manifest, character["id"], "normalized_model", "model.glb",
                          output.relative_to(root).as_posix(), status="candidate",
                          derived_from=[{"asset_id": character["id"], "output_id": source_output}],
                          provenance={"source_sha256": source_hash, "normalized_sha256": report["normalized"]["sha256"],
                                      "report_path": report["report_path"]}, approval_status="pending")
        character["normalization"] = report
        character.setdefault("pipeline_status", {})["normalization_status"] = "pending_review"
        return report
    except Exception:
        for candidate in directory.iterdir():
            if candidate not in previous_files and candidate.is_file():
                candidate.unlink()
        if not existed:
            directory.rmdir()
        raise


def approve_character_normalization(project_root, manifest, character_selector, *, approved_by=None):
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)
    result = character.get("normalization")
    if not isinstance(result, dict) or "normalized_model" not in character.get("artifacts", {}):
        raise ValueError("Run character normalization before approving it")
    _, report_path = _project_file(root, result.get("report_path"), "Normalization report")
    if not report_path.is_file():
        raise FileNotFoundError(f"Normalization report is missing: {report_path}")
    report = json.loads(report_path.read_text())
    _require_successful_report(report, report_path.parent)
    artifact = character["artifacts"]["normalized_model"]
    _, output = _project_file(root, artifact.get("path"), "Normalized model")
    if not output.is_file() or _sha256_file(output) != report.get("normalized", {}).get("sha256"):
        raise ValueError("Normalized model is missing or changed")
    approval = set_artifact_approval(manifest, character["id"], "normalized_model", "approved", approved_by=approved_by)
    artifact["status"] = "ready"
    result["approval"] = approval
    result["approved_at"] = datetime.now(timezone.utc).isoformat()
    report["approval"] = approval
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    character.setdefault("pipeline_status", {})["normalization_status"] = "approved"
    return result
