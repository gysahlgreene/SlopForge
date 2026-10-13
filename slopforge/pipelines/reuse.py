from pathlib import Path, PurePosixPath

from ..provenance import file_sha256


_STAGE_ORDER = (
    "concept_generation", "conditioning_preparation", "mesh_workflow_execution",
    "mesh_raw_acquisition", "mesh_preparation", "material_generation",
    "mesh_output_acquisition", "material_map_acquisition", "material_assembly_export",
    "final_publication",
)


def artifact_integrity(project_root: Path, reference: dict) -> tuple[bool, str | None]:
    if not isinstance(reference, dict):
        return False, "missing artifact reference"
    path = reference.get("path")
    if not isinstance(path, str) or not path or "\\" in path:
        return False, "missing artifact path"
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts or relative.parts[0].endswith(":"):
        return False, "missing artifact: path is not project-relative"
    root = Path(project_root).resolve()
    file = root / Path(*relative.parts)
    try:
        file.resolve().relative_to(root)
        digest = file_sha256(file)
    except (OSError, ValueError):
        return False, f"missing or unreadable artifact: {path}"
    if digest != reference.get("sha256"):
        return False, f"hash mismatch for artifact: {path}"
    return True, None


def _identity(refs):
    return [(item.get("id"), item.get("sha256")) for item in refs]


def stage_reuse_decision(project_root: Path, stage: dict, *, inputs: list[dict], settings: dict) -> dict:
    reasons = []
    if not isinstance(stage, dict):
        return {"reusable": False, "reasons": ["malformed stage record"]}
    if stage.get("name") not in _STAGE_ORDER:
        reasons.append("semantic mismatch: stage name is not in the fixed prop route")
    stage_attempt = stage.get("attempt")
    if isinstance(stage_attempt, bool) or not isinstance(stage_attempt, int) or stage_attempt < 1:
        reasons.append("semantic mismatch: stage attempt must be a positive integer")
    if stage.get("status") != "succeeded":
        reasons.append(f"stage status is {stage.get('status', 'unknown')}; only succeeded stages are reusable")
    if not isinstance(stage.get("inputs"), list) or any(
            not isinstance(ref, dict) or not ref.get("id") or not ref.get("sha256")
            for ref in stage.get("inputs", [])):
        reasons.append("semantic mismatch: recorded inputs are incomplete")
    elif _identity(stage.get("inputs", [])) != _identity(inputs):
        reasons.append("semantic mismatch: ordered input artifact identities changed")
    if stage.get("settings") != settings:
        reasons.append("semantic mismatch: settings changed")
    recorded_inputs = stage.get("inputs") if isinstance(stage.get("inputs"), list) else []
    outputs = stage.get("outputs")
    if not isinstance(outputs, list):
        reasons.append("missing output artifacts")
        return {"reusable": not reasons, "reasons": reasons}
    required_types = {"mesh_workflow_execution": {"mesh.glb"}}
    required = required_types.get(stage.get("name"), set())
    if required and not any(isinstance(output, dict) and output.get("type") in required for output in outputs):
        reasons.append("missing required output artifact type: " + ", ".join(sorted(required)))
    # Validate member shapes and check for duplicate output IDs
    output_ids = set()
    for output in outputs or []:
        if not isinstance(output, dict):
            reasons.append("missing output artifacts")
            break
        oid = output.get("id", "")
        if oid in output_ids:
            reasons.append("semantic mismatch: duplicate output identity")
            break
        output_ids.add(oid)
    for output in outputs or []:
        attempt = output.get("attempt") if isinstance(output, dict) else None
        if (not isinstance(output, dict) or not isinstance(output.get("id"), str) or not output["id"].strip()
                or output.get("stage") != stage.get("name") or isinstance(attempt, bool)
                or not isinstance(attempt, int) or attempt != stage.get("attempt")):
            reasons.append("semantic mismatch: output artifact identity does not match its stage attempt")
        intact, reason = artifact_integrity(project_root, output)
        if not intact:
            reasons.append(reason)
        parents = output.get("derived_from") if isinstance(output, dict) else None
        allowed = {(item.get("id"), item.get("sha256")) for item in recorded_inputs if isinstance(item, dict)}
        recorded = {(parent.get("artifact_id"), parent.get("sha256"))
                    for parent in parents if isinstance(parent, dict)} if isinstance(parents, list) else set()
        if (not isinstance(parents, list)
                or len(recorded) != len(parents)
                or any(not artifact_id or not digest or (artifact_id, digest) not in allowed
                       for artifact_id, digest in recorded)
                or (recorded_inputs and not recorded)):
            reasons.append("lineage mismatch: output derivation links differ from requested inputs")
    return {"reusable": not reasons, "reasons": reasons}


def earliest_stale_stage(project_root: Path, stages: list[dict], requested: dict[str, tuple[list[dict], dict]]) -> str | None:
    unknown = [name for name in requested if name not in _STAGE_ORDER]
    if unknown:
        raise ValueError(f"unsupported prop stage(s): {', '.join(unknown)}")
    by_name = {}
    for stage in stages:
        by_name.setdefault(stage.get("name"), []).append(stage)
    ordered = [name for name in _STAGE_ORDER if name in requested]
    # The fixed route selects one material branch: native mesh PBR or swatch maps.
    for name in ordered:
        candidates = by_name.get(name, [])
        if not candidates:
            return name
        inputs, settings = requested[name]
        if not any(stage_reuse_decision(project_root, stage, inputs=inputs, settings=settings)["reusable"]
                   for stage in candidates):
            return name
    return None
