import copy
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import SCHEMA_VERSION


def asset_key(asset_type, name):
    return f"{asset_type}:{name}"


def _migrate(data):
    version = data.get("schema_version")
    if version == SCHEMA_VERSION:
        return data
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise ValueError(f"Manifest schema {version} is newer than supported schema {SCHEMA_VERSION}")
    if version == 2:
        migrated = copy.deepcopy(data)
        migrated["schema_version"] = 3
        return _migrate(migrated)
    if version == 3:
        migrated = copy.deepcopy(data)
        for asset in migrated.get("assets", {}).values():
            asset.setdefault("executions", [])
            asset.setdefault("lineage_status", {
                "status": "unknown", "reason": "legacy manifest predates execution lineage"})
        migrated["schema_version"] = SCHEMA_VERSION
        return migrated
    old_style = data.get("style") or {}
    assets = {}
    for key, old in data.get("assets", {}).items():
        record = {
            "id": old.get("id") or str(uuid.uuid4()),
            "name": old.get("name", key),
            "type": old.get("type"),
            "description": old.get("description", old.get("prompt", "")),
            "style": old.get("style", old_style.get("name")),
            "style_version": old.get("style_version", old_style.get("version")),
            "status": old.get("status", "ready"),
            "created_at": old.get("created_at", old.get("generated_at")),
            "generator": copy.deepcopy(old.get("generator") or {
                "workflow": old.get("workflow"), "model": None, "seed": None,
            }),
            "conditioning": {"strategy": "text_only", "references_used": []},
            "candidates": {"items": [], "selected": None},
            "source": {k: v for k, v in (("concept", old.get("concept")), ("glb", old.get("source"))) if v},
            "outputs": {k: v for k, v in (("asset", old.get("asset")), ("preview_blend", old.get("preview"))) if v},
            "validation": {"status": "unknown", "warnings": ["Migrated legacy manifest entry; validation facts were not recorded."], "measured": {}},
            "legacy": copy.deepcopy(old),
        }
        for field in ("approval", "provenance"):
            if field in old:
                record[field] = copy.deepcopy(old[field])
        assets[key] = record
    migrated = {name: copy.deepcopy(value) for name, value in data.items()
                if name not in {"schema_version", "style", "assets"}}
    active_style = copy.deepcopy(old_style)
    active_style.update({"name": old_style.get("name"), "version": old_style.get("version")})
    migrated.update({
        "schema_version": 3,
        "active_style": active_style,
        "assets": assets,
    })
    return _migrate(migrated)


def load_manifest(path):
    path = Path(path)
    return _migrate(json.loads(path.read_text())) if path.is_file() else {"schema_version": SCHEMA_VERSION, "active_style": {}, "assets": {}}


def save_manifest(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def find_asset(manifest, selector):
    exact = manifest["assets"].get(selector)
    if exact:
        return exact
    found = [asset for asset in manifest["assets"].values() if asset.get("name") == selector or asset.get("id") == selector]
    if len(found) != 1:
        if not found:
            raise KeyError(f"No asset named {selector!r}")
        raise ValueError(f"Asset name {selector!r} is ambiguous; use its asset id")
    return found[0]


_ARTIFACT_STATUSES = {"planned", "candidate", "ready", "failed", "superseded"}
_APPROVAL_STATUSES = {"pending", "approved", "rejected", "not_required"}


def _project_path(path):
    if not isinstance(path, str) or not path or "\\" in path:
        raise ValueError("Artifact paths must be non-empty project-relative POSIX paths")
    relative = PurePosixPath(path)
    if (relative == PurePosixPath(".") or relative.is_absolute() or ".." in relative.parts
            or relative.parts[0].endswith(":")):
        raise ValueError("Artifact paths must stay within the project")
    return relative.as_posix()


def _manifest_asset(manifest, selector):
    try:
        return manifest["assets"][selector]
    except KeyError:
        return find_asset(manifest, selector)


def _validate_digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Artifact SHA-256 must be 64 lowercase hexadecimal characters")


def _validate_artifact_ref(reference):
    if not isinstance(reference, dict):
        raise ValueError("Artifact references must be objects")
    for field in ("id", "type", "stage"):
        if not isinstance(reference.get(field), str) or not reference[field].strip():
            raise ValueError(f"Artifact reference requires {field}")
    _project_path(reference.get("path"))
    _validate_digest(reference.get("sha256"))
    attempt = reference.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("Artifact attempt must be a positive integer")
    derived = reference.get("derived_from", [])
    if not isinstance(derived, list):
        raise ValueError("Artifact derived_from must be a list")
    for parent in derived:
        if not isinstance(parent, dict) or not isinstance(parent.get("artifact_id"), str):
            raise ValueError("Derived artifact references require artifact_id and sha256")
        _validate_digest(parent.get("sha256"))
    return copy.deepcopy(reference)


def _execution_identity_digest(identity_inputs):
    encoded = json.dumps(identity_inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def start_execution(asset, identity_inputs, parent_execution_id=None):
    if not isinstance(identity_inputs, dict):
        raise ValueError("Execution identity inputs must be an object")
    executions = asset.setdefault("executions", [])
    if parent_execution_id is not None and not any(
            item.get("id") == parent_execution_id for item in executions):
        raise ValueError(f"Unknown parent execution {parent_execution_id!r}")
    execution = {
        "id": str(uuid.uuid4()),
        "parent_execution_id": parent_execution_id,
        "identity_sha256": _execution_identity_digest(identity_inputs),
        "identity_inputs": copy.deepcopy(identity_inputs),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "stages": [],
    }
    executions.append(execution)
    return execution


def set_execution_identity(execution, identity_inputs):
    if execution.get("stages"):
        raise ValueError("Execution identity cannot change after a stage starts")
    if not isinstance(identity_inputs, dict):
        raise ValueError("Execution identity inputs must be an object")
    execution["identity_inputs"] = copy.deepcopy(identity_inputs)
    execution["identity_sha256"] = _execution_identity_digest(identity_inputs)
    return execution


def start_stage(execution, name, attempt, inputs, settings, provenance):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Stage name must be a non-empty string")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("Stage attempt must be a positive integer")
    if not isinstance(inputs, list) or not isinstance(settings, dict) or not isinstance(provenance, dict):
        raise ValueError("Stage inputs must be a list and settings/provenance must be objects")
    stage = {
        "name": name,
        "attempt": attempt,
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "inputs": [_validate_artifact_ref(item) for item in inputs],
        "outputs": [],
        "settings": copy.deepcopy(settings),
        "provenance": copy.deepcopy(provenance),
        "error": None,
    }
    execution.setdefault("stages", []).append(stage)
    return stage


def begin_stage(stage):
    if stage.get("status") != "pending":
        raise ValueError("Only pending stages can start")
    stage["status"] = "running"
    stage["started_at"] = datetime.now(timezone.utc).isoformat()
    return stage


def finish_stage(stage, status, outputs=(), error=None):
    if status not in {"succeeded", "failed"}:
        raise ValueError(f"Unknown stage status {status!r}")
    if stage.get("status") != "running":
        raise ValueError("Only running stages can finish")
    if status == "failed" and (not isinstance(error, str) or not error):
        raise ValueError("Failed stages require an error message")
    if status == "succeeded" and error is not None:
        raise ValueError("Succeeded stages cannot have an error message")
    stage["outputs"] = [_validate_artifact_ref(item) for item in outputs]
    stage["status"] = status
    stage["finished_at"] = datetime.now(timezone.utc).isoformat()
    stage["error"] = error
    return stage


def finish_execution(execution, status):
    if status not in {"succeeded", "failed"}:
        raise ValueError(f"Unknown execution status {status!r}")
    if execution.get("status") != "running":
        raise ValueError("Only running executions can finish")
    execution["status"] = status
    execution["finished_at"] = datetime.now(timezone.utc).isoformat()
    return execution


def register_artifact(manifest, asset_selector, artifact_id, artifact_type, path, *, status="ready",
                      derived_from=None, provenance=None, approval_status="pending", validation=None):
    """Record a typed project-relative output and maintain the legacy path map."""
    if not isinstance(artifact_id, str) or not artifact_id.strip() or artifact_id != artifact_id.strip():
        raise ValueError("Artifact id must be a non-empty string")
    if not isinstance(artifact_type, str) or not artifact_type.strip() or artifact_type != artifact_type.strip():
        raise ValueError("Artifact type must be a non-empty string")
    if status not in _ARTIFACT_STATUSES:
        raise ValueError(f"Unknown artifact status {status!r}")
    if approval_status not in _APPROVAL_STATUSES:
        raise ValueError(f"Unknown approval status {approval_status!r}")
    if provenance is not None and not isinstance(provenance, dict):
        raise ValueError("Artifact provenance must be an object")
    if validation is not None and not isinstance(validation, dict):
        raise ValueError("Artifact validation must be an object")

    asset = _manifest_asset(manifest, asset_selector)
    sources = []
    assets_by_id = {item.get("id"): item for item in manifest["assets"].values()}
    for source in derived_from or ():
        if not isinstance(source, dict) or not source.get("asset_id") or not source.get("output_id"):
            raise ValueError("Derived-from references require asset_id and output_id")
        source_asset = assets_by_id.get(source["asset_id"])
        if source_asset is None:
            raise ValueError(f"Unknown source asset {source['asset_id']!r}")
        source_outputs = source_asset.get("artifacts", {})
        if source["output_id"] not in source_outputs and source["output_id"] not in source_asset.get("outputs", {}):
            raise ValueError(f"Unknown source output {source['output_id']!r}")
        sources.append({"asset_id": source["asset_id"], "output_id": source["output_id"]})

    approval = {"status": approval_status}
    if approval_status == "approved":
        approval["approved_at"] = datetime.now(timezone.utc).isoformat()
    artifact = {
        "id": artifact_id,
        "type": artifact_type,
        "status": status,
        "path": _project_path(path),
        "derived_from": sources,
        "provenance": copy.deepcopy(provenance or {}),
        "approval": approval,
        "validation": copy.deepcopy(validation or {"status": "not_run", "errors": [], "warnings": [], "measured": {}}),
    }
    asset.setdefault("artifacts", {})[artifact_id] = artifact
    asset.setdefault("outputs", {})[artifact_id] = artifact["path"]
    return artifact


def set_artifact_approval(manifest, asset_selector, artifact_id, status, *, approved_by=None, approved_at=None):
    if status not in _APPROVAL_STATUSES:
        raise ValueError(f"Unknown approval status {status!r}")
    asset = _manifest_asset(manifest, asset_selector)
    try:
        artifact = asset["artifacts"][artifact_id]
    except KeyError as exc:
        raise KeyError(f"No artifact {artifact_id!r} on asset {asset.get('name')!r}") from exc
    approval = {"status": status}
    if status == "approved":
        approval["approved_at"] = approved_at or datetime.now(timezone.utc).isoformat()
        if approved_by is not None:
            approval["approved_by"] = approved_by
    artifact["approval"] = approval
    return approval


def children_of(manifest, parent_selector):
    parent = _manifest_asset(manifest, parent_selector)
    return [asset for asset in manifest["assets"].values() if asset.get("parent_id") == parent.get("id")]


def set_parent(manifest, child_selector, parent_selector):
    child = _manifest_asset(manifest, child_selector)
    parent = _manifest_asset(manifest, parent_selector)
    by_id = {asset.get("id"): asset for asset in manifest["assets"].values()}
    cursor = parent
    while cursor is not None:
        if cursor.get("id") == child.get("id"):
            raise ValueError("Parent relationship would create a cycle")
        parent_id = cursor.get("parent_id")
        cursor = by_id.get(parent_id) if parent_id else None
    child["parent_id"] = parent["id"]
    return child


def add_dependency(manifest, asset_selector, dependency_selector, *, output_id=None):
    asset = _manifest_asset(manifest, asset_selector)
    dependency = _manifest_asset(manifest, dependency_selector)
    if asset.get("id") == dependency.get("id"):
        raise ValueError("An asset cannot depend on itself")
    if output_id is not None and output_id not in dependency.get("artifacts", {}) and output_id not in dependency.get("outputs", {}):
        raise ValueError(f"Unknown dependency output {output_id!r}")
    reference = {"asset_id": dependency["id"]}
    if output_id is not None:
        reference["output_id"] = output_id
    dependencies = asset.setdefault("dependencies", [])
    if reference not in dependencies:
        dependencies.append(reference)
    return reference


def add_candidate(manifest, key, candidate):
    asset = manifest["assets"][key]
    asset.setdefault("candidates", {"items": [], "selected": None})["items"].append(candidate)
    asset["status"] = "candidate"


def new_record(asset_type, name, description, style, conditioning):
    return {"id": str(uuid.uuid4()), "name": name, "type": asset_type, "description": description,
            "style": style["name"], "style_version": style["version"], "status": "planned",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "generator": {"workflow": None, "model": None, "seed": None},
            "conditioning": {"strategy": conditioning["strategy"], "references_used": []},
            "candidates": {"items": [], "selected": None}, "source": {}, "outputs": {}, "executions": [],
            "validation": {"status": "not_run", "warnings": [], "measured": {}}}
