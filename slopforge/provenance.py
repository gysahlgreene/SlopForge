def generator_provenance(workflow, metadata=None):
    metadata = metadata or {}
    result = {
        "workflow": workflow,
        "model": metadata.get("model"),
        "seed": metadata.get("seed"),
        "prompt_id": metadata.get("prompt_id"),
    }
    for field in ("quality", "references_used"):
        if field in metadata:
            result[field] = metadata[field]
    return result
