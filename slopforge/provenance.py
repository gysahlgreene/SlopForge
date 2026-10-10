import hashlib
import json
import re
from pathlib import Path


_VOLATILE_FIELDS = {
    "uuid", "run_uuid", "started_at", "finished_at", "timestamp", "created_at", "updated_at",
    "candidate_number", "attempt_number", "prompt_id", "output_filename", "filename_prefix",
    "temporary_filename", "subfolder",
}
_FACT_STATUSES = {"known", "unavailable", "not_recorded"}
_MISSING = object()


def _json_sha256(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _semantic_value(value):
    if isinstance(value, dict):
        return {key: _semantic_value(item) for key, item in value.items()
                if key.lower() not in _VOLATILE_FIELDS and not key.lower().endswith("_path") and key.lower() != "path"}
    if isinstance(value, list):
        return [_semantic_value(item) for item in value]
    return value


def execution_identity(identity_inputs):
    if not isinstance(identity_inputs, dict):
        raise ValueError("Execution identity inputs must be an object")
    return _json_sha256(_semantic_value(identity_inputs))


def canonical_workflow_identity(source_workflow, effective_workflow, uploaded_inputs):
    if not all(isinstance(value, dict) for value in (source_workflow, effective_workflow, uploaded_inputs)):
        raise ValueError("Workflow identity inputs must be objects")
    workflow = json.loads(json.dumps(effective_workflow))
    bindings = {}
    for slot, digest in uploaded_inputs.items():
        node_id, separator, input_name = slot.partition(".")
        if not separator or node_id not in workflow or input_name not in workflow[node_id].get("inputs", {}):
            raise ValueError(f"Uploaded input slot {slot!r} is not present in the effective workflow")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Uploaded input slot {slot!r} requires a SHA-256 content hash")
        workflow[node_id]["inputs"][input_name] = {"content_sha256": digest}
        bindings[slot] = digest
    return {
        "source_sha256": _json_sha256(source_workflow),
        "effective_sha256": _json_sha256(_semantic_value(workflow)),
        "bindings": bindings,
    }


def provenance_fact(status, *, value=_MISSING, reason=None):
    if status not in _FACT_STATUSES:
        raise ValueError(f"Unknown provenance fact status {status!r}")
    if status == "known":
        if value is _MISSING:
            raise ValueError("Known facts require a value")
        return {"status": status, "value": value}
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Unavailable and not_recorded provenance facts require a reason")
    return {"status": status, "reason": reason}


def workflow_sha256(path):
    return file_sha256(path)


def generator_provenance(workflow, metadata=None):
    metadata = metadata or {}
    result = {
        "workflow": workflow,
        "model": metadata.get("model"),
        "seed": metadata.get("seed"),
        "prompt_id": metadata.get("prompt_id"),
    }
    for field in ("quality", "references_used", "workflow_sha256", "workflow_requirements"):
        if field in metadata and (field != "workflow_sha256" or metadata[field] is not None):
            result[field] = metadata[field]
    return result
