import hashlib
import re
from pathlib import Path

import yaml


REQUIRED = ("name", "version", "identity", "shape_language", "palette", "materials", "surface_language", "lighting", "asset_rules", "material_generation")


def style_identity(style):
    data = {key: value for key, value in style.items() if not key.startswith("_")}
    digest = hashlib.sha256(yaml.safe_dump(data, sort_keys=True).encode()).hexdigest()
    return {"key": style.get("_key"), "name": style["name"], "version": style["version"], "sha256": digest}


def load_style(project_root, config=None):
    root = Path(project_root).resolve()
    if config is None:
        from .config import load_project
        config = load_project(root)
    key = config["asset_pipeline"]["active_style"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise ValueError(f"Invalid style pack name: {key}")
    directory = root / "ai/styles" / key
    path = directory / "style.yaml"
    if not path.is_file():
        raise ValueError(f"Active style pack not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    missing = [field for field in REQUIRED if field not in data]
    if missing:
        raise ValueError(f"Style pack {key} missing required fields: {', '.join(missing)}")
    for field in ("identity", "shape_language", "palette", "materials", "surface_language", "lighting", "asset_rules", "material_generation"):
        if not isinstance(data[field], dict):
            raise ValueError(f"Style pack field {field} must be a mapping")
    data["_key"] = key
    data["_directory"] = directory
    return data


def _bullets(values):
    if not values:
        return "- none specified"
    return "\n".join(f"- {value}" for value in values)


def build_prompt(style, asset_type, description, mode="asset"):
    identity = style["identity"]
    palette = "\n".join(f"- {key}: {value.get('hex', '')} — {value.get('usage', '')}" for key, value in style["palette"].items())
    materials = "\n".join(f"- {key}: {value.get('description', '')}" for key, value in style["materials"].items())
    if mode == "material":
        rules = style["material_generation"].get("rules", [])
        requirements = asset_type.get("requirements", []) if asset_type.get("pipeline") != "model" else []
        avoid = asset_type.get("avoid", []) if asset_type.get("pipeline") != "model" else []
        return f"PROJECT STYLE: {style['name']} v{style['version']}\n{identity.get('genre', '')}; {identity.get('rendering', '')}\nPALETTE:\n{palette}\nMATERIAL LANGUAGE:\n{materials}\nMATERIAL RULES:\n{_bullets(rules)}\nASSET TYPE REQUIREMENTS:\n{_bullets(requirements)}\nASSET TYPE AVOID:\n{_bullets(avoid)}\nASSET DESCRIPTION:\n{description}\nCreate a flat material surface consistent with this style, filling the frame. Surface only: no standalone object, no environment, no perspective, no text, no cast shadows or baked lighting."
    rules = list(asset_type.get("requirements", []))
    if asset_type["pipeline"] == "model":
        rules.extend([
            "Complete centered asset with margin around every extremity; plain neutral background, no scene or cast shadow",
            "Soft even studio lighting that clearly reveals local color and material boundaries; no dramatic shadows or baked highlights",
            "Sharp readable surface detail and distinct material regions; no depth of field, motion blur, text, or watermark",
        ])
    avoid = asset_type.get("avoid", [])
    project_rules = style["asset_rules"].get(asset_type["name"], [])
    if asset_type["pipeline"] == "model" and not project_rules:
        project_rules = style["asset_rules"].get("model", [])
    lighting = _bullets([f"{key}: {value}" for key, value in style["lighting"].items()])
    composition = _bullets([f"{key}: {value}" for key, value in style.get("composition", {}).items()])
    return f"PROJECT ART DIRECTION: {style['name']}\nSTYLE VERSION: {style['version']}\nGENRE: {identity.get('genre', '')}\nRENDERING: {identity.get('rendering', '')}\nDETAIL LEVEL: {identity.get('detail_level', '')}\nMOOD:\n{_bullets(identity.get('mood', []))}\nSHAPE LANGUAGE:\n{_bullets(style['shape_language'].get('preferred', []))}\nAVOID:\n{_bullets(style['shape_language'].get('avoid', []))}\nPALETTE:\n{palette}\nMATERIALS:\n{materials}\nSURFACE LANGUAGE:\n{_bullets(style['surface_language'].get('preferred', []))}\nSURFACE AVOID:\n{_bullets(style['surface_language'].get('avoid', []))}\nLIGHTING:\n{lighting}\nCOMPOSITION:\n{composition}\nASSET TYPE REQUIREMENTS:\n{_bullets(rules)}\nASSET TYPE AVOID:\n{_bullets(avoid)}\nSTYLE-SPECIFIC ASSET RULES:\n{_bullets(project_rules)}\nREQUESTED ASSET:\n{description}"
