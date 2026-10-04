from pathlib import Path

from PIL import Image


def validate_image(path, expected_format="PNG", require_alpha=False, max_bytes=50_000_000, report_path=None):
    path = Path(path)
    checks = ["exists", "non_empty", "decodable", "dimensions", "format", "file_size"]
    if require_alpha:
        checks.append("alpha")
    measured = {"path": str(report_path if report_path is not None else path), "bytes": path.stat().st_size if path.is_file() else 0}
    errors, warnings = [], []
    if not path.is_file() or measured["bytes"] == 0:
        errors.append("image file is missing or empty")
    else:
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                measured["format"] = image.format
                measured["dimensions"] = list(image.size)
                measured["mode"] = image.mode
                measured["has_alpha"] = "A" in image.getbands() or "transparency" in image.info
            if not all(measured["dimensions"]):
                errors.append("image dimensions must be greater than zero")
            if expected_format and measured["format"] != expected_format:
                errors.append(f"expected {expected_format}, got {measured['format']}")
            if require_alpha and not measured["has_alpha"]:
                errors.append("image is missing required alpha channel")
            if measured["bytes"] > max_bytes:
                warnings.append(f"image exceeds {max_bytes} byte size guideline")
        except Exception as exc:
            errors.append(f"invalid image: {exc}")
    return {"status": "failed" if errors else "passed_with_warnings" if warnings else "passed", "checks": checks, "errors": errors, "warnings": warnings, "measured": measured}


def validate_model_outputs(paths, inspection=None, face_budget=None, project_root=None, max_components=None,
                           max_nonmanifold_edges=None):
    errors, warnings = [], []
    root = Path(project_root).resolve() if project_root else None
    measured = {key: (Path(path).resolve().relative_to(root).as_posix() if root and Path(path).resolve().is_relative_to(root) else str(path)) for key, path in paths.items()}
    for key, path in paths.items():
        path = Path(path)
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"{key} is missing or empty: {path}")
    if inspection:
        measured.update(inspection.get("measured", {}))
        errors.extend(inspection.get("errors", []))
        warnings.extend(inspection.get("warnings", []))
        if face_budget and inspection.get("measured", {}).get("face_count", 0) > face_budget:
            errors.append(f"face count exceeds budget {face_budget}")
        component_count = inspection.get("measured", {}).get("component_count")
        if max_components is not None:
            if component_count is None:
                errors.append("component count was not measured")
            elif component_count > max_components:
                errors.append(f"component count {component_count} exceeds budget {max_components}")
        nonmanifold_edge_count = inspection.get("measured", {}).get("nonmanifold_edge_count")
        if max_nonmanifold_edges is not None:
            if nonmanifold_edge_count is None:
                errors.append("non-manifold edge count was not measured")
            elif nonmanifold_edge_count > max_nonmanifold_edges:
                errors.append(f"non-manifold edge count {nonmanifold_edge_count} exceeds budget {max_nonmanifold_edges}")
    else:
        warnings.append("Blender mesh inspection did not run")
        if max_components is not None:
            errors.append("component count was not measured")
        if max_nonmanifold_edges is not None:
            errors.append("non-manifold edge count was not measured")
    return {"status": "failed" if errors else "passed_with_warnings" if warnings else "passed", "errors": errors, "warnings": warnings, "measured": measured}


def summarize_validation(result):
    lines = [f"Validation: {result['status'].replace('_', ' ')}"]
    lines.extend(f"FAIL: {item}" for item in result.get("errors", []))
    lines.extend(f"WARN: {item}" for item in result.get("warnings", []))
    if not result.get("errors") and not result.get("warnings"):
        lines.append("PASS: all configured checks ran")
    return "\n".join(lines)
