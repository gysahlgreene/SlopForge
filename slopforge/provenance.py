def generator_provenance(workflow, metadata=None):
    metadata = metadata or {}
    return {
        "workflow": workflow,
        "model": metadata.get("model"),
        "seed": metadata.get("seed"),
        "prompt_id": metadata.get("prompt_id"),
    }
