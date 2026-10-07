import re
from pathlib import Path

import yaml


LEGACY_ALIASES = {"model": "prop"}


def load_taxonomy(project_root):
    root = Path(project_root) / "ai/asset_types"
    types = {}
    if not root.is_dir():
        raise ValueError(f"Missing asset taxonomy directory: {root}")
    for path in sorted(root.glob("*.yaml")):
        item = yaml.safe_load(path.read_text()) or {}
        name = item.get("name", path.stem)
        if name != path.stem or item.get("pipeline") not in {"image", "model"}:
            raise ValueError(f"Invalid asset type definition: {path}")
        if not isinstance(item.get("requirements", []), list) or not isinstance(item.get("avoid", []), list):
            raise ValueError(f"Asset type requirements and avoid must be lists: {path}")
        types[name] = item
    if not types:
        raise ValueError(f"No asset type definitions found in {root}")
    return types


def canonical_type(asset_type, types):
    selected = LEGACY_ALIASES.get(asset_type, asset_type)
    if selected not in types:
        raise ValueError(f"Unknown asset type {asset_type!r}; available: {', '.join(sorted(types))}")
    return selected


def validate_asset_name(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
        raise ValueError("Asset name may contain only letters, digits, underscores, and hyphens")


def output_path(project_root, config, asset_type, name, extension=None):
    validate_asset_name(name)
    if isinstance(asset_type, str):
        asset_type = load_taxonomy(project_root)[canonical_type(asset_type, load_taxonomy(project_root))]
    root = Path(project_root).resolve() / config["asset_pipeline"]["output_root"]
    pipeline = asset_type["pipeline"]
    folder = asset_type.get("output_folder")
    if folder is None:
        return None
    path = root / folder / name
    return path.with_suffix(extension or ".png") if pipeline == "image" else path
