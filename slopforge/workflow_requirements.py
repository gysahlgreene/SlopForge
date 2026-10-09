import re
from pathlib import Path

import yaml

from .backends.comfyui import ComfyUIClient, workflow_mask_errors
from .provenance import workflow_sha256


def requirements_path(workflow_path):
    path = Path(workflow_path)
    return path.with_name(f"{path.stem}.requirements.yaml")


def _string_list(value, field, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty) or any(
            not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"Workflow requirements {field} must be a list of non-empty strings")


def _entry_list(value, field, required_fields):
    if not isinstance(value, list):
        raise ValueError(f"Workflow requirements {field} must be a list")
    for index, entry in enumerate(value):
        if not isinstance(entry, dict) or any(
                not isinstance(entry.get(key), str) or not entry[key].strip() for key in required_fields):
            names = ", ".join(required_fields)
            raise ValueError(f"Workflow requirements {field}[{index}] must define {names}")


def load_workflow_requirements(workflow_path):
    """Load and validate a workflow's adjacent requirements sidecar, or return None."""
    sidecar = requirements_path(workflow_path)
    if not sidecar.is_file():
        return None
    try:
        manifest = yaml.safe_load(sidecar.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid workflow requirements YAML in {sidecar.name}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"Workflow requirements in {sidecar.name} must be a mapping")
    schema_version = manifest.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version != 1:
        raise ValueError(f"Workflow requirements schema_version must be 1 (got {schema_version!r})")
    if not isinstance(manifest.get("id"), str) or not manifest["id"].strip():
        raise ValueError("Workflow requirements id must be a non-empty string")
    version = manifest.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("Workflow requirements version must be a positive integer")
    _string_list(manifest.get("capabilities"), "capabilities")
    _string_list(manifest.get("profiles"), "profiles")
    _entry_list(manifest.get("nodes"), "nodes", ("class", "source", "revision"))
    _entry_list(manifest.get("models"), "models", ("name", "source", "license", "license_source", "sha256"))
    _entry_list(manifest.get("inputs"), "inputs", ("name", "type"))
    _entry_list(manifest.get("outputs"), "outputs", ("name", "type"))
    tested_on = manifest.get("tested_on")
    if not isinstance(tested_on, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("profile"), str)
            or not isinstance(item.get("backend"), str) for item in tested_on):
        raise ValueError("Workflow requirements tested_on must be a list of profile/backend mappings")
    resource = manifest.get("estimated_resource_class")
    if not isinstance(resource, str) or not resource.strip():
        raise ValueError("Workflow requirements estimated_resource_class must be a non-empty string")
    graph_hash = manifest.get("workflow_sha256")
    if not isinstance(graph_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", graph_hash):
        raise ValueError("Workflow requirements workflow_sha256 must be a lowercase SHA-256 hex digest")
    classes = [node["class"] for node in manifest["nodes"]]
    if len(classes) != len(set(classes)):
        raise ValueError("Workflow requirements nodes contain duplicate class entries")
    models = [model["name"] for model in manifest["models"]]
    if len(models) != len(set(models)):
        raise ValueError("Workflow requirements models contain duplicate names")
    return manifest


def validate_workflow_requirements(workflow_path, workflow, manifest):
    """Return static sidecar/graph mismatches. Backend availability is checked separately."""
    problems = workflow_mask_errors(workflow)
    expected_hash = manifest.get("workflow_sha256")
    if expected_hash and workflow_sha256(workflow_path) != expected_hash:
        problems.append("workflow_sha256 does not match the selected workflow file")

    graph_nodes = {node.get("class_type") for node in workflow.values()
                   if isinstance(node, dict) and isinstance(node.get("class_type"), str)}
    declared_nodes = {node["class"] for node in manifest["nodes"]}
    undeclared_nodes = sorted(graph_nodes - declared_nodes)
    stale_nodes = sorted(declared_nodes - graph_nodes)
    if undeclared_nodes:
        problems.append("undeclared node classes: " + ", ".join(undeclared_nodes))
    if stale_nodes:
        problems.append("declared node classes absent from graph: " + ", ".join(stale_nodes))

    graph_models = set()
    for node in workflow.values():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if isinstance(inputs, dict):
            graph_models.update(value for key, value in inputs.items()
                                if key in ComfyUIClient.MODEL_INPUTS and isinstance(value, str))
    declared_models = {model["name"] for model in manifest["models"]}
    undeclared_models = sorted(graph_models - declared_models)
    stale_models = sorted(declared_models - graph_models)
    if undeclared_models:
        problems.append("undeclared model files: " + ", ".join(undeclared_models))
    if stale_models:
        problems.append("declared model files absent from graph: " + ", ".join(stale_models))
    return problems


def workflow_requirements_identity(workflow_path, workflow=None):
    manifest = load_workflow_requirements(workflow_path)
    if manifest is None:
        return {"status": "unknown"}
    if workflow is not None:
        problems = validate_workflow_requirements(workflow_path, workflow, manifest)
        if problems:
            raise ValueError("Invalid workflow requirements: " + "; ".join(problems))
    return {"id": manifest["id"], "version": manifest["version"],
            "schema_version": manifest["schema_version"]}
