from pathlib import Path, PurePosixPath

from ..provenance import file_sha256


_STAGE_ORDER = (
    "concept_generation", "conditioning_preparation", "mesh_workflow_execution",
    "mesh_raw_acquisition", "mesh_preparation", "material_generation",
    "mesh_output_acquisition", "material_map_acquisition", "material_assembly_export",
    "final_publication",
)
_REQUIRED_OUTPUT_TYPES = {
    "conditioning_preparation": {"image.cutout", "image.3d_input"},
    "mesh_workflow_execution": {"mesh.glb"},
    "material_map_acquisition": {
        "texture.basecolor", "texture.normal", "texture.roughness", "texture.metallic",
        "texture.metallic_gloss", "texture.emission",
    },
    "material_assembly_export": {
        "mesh.fbx", "project.blend", "preview.front", "preview.side",
        "preview.rear", "preview.three_quarter", "validation.json",
    },
}


def _valid_sha256(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def artifact_integrity(project_root: Path, reference: dict) -> tuple[bool, str | None]:
    if not isinstance(reference, dict):
        return False, "missing artifact reference"
    path = reference.get("path")
    if not isinstance(path, str) or not path or "\\" in path:
        return False, "missing artifact path"
    relative = PurePosixPath(path)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts or relative.parts[0].endswith(":"):
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
            or not _valid_sha256(ref["sha256"]) for ref in refs)
            or any(not isinstance(output["id"], str) or not output["id"].strip()
                   or not isinstance(output["type"], str) or not output["type"]
                   or not isinstance(output["path"], str) or not output["path"]
                   or not _valid_sha256(output["sha256"])
                   or not isinstance(output["stage"], str) or type(output["attempt"]) is not int
                   for output in outputs)
            or any(not isinstance(parent["artifact_id"], str) or not parent["artifact_id"]
                   or not _valid_sha256(parent["sha256"])
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
    required = _REQUIRED_OUTPUT_TYPES.get(name, set())
    recorded_types = {output["type"] for output in outputs}
    missing = required - recorded_types
    if name == "material_generation" and not (
            {"surface.swatch", "generation.metadata"} <= recorded_types or
            {"texture.basecolor", "texture.normal", "texture.roughness",
             "texture.metallic"} <= recorded_types):
        missing.update({"surface.swatch", "generation.metadata"} - recorded_types)
    if missing:
        reasons.append("missing required output artifact type: " + ", ".join(sorted(missing)))
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
    ordered = [name for name in _STAGE_ORDER if name in requested]
    if not ordered:
        return None

    def stale(name=None):
        return name if name in requested else ordered[0]

    if not isinstance(stages, list):
        return stale()
    by_name = {}
    stage_ids = set()
    stage_attempts = set()
    malformed_names = set()
    for stage in stages:
        if not isinstance(stage, dict):
            return stale()
        name = stage.get("name")
        if not isinstance(name, str) or name not in _STAGE_ORDER:
            return stale()
        if "id" in stage:
            stage_id = stage["id"]
            if not isinstance(stage_id, str) or not stage_id:
                if name in requested:
                    malformed_names.add(name)
                    continue
                return stale()
            if stage_id in stage_ids:
                return stale()
            stage_ids.add(stage_id)
        attempt = stage.get("attempt")
        if type(attempt) is not int or attempt < 1:
            if name in requested:
                malformed_names.add(name)
                continue
            return stale()
        if (not all(key in stage for key in ("status", "inputs", "outputs", "settings"))
                or not isinstance(stage["status"], str)
                or stage["status"] not in {"pending", "running", "succeeded", "failed"}
                or not isinstance(stage["inputs"], list)
                or not isinstance(stage["outputs"], list)
                or not isinstance(stage["settings"], dict)):
            if name in requested:
                malformed_names.add(name)
                continue
            return stale()
        identity = (name, attempt)
        if identity in stage_attempts:
            if name in requested:
                malformed_names.add(name)
                continue
            return stale()
        stage_attempts.add(identity)
        malformed = False
        for ref in stage["inputs"]:
            if (not isinstance(ref, dict) or not isinstance(ref.get("id"), str) or not ref["id"]
                    or not _valid_sha256(ref.get("sha256"))):
                malformed = True
                break
        output_ids = set()
        if not malformed:
            for output in stage["outputs"]:
                if (not isinstance(output, dict)
                        or not all(key in output for key in
                                   ("id", "type", "path", "sha256", "stage", "attempt", "derived_from"))
                        or not isinstance(output["id"], str) or not output["id"]
                        or not isinstance(output["type"], str) or not output["type"]
                        or not isinstance(output["path"], str) or not output["path"]
                        or not _valid_sha256(output["sha256"])
                        or output["stage"] != name or type(output["attempt"]) is not int
                        or output["attempt"] != attempt
                        or not isinstance(output["derived_from"], list)):
                    malformed = True
                    break
                if output["id"] in output_ids:
                    malformed = True
                    break
                output_ids.add(output["id"])
                if any(not isinstance(parent, dict)
                       or not isinstance(parent.get("artifact_id"), str) or not parent["artifact_id"]
                       or not _valid_sha256(parent.get("sha256"))
                       for parent in output["derived_from"]):
                    malformed = True
                    break
        if malformed:
            if name in requested:
                malformed_names.add(name)
                continue
            return stale()
        by_name.setdefault(name, []).append(stage)
    # The fixed route selects one material branch: native mesh PBR or swatch maps.
    for name in ordered:
        if name in malformed_names:
            return name
        candidates = by_name.get(name, [])
        if not candidates:
            return name
        inputs, settings = requested[name]
        try:
            decisions = [stage_reuse_decision(project_root, stage, inputs=inputs, settings=settings)
                         for stage in candidates]
        except (AttributeError, KeyError, TypeError, ValueError):
            return name
        if not any(decision["reusable"] for decision in decisions):
            return name
    return None
