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


MATERIAL_CLASSES = {
    "nonmetal": "matte non-metallic surface; no mirror-like reflections or polished highlights",
    "metal": "metallic surface with visible metal sheen",
    # Image-to-3D reads glowing or translucent regions as empty space (issue #44), so concepts show emissive
    # regions unlit; the material stage adds the glow. Naming the glow ("switched off, not glowing") drew it lit
    # in every concept, so the rule only describes the unlit look (docs/MATERIALS.md, Known limits).
    "emissive": "a solid opaque surface with a dull matte finish in its own flat daytime colour",
    # Glass drawn see-through reconstructed as shattered shards (2026-10-22 potion bottle); drawn as a solid tinted
    # surface it came out whole. The material stage makes it see-through (docs/MATERIALS.md, Glass).
    "glass": "a solid smooth glossy surface in its own tint with a faint sheen; nothing visible through it and nothing inside it",
}


def parse_material_spec(spec):
    """Parse 'region=class[: description]'; class is nonmetal, metal, emissive[#rrggbb] or glass[#rrggbb].

    The optional colour is the region's base colour in the concept; the material stage matches it in the
    generated base colour map (emitters glow in it, glass turns see-through there). Without one, the region is
    found as the map's pale near-neutral area.
    """
    region, separator, rest = spec.partition("=")
    material_class, _, detail = rest.partition(":")
    material_class, _, color = material_class.strip().lower().partition("#")
    region, detail = region.strip(), detail.strip()
    valid_color = not color or (material_class in ("emissive", "glass") and len(color) == 6
                                and all(c in "0123456789abcdef" for c in color))
    if not separator or not region or material_class not in MATERIAL_CLASSES or not valid_color:
        raise ValueError("--material must be 'region=nonmetal|metal|emissive[#rrggbb]|glass[#rrggbb][: description]', "
                         f"got {spec!r}")
    item = {"region": region, "class": material_class, "description": detail}
    if color:
        item["color"] = "#" + color
    return item


def reconstruction_rules(asset_type, materials=()):
    """Rules every image-to-3D concept needs, appended even to agent-authored prompts."""
    if asset_type.get("pipeline") != "model":
        return ""
    lines = ["RECONSTRUCTION REQUIREMENTS:",
             "- Complete centered asset with margin around every extremity; plain neutral background, no scene or cast shadow",
             "- Soft even studio lighting that clearly reveals local color and material boundaries; no dramatic shadows or baked highlights",
             "- Sharp readable surface detail and distinct material regions; no depth of field, motion blur, text, or watermark",
             "- Solid chunky forms with thick walls; no thin hollow tubes, open rings, wires, or paper-thin parts"]
    if asset_type.get("prompt_mode") == "character":
        # Hands touching the thighs reconstruct as fused geometry that tears when the arm moves.
        lines.append("- Arms held 30 to 45 degrees from the body with a clear gap between each hand and the hips "
                     "and thighs; fingers together, hands not touching the body or clothing")
    if materials:
        lines.append("MATERIAL REGIONS:")
        lines.extend(f"- {item['region']}: {item['description'] + '; ' if item['description'] else ''}"
                     f"{MATERIAL_CLASSES[item['class']]}" for item in materials)
    return "\n".join(lines)


def build_prompt(style, asset_type, description, mode="asset", materials=()):
    identity = style["identity"]
    palette = "\n".join(f"- {key}: {value.get('hex', '')} — {value.get('usage', '')}" for key, value in style["palette"].items())
    style_materials = "\n".join(f"- {key}: {value.get('description', '')}" for key, value in style["materials"].items())
    if mode == "material":
        rules = style["material_generation"].get("rules", [])
        requirements = asset_type.get("requirements", []) if asset_type.get("pipeline") != "model" else []
        avoid = asset_type.get("avoid", []) if asset_type.get("pipeline") != "model" else []
        return f"PROJECT STYLE: {style['name']} v{style['version']}\n{identity.get('genre', '')}; {identity.get('rendering', '')}\nPALETTE:\n{palette}\nMATERIAL LANGUAGE:\n{style_materials}\nMATERIAL RULES:\n{_bullets(rules)}\nASSET TYPE REQUIREMENTS:\n{_bullets(requirements)}\nASSET TYPE AVOID:\n{_bullets(avoid)}\nASSET DESCRIPTION:\n{description}\nCreate a flat material surface consistent with this style, filling the frame. Surface only: no standalone object, no environment, no perspective, no text, no cast shadows or baked lighting."
    rules = list(asset_type.get("requirements", []))
    avoid = asset_type.get("avoid", [])
    project_rules = style["asset_rules"].get(asset_type["name"], [])
    if asset_type["pipeline"] == "model" and not project_rules:
        project_rules = style["asset_rules"].get("model", [])
    lighting = _bullets([f"{key}: {value}" for key, value in style["lighting"].items()])
    composition = _bullets([f"{key}: {value}" for key, value in style.get("composition", {}).items()])
    return f"PROJECT ART DIRECTION: {style['name']}\nSTYLE VERSION: {style['version']}\nGENRE: {identity.get('genre', '')}\nRENDERING: {identity.get('rendering', '')}\nDETAIL LEVEL: {identity.get('detail_level', '')}\nMOOD:\n{_bullets(identity.get('mood', []))}\nSHAPE LANGUAGE:\n{_bullets(style['shape_language'].get('preferred', []))}\nAVOID:\n{_bullets(style['shape_language'].get('avoid', []))}\nPALETTE:\n{palette}\nMATERIALS:\n{style_materials}\nSURFACE LANGUAGE:\n{_bullets(style['surface_language'].get('preferred', []))}\nSURFACE AVOID:\n{_bullets(style['surface_language'].get('avoid', []))}\nLIGHTING:\n{lighting}\nCOMPOSITION:\n{composition}\nASSET TYPE REQUIREMENTS:\n{_bullets(rules)}\nASSET TYPE AVOID:\n{_bullets(avoid)}\nSTYLE-SPECIFIC ASSET RULES:\n{_bullets(project_rules)}\nREQUESTED ASSET:\n{description}" + (
        "\n" + reconstruction_rules(asset_type, materials) if asset_type["pipeline"] == "model" else "")
