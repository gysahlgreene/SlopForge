import json
import secrets
import shutil
from pathlib import Path

from .manifest import add_candidate
from .provenance import generator_provenance
from .taxonomy import output_path
from .validation import validate_image


def generate_candidates(project_root, config, asset_type, style, name, description, count, manifest, key, backend_generate):
    root = Path(project_root).resolve()
    final_path = output_path(root, config, asset_type, name)
    candidate_dir = root / config["asset_pipeline"]["candidate_root"] / asset_type["name"] / name
    existing = manifest["assets"][key].setdefault("candidates", {"items": [], "selected": None})["items"]
    start = max((int(item["number"]) for item in existing), default=0) + 1
    results = []
    for number in range(start, start + count):
        candidate_path = candidate_dir / f"candidate_{number:02d}.png"
        metadata_path = candidate_dir / f"candidate_{number:02d}.json"
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        seed = secrets.randbits(32)
        record = {"number": number, "path": candidate_path.relative_to(root).as_posix(), "prompt": description, "status": "failed", "seed": seed, "validation": {"status": "not_run", "errors": [], "warnings": [], "measured": {}}}
        try:
            backend_generate(description, candidate_path, seed, metadata_path)
            record["validation"] = validate_image(candidate_path, expected_format=asset_type.get("format", "PNG"), require_alpha=bool(asset_type.get("alpha_required", False)), report_path=candidate_path.relative_to(root))
            record["status"] = "candidate" if record["validation"]["status"] != "failed" else "failed"
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text())
                record["generator"] = generator_provenance(metadata.get("workflow"), metadata)
                asset = manifest["assets"][key]
                asset["generator"] = generator_provenance(metadata.get("workflow"), metadata)
        except Exception as exc:
            record["error"] = str(exc)
            record["validation"]["errors"].append(str(exc))
        add_candidate(manifest, key, record)
        results.append(record)
    asset = manifest["assets"][key]
    if final_path is not None:
        asset.setdefault("outputs", {})["final_path"] = final_path.relative_to(root).as_posix()
    if not any(item["status"] == "candidate" for item in results):
        asset["status"] = "failed"
        raise RuntimeError(f"No valid candidates generated for {name}; see manifest candidate errors")
    return results


def approve_image_candidate(project_root, config, asset_type, manifest, key, number, force=False):
    root = Path(project_root).resolve()
    asset = manifest["assets"][key]
    candidate = next((item for item in asset.get("candidates", {}).get("items", []) if item["number"] == number), None)
    if candidate is None or candidate.get("status") != "candidate":
        raise ValueError(f"Candidate {number} is not a valid candidate for {asset['name']}")
    source = root / candidate["path"]
    destination = output_path(root, config, asset_type, asset["name"])
    if destination.exists() and not (force or config["asset_pipeline"].get("overwrite_existing")):
        raise FileExistsError(f"Output exists; pass --force to replace: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    result = validate_image(destination, expected_format=asset_type.get("format", "PNG"), require_alpha=bool(asset_type.get("alpha_required", False)), report_path=destination.relative_to(root))
    if asset_type.get("alpha_recommended") and not result["measured"].get("has_alpha", False):
        result["warnings"].append("alpha channel is recommended for this asset type")
        if result["status"] == "passed":
            result["status"] = "passed_with_warnings"
    candidate["approval"] = "approved"
    asset["candidates"]["selected"] = number
    asset["outputs"]["image"] = destination.relative_to(root).as_posix()
    asset["validation"] = result
    asset["status"] = "ready" if result["status"] != "failed" else "failed"
    return result
