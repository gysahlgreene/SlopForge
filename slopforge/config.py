import os
import re
import copy
from pathlib import Path

import yaml


DEFAULTS = {
    "output_root": "Assets/Art/Generated",
    "candidate_root": "ai/assets/candidates",
    "manifest": "ai/assets/manifest.json",
    "defaults": {"image_candidates": 4, "model_candidates": 2, "material_candidates": 2},
    "model_budgets": {"prop_faces": 30000, "hero_prop_faces": 60000, "architecture_faces": 60000,
                      "collectible_faces": 20000, "character_faces": 60000},
    "character_rigging_provider": "blender_rigify",
    "workflows": {"image": "image_text2img_api.json"},
    "tools": {"comfy_url": "http://127.0.0.1:8188", "comfy_backend": "auto", "comfy_home": None, "blender": None, "asset_python": None, "hunyuan_checkpoint": "hunyuan3d-dit-v2_fp16.safetensors"},
    "compute_profile": "default",
    "compute_profiles": {},
    "quality_tier": "normal",
    "quality_tiers": {
        "draft": {"defaults": {"image_candidates": 1, "model_candidates": 1, "material_candidates": 1}},
        "normal": {},
        "final": {"defaults": {"image_candidates": 6, "model_candidates": 3, "material_candidates": 3}},
    },
    "conditioning": {"strategy": "text_only", "max_references": 3, "strength": 0.65, "workflow_inputs": []},
    "overwrite_existing": False,
    "retain_sources": True,
    "retain_blend_preview": True,
}


def _merge(base, update):
    result = dict(base)
    for key, value in update.items():
        result[key] = _merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def select_quality_tier(config, tier=None):
    result = copy.deepcopy(config)
    base = copy.deepcopy(config.get("_quality_base_pipeline", config["asset_pipeline"]))
    selected = tier or os.environ.get("SLOPFORGE_QUALITY_TIER") or base.get("quality_tier", "normal")
    tiers = base.get("quality_tiers", DEFAULTS["quality_tiers"])
    if not isinstance(selected, str) or selected not in tiers:
        raise ValueError(f"Unknown quality tier {selected!r}; define it in asset_pipeline.quality_tiers")
    settings = tiers[selected]
    if not isinstance(settings, dict):
        raise ValueError(f"Quality tier {selected!r} must be a mapping")
    unsupported = set(settings) - {"defaults", "workflows", "model_budgets", "workflow_inputs", "estimate"}
    if unsupported:
        raise ValueError(f"Quality tier {selected!r} has unsupported settings: {', '.join(sorted(unsupported))}")
    effective = _merge(base, {key: value for key, value in settings.items() if key != "estimate"})
    profile_workflows = config.get("_compute_profile_workflows", {})
    if profile_workflows:
        effective = _merge(effective, {"workflows": profile_workflows})
    effective["quality_tier"] = selected
    effective["selected_quality_tier"] = selected
    effective["quality_settings"] = copy.deepcopy(settings)
    result["asset_pipeline"] = effective
    result["_quality_base_pipeline"] = base
    return result


def workflow_node_inputs(config, stage, workflow):
    settings = config["asset_pipeline"].get("quality_settings", {})
    by_workflow = settings.get("workflow_inputs", {}).get(stage, {})
    if not isinstance(by_workflow, dict):
        raise ValueError(f"Quality workflow_inputs.{stage} must map workflow names to node inputs")
    selected = by_workflow.get(Path(workflow).name, by_workflow.get("*", {}))
    if not isinstance(selected, dict):
        raise ValueError(f"Quality workflow inputs for {workflow!r} must be a node/input mapping")
    return selected


def load_project(project_root):
    root = Path(project_root).expanduser().resolve()
    path = root / "ai/project.yaml"
    if not path.is_file():
        raise ValueError(f"Missing project config: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    project = data.get("project")
    pipeline = data.get("asset_pipeline")
    if not isinstance(project, dict) or not isinstance(pipeline, dict):
        raise ValueError("ai/project.yaml requires project: and asset_pipeline: mappings")
    active_style = pipeline.get("active_style")
    if not isinstance(active_style, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", active_style):
        raise ValueError("asset_pipeline.active_style must be a simple style-pack name")
    result = dict(data)
    result["project"] = project
    result["asset_pipeline"] = _merge(DEFAULTS, pipeline)
    result["_project_root"] = root
    tools = result["asset_pipeline"]["tools"]
    env_url = os.environ.get("COMFYUI_URL")
    if env_url:
        tools["comfy_url"] = env_url.rstrip("/")
    env_backend = os.environ.get("SLOPFORGE_COMFYUI_BACKEND")
    if env_backend:
        tools["comfy_backend"] = env_backend
    env_home = os.environ.get("COMFYUI_HOME")
    if env_home:
        tools["comfy_home"] = env_home
    env_blender = os.environ.get("BLENDER_BIN")
    if env_blender:
        tools["blender"] = env_blender
    env_python = os.environ.get("SLOPFORGE_PYTHON")
    if env_python:
        tools["asset_python"] = env_python
    profile = os.environ.get("SLOPFORGE_COMPUTE_PROFILE", result["asset_pipeline"].get("compute_profile", "default"))
    profiles = result["asset_pipeline"].get("compute_profiles", {})
    if profile != "default" and profile not in profiles:
        raise ValueError(f"Unknown compute profile {profile!r}; define it in asset_pipeline.compute_profiles")
    overrides = profiles.get(profile, {})
    for key, value in overrides.items():
        if key == "tools" and isinstance(value, dict):
            value = {name: item for name, item in value.items()
                     if name not in {"comfy_url", "comfy_backend", "comfy_home"}}
        if isinstance(value, dict) and isinstance(result["asset_pipeline"].get(key), dict):
            result["asset_pipeline"][key] = _merge(result["asset_pipeline"][key], value)
        else:
            result["asset_pipeline"][key] = value
    result["asset_pipeline"]["selected_compute_profile"] = profile
    result["_compute_profile_workflows"] = copy.deepcopy(overrides.get("workflows", {}))
    result["_quality_base_pipeline"] = copy.deepcopy(result["asset_pipeline"])
    quality_tier = os.environ.get("SLOPFORGE_QUALITY_TIER", result["asset_pipeline"].get("quality_tier", "normal"))
    return select_quality_tier(result, quality_tier)
