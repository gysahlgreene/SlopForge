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
    if stage.get("name") not in _STAGE_ORDER:
        reasons.append("semantic mismatch: stage name is not in the fixed prop route")
    if stage.get("status") != "succeeded":
        reasons.append(f"stage status is {stage.get('status', 'unknown')}; only succeeded stages are reusable")
    if stage.get("inputs") is None or any(not ref.get("id") or not ref.get("sha256") for ref in stage.get("inputs", [])):
        reasons.append("semantic mismatch: recorded inputs are incomplete")
    elif _identity(stage.get("inputs", [])) != _identity(inputs):
        reasons.append("semantic mismatch: ordered input artifact identities changed")
    if stage.get("settings") != settings:
        reasons.append("semantic mismatch: settings changed")
    outputs = stage.get("outputs")
    if not outputs:
        reasons.append("missing output artifacts")
    for output in outputs or []:
        intact, reason = artifact_integrity(project_root, output)
        if not intact:
            reasons.append(reason)
        parents = output.get("derived_from")
        expected = [{"artifact_id": item.get("id"), "sha256": item.get("sha256")} for item in inputs]
        if parents is None or any(not parent.get("artifact_id") or not parent.get("sha256") for parent in parents) or parents != expected:
            reasons.append("lineage mismatch: output derivation links differ from requested inputs")
    return {"reusable": not reasons, "reasons": reasons}


def earliest_stale_stage(project_root: Path, stages: list[dict], requested: dict[str, tuple[list[dict], dict]]) -> str | None:
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
