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
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inspection_evidence_hash(report):
    evidence = {"source": report.get("source"), "measured": report.get("measured")}
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


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
    source_path = root / source_record["path"] if source_record["path"] else None
    if source_path and source_record["status"] == "verified":
        with source_path.open("rb") as stream:
            header = stream.read(21)
        valid_model = (header[:4] == b"glTF" if source_path.suffix.lower() == ".glb"
                       else header.startswith(b"Kaydara FBX Binary  "))
        if not valid_model:
            raise ValueError(f"Source model file has an invalid {source_path.suffix.lower()} header: {source_record['path']}")
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
                                                       artifact=record, image=True))
    for record in asset.get("material_artifacts", []):
        if isinstance(record, dict) and record.get("path"):
            material_artifacts.append(_file_record(root, record["path"], "material_artifacts", missing,
                                                   artifact=record, image=True))
    if not material_artifacts:
        missing.append("material_artifacts")
    inspection_artifact = _artifact(asset, "inspection") or _artifact(asset, "inspection.json")
    inspection_path = (inspection_artifact or {}).get("path") or asset.get("animation_readiness", {}).get("report_path")
    inspection = None
    inspection_bytes = None
    if inspection_path:
        inspection_file = _file_record(root, inspection_path, "inspection", missing, artifact=inspection_artifact)
        inspection = {**inspection_file, "findings": []}
        if inspection_file["status"] == "verified":
            try:
                report = json.loads((root / inspection_path).read_text())
                inspection_bytes = (root / inspection_path).read_bytes()
            except (ValueError, OSError) as exc:
                raise ValueError(f"Inspection report is not valid JSON: {inspection_path}") from exc
            measured = report.get("measured", {})
            source_identity = report.get("source", {})
            expected_source_hash = source_record.get("sha256")
            if (not isinstance(measured, dict) or not measured.get("component_details") or
                    not isinstance(measured.get("topology_diagnostics"), list) or
                    source_identity.get("artifact_id") != source.get("id") or
                    source_identity.get("sha256") != expected_source_hash):
                missing.append("inspection completeness or source identity")
            else:
                summaries = {"component_count": len(measured["component_details"]),
                             "boundary_edge_count": sum(item.get("kind") == "boundary_edge" for item in measured["topology_diagnostics"]),
                             "nonmanifold_edge_count": sum(item.get("kind") == "nonmanifold_edge" for item in measured["topology_diagnostics"]),
                             "degenerate_face_count": sum(item.get("kind") == "degenerate_face" for item in measured["topology_diagnostics"])}
                if any(measured.get(key) != count for key, count in summaries.items()):
                    missing.append("inspection summary counts disagree with detailed evidence")
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
    route, geometry_inputs, mesh_outputs, workflow_settings = _geometry_provenance(asset)
    for index, geometry_input in enumerate(geometry_inputs):
        evidence = _file_record(root, geometry_input.get("path"), f"conditioning.geometry_inputs.{index}", missing,
                                artifact=geometry_input, image=True)
        if geometry_input.get("sha256") != evidence.get("sha256"):
            missing.append(f"conditioning.geometry_inputs.{index} identity mismatch")
        geometry_input.update(evidence)
    for index, mesh_output in enumerate(mesh_outputs):
        evidence = _file_record(root, mesh_output.get("path"), f"conditioning.mesh_outputs.{index}", missing,
                                artifact=mesh_output)
        if mesh_output.get("sha256") != evidence.get("sha256"):
            missing.append(f"conditioning.mesh_outputs.{index} identity mismatch")
        mesh_output.update(evidence)
    recorded_references = []
    for index, reference in enumerate(references):
        relative = reference.get("path") if isinstance(reference, dict) else reference if isinstance(reference, str) else None
        if isinstance(relative, str) and relative and not Path(relative).is_absolute() and "://" not in relative:
            record = _file_record(root, relative, f"conditioning.references.{index}", missing,
                                  image=Path(relative).suffix.lower() in _IMAGE_EXTENSIONS)
            recorded_references.append({"value": reference, **record})
        else:
            recorded_references.append({"value": reference, "sha256": None, "status": "unknown"})
    conditioning_record = {"route": route, "strategy": strategy, "style_references": references,
                           "reference_files": recorded_references,
                           "geometry_inputs": geometry_inputs, "mesh_outputs": mesh_outputs,
                           "workflow_settings": workflow_settings,
                           "limitation": "Records the selected route and references; it does not imply multi-view conditioning."}
    review_id = str(uuid.uuid4())
    report_path = (PurePosixPath("ai/assets/candidates/character") / asset["name"] /
                   f"source_review_{review_id}" / "review.json").as_posix()
    if inspection and inspection_artifact is None and inspection_bytes is not None:
        inspection["readiness_report_path"] = inspection_path
        inspection["path"] = (PurePosixPath(report_path).parent / "inspection.json").as_posix()
    review = {"id": review_id, "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "incomplete" if missing else "ready_for_review", "report_path": report_path,
              "source_output": source_output, "source_artifact": source_record, "concept_views": concepts,
              "critical_regions": regions, "conditioning": conditioning_record, "previews": previews,
              "material_artifacts": material_artifacts, "inspection": inspection, "findings": findings,
              "missing": sorted(set(missing)),
              "unknowns": ["generator_model_identity", "node_identity_and_versions",
                           "dependency_model_and_node_license_terms", "material_appearance_approval"]}
    review["artifact_refs"] = {"source": {"id": source.get("id"), "path": source.get("path"),
                                           "sha256": source_record["sha256"]},
                               "previews": {view: {"id": artifact.get("id"), "path": artifact.get("path"),
                                                   "sha256": previews[view].get("sha256")}
                                            for view, artifact in ((view, _artifact(asset, f"preview_{view}") or _artifact(asset, kind))
                                                                   for view, kind in _VIEWS.items()) if artifact},
                               "inspection": {"id": inspection_artifact.get("id") if inspection_artifact else None,
                                              "path": inspection_path, "sha256": inspection.get("sha256"),
                                              "snapshot_path": inspection.get("path"),
                                              "inspected_at": asset.get("animation_readiness", {}).get("inspected_at"),
                                              "readiness_report": inspection_artifact is None} if inspection else None,
                               "materials": ([{"id": record.get("id"), "path": record.get("path")}
                                             for record in asset.get("artifacts", {}).values()
                                             if str(record.get("type", "")).startswith("texture.")] +
                                            [{"id": record.get("id"), "path": record.get("path")}
                                             for record in asset.get("material_artifacts", [])
                                             if isinstance(record, dict) and record.get("path")])}
    review["sha256"] = {"source_artifact": source_record["sha256"],
                        **{f"concept_views.{key}": value["sha256"] for key, value in concepts.items()},
                        **{f"previews.{key}": value["sha256"] for key, value in previews.items()},
                        **{f"critical_regions.{region['name']}.{key}": region[key]["sha256"]
                           for region in regions for key in ("concept_crop", "model_closeup")},
                        **{f"material_artifacts.{index}": value["sha256"] for index, value in enumerate(material_artifacts)},
                        **{f"conditioning.references.{index}": value["sha256"]
                           for index, value in enumerate(recorded_references)},
                        **{f"conditioning.geometry_inputs.{index}": value["sha256"]
                           for index, value in enumerate(geometry_inputs)},
                        **{f"conditioning.mesh_outputs.{index}": value["sha256"]
                           for index, value in enumerate(mesh_outputs)},
                        "inspection": inspection["sha256"] if inspection else None}
    review["file_paths"] = {"source_artifact": source_record["path"],
                            **{f"concept_views.{key}": value.get("path") for key, value in concepts.items()},
                            **{f"previews.{key}": value.get("path") for key, value in previews.items()},
                            **{f"critical_regions.{region['name']}.{key}": region[key].get("path")
                               for region in regions for key in ("concept_crop", "model_closeup")},
                            **{f"material_artifacts.{index}": value.get("path")
                               for index, value in enumerate(material_artifacts)},
                            **{f"conditioning.references.{index}": value.get("path")
                               for index, value in enumerate(recorded_references)},
                            **{f"conditioning.geometry_inputs.{index}": value.get("path")
                               for index, value in enumerate(geometry_inputs)},
                            **{f"conditioning.mesh_outputs.{index}": value.get("path")
                               for index, value in enumerate(mesh_outputs)},
                            "inspection": inspection.get("path") if inspection else None}
    report_file = root / report_path
    if not report_file.resolve().is_relative_to(root):
        raise ValueError("Source review output must stay within the project")
    if report_file.exists():
        raise FileExistsError(f"Source review report already exists: {report_path}")
    report_file.parent.mkdir(parents=True, exist_ok=True)
    if inspection and inspection_artifact is None and inspection_bytes is not None:
        snapshot_path = root / inspection["path"]
        if snapshot_path.exists():
            raise FileExistsError(f"Source review inspection snapshot already exists: {inspection['path']}")
        snapshot_path.write_bytes(inspection_bytes)
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


def is_character_source_review_current(project_root, review):
    if not isinstance(review, dict) or review.get("status") != "ready_for_review" or review.get("missing"):
        return False
    paths = review.get("file_paths", {})
    expected = review.get("sha256", {})
    if set(paths) != set(expected):
        return False
    root = Path(project_root).expanduser().resolve()
    current = {}
    for key, relative in paths.items():
        if not relative:
            return False
        try:
            path = _safe_file(root, relative, key)
        except (OSError, TypeError, ValueError):
            return False
        if not path:
            return False
        current[key] = _sha256(path)
    return current == expected


def _geometry_provenance(asset):
    attempts = asset.get("model_attempts", [])
    attempt = next((item for item in reversed(attempts) if item.get("status") in {"qualified", "accepted"}), None)
    execution = next((item for item in asset.get("executions", [])
                      if attempt and item.get("id") == attempt.get("execution_id")), None)
    if not execution:
        return "unknown", [], [], {"status": "unknown", "reason": "retained mesh stage evidence unavailable"}
    stages = execution.get("stages", [])
    mesh = next((item for item in stages if item.get("name") == "mesh_workflow_execution" and
                 item.get("attempt") == attempt.get("stage_attempt")), None)
    conditioning = next((item for item in stages if item.get("name") == "conditioning_preparation"), None)
    candidates = [ref for ref in (conditioning or {}).get("outputs", [])
                  if ref.get("type") in {"image.cutout", "image.3d_input"}]
    expected_hash = attempt.get("input_sha256") if attempt else None
    selected = next((ref for ref in candidates if expected_hash and ref.get("sha256") == expected_hash), None)
    if selected is None and candidates:
        workflow = (mesh or {}).get("settings", {}).get("workflow")
        selected_type = "image.3d_input" if workflow == "hunyuan3d_image_to_model_api" else "image.cutout"
        selected = next((ref for ref in candidates if ref.get("type") == selected_type), None)
        if selected is None and len(candidates) == 1:
            selected = candidates[0]
    inputs = ([{key: selected.get(key) for key in ("id", "type", "path", "sha256")}] if selected else [])
    route = "single_image" if len(inputs) == 1 else "unknown"
    outputs = [{key: ref.get(key) for key in ("id", "type", "path", "sha256")}
               for ref in (mesh or {}).get("outputs", [])]
    settings = {"status": "known", "workflow": (mesh or {}).get("settings", {}).get("workflow", "unknown"),
                "settings": (mesh or {}).get("settings", {})} if mesh else {"status": "unknown"}
    return route, inputs, outputs, settings


def _source_review(manifest, character_selector, review_id):
    asset = find_asset(manifest, character_selector)
    review = next((item for item in asset.get("source_quality_reviews", []) if item.get("id") == review_id), None)
    if review is None:
        raise ValueError(f"No source-quality review {review_id!r} is recorded for this character")
    return asset, review


def is_character_source_review_active(project_root, character, review):
    if not is_character_source_review_current(project_root, review):
        return False
    refs = review.get("artifact_refs", {})
    source = _artifact(character, review.get("source_output", "model"))
    if not source or not refs.get("source") or any(source.get(key) != refs["source"].get(key)
                                                   for key in ("id", "path")):
        return False
    for view, kind in _VIEWS.items():
        current = _artifact(character, f"preview_{view}") or _artifact(character, kind)
        recorded = refs.get("previews", {}).get(view)
        if not current or not recorded or any(current.get(key) != recorded.get(key) for key in ("id", "path")):
            return False
    inspection = _artifact(character, "inspection") or _artifact(character, "inspection.json")
    recorded = refs.get("inspection")
    if inspection and recorded and all(inspection.get(key) == recorded.get(key) for key in ("id", "path")):
        pass
    else:
        if not recorded or not recorded.get("readiness_report"):
            return False
        readiness = character.get("animation_readiness", {})
        try:
            live_path = _safe_file(Path(project_root).expanduser().resolve(), recorded.get("path"), "readiness report")
            snapshot_path = _safe_file(Path(project_root).expanduser().resolve(), recorded.get("snapshot_path"), "inspection snapshot")
            live = json.loads(live_path.read_text()) if live_path else {}
            snapshot = json.loads(snapshot_path.read_text()) if snapshot_path else {}
        except (OSError, TypeError, ValueError):
            return False
        if not (recorded and recorded.get("readiness_report") and
                readiness.get("report_path") == recorded.get("path") and
                readiness.get("source", {}).get("artifact_id") == refs.get("source", {}).get("id") and
                readiness.get("source", {}).get("sha256") == refs.get("source", {}).get("sha256") and
                readiness.get("inspected_at") == recorded.get("inspected_at") and
                _inspection_evidence_hash(live) == _inspection_evidence_hash(snapshot)):
            return False
    materials = ([{"id": record.get("id"), "path": record.get("path")}
                  for record in character.get("artifacts", {}).values()
                  if str(record.get("type", "")).startswith("texture.")] +
                 [{"id": record.get("id"), "path": record.get("path")}
                  for record in character.get("material_artifacts", [])
                  if isinstance(record, dict) and record.get("path")])
    return sorted(materials, key=lambda item: (str(item.get("id")), str(item.get("path")))) == sorted(
        refs.get("materials", []), key=lambda item: (str(item.get("id")), str(item.get("path"))))


def approve_character_source_review(project_root, manifest, character_selector, review_id, *, approved_by=None):
    asset, review = _source_review(manifest, character_selector, review_id)
    if review.get("status") != "ready_for_review" or review.get("missing"):
        raise ValueError("A complete source-quality review is required before approval")
    if any(finding.get("classification") not in _CLASSIFICATIONS for finding in review.get("findings", [])):
        raise ValueError("Every source-quality finding must be classified before approval")
    if not is_character_source_review_active(project_root, asset, review):
        raise ValueError("Source-quality review evidence is stale or missing; create a new review")
    decision = {"decision": "approved", "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "reviewed_sha256": dict(review["sha256"])}
    if approved_by:
        decision["reviewed_by"] = approved_by
    review.setdefault("decisions", []).append(decision)
    return review


def reject_character_source_review(project_root, manifest, character_selector, review_id, reason):
    _, review = _source_review(manifest, character_selector, review_id)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("A non-empty rejection reason is required")
    review.setdefault("decisions", []).append({"decision": "rejected", "reason": reason.strip(),
                                                "reviewed_at": datetime.now(timezone.utc).isoformat()})
    return review


def require_current_character_source_approval(project_root, character, source_output):
    reviews = character.get("source_quality_reviews", [])
    for review in reversed(reviews):
        decisions = review.get("decisions", [])
        if not decisions:
            continue
        latest = decisions[-1]
        if review.get("source_output") == source_output and latest.get("decision") == "rejected":
            raise ValueError("The current source-quality review was rejected")
        if latest.get("decision") != "approved":
            continue
        if review.get("source_output") != source_output or latest.get("reviewed_sha256") != review.get("sha256"):
            continue
        if not is_character_source_review_current(project_root, review):
            continue
        if not is_character_source_review_active(project_root, character, review):
            continue
        if any(finding.get("classification") != "intentional" for finding in review.get("findings", [])):
            raise ValueError("Source-quality findings must be intentional before rigging")
        return review
    raise ValueError("Rigging requires a current approved source-quality review")
