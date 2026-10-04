import os
import re
from pathlib import Path

import yaml


DEFAULTS = {
    "output_root": "Assets/Art/Generated",
    "candidate_root": "ai/assets/candidates",
    "manifest": "ai/assets/manifest.json",
    "defaults": {"image_candidates": 4, "model_candidates": 2, "material_candidates": 2},
    "model_budgets": {"prop_faces": 30000, "hero_prop_faces": 60000, "architecture_faces": 60000, "collectible_faces": 20000},
    "workflows": {"image": "image_text2img_api.json"},
    "tools": {"comfy_url": "http://127.0.0.1:8188", "comfy_backend": "auto", "comfy_home": None, "blender": None, "asset_python": None, "hunyuan_checkpoint": "hunyuan3d-dit-v2_fp16.safetensors"},
    "compute_profile": "default",
    "compute_profiles": {},
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
    return result
