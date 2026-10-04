import copy
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .manifest import asset_key, find_asset, new_record
from .taxonomy import validate_asset_name
from .validation import validate_image


def parse_variations(values):
    if not isinstance(values, (list, tuple)) or any(not isinstance(value, str) for value in values):
        raise ValueError("Variations must be a list of dimension=value strings")
    variations = []
    for value in values:
        variation = {}
        for item in value.split(";"):
            dimension, separator, choice = item.partition("=")
            dimension, choice = dimension.strip(), choice.strip()
            if not separator or not dimension or not choice:
                raise ValueError(f"Variation must use dimension=value: {item!r}")
            if dimension in variation:
                raise ValueError(f"Variation repeats dimension {dimension!r}")
            variation[dimension] = choice
        variations.append(variation)
    if len(variations) < 2:
        raise ValueError("Explore requires at least two deliberate --variation values")
    return variations


def promote_candidate(project_root, candidate_root, manifest, source_selector, number, target_name, asset_type, style):
    root = Path(project_root).resolve()
    source = find_asset(manifest, source_selector)
    if source.get("generation_mode") != "explore":
        raise ValueError(f"{source.get('name')} is not an exploration")
    validate_asset_name(target_name)
    target_key = asset_key(asset_type["name"], target_name)
    if target_key in manifest["assets"]:
        raise FileExistsError(f"Asset {target_name!r} already exists")
    candidate = next((item for item in source.get("candidates", {}).get("items", [])
                      if item.get("number") == number and item.get("status") == "candidate"), None)
    if candidate is None:
        raise ValueError(f"Exploration candidate {number} is not available to promote")

    source_path = Path(candidate.get("path", ""))
    source_file = (root / source_path).resolve()
    if not source_file.is_relative_to(root) or not source_file.is_file():
        raise ValueError("Exploration candidate file is missing or outside the project")
    destination = (root / candidate_root / asset_type["name"] / target_name / "candidate_01.png").resolve()
    if not destination.is_relative_to(root):
        raise ValueError("Promoted candidate path must stay within the project")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copy2(source_file, temporary)
        validation = validate_image(temporary, expected_format=asset_type.get("format", "PNG"),
                                    require_alpha=bool(asset_type.get("alpha_required", False)))
        if validation["status"] == "failed":
            raise ValueError("Exploration candidate failed promotion validation: " + "; ".join(validation["errors"]))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    record = new_record(asset_type["name"], target_name, source["description"], style,
                        copy.deepcopy(source.get("conditioning", {"strategy": "text_only"})))
    promoted = copy.deepcopy(candidate)
    promoted.update({"number": 1, "status": "candidate", "approval": None,
                     "path": destination.relative_to(root).as_posix(),
                     "source_candidate": {"asset_id": source["id"], "name": source["name"], "number": number,
                                          "path": candidate["path"]}})
    record["generation_mode"] = "produce"
    if candidate.get("style"):
        record["style"] = candidate["style"].get("name", record["style"])
        record["style_version"] = candidate["style"].get("version", record["style_version"])
    record["generation_prompt"] = candidate.get("prompt", source.get("generation_prompt"))
    record["candidates"] = {"items": [promoted], "selected": None}
    record["status"] = "candidate"
    record["generator"] = copy.deepcopy(candidate.get("generator") or record["generator"])
    record["promoted_from"] = {"asset_id": source["id"], "name": source["name"], "candidate": number,
                               "path": candidate["path"],
                               "variation": copy.deepcopy(candidate.get("variation")),
                               "promoted_at": datetime.now(timezone.utc).isoformat()}
    manifest["assets"][target_key] = record
    candidate["status"] = "promoted"
    candidate["promoted_to"] = {"asset_id": record["id"], "name": target_name}
    return record
