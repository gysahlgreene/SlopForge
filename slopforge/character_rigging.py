"""Validate and record outputs from an external character-rigging provider."""
import re
from pathlib import Path, PurePosixPath

from .manifest import register_artifact
from .validation import validate_image


RECOMMENDED_POSES = ("t_pose", "raised_arms", "crouch", "leg_lift", "elbow_bend", "shoulder_rotation")
_POSE_ID = re.compile(r"[a-z][a-z0-9_]*\Z")


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


def record_rigging_result(project_root, manifest, character_selector, result):
    """Record provider exports as pending typed artifacts; never auto-approve a rig."""
    if not isinstance(result, dict):
        raise ValueError("Rigging provider result must be an object")
    root = Path(project_root).resolve()
    character = manifest["assets"].get(character_selector)
    if character is None:
        matches = [item for item in manifest["assets"].values()
                   if item.get("id") == character_selector or item.get("name") == character_selector]
        if len(matches) != 1:
            raise KeyError(f"No unique character asset named {character_selector!r}")
        character = matches[0]
    if character.get("type") != "character":
        raise ValueError("Rigging results can only be recorded on a character asset")

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
    if not isinstance(evidence, dict) or not isinstance(mapping, dict):
        raise ValueError("Rig evidence and skeleton mapping must be mappings")
    if any(not isinstance(source, str) or not source.strip() or not isinstance(target, str) or not target.strip()
           for source, target in mapping.items()):
        raise ValueError("Skeleton mapping entries must map non-empty bone names")

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
                            "validation": validation, "missing_recommended_poses": missing}
    character["status"] = "candidate"
    return {"status": "review_required", "rig_artifact": registered, "missing_recommended_poses": missing}
