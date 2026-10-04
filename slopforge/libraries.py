import hashlib
import re
from pathlib import Path

import yaml


_ID = re.compile(r"[A-Za-z0-9_-]+\Z")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _library_path(root, selector):
    parts = selector.split("/") if isinstance(selector, str) else []
    if len(parts) != 2 or any(not _ID.fullmatch(part) for part in parts):
        raise ValueError("Library selector must be a kind/name pair, such as character/alice")
    return Path(root) / "ai/libraries" / parts[0] / f"{parts[1]}.yaml"


def list_libraries(project_root):
    root = Path(project_root).resolve() / "ai/libraries"
    if not root.is_dir():
        return []
    return sorted(f"{path.parent.name}/{path.stem}" for path in root.glob("*/*.yaml") if path.is_file())


def _approved_asset_path(manifest, source):
    assets = [asset for asset in manifest.get("assets", {}).values() if asset.get("id") == source.get("asset_id")]
    if len(assets) != 1:
        raise ValueError(f"Library references unknown or ambiguous asset id {source.get('asset_id')!r}")
    asset = assets[0]
    output_id = source.get("output_id")
    artifact = asset.get("artifacts", {}).get(output_id)
    if artifact:
        if artifact.get("approval", {}).get("status") != "approved":
            raise ValueError(f"Library output {output_id!r} on {asset.get('name')!r} is not approved")
        path = artifact.get("path")
    else:
        selected = asset.get("candidates", {}).get("selected")
        approved_candidate = any(item.get("number") == selected and item.get("approval") == "approved"
                                 for item in asset.get("candidates", {}).get("items", []))
        if asset.get("status") != "ready" or not approved_candidate:
            raise ValueError(f"Library asset {asset.get('name')!r} is not approved")
        path = asset.get("outputs", {}).get(output_id)
    if not path:
        raise ValueError(f"Library output {output_id!r} does not exist on {asset.get('name')!r}")
    return path


def resolve_library(project_root, selector, manifest=None):
    root = Path(project_root).expanduser().resolve()
    path = _library_path(root, selector)
    if not path.is_file():
        raise FileNotFoundError(f"Reference library not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ValueError(f"Reference library must contain an entries list: {path}")
    selector_kind, selector_name = selector.split("/")
    if data.get("kind", selector_kind) != selector_kind:
        raise ValueError(f"Reference library kind must match its path: {path}")
    identifiers = set()
    entries = []
    for order, entry in enumerate(data["entries"]):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"].strip():
            raise ValueError(f"Reference library entry {order + 1} requires a non-empty id")
        if entry["id"] in identifiers:
            raise ValueError(f"Duplicate reference library entry id {entry['id']!r}")
        identifiers.add(entry["id"])
        has_path, has_asset = "path" in entry, "asset" in entry
        if has_path == has_asset:
            raise ValueError(f"Reference library entry {entry['id']!r} must define exactly one of path or asset")
        if has_asset and not isinstance(entry["asset"], dict):
            raise ValueError(f"Reference library entry {entry['id']!r} asset must be a mapping")
        source = dict(entry["asset"]) if has_asset else {"path": entry["path"]}
        if has_asset:
            if not isinstance(source, dict) or not source.get("asset_id") or not source.get("output_id") or manifest is None:
                raise ValueError(f"Reference library entry {entry['id']!r} needs asset_id/output_id and a project manifest")
            source_path = _approved_asset_path(manifest, source)
            resolved_path = (root / source_path).resolve()
        else:
            source_path = source["path"]
            if not isinstance(source_path, str) or not source_path:
                raise ValueError(f"Reference library entry {entry['id']!r} path must be a non-empty string")
            candidate = Path(source_path).expanduser()
            resolved_path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
            if not candidate.is_absolute() and not resolved_path.is_relative_to(root):
                raise ValueError(f"Project-relative library path escapes the project: {source_path}")
        if has_asset and not resolved_path.is_relative_to(root):
            raise ValueError(f"Manifest asset output escapes the project: {source_path}")
        expected = entry.get("sha256")
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected)):
            raise ValueError(f"Reference library entry {entry['id']!r} has an invalid sha256")
        actual = _sha256(resolved_path) if resolved_path.is_file() else None
        status = "missing" if actual is None else "changed" if expected and actual.lower() != expected.lower() else "ready"
        strength = entry.get("strength")
        if strength is not None and (not isinstance(strength, (int, float)) or not 0 <= strength <= 1):
            raise ValueError(f"Reference library entry {entry['id']!r} strength must be between 0 and 1")
        entries.append({"id": entry["id"], "order": order, "category": entry.get("category"),
                        "strength": strength, "path": str(resolved_path), "status": status,
                        "sha256": actual, "expected_sha256": expected, "source": source})
    return {"id": selector, "kind": data.get("kind", selector_kind), "name": data.get("name", selector_name),
            "version": data.get("version", 1), "path": path.relative_to(root).as_posix(), "entries": entries}
