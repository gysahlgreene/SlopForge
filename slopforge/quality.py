def apply_workflow_inputs(workflow, overrides):
    if not isinstance(overrides, dict):
        raise ValueError("Quality workflow inputs must be a node/input mapping")
    for node_id, values in overrides.items():
        node = workflow.get(str(node_id))
        if not isinstance(values, dict) or not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            raise ValueError(f"Quality workflow override targets a missing node/input: {node_id}")
        missing = set(values) - node["inputs"].keys()
        if missing:
            raise ValueError(f"Quality workflow override targets a missing node/input: {node_id}.{sorted(missing)[0]}")
    for node_id, values in overrides.items():
        workflow[str(node_id)]["inputs"].update(values)
    return workflow
