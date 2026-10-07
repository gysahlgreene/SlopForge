"""Deterministic mesh checks that gate character rigging, not deformation quality."""
import hashlib
import json
import math
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .paths import blender_executable, tool_root


def _character_asset(manifest, selector):
    character = manifest.get("assets", {}).get(selector)
    if character is None:
        matches = [asset for asset in manifest.get("assets", {}).values()
                   if asset.get("id") == selector or asset.get("name") == selector]
        if len(matches) != 1:
            raise KeyError(f"No unique character asset named {selector!r}")
        character = matches[0]
    if character.get("type") != "character":
        raise ValueError("Animation readiness can only be recorded on a character asset")
    return character


def _project_file(root, relative, label):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError(f"{label} must be a project-relative path")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or (path.parts and path.parts[0].endswith(":")):
        raise ValueError(f"{label} must be a project-relative path")
    resolved = (root / Path(*path.parts)).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} must stay inside the project")
    return path.as_posix(), resolved


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def classify_character_readiness(mesh_report):
    measured = mesh_report.get("measured", {}) if isinstance(mesh_report, dict) else {}
    if not isinstance(measured, dict):
        measured = {}
    reasons = []
    hard_failures = []

    required = {
        "mesh_objects", "vertex_count", "face_count", "dimensions", "transforms_applied",
        "component_count", "boundary_edge_count", "nonmanifold_edge_count", "degenerate_face_count",
        "zero_normal_count", "face_budget", "uv_layers", "mesh_without_uv_count", "material_count",
        "mesh_without_material_count", "image_texture_count", "mesh_without_texture_count",
        "missing_textures", "coordinate_system",
        "rest_pose_status", "auxiliary_objects",
    }
    if required - measured.keys():
        hard_failures.append("material and UV measurements are incomplete" if required - measured.keys()
                             <= {"uv_layers", "mesh_without_uv_count", "material_count",
                                 "mesh_without_material_count", "image_texture_count", "mesh_without_texture_count",
                                 "missing_textures"}
                             else "geometry, coordinate, or review measurements are incomplete")
    for key in ("mesh_objects", "vertex_count", "face_count", "component_count", "boundary_edge_count",
                "nonmanifold_edge_count", "degenerate_face_count", "zero_normal_count", "uv_layers",
                "mesh_without_uv_count", "material_count", "mesh_without_material_count", "image_texture_count",
                "mesh_without_texture_count"):
        value = measured.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            hard_failures.append(f"{key} is missing or invalid")
    face_budget = measured.get("face_budget")
    if not isinstance(face_budget, int) or isinstance(face_budget, bool) or face_budget < 1:
        hard_failures.append("face budget is missing or invalid")
    if not isinstance(measured.get("transforms_applied"), bool):
        hard_failures.append("transform status is missing or invalid")
    if not isinstance(measured.get("missing_textures"), list):
        hard_failures.append("missing texture report is incomplete")
    coordinate = measured.get("coordinate_system")
    if (not isinstance(coordinate, dict)
            or coordinate.get("unit_system") not in ("NONE", "METRIC", "IMPERIAL")
            or not _finite_number(coordinate.get("scale_length"))
            or coordinate.get("scale_length", 0) <= 0
            or coordinate.get("up_axis") not in ("X", "Y", "Z")
            or coordinate.get("forward_axis") not in ("-X", "+X", "-Y", "+Y", "-Z", "+Z")
            or coordinate["up_axis"] == coordinate["forward_axis"][-1]
            or coordinate.get("basis") != "Blender world"
            or coordinate.get("measured_unit") != "Blender units"):
        hard_failures.append("coordinate system or units are missing or invalid")
    if measured.get("rest_pose_status") not in ("visual_review_required", "reviewed"):
        hard_failures.append("rest-pose status is missing or invalid")
    auxiliary = measured.get("auxiliary_objects")
    if (not isinstance(auxiliary, list) or any(not isinstance(obj, dict)
            or any(not isinstance(obj.get(key), str) or not obj[key].strip() for key in ("name", "type"))
            for obj in auxiliary)):
        hard_failures.append("helper-object report is incomplete")

    dimensions = measured.get("dimensions", ())
    if (not isinstance(dimensions, (list, tuple)) or len(dimensions) != 3
            or any(not _finite_number(value) or value <= 1e-5 for value in dimensions)):
        hard_failures.append("mesh bounds are degenerate or non-finite")
    if hard_failures:
        return {"status": "fail", "approval": {"status": "pending"}, "measured": measured,
                "reasons": hard_failures, "checks": {},
                "limitations": ["Missing or malformed measurements cannot establish character readiness."]}

    if measured.get("mesh_objects", 0) < 1:
        hard_failures.append("no mesh objects were imported")
    if measured.get("vertex_count", 0) < 3 or measured.get("face_count", 0) < 1:
        hard_failures.append("mesh has no usable surface geometry")
    if measured.get("degenerate_face_count", 0) > 0:
        hard_failures.append(f"{measured['degenerate_face_count']} zero-area faces")
    if measured.get("zero_normal_count", 0) > 0:
        hard_failures.append(f"{measured['zero_normal_count']} zero-length face normals")
    if measured["missing_textures"]:
        hard_failures.append(f"{len(measured['missing_textures'])} referenced texture files are missing")

    if measured.get("uv_layers", 0) < 1 or measured.get("mesh_without_uv_count", 0) > 0:
        hard_failures.append("UV coverage is incomplete")
    if measured.get("material_count", 0) < 1:
        hard_failures.append("mesh has no material")
    if measured.get("mesh_without_material_count", 0) > 0:
        hard_failures.append(f"{measured['mesh_without_material_count']} mesh objects have no assigned material")
    if measured.get("image_texture_count", 0) < 1:
        hard_failures.append("no linked image textures were found")
    if measured.get("mesh_without_texture_count", 0) > 0:
        hard_failures.append(f"{measured['mesh_without_texture_count']} mesh objects have no linked image texture")
    if measured.get("rest_pose_status") == "visual_review_required":
        reasons.append("rest pose and model orientation require human review")
    if measured.get("auxiliary_objects"):
        reasons.append("auxiliary objects require helper-policy review")

    if measured.get("boundary_edge_count", 0) > 0:
        reasons.append(f"{measured['boundary_edge_count']} boundary edges")
    if measured.get("nonmanifold_edge_count", 0) > 0:
        reasons.append(f"{measured['nonmanifold_edge_count']} non-manifold edges")
    if measured.get("component_count", 0) > measured.get("mesh_objects", 0):
        reasons.append(f"{measured['component_count']} disconnected mesh components")
    if not measured.get("transforms_applied", False):
        reasons.append("object rotation or scale is unapplied")
    if isinstance(face_budget, int) and measured.get("face_count", 0) > face_budget:
        reasons.append(f"face count exceeds configured budget {face_budget}")
    dimensions_meters = [value * coordinate["scale_length"] for value in dimensions]
    if not all(math.isfinite(value) for value in dimensions_meters):
        hard_failures.append("physical mesh bounds are non-finite")
    else:
        largest = max(dimensions_meters)
        if largest < 0.05 or largest > 5.0:
            reasons.append(f"largest dimension {largest:.4g} is outside the character scale range 0.05–5 metres")
    if coordinate["unit_system"] == "NONE":
        reasons.append("scene units are unspecified; confirm physical scale")

    status = "fail" if hard_failures else "needs_review" if reasons else "pass"
    return {
        "status": status,
        "approval": {"status": "pending"},
        "measured": measured,
        "reasons": hard_failures + reasons,
        "checks": {
            "face_budget": measured.get("face_budget"),
            "prototype_scale_meters": [0.05, 5.0],
            "dimensions_meters": dimensions_meters,
            "boundary_edge_count": measured.get("boundary_edge_count"),
            "nonmanifold_edge_count": measured.get("nonmanifold_edge_count"),
            "component_count": measured.get("component_count"),
            "transforms_applied": measured.get("transforms_applied"),
            "uv_layers": measured.get("uv_layers"),
            "mesh_without_uv_count": measured.get("mesh_without_uv_count"),
            "material_count": measured.get("material_count"),
            "mesh_without_material_count": measured.get("mesh_without_material_count"),
            "image_texture_count": measured.get("image_texture_count"),
            "mesh_without_texture_count": measured.get("mesh_without_texture_count"),
            "missing_textures": measured.get("missing_textures"),
            "coordinate_system": measured.get("coordinate_system"),
            "rest_pose_status": measured.get("rest_pose_status"),
            "auxiliary_objects": measured.get("auxiliary_objects"),
        },
        "limitations": [
            "Topology and bounds do not establish that limbs are separated, anatomy is suitable, or skin weights will deform well.",
            "Review representative poses and deformations after rigging; a pass is not a guarantee of animation quality.",
        ],
    }


def readiness_allows_rigging(readiness):
    return (isinstance(readiness, dict)
            and readiness.get("status") in ("pass", "needs_review")
            and isinstance(readiness.get("approval"), dict)
            and readiness["approval"].get("status") == "approved"
            and classify_character_readiness(readiness)["status"] != "fail")


def run_character_readiness(project_root, config, manifest, character_selector, *, source_output="model"):
    """Inspect an approved character mesh in Blender and save a readiness report."""
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)
    artifact = character.get("artifacts", {}).get(source_output)
    if (not artifact or artifact.get("status") != "ready"
            or artifact.get("approval", {}).get("status") != "approved"):
        raise ValueError(f"Readiness source output {source_output!r} must be a ready approved artifact")
    if artifact.get("type") not in {"model.glb", "model.fbx"}:
        raise ValueError("Readiness source must be a GLB or FBX model")
    _, source = _project_file(root, artifact.get("path"), "Readiness source model")
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"Readiness source model is missing or empty: {artifact.get('path')}")
    source_hash = _sha256_file(source)

    pipeline = config["asset_pipeline"]
    face_budget = pipeline.get("model_budgets", {}).get("character_faces", 60000)
    output_root = Path(pipeline["output_root"])
    report_path = (root / output_root / "Characters" / character["name"] / "Readiness" / "report.json").resolve()
    if not report_path.is_relative_to(root):
        raise ValueError("Readiness output directory must stay inside the project")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    script = tool_root() / "blender/inspect_model.py"
    from .backends.blender import blender_environment
    with tempfile.TemporaryDirectory(prefix="slopforge-readiness-") as temporary:
        raw_report = Path(temporary) / "inspection.json"
        command = [blender_executable(config, root), "--background", "--factory-startup", "--python-exit-code", "1",
                   "--python", str(script), "--", str(source), str(raw_report), str(face_budget)]
        subprocess.run(command, check=True, env=blender_environment())
        if not raw_report.is_file():
            raise RuntimeError("Blender completed without creating a character-readiness report")
        inspection = json.loads(raw_report.read_text())
    if not source.is_file() or _sha256_file(source) != source_hash:
        raise RuntimeError("Readiness source changed during inspection; rerun character readiness")
    readiness = classify_character_readiness(inspection)
    readiness["source_output"] = source_output
    readiness["source"] = {
        "artifact_id": artifact.get("id"),
        "path": artifact["path"],
        "sha256": source_hash,
    }
    readiness["report_path"] = report_path.relative_to(root).as_posix()
    readiness["inspected_at"] = datetime.now(timezone.utc).isoformat()
    character["animation_readiness"] = readiness
    report_path.write_text(json.dumps(readiness, indent=2) + "\n")
    statuses = character.setdefault("pipeline_status", {})
    statuses["model_generation_status"] = artifact.get("status", "unknown")
    statuses["animation_readiness_status"] = readiness["status"]
    for stage in ("rigging_status", "deformation_status", "unity_avatar_status"):
        statuses.setdefault(stage, "not_started")
    return readiness


def approve_character_readiness(project_root, manifest, character_selector, *, approved_by=None):
    """Record explicit human acceptance of a non-failing readiness report."""
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)
    readiness = character.get("animation_readiness")
    if not isinstance(readiness, dict):
        raise ValueError("Run character readiness before approving it")
    if readiness.get("status") == "fail":
        raise ValueError("A failed animation-readiness report cannot be approved")
    if readiness.get("status") not in ("pass", "needs_review"):
        raise ValueError("Animation-readiness report has an unsupported status")
    if classify_character_readiness(readiness)["status"] == "fail":
        raise ValueError("Incomplete or invalid animation-readiness measurements; run character readiness again")
    relative, report_path = _project_file(root, readiness.get("report_path"), "Readiness report")
    if not report_path.is_file():
        raise FileNotFoundError(f"Animation-readiness report is missing: {relative}")
    readiness["approval"] = {"status": "approved", "approved_at": datetime.now(timezone.utc).isoformat()}
    if approved_by:
        readiness["approval"]["approved_by"] = approved_by
    statuses = character.setdefault("pipeline_status", {})
    statuses["animation_readiness_status"] = readiness["status"]
    statuses.setdefault("rigging_status", "not_started")
    statuses.setdefault("deformation_status", "not_started")
    statuses.setdefault("unity_avatar_status", "not_started")
    report_path.write_text(json.dumps(readiness, indent=2) + "\n")
    return readiness
