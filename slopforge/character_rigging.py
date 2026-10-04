"""Validate and record outputs from an external character-rigging provider."""
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from .manifest import register_artifact
from .paths import blender_executable, tool_root
from .validation import validate_image


RECOMMENDED_POSES = ("t_pose", "raised_arms", "crouch", "leg_lift", "elbow_bend", "shoulder_rotation")
_POSE_ID = re.compile(r"[a-z][a-z0-9_]*\Z")
WELD_RELATIVE_TOLERANCE = 1e-5


def welding_tolerance(low, high):
    spans = [float(high[axis]) - float(low[axis]) for axis in range(3)]
    if any(not math.isfinite(span) or span <= 0 for span in spans):
        raise ValueError("Character model bounds must be finite and non-degenerate")
    return max(spans) * WELD_RELATIVE_TOLERANCE


def _project_file(root, relative, label):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError(f"{label} must be a project-relative path")
    path = PurePosixPath(relative)
    if not path.parts or path.is_absolute() or ".." in path.parts or path.parts[0].endswith(":"):
        raise ValueError(f"{label} must be a project-relative path")
    resolved = (root / Path(*path.parts)).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} must stay inside the project")
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise ValueError(f"{label} is missing or empty: {relative}")
    return path.as_posix(), resolved


def _character_asset(manifest, selector):
    character = manifest["assets"].get(selector)
    if character is None:
        matches = [item for item in manifest["assets"].values()
                   if item.get("id") == selector or item.get("name") == selector]
        if len(matches) != 1:
            raise KeyError(f"No unique character asset named {selector!r}")
        character = matches[0]
    if character.get("type") != "character":
        raise ValueError("Rigging results can only be recorded on a character asset")
    return character


def resolve_rigging_source(project_root, manifest, character_selector, source_output):
    """Resolve a ready, explicitly approved model artifact for rigging."""
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)
    artifact = character.get("artifacts", {}).get(source_output)
    if (not artifact or artifact.get("status") != "ready"
            or artifact.get("approval", {}).get("status") != "approved"):
        raise ValueError(f"Rigging source output {source_output!r} must be a ready approved artifact")
    if artifact.get("type") not in {"model.glb", "model.fbx"}:
        raise ValueError(f"Rigging source output {source_output!r} must be a GLB or FBX model")
    _, path = _project_file(root, artifact.get("path"), "Rigging source model")
    if path.suffix.lower() not in {".glb", ".fbx"}:
        raise ValueError("Rigging source artifact extension must be .glb or .fbx")
    return path


def rigify_character(project_root, config, manifest, character_selector, *, source_output="model"):
    """Run Blender's bundled Rigify provider and record its exports for review."""
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)
    source = resolve_rigging_source(root, manifest, character_selector, source_output)
    output_root = Path(config["asset_pipeline"]["output_root"])
    output = (root / output_root / "Characters" / character["name"] / "Rigging").resolve()
    if not output.is_relative_to(root):
        raise ValueError("Rigging output directory must stay inside the project")
    rigged_model = output / f"{character['name']}_rigged.fbx"
    evidence = {pose: (output / "Review" / f"{pose}.png") for pose in RECOMMENDED_POSES}
    if rigged_model.exists() or any(path.exists() for path in evidence.values()):
        raise FileExistsError(f"Rigging outputs already exist; inspect or move them before retrying: {output}")
    output.mkdir(parents=True, exist_ok=True)
    script = tool_root() / "blender/rigify_character.py"
    try:
        with tempfile.TemporaryDirectory(prefix="slopforge-rigify-") as temporary:
            request_path = Path(temporary) / "request.json"
            report_path = Path(temporary) / "result.json"
            request_path.write_text(json.dumps({"source": str(source), "rigged_model": str(rigged_model),
                "evidence": {pose: str(path) for pose, path in evidence.items()}, "report": str(report_path),
                "weld_relative_tolerance": WELD_RELATIVE_TOLERANCE}))
            command = [blender_executable(config, root), "--background", "--factory-startup",
                       "--python", str(script), "--", str(request_path)]
            try:
                subprocess.run(command, check=True)
            except subprocess.CalledProcessError:
                pass
            if not report_path.is_file():
                raise RuntimeError("Blender Rigify failed without a provider result report")
            result = json.loads(report_path.read_text())
            if result.get("status") != "complete":
                raise RuntimeError("Blender Rigify failed: " + str(result.get("error", "provider did not complete")))
            result["rigged_model"] = rigged_model.relative_to(root).as_posix()
            result["source_output"] = source_output
            result["evidence"] = {pose: path.relative_to(root).as_posix() for pose, path in evidence.items()
                                  if path.is_file()}
            if len(result["evidence"]) != len(RECOMMENDED_POSES):
                raise RuntimeError("Blender Rigify did not render all recommended review poses")
            return record_rigging_result(root, manifest, character["id"], result)
    except Exception:
        rigged_model.unlink(missing_ok=True)
        for path in evidence.values():
            path.unlink(missing_ok=True)
        raise


def run_character_rigging(project_root, config, manifest, character_selector, *, source_output="model"):
    """Select the configured character-rigging provider without changing the result contract."""
    provider = config["asset_pipeline"].get("character_rigging_provider", "blender_rigify")
    if provider == "blender_rigify":
        return rigify_character(project_root, config, manifest, character_selector, source_output=source_output)
    raise ValueError(f"Unsupported character_rigging_provider {provider!r}; available provider: blender_rigify")


def record_rigging_result(project_root, manifest, character_selector, result):
    """Record provider exports as pending typed artifacts; never auto-approve a rig."""
    if not isinstance(result, dict):
        raise ValueError("Rigging provider result must be an object")
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)

    provider = result.get("provider")
    required_provider = ("name", "version", "source", "license")
    if not isinstance(provider, dict) or any(not isinstance(provider.get(key), str) or not provider[key].strip()
                                              for key in required_provider):
        raise ValueError("Rigging provider provenance requires name, version, source, and license")
    source_output = result.get("source_output")
    if (not isinstance(source_output, str)
            or source_output not in character.get("artifacts", {})
            and source_output not in character.get("outputs", {})):
        raise ValueError("Rigging result must name an existing source output")
    if source_output in character.get("artifacts", {}):
        artifact = character["artifacts"][source_output]
        if artifact.get("status") != "ready" or artifact.get("approval", {}).get("status") != "approved":
            raise ValueError("Rigging source output must be ready and approved")

    rig_path, rig_file = _project_file(root, result.get("rigged_model"), "Rigged model")
    if rig_file.suffix.lower() not in {".fbx", ".glb"}:
        raise ValueError("Rigged model must be an FBX or GLB export")
    evidence = result.get("evidence", {})
    mapping = result.get("skeleton_mapping", {})
    deformation = result.get("deformation_evidence", {})
    mesh_repair = result.get("mesh_repair", {})
    if (not isinstance(evidence, dict) or not isinstance(mapping, dict) or not isinstance(deformation, dict)
            or not isinstance(mesh_repair, dict)):
        raise ValueError("Rig evidence, deformation evidence, skeleton mapping, and mesh repair must be mappings")
    if any(not isinstance(source, str) or not source.strip() or not isinstance(target, str) or not target.strip()
           for source, target in mapping.items()):
        raise ValueError("Skeleton mapping entries must map non-empty bone names")
    for pose, metrics in deformation.items():
        value = metrics.get("max_vertex_displacement") if isinstance(metrics, dict) else None
        if (not isinstance(pose, str) or not isinstance(metrics, dict) or not isinstance(value, (int, float))
                or isinstance(value, bool) or not math.isfinite(value) or value < 0):
            raise ValueError("Deformation evidence requires finite non-negative max_vertex_displacement metrics")

    evidence_files = []
    for pose, relative in evidence.items():
        if not isinstance(pose, str) or not _POSE_ID.fullmatch(pose):
            raise ValueError(f"Invalid rig evidence pose id: {pose!r}")
        relative, path = _project_file(root, relative, f"Rig evidence {pose}")
        check = validate_image(path, expected_format="PNG")
        if check["status"] == "failed":
            raise ValueError(f"Rig evidence {pose} is not a valid PNG: " + "; ".join(check["errors"]))
        evidence_files.append((pose, relative, check))

    provenance = {key: provider[key] for key in required_provider}
    for key in ("model", "model_license", "source_revision"):
        if key in provider:
            provenance[key] = provider[key]
    derived = [{"asset_id": character["id"], "output_id": source_output}]
    validation = {"status": "not_run", "errors": [],
                  "warnings": ["Structural export checks passed; deformation quality requires manual review."],
                  "measured": {"skeleton_mapping_count": len(mapping), "evidence_pose_count": len(evidence_files)}}
    registered = register_artifact(manifest, character["id"], "rig", "model.rigged", rig_path,
                                   status="candidate", derived_from=derived, provenance=provenance,
                                   approval_status="pending", validation=validation)
    for pose, relative, check in evidence_files:
        register_artifact(manifest, character["id"], f"rig_pose.{pose}", "image.rig_evidence", relative,
                          status="candidate", derived_from=derived, provenance=provenance,
                          approval_status="pending", validation=check)
    missing = [pose for pose in RECOMMENDED_POSES if pose not in evidence]
    character["rigging"] = {"status": "review_required", "source_output": source_output,
                            "provider": provenance, "skeleton_mapping": dict(mapping),
                            "deformation_evidence": deformation,
                            "mesh_repair": mesh_repair,
                            "validation": validation, "missing_recommended_poses": missing}
    character["status"] = "candidate"
    return {"status": "review_required", "rig_artifact": registered, "missing_recommended_poses": missing}
