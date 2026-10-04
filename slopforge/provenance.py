import hashlib


def workflow_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as workflow:
        for chunk in iter(lambda: workflow.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generator_provenance(workflow, metadata=None):
    metadata = metadata or {}
    result = {
        "workflow": workflow,
        "model": metadata.get("model"),
        "seed": metadata.get("seed"),
        "prompt_id": metadata.get("prompt_id"),
    }
    for field in ("quality", "references_used", "workflow_sha256"):
        if field in metadata and (field != "workflow_sha256" or metadata[field] is not None):
            result[field] = metadata[field]
    return result
