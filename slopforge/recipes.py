"""Data-driven orchestration of existing atomic asset pipelines."""
import copy
import math
import re
from pathlib import Path

import yaml

from .manifest import add_dependency, asset_key, new_record, register_artifact, set_parent
from .config import select_quality_tier
from .libraries import list_libraries, resolve_library
from .pipelines import image, model
from .taxonomy import canonical_type, validate_asset_name


def _ordered_children(definition):
    children = definition.get("children")
    if not isinstance(children, list) or not children:
        raise ValueError("Recipe must define at least one child")
    ids = [item.get("id") if isinstance(item, dict) else None for item in children]
    if any(not isinstance(child_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", child_id) for child_id in ids):
        raise ValueError("Recipe child ids must be simple names")
    if len(set(ids)) != len(ids):
        raise ValueError("Recipe child ids must be unique")
    known = set(ids)
    for child in children:
        deps = child.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(dep, str) or dep not in known for dep in deps):
            raise ValueError(f"Invalid dependencies for recipe child {child['id']!r}")
        if child["id"] in deps:
            raise ValueError(f"Recipe dependency cycle at {child['id']!r}")

    ordered, pending = [], list(children)
    resolved = set()
    while pending:
        ready = next((child for child in pending if set(child.get("depends_on", [])) <= resolved), None)
        if ready is None:
            raise ValueError("Recipe dependencies contain a cycle")
        ordered.append(ready)
        resolved.add(ready["id"])
        pending.remove(ready)
    return ordered


def _validate_kit_constraints(definition, child_ids):
    constraints = definition.get("kit_constraints")
    if constraints is None:
        return
    if not isinstance(constraints, dict):
        raise ValueError("kit_constraints must be a mapping")
    for name, default in (("grid_size", 1.0), ("snap_tolerance", 0.05), ("pivot_tolerance", 0.05)):
        value = constraints.get(name, default)
        if (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
                or (value <= 0 if name == "grid_size" else value < 0)):
            raise ValueError(f"kit_constraints.{name} has an invalid value")
    maximum = constraints.get("max_dimension")
    if maximum is not None and (not isinstance(maximum, (int, float)) or isinstance(maximum, bool)
                                or not math.isfinite(maximum) or maximum <= 0):
        raise ValueError("kit_constraints.max_dimension must be positive")
    pivot = constraints.get("pivot")
    if pivot is not None and pivot not in {"center", "bottom_center", "origin"}:
        raise ValueError("kit_constraints.pivot is unsupported")
    modules = constraints.get("modules", {})
    if not isinstance(modules, dict) or not set(modules) <= child_ids:
        raise ValueError("kit_constraints.modules must map known child ids to rules")
    for child_id, rule in modules.items():
        if not isinstance(rule, dict):
            raise ValueError(f"kit_constraints.modules.{child_id} must be a mapping")
        maximum = rule.get("max_dimension")
        if maximum is not None and (not isinstance(maximum, (int, float)) or isinstance(maximum, bool)
                                    or not math.isfinite(maximum) or maximum <= 0):
            raise ValueError(f"kit_constraints.modules.{child_id}.max_dimension must be positive")
        tolerance = rule.get("snap_tolerance")
        if tolerance is not None and (not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool)
                                      or not math.isfinite(tolerance) or tolerance < 0):
            raise ValueError(f"kit_constraints.modules.{child_id}.snap_tolerance cannot be negative")
        axes = rule.get("snap_axes", [])
        if not isinstance(axes, list) or any(type(axis) is not int or axis not in (0, 1, 2) for axis in axes):
            raise ValueError(f"kit_constraints.modules.{child_id}.snap_axes must contain axes 0, 1, or 2")
        for axis_name in ("vertical_axis", "flat_axis"):
            axis = rule.get(axis_name)
            if axis is not None and (type(axis) is not int or axis not in (0, 1, 2)):
                raise ValueError(f"kit_constraints.modules.{child_id}.{axis_name} must be axis 0, 1, or 2")
        pivot = rule.get("pivot")
        if pivot is not None and pivot not in {"center", "bottom_center", "origin"}:
            raise ValueError(f"kit_constraints.modules.{child_id}.pivot is unsupported")


def load_recipe(project_root, name, asset_types, *, reference_library=None):
    validate_asset_name(name)
    path = Path(project_root) / "ai/recipes" / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Recipe not found: {path}")
    definition = yaml.safe_load(path.read_text())
    if not isinstance(definition, dict) or definition.get("id") != name:
        raise ValueError(f"Recipe id must match its filename: {path}")
    if type(definition.get("version")) is not int or definition["version"] < 1:
        raise ValueError(f"Recipe version must be a positive integer: {path}")
    if not isinstance(definition.get("description"), str) or not definition["description"].strip():
        raise ValueError(f"Recipe requires a description: {path}")
    if definition.get("quality_tier") is not None and not isinstance(definition["quality_tier"], str):
        raise ValueError("Recipe quality_tier must be a string")
    if reference_library is not None:
        if not isinstance(reference_library, str) or reference_library not in list_libraries(project_root):
            raise ValueError(f"Recipe references unknown library {reference_library!r}")
        definition["reference_library"] = reference_library
    children = _ordered_children(definition)
    _validate_kit_constraints(definition, {child["id"] for child in children})
    for child in children:
        if not isinstance(child.get("description"), str) or not child["description"].strip():
            raise ValueError(f"Recipe child {child['id']!r} requires a description")
        child["type"] = canonical_type(child.get("type", ""), asset_types)
        child_type = asset_types[child["type"]]
        if child_type.get("pipeline") not in PIPELINE_HANDLERS:
            raise ValueError(f"Recipe pipeline {child_type.get('pipeline')!r} is not supported")
        child["depends_on"] = list(child.get("depends_on", []))
        if "count" in child and (type(child["count"]) is not int or child["count"] < 1):
            raise ValueError(f"Recipe child {child['id']!r} count must be positive")
        if child.get("generation_prompt") is not None and not isinstance(child["generation_prompt"], str):
            raise ValueError(f"Recipe child {child['id']!r} generation_prompt must be a string")
        if reference_library is not None:
            child["reference_library"] = reference_library
        library = child.get("reference_library")
        if library is not None and library not in list_libraries(project_root):
            raise ValueError(f"Recipe child {child['id']!r} references unknown library {library!r}")
        if child.get("quality_tier") is not None and not isinstance(child["quality_tier"], str):
            raise ValueError(f"Recipe child {child['id']!r} quality_tier must be a string")
    return definition, children


def list_recipes(project_root):
    directory = Path(project_root) / "ai/recipes"
    return sorted(path.stem for path in directory.glob("*.yaml")) if directory.is_dir() else []


def _image(root, config, style, asset_type, child, manifest, key):
    count = child.get("count", config["asset_pipeline"]["defaults"]["image_candidates"])
    references = resolve_library(root, child["reference_library"], manifest)["entries"] if child.get("reference_library") else None
    return image.generate(root, config, asset_type, style, manifest["assets"][key]["name"],
                          child["description"], count, manifest, key,
                          generation_prompt=child.get("generation_prompt"), reference_entries=references)


def _model(root, config, style, asset_type, child, manifest, key):
    count = child.get("count", config["asset_pipeline"]["defaults"]["model_candidates"])
    references = resolve_library(root, child["reference_library"], manifest)["entries"] if child.get("reference_library") else None
    return model.generate(root, config, asset_type, style, manifest["assets"][key]["name"],
                          child["description"], count, manifest, key,
                          generation_prompt=child.get("generation_prompt"), reference_entries=references)


PIPELINE_HANDLERS = {"image": _image, "model": _model}


def _save(save, manifest):
    if save:
        save(manifest)


def _asset_artifact_type(asset, output_id, path):
    suffix = Path(path).suffix.lower().lstrip(".") or "data"
    if output_id.startswith("candidate."):
        return f"{asset['type']}.candidate"
    return {"png": f"image.{asset['type']}", "glb": "model.glb", "fbx": "model.fbx",
            "blend": "model.blend", "mat": "unity.material", "json": "data.json"}.get(suffix, f"file.{suffix}")


def _sync_child_artifacts(root, asset, key):
    for candidate in asset.get("candidates", {}).get("items", []):
        if not candidate.get("path") or candidate.get("status") not in {"candidate", "failed"}:
            continue
        candidate_id = f"candidate.{candidate['number']}"
        register_artifact({"assets": {key: asset}}, key, candidate_id,
                          f"{asset['type']}.candidate", candidate["path"],
                          status="candidate" if candidate["status"] == "candidate" else "failed",
                          provenance=candidate.get("generator") or {"seed": candidate.get("seed")},
                          approval_status="approved" if candidate.get("approval") == "approved" else "pending",
                          validation=candidate.get("validation"))
    if asset.get("status") != "ready":
        return
    for output_id, path in list(asset.get("outputs", {}).items()):
        if output_id.startswith("candidate.") or not isinstance(path, str) or not (Path(root) / path).is_file():
            continue
        validation = asset.get("validation", {})
        existing = asset.get("artifacts", {}).get(f"output.{output_id}", {})
        register_artifact({"assets": {key: asset}}, key, f"output.{output_id}",
                          _asset_artifact_type(asset, output_id, path), path, status="ready",
                          provenance=asset.get("generator") or {}, approval_status="approved",
                          validation=validation or existing.get("validation"))


def _sync_recipe_artifacts(recipe_asset, stages, manifest):
    for child_id, stage in stages.items():
        child = manifest["assets"].get(stage["asset_key"])
        if child is None:
            continue
        for artifact_id, artifact in child.get("artifacts", {}).items():
            aggregate_id = f"{child_id}.{artifact_id}"
            register_artifact(manifest, f"recipe:{recipe_asset['name']}", aggregate_id,
                              artifact["type"], artifact["path"], status=artifact["status"],
                              derived_from=[{"asset_id": child["id"], "output_id": artifact_id}],
                              provenance=artifact.get("provenance"),
                              approval_status=artifact.get("approval", {}).get("status", "pending"),
                              validation=artifact.get("validation"))


def _recipe_status(stages):
    states = [stage["status"] for stage in stages.values()]
    if states and all(state == "approved" for state in states):
        return "ready"
    if any(state in {"failed", "blocked"} for state in states):
        return "partial"
    if any(state == "running" for state in states):
        return "running"
    if all(state in {"approved", "completed"} for state in states):
        return "awaiting_approval"
    return "planned"


def _instance_key(instance_name):
    validate_asset_name(instance_name)
    return asset_key("recipe", instance_name)


def run_recipe(project_root, config, style, asset_types, manifest, recipe_name, *, instance_name=None,
               quality_tier=None, reference_library=None, child_overrides=None, save=None):
    root = Path(project_root).resolve()
    definition, children = load_recipe(root, recipe_name, asset_types, reference_library=reference_library)
    overrides = child_overrides or {}
    if not isinstance(overrides, dict) or not set(overrides) <= {child["id"] for child in children}:
        raise ValueError("Recipe child overrides must target known child ids")
    for child in children:
        override = overrides.get(child["id"], {})
        if not isinstance(override, dict) or not set(override) <= {"description", "generation_prompt"}:
            raise ValueError(f"Invalid content override for recipe child {child['id']!r}")
        for field in ("description", "generation_prompt"):
            if field not in override:
                continue
            value = override[field]
            if not isinstance(value, str) or (field == "description" and not value.strip()):
                raise ValueError(f"Recipe child override {field} must be a {'non-empty ' if field == 'description' else ''}string")
            child[field] = value
    tier = quality_tier or definition.get("quality_tier") or config["asset_pipeline"].get("selected_quality_tier", "normal")
    config = select_quality_tier(config, tier)
    definition["quality_tier"] = tier
    for child in children:
        if child.get("quality_tier"):
            select_quality_tier(config, child["quality_tier"])
    for child in children:
        if child.get("reference_library"):
            library = resolve_library(root, child["reference_library"], manifest)
            invalid = [entry for entry in library["entries"] if entry["status"] != "ready"]
            if invalid:
                raise ValueError(f"Recipe reference library {library['id']!r} has missing or changed entries: " +
                                 ", ".join(entry["id"] for entry in invalid))
    instance_name = instance_name or recipe_name
    recipe_key = _instance_key(instance_name)
    if recipe_key in manifest["assets"]:
        raise FileExistsError(f"Recipe run {instance_name!r} already exists; resume it or choose another name")

    recipe_asset = new_record("recipe", instance_name, definition["description"], style, {"strategy": "text_only"})
    stages = {}
    recipe_asset["recipe_instance"] = {
        "definition": copy.deepcopy(definition),
        "definition_path": f"ai/recipes/{recipe_name}.yaml",
        "quality_tier": tier,
        "stages": stages,
    }
    planned_children = []
    for child in children:
        child_name = f"{instance_name}_{child['id']}"
        validate_asset_name(child_name)
        key = asset_key(child["type"], child_name)
        if key in manifest["assets"]:
            raise FileExistsError(f"Recipe child asset {child_name!r} already exists")
        planned_children.append((child, child_name, key))
    manifest["assets"][recipe_key] = recipe_asset
    for child, child_name, key in planned_children:
        asset = new_record(child["type"], child_name, child["description"], style,
                           {"strategy": config.get("asset_pipeline", {}).get("conditioning", {}).get("strategy", "text_only")})
        manifest["assets"][key] = asset
        set_parent(manifest, key, recipe_key)
        stages[child["id"]] = {"asset_key": key, "asset_id": asset["id"], "status": "pending",
                                "depends_on": child["depends_on"], "attempts": 0, "errors": []}
    for child in children:
        key = stages[child["id"]]["asset_key"]
        for dependency_id in child["depends_on"]:
            add_dependency(manifest, key, stages[dependency_id]["asset_key"])
    return _execute(root, config, style, asset_types, manifest, recipe_key, save=save)


def resume_recipe(project_root, config, style, asset_types, manifest, instance_name, *, save=None):
    recipe_key = _instance_key(instance_name)
    if recipe_key not in manifest["assets"] or "recipe_instance" not in manifest["assets"][recipe_key]:
        raise KeyError(f"No recipe run named {instance_name!r}")
    return _execute(Path(project_root).resolve(), config, style, asset_types, manifest, recipe_key, save=save)


def regenerate_child(project_root, config, style, asset_types, manifest, instance_name, child_id, *, save=None):
    recipe_key = _instance_key(instance_name)
    if recipe_key not in manifest["assets"]:
        raise KeyError(f"No recipe run named {instance_name!r}")
    return _execute(Path(project_root).resolve(), config, style, asset_types, manifest, recipe_key,
                    child_id=child_id, regenerate=True, save=save)


def _execute(root, config, style, asset_types, manifest, recipe_key, *, child_id=None, regenerate=False, save=None):
    recipe_asset = manifest["assets"][recipe_key]
    instance = recipe_asset["recipe_instance"]
    config = select_quality_tier(config, instance.get("quality_tier", "normal"))
    definition = instance["definition"]
    children = _ordered_children(definition)
    stages = instance["stages"]
    child_map = {child["id"]: child for child in children}
    if child_id is not None and child_id not in child_map:
        raise KeyError(f"Recipe has no child {child_id!r}")

    for child in children:
        stage = stages[child["id"]]
        asset = manifest["assets"][stage["asset_key"]]
        if asset.get("status") == "ready":
            stage["status"] = "approved"
        elif stage["status"] == "running":
            before = stage.get("candidate_count_before", 0)
            count = len(asset.get("candidates", {}).get("items", []))
            stage["status"] = "completed" if count > before else "pending"
        _sync_child_artifacts(root, asset, stage["asset_key"])
    _sync_recipe_artifacts(recipe_asset, stages, manifest)
    _save(save, manifest)

    selected = {child_id} if child_id is not None else set(child_map)
    for child in children:
        if child["id"] not in selected:
            continue
        stage = stages[child["id"]]
        asset = manifest["assets"][stage["asset_key"]]
        original = {key: copy.deepcopy(asset.get(key)) for key in ("status", "generator", "outputs", "candidates")}
        if not regenerate and stage["status"] in {"completed", "approved"}:
            continue
        if any(stages[dependency]["status"] not in {"completed", "approved"}
               for dependency in child["depends_on"]):
            stage["status"] = "blocked"
            stage["errors"] = ["Dependencies are not complete"]
            recipe_asset["status"] = _recipe_status(stages)
            _sync_recipe_artifacts(recipe_asset, stages, manifest)
            _save(save, manifest)
            continue

        stage["candidate_count_before"] = len(asset.get("candidates", {}).get("items", []))
        stage["status"] = "running"
        stage["quality_tier"] = child.get("quality_tier", instance.get("quality_tier", "normal"))
        stage["attempts"] += 1
        stage["errors"] = []
        recipe_asset["status"] = "running"
        _save(save, manifest)
        try:
            asset_type = asset_types[child["type"]]
            pipeline = asset_type["pipeline"]
            handler = PIPELINE_HANDLERS.get(pipeline)
            if handler is None:
                raise ValueError(f"No recipe handler is registered for pipeline {pipeline!r}")
            tier = stage["quality_tier"]
            child_config = select_quality_tier(config, tier)
            result = handler(root, child_config, style, asset_type, child, manifest, stage["asset_key"])
            generated = [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []
            _sync_child_artifacts(root, asset, stage["asset_key"])
            successful = any(item.get("status") == "candidate" for item in generated)
            if not successful:
                raise RuntimeError(f"No valid candidates generated for recipe child {child['id']!r}")
            if original.get("status") == "ready":
                asset["status"] = original["status"]
                asset["generator"] = original.get("generator")
                asset["outputs"] = original.get("outputs", {})
                asset["candidates"]["selected"] = original.get("candidates", {}).get("selected")
            stage["status"] = "approved" if asset.get("status") == "ready" else "completed"
            stage["provenance"] = copy.deepcopy(asset.get("generator", {}))
        except Exception as exc:
            if original.get("status") == "ready":
                asset.update({key: value for key, value in original.items() if value is not None})
                stage["status"] = "approved"
            else:
                stage["status"] = "failed"
            stage["errors"] = [str(exc)]
        recipe_asset["status"] = _recipe_status(stages)
        _sync_child_artifacts(root, asset, stage["asset_key"])
        _sync_recipe_artifacts(recipe_asset, stages, manifest)
        _save(save, manifest)

    recipe_asset["status"] = _recipe_status(stages)
    _sync_recipe_artifacts(recipe_asset, stages, manifest)
    _save(save, manifest)
    return recipe_asset
