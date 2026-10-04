"""Approval-gated orchestration of existing recipes into prototype plans."""
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import recipes
from .config import select_quality_tier
from .manifest import add_dependency, asset_key, new_record, set_parent
from .taxonomy import validate_asset_name


def plan_path(project_root, name):
    validate_asset_name(name)
    return Path(project_root) / "ai/prototypes" / f"{name}.yaml"


def _fingerprint(plan):
    value = copy.deepcopy(plan)
    value.pop("approval", None)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _candidate_estimate(config, children, asset_types, tier):
    total = 0
    for child in children:
        pipeline = asset_types[child["type"]]["pipeline"]
        defaults = select_quality_tier(config, child.get("quality_tier", tier))["asset_pipeline"]["defaults"]
        count_key = "image_candidates" if pipeline == "image" else "model_candidates"
        total += child.get("count", defaults[count_key])
    return total


def propose(project_root, name, description, style, asset_types, config, *, recipe_names=None,
            quality_tier="draft", candidate_budget=None):
    root = Path(project_root).resolve()
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Prototype description must not be empty")
    path = plan_path(root, name)
    if path.exists():
        raise FileExistsError(f"Prototype plan already exists: {path}")
    available = recipes.list_recipes(root)
    selected = recipe_names or available
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Select at least one unique recipe")
    stages = []
    contents = []
    estimated_candidates = 0
    for index, recipe_name in enumerate(selected):
        definition, children = recipes.load_recipe(root, recipe_name, asset_types)
        stage_id = recipe_name
        stages.append({"id": stage_id, "recipe": recipe_name,
                       "depends_on": [stages[-1]["id"]] if stages else [],
                       "quality_tier": quality_tier})
        contents.extend({"stage": stage_id, "id": child["id"], "type": child["type"],
                         "description": child["description"],
                         **({"generation_prompt": child["generation_prompt"]}
                            if child.get("generation_prompt") is not None else {})} for child in children)
        estimated_candidates += _candidate_estimate(config, children, asset_types, quality_tier)
    plan = {"version": 1, "id": name, "description": description,
            "art_direction": {"brief": description, "style": style["name"], "style_version": style["version"]},
            "quality_tier": quality_tier, "candidate_budget": 100 if candidate_budget is None else candidate_budget,
            "estimated_candidates": estimated_candidates,
            "content_plan": contents, "stages": stages, "approval": {"status": "proposed"}}
    if type(plan["candidate_budget"]) is not int or plan["candidate_budget"] < 1:
        raise ValueError("candidate_budget must be a positive integer")
    # Validate the tier before a plan can be approved and run.
    select_quality_tier(config, quality_tier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True))
    return plan


def load_plan(project_root, name, *, check_approval=True):
    path = plan_path(project_root, name)
    if not path.is_file():
        raise FileNotFoundError(f"Prototype plan not found: {path}")
    plan = yaml.safe_load(path.read_text())
    if not isinstance(plan, dict) or plan.get("version") != 1 or plan.get("id") != name:
        raise ValueError("Prototype plan version/id does not match its file")
    stages = plan.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError("Prototype plan requires stages")
    ids = [stage.get("id") if isinstance(stage, dict) else None for stage in stages]
    if any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("Prototype stage ids must be unique strings")
    for stage_id in ids:
        validate_asset_name(stage_id)
    known, done = set(ids), set()
    positions = {stage_id: index for index, stage_id in enumerate(ids)}
    for index, stage in enumerate(stages):
        if not isinstance(stage.get("recipe"), str) or not isinstance(stage.get("depends_on", []), list):
            raise ValueError("Prototype stages require a recipe and dependency list")
        deps = stage.get("depends_on", [])
        if stage["id"] in deps:
            raise ValueError(f"Prototype stage dependencies contain a cycle at {stage['id']!r}")
        if any(dep not in known for dep in deps):
            raise ValueError(f"Invalid dependencies for prototype stage {stage['id']!r}")
        if len(set(deps)) != len(deps) or any(positions[dependency] >= index for dependency in deps):
            raise ValueError("Prototype stages must list dependencies before their dependents")
        if stage.get("quality_tier") is not None and not isinstance(stage["quality_tier"], str):
            raise ValueError(f"Prototype stage {stage['id']!r} quality_tier must be a string")
    content_plan = plan.get("content_plan", [])
    if not isinstance(content_plan, list):
        raise ValueError("Prototype content_plan must be a list")
    content_ids = set()
    for child in content_plan:
        if (not isinstance(child, dict) or child.get("stage") not in known
                or not isinstance(child.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", child["id"])
                or not isinstance(child.get("type"), str) or not isinstance(child.get("description"), str)
                or not child["description"].strip()):
            raise ValueError("Prototype content items require a known stage, id, type, and description")
        key = (child["stage"], child["id"])
        if key in content_ids:
            raise ValueError(f"Duplicate prototype content item {key[0]}:{key[1]}")
        content_ids.add(key)
        if child.get("generation_prompt") is not None and not isinstance(child["generation_prompt"], str):
            raise ValueError(f"Prototype content item {key[0]}:{key[1]} generation_prompt must be a string")
    pending = list(stages)
    while pending:
        ready = next((stage for stage in pending if set(stage.get("depends_on", [])) <= done), None)
        if ready is None:
            raise ValueError("Prototype stage dependencies contain a cycle")
        done.add(ready["id"])
        pending.remove(ready)
    if type(plan.get("candidate_budget")) is not int or plan["candidate_budget"] < 1:
        raise ValueError("candidate_budget must be a positive integer")
    if check_approval and plan.get("approval", {}).get("status") == "approved":
        if plan["approval"].get("fingerprint") != _fingerprint(plan):
            raise ValueError("Prototype plan changed after approval; approve the edited plan again")
    return plan


def approve(project_root, name):
    plan = load_plan(project_root, name, check_approval=False)
    plan["approval"] = {"status": "approved", "approved_at": datetime.now(timezone.utc).isoformat(),
                        "fingerprint": _fingerprint(plan)}
    path = plan_path(project_root, name)
    path.write_text(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True))
    return plan


def _instance_key(name):
    return asset_key("prototype", name)


def _candidate_count(manifest, recipe_asset):
    recipe_id = recipe_asset["id"]
    return sum(len(child.get("candidates", {}).get("items", []))
               for child in manifest["assets"].values() if child.get("parent_id") == recipe_id)


def _child_overrides(plan, stage_id, children):
    by_id = {child["id"]: child for child in children}
    overrides = {}
    for item in plan.get("content_plan", []):
        if item.get("stage") != stage_id:
            continue
        child = by_id.get(item["id"])
        if child is None or item.get("type") != child["type"]:
            raise ValueError(f"Prototype content item {stage_id}:{item['id']} does not match its recipe child")
        overrides[item["id"]] = {field: item[field] for field in ("description", "generation_prompt")
                                  if field in item}
    return overrides


def run(project_root, config, style, asset_types, manifest, name, *, save=None):
    root = Path(project_root).resolve()
    plan = load_plan(root, name)
    if plan.get("approval", {}).get("status") != "approved":
        raise ValueError("Prototype plan must be explicitly approved before generation")
    for stage in plan["stages"]:
        recipes.load_recipe(root, stage["recipe"], asset_types)
        select_quality_tier(config, stage.get("quality_tier", plan["quality_tier"]))
    prototype_key = _instance_key(name)
    if prototype_key not in manifest["assets"]:
        record = new_record("prototype", name, plan["description"], style, {"strategy": "text_only"})
        record["prototype"] = {"plan_path": plan_path(root, name).relative_to(root).as_posix(),
                                "plan_fingerprint": plan["approval"]["fingerprint"],
                                "quality_tier": plan["quality_tier"], "candidate_budget": plan["candidate_budget"],
                                "stages": {stage["id"]: {"recipe": stage["recipe"],
                                    "instance": f"{name}_{stage['id']}", "depends_on": list(stage.get("depends_on", [])),
                                    "status": "pending", "attempts": 0, "errors": []} for stage in plan["stages"]}}
        manifest["assets"][prototype_key] = record
    prototype = manifest["assets"][prototype_key]
    if prototype.get("prototype", {}).get("plan_fingerprint") != plan["approval"]["fingerprint"]:
        raise ValueError("Prototype plan differs from the manifest snapshot; create a new plan name")
    stages = prototype["prototype"]["stages"]
    plan_stages = {stage["id"]: stage for stage in plan["stages"]}
    already_generated = sum(_candidate_count(manifest, record) for record in manifest["assets"].values()
                            if record.get("type") == "recipe" and record.get("parent_id") == prototype["id"])
    for stage_id, stage_state in stages.items():
        if any(stages[dependency]["status"] != "approved" for dependency in stage_state["depends_on"]):
            stage_state["status"] = "blocked"
            stage_state["errors"] = ["Dependencies require approved outputs"]
            continue
        recipe_name = stage_state["recipe"]
        instance_name = stage_state["instance"]
        definition, children = recipes.load_recipe(root, recipe_name, asset_types)
        stage_tier = plan_stages[stage_id].get("quality_tier", plan["quality_tier"])
        effective = select_quality_tier(config, stage_tier)
        estimate = _candidate_estimate(config, children, asset_types, stage_tier)
        recipe_key = asset_key("recipe", instance_name)
        recipe_asset = manifest["assets"].get(recipe_key)
        no_inference_needed = recipe_asset and recipe_asset.get("status") in {"ready", "awaiting_approval"}
        if (not no_inference_needed and already_generated + estimate > plan["candidate_budget"]):
            stage_state["status"] = "blocked"
            stage_state["errors"] = [f"Stage estimate ({estimate}) exceeds remaining candidate budget"]
            continue
        if stage_state["status"] in {"approved", "ready"} and no_inference_needed and recipe_asset["status"] == "ready":
            continue
        stage_state["status"] = "running"
        stage_state["attempts"] += 1
        stage_state["errors"] = []
        if save:
            save(manifest)
        try:
            existing = recipe_key in manifest["assets"]
            recipe_asset = (recipes.resume_recipe(root, config, style, asset_types, manifest, instance_name, save=save)
                            if existing else recipes.run_recipe(root, effective, style, asset_types, manifest,
                                recipe_name, instance_name=instance_name, quality_tier=stage_tier,
                                child_overrides=_child_overrides(plan, stage_id, children), save=save))
            if recipe_asset.get("parent_id") is None:
                set_parent(manifest, recipe_asset["id"], prototype["id"])
            for dependency_id in stage_state["depends_on"]:
                previous = stages[dependency_id]
                add_dependency(manifest, recipe_asset["id"], asset_key("recipe", previous["instance"]))
            stage_state["status"] = "approved" if recipe_asset["status"] == "ready" else recipe_asset["status"]
            stage_state["provenance"] = {"recipe": recipe_name, "quality_tier": stage_tier,
                                          "plan_fingerprint": plan["approval"]["fingerprint"]}
            if stage_state["status"] in {"partial", "failed"}:
                stage_state["errors"] = [error for child_stage in recipe_asset.get("recipe_instance", {}).get("stages", {}).values()
                                          for error in child_stage.get("errors", [])]
            already_generated = sum(_candidate_count(manifest, record) for record in manifest["assets"].values()
                                    if record.get("type") == "recipe" and record.get("parent_id") == prototype["id"])
        except Exception as exc:
            stage_state["status"] = "partial"
            stage_state["errors"] = [str(exc)]
        if save:
            save(manifest)
    statuses = [stage["status"] for stage in stages.values()]
    if all(status == "approved" for status in statuses):
        prototype["status"] = "ready"
    elif any(status in {"partial", "failed"} for status in statuses) or any(
            stage["status"] == "blocked" and stage["errors"] != ["Dependencies require approved outputs"]
            for stage in stages.values()):
        prototype["status"] = "partial"
    elif any(status == "awaiting_approval" for status in statuses):
        prototype["status"] = "awaiting_approval"
    elif any(status == "blocked" for status in statuses):
        prototype["status"] = "planned"
    else:
        prototype["status"] = "planned"
    prototype["prototype"]["candidate_count"] = already_generated
    prototype["prototype"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    if save:
        save(manifest)
    return prototype
