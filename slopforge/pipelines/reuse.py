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
    name = stage.get("name")
    stage_attempt = stage.get("attempt")
    if not all(field in stage for field in ("name", "attempt", "inputs", "outputs")):
        return {"reusable": False, "reasons": ["malformed stage identity or artifact collections"]}
    if not isinstance(name, str):
        return {"reusable": False, "reasons": ["semantic mismatch: stage name is malformed"]}
    if type(stage_attempt) is not int or stage_attempt < 1:
        return {"reusable": False, "reasons": ["semantic mismatch: stage attempt must be a positive integer"]}
    recorded_inputs = stage.get("inputs")
    outputs = stage.get("outputs")
    if not isinstance(recorded_inputs, list) or not isinstance(outputs, list) or not isinstance(inputs, list):
        return {"reusable": False, "reasons": ["missing or malformed artifact collections"]}
    if (not all(isinstance(ref, dict) for ref in recorded_inputs + inputs)
            or not all(isinstance(output, dict) for output in outputs)):
        return {"reusable": False, "reasons": ["malformed artifact collection member"]}
    if (any(not all(field in ref for field in ("id", "sha256")) for ref in recorded_inputs + inputs)
            or any(not all(field in output for field in
                           ("id", "type", "path", "sha256", "stage", "attempt", "derived_from"))
                   for output in outputs)):
        return {"reusable": False, "reasons": ["artifact identity fields are incomplete"]}
    parents = [parent for output in outputs for parent in
               (output["derived_from"] if isinstance(output["derived_from"], list) else [])]
    if (any(not isinstance(output["derived_from"], list) for output in outputs)
            or not all(isinstance(parent, dict) for parent in parents)):
        return {"reusable": False, "reasons": ["lineage mismatch: output derivation links are malformed"]}
    if any(not all(field in parent for field in ("artifact_id", "sha256")) for parent in parents):
        return {"reusable": False, "reasons": ["lineage mismatch: output derivation links are incomplete"]}
    refs = recorded_inputs + inputs
    if (any(not isinstance(ref["id"], str) or not ref["id"]
            or not isinstance(ref["sha256"], str) or len(ref["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in ref["sha256"]) for ref in refs)
            or any(not isinstance(output["id"], str) or not output["id"].strip()
                   or not isinstance(output["type"], str) or not output["type"]
                   or not isinstance(output["path"], str) or not output["path"]
                   or not isinstance(output["sha256"], str) or len(output["sha256"]) != 64
                   or any(c not in "0123456789abcdef" for c in output["sha256"])
                   or not isinstance(output["stage"], str) or type(output["attempt"]) is not int
                   for output in outputs)
            or any(not isinstance(parent["artifact_id"], str) or not parent["artifact_id"]
                   or not isinstance(parent["sha256"], str) or len(parent["sha256"]) != 64
                   or any(c not in "0123456789abcdef" for c in parent["sha256"])
                   for parent in parents)):
        return {"reusable": False, "reasons": ["semantic mismatch: artifact identity is malformed"]}
    # Identity types are checked above before uniqueness keys are constructed.
    output_ids = set()
    for output in outputs:
        oid = output["id"]
        if oid in output_ids:
            reasons.append("semantic mismatch: duplicate output identity")
            break
        output_ids.add(oid)
    if reasons:
        return {"reusable": False, "reasons": reasons}
    if stage.get("status") != "succeeded":
        reasons.append(f"stage status is {stage.get('status', 'unknown')}; only succeeded stages are reusable")
    if name not in _STAGE_ORDER:
        reasons.append("semantic mismatch: stage name is not in the fixed prop route")
    if any(output.get("stage") != name or output.get("attempt") != stage_attempt for output in outputs):
        reasons.append("semantic mismatch: output artifact identity does not match its stage attempt")
    if _identity(recorded_inputs) != _identity(inputs):
        reasons.append("semantic mismatch: ordered input artifact identities changed")
    if stage.get("settings") != settings:
        reasons.append("semantic mismatch: settings changed")
    required_types = {"mesh_workflow_execution": {"mesh.glb"}}
    required = required_types.get(name, set())
    if required and not any(output.get("type") in required for output in outputs):
        reasons.append("missing required output artifact type: " + ", ".join(sorted(required)))
    for output in outputs:
        intact, reason = artifact_integrity(project_root, output)
        if not intact:
            reasons.append(reason)
        allowed = {(item["id"], item["sha256"]) for item in recorded_inputs}
        recorded = {(parent["artifact_id"], parent["sha256"]) for parent in output["derived_from"]}
        if (len(recorded) != len(output["derived_from"])
                or any((artifact_id, digest) not in allowed
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
