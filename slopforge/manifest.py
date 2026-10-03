import copy
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import SCHEMA_VERSION


def asset_key(asset_type, name):
    return f"{asset_type}:{name}"


def _migrate(data):
    if data.get("schema_version") == SCHEMA_VERSION:
        return data
    old_style = data.get("style", {})
    assets = {}
    for key, old in data.get("assets", {}).items():
        assets[key] = {
            "id": old.get("id") or str(uuid.uuid4()),
            "name": old.get("name", key),
            "type": old.get("type"),
            "description": old.get("description", old.get("prompt", "")),
            "style": old.get("style", old_style.get("name")),
            "style_version": old.get("style_version", old_style.get("version")),
            "status": old.get("status", "ready"),
            "created_at": old.get("created_at", old.get("generated_at")),
            "generator": {"workflow": old.get("workflow"), "model": None, "seed": None},
            "conditioning": {"strategy": "text_only", "references_used": []},
            "candidates": {"items": [], "selected": None},
            "source": {
                k: v
                for k, v in (
                    ("concept", old.get("concept")),
                    ("glb", old.get("source")),
                )
                if v
            },
            "outputs": {
                k: v
                for k, v in (
                    ("asset", old.get("asset")),
                    ("preview_blend", old.get("preview")),
                )
                if v
            },
            "validation": {
                "status": "unknown",
                "warnings": [
                    "Migrated legacy manifest entry; validation facts were not recorded."
                ],
                "measured": {},
            },
            "legacy": copy.deepcopy(old),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "active_style": {
            "name": old_style.get("name"),
            "version": old_style.get("version"),
        },
        "assets": assets,
    }


def load_manifest(path):
    path = Path(path)
    return (
        _migrate(json.loads(path.read_text()))
        if path.is_file()
        else {"schema_version": SCHEMA_VERSION, "active_style": {}, "assets": {}}
    )


def save_manifest(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def find_asset(manifest, selector):
    exact = manifest["assets"].get(selector)
    if exact:
        return exact
    found = [
        asset
        for asset in manifest["assets"].values()
        if asset.get("name") == selector or asset.get("id") == selector
    ]
    if len(found) != 1:
        if not found:
            raise KeyError(f"No asset named {selector!r}")
        raise ValueError(f"Asset name {selector!r} is ambiguous; use its asset id")
    return found[0]


def add_candidate(manifest, key, candidate):
    asset = manifest["assets"][key]
    asset.setdefault("candidates", {"items": [], "selected": None})["items"].append(
        candidate
    )
    asset["status"] = "candidate"


def new_record(asset_type, name, description, style, conditioning):
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "type": asset_type,
        "description": description,
        "style": style["name"],
        "style_version": style["version"],
        "status": "planned",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generator": {"workflow": None, "model": None, "seed": None},
        "conditioning": {"strategy": conditioning["strategy"], "references_used": []},
        "candidates": {"items": [], "selected": None},
        "source": {},
        "outputs": {},
        "validation": {"status": "not_run", "warnings": [], "measured": {}},
    }
