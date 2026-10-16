"""Hash-linked evidence and human findings for character source geometry."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from PIL import Image

from .manifest import find_asset


_VIEWS = {"front": "preview.front", "side": "preview.side", "rear": "preview.rear",
          "three_quarter": "preview.three_quarter"}
_CONCEPT_VIEWS = ("front", "left", "rear")
_CLASSIFICATIONS = {"intentional", "repairable", "unresolved"}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_file(root, relative, label, *, image=False):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError(f"{label} path must be project-relative: {relative!r}")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or path.parts[0].endswith(":"):
        raise ValueError(f"{label} path must be project-relative and stay within the project: {relative!r}")
    resolved = (root / Path(*path.parts)).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} path must resolve within the project: {relative!r}")
    if not resolved.is_file() or resolved.stat().st_size == 0:
        return None
    if image:
        try:
            with Image.open(resolved) as image_file:
                image_file.verify()
        except Exception as exc:
            raise ValueError(f"{label} must be a valid image: {relative!r}") from exc
    return resolved


def _file_record(root, relative, label, missing, *, artifact=None, image=False):
    if not relative:
        missing.append(label)
        return {"path": relative, "artifact_id": artifact.get("id") if artifact else None,
                "type": artifact.get("type") if artifact else None, "sha256": None, "status": "missing"}
    path = _safe_file(root, relative, label, image=image)
    if path is None:
        missing.append(f"{label}")
        return {"path": relative, "artifact_id": artifact.get("id") if artifact else None,
                "sha256": None, "status": "missing"}
    return {"path": relative, "artifact_id": artifact.get("id") if artifact else None,
            "type": artifact.get("type") if artifact else None, "sha256": _sha256(path), "status": "verified"}


def _artifact(asset, key_or_type):
    artifacts = asset.get("artifacts", {})
    if key_or_type in artifacts:
        return artifacts[key_or_type]
    return next((record for record in artifacts.values() if record.get("type") == key_or_type), None)


def _critical_regions(regions):
    if isinstance(regions, dict):
        result = []
        for name, pair in regions.items():
            result.append({"name": name, **(pair if isinstance(pair, dict) else {})})
        regions = result
    if not isinstance(regions, (list, tuple)) or not regions:
        raise ValueError("At least one named critical region is required")
    normalized = []
    names = set()
    for region in regions:
        if not isinstance(region, dict) or not isinstance(region.get("name"), str) or not region["name"].strip():
            raise ValueError("Critical regions require unique non-empty names")
        name = region["name"].strip()
        if name in names:
            raise ValueError(f"Critical region {name!r} is repeated")
        names.add(name)
        normalized.append({"name": name, "concept_crop": region.get("concept_crop"),
                           "model_closeup": region.get("model_closeup")})
    return normalized


def _finding_id(kind, data):
    identity = {key: data.get(key) for key in ("object_name", "component_index", "kind", "polygon_index", "source_vertex_indices")}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    return f"{kind}-{digest}"


def create_character_source_review(project_root, manifest, character_selector, concept_views, critical_regions,
                                   *, source_output="model"):
    root = Path(project_root).expanduser().resolve()
    asset = find_asset(manifest, character_selector)
    missing = []
    if not isinstance(concept_views, dict):
        raise ValueError("Concept views must map front, left, and rear to project-relative images")
    source = _artifact(asset, source_output)
    if (not source or source.get("type") not in {"model.glb", "model.fbx"}
            or source.get("status") != "ready" or source.get("approval", {}).get("status") != "approved"):
        raise ValueError(f"Source output {source_output!r} must be a ready approved model artifact")
    source_record = _file_record(root, source.get("path"), "source_artifact", missing, artifact=source)
    concepts = {}
    for view in _CONCEPT_VIEWS:
        relative = concept_views.get(view)
        if not relative:
            missing.append(f"concept_views.{view}")
            concepts[view] = {"path": relative, "sha256": None, "status": "missing"}
        else:
            concepts[view] = _file_record(root, relative, f"concept_views.{view}", missing, image=True)
    previews = {}
    for view, artifact_type in _VIEWS.items():
        artifact = _artifact(asset, f"preview_{view}") or _artifact(asset, artifact_type)
        if not artifact or not artifact.get("path"):
            missing.append(f"previews.{view}")
            previews[view] = {"path": None, "sha256": None, "status": "missing"}
        else:
            previews[view] = _file_record(root, artifact["path"], f"previews.{view}", missing,
                                          artifact=artifact, image=True)
    regions = []
    for region in _critical_regions(critical_regions):
        pair = {"name": region["name"]}
        for field in ("concept_crop", "model_closeup"):
            relative = region[field]
            key = f"critical_regions.{region['name']}.{field}"
            if not relative:
                missing.append(key)
                pair[field] = {"path": None, "sha256": None, "status": "missing"}
            else:
                pair[field] = _file_record(root, relative, key, missing, image=True)
        regions.append(pair)
    material_artifacts = []
    for record in asset.get("artifacts", {}).values():
        if str(record.get("type", "")).startswith("texture."):
            material_artifacts.append(_file_record(root, record.get("path"), "material_artifacts", missing,
                                                   artifact=record))
    for record in asset.get("material_artifacts", []):
        if isinstance(record, dict) and record.get("path"):
            material_artifacts.append(_file_record(root, record["path"], "material_artifacts", missing,
                                                   artifact=record))
    if not material_artifacts:
        missing.append("material_artifacts")
    inspection_artifact = _artifact(asset, "inspection") or _artifact(asset, "inspection.json")
    inspection_path = (inspection_artifact or {}).get("path") or asset.get("animation_readiness", {}).get("report_path")
    inspection = None
    if inspection_path:
        inspection_file = _file_record(root, inspection_path, "inspection", missing, artifact=inspection_artifact)
        inspection = {**inspection_file, "findings": []}
        if inspection_file["status"] == "verified":
            try:
                report = json.loads((root / inspection_path).read_text())
            except (ValueError, OSError) as exc:
                raise ValueError(f"Inspection report is not valid JSON: {inspection_path}") from exc
            measured = report.get("measured", {})
            for component in measured.get("component_details", []):
                finding = {"kind": "component", **component}
                inspection["findings"].append(finding)
            for diagnostic in measured.get("topology_diagnostics", []):
                inspection["findings"].append(dict(diagnostic))
    else:
        missing.append("inspection")
    findings = []
    for item in inspection.get("findings", []) if inspection else []:
        kind = item.get("kind", "component")
        findings.append({"id": _finding_id(kind, item), "kind": kind, **item,
                         "classification": "unclassified", "classification_history": []})
    conditioning = asset.get("conditioning") or {}
    strategy = conditioning.get("strategy", "unknown")
    references = conditioning.get("references_used", [])
    route = "single_image" if len(references) == 1 else "multi_image" if len(references) > 1 else strategy
    recorded_references = []
    for index, reference in enumerate(references):
        relative = reference.get("path") if isinstance(reference, dict) else reference if isinstance(reference, str) else None
        if isinstance(relative, str) and relative and not Path(relative).is_absolute() and "://" not in relative:
            record = _file_record(root, relative, f"conditioning.references.{index}", missing)
            recorded_references.append({"value": reference, **record})
        else:
            recorded_references.append({"value": reference, "sha256": None, "status": "unknown"})
    conditioning_record = {"route": route, "strategy": strategy, "references": references,
                           "reference_files": recorded_references,
                           "limitation": "Records the selected route and references; it does not imply multi-view conditioning."}
    review_id = str(uuid.uuid4())
    report_path = (PurePosixPath("ai/assets/candidates/character") / asset["name"] /
                   f"source_review_{review_id}" / "review.json").as_posix()
    review = {"id": review_id, "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "incomplete" if missing else "ready_for_review", "report_path": report_path,
              "source_output": source_output, "source_artifact": source_record, "concept_views": concepts,
              "critical_regions": regions, "conditioning": conditioning_record, "previews": previews,
              "material_artifacts": material_artifacts, "inspection": inspection, "findings": findings,
              "missing": sorted(set(missing)),
              "unknowns": ["generator_model_identity", "node_identity_and_versions",
                           "dependency_model_and_node_license_terms", "material_appearance_approval"]}
    review["sha256"] = {"source_artifact": source_record["sha256"],
                        **{f"concept_views.{key}": value["sha256"] for key, value in concepts.items()},
                        **{f"previews.{key}": value["sha256"] for key, value in previews.items()},
                        **{f"critical_regions.{region['name']}.{key}": region[key]["sha256"]
                           for region in regions for key in ("concept_crop", "model_closeup")},
                        **{f"material_artifacts.{index}": value["sha256"] for index, value in enumerate(material_artifacts)},
                        **{f"conditioning.references.{index}": value["sha256"]
                           for index, value in enumerate(recorded_references)},
                        "inspection": inspection["sha256"] if inspection else None}
    report_file = root / report_path
    if not report_file.resolve().is_relative_to(root):
        raise ValueError("Source review output must stay within the project")
    if report_file.exists():
        raise FileExistsError(f"Source review report already exists: {report_path}")
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n")
    asset.setdefault("source_quality_reviews", []).append(review)
    return review


def classify_character_source_findings(project_root, manifest, character_selector, review_id, classifications):
    asset = find_asset(manifest, character_selector)
    review = next((item for item in asset.get("source_quality_reviews", []) if item.get("id") == review_id), None)
    if not review:
        raise ValueError(f"Unknown source review {review_id!r}")
    if not isinstance(classifications, dict) or not classifications:
        raise ValueError("At least one finding classification is required")
    findings = {finding["id"]: finding for finding in review.get("findings", [])}
    unknown = set(classifications) - set(findings)
    if unknown:
        raise ValueError(f"Unknown finding ID(s): {', '.join(sorted(unknown))}")
    invalid = {value for value in classifications.values() if value not in _CLASSIFICATIONS}
    if invalid:
        raise ValueError(f"Invalid classification(s): {', '.join(sorted(map(str, invalid)))}")
    for finding_id, classification in classifications.items():
        finding = findings[finding_id]
        entry = {"classification": classification, "classified_at": datetime.now(timezone.utc).isoformat()}
        finding.setdefault("classification_history", []).append(entry)
        finding["classification"] = classification
    return review
