from pathlib import Path
import math

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


def is_placeholder_normal(path):
    """True for a decodable 1x1 image, the neutral stand-in written when no real normal map exists."""
    try:
        with Image.open(path) as image:
            return image.size == (1, 1)
    except Exception:
        return False  # undecodable maps are a separate validity failure


def measure_material_maps(paths, near_black_level=8):
    """Report per-map pixel statistics. Warnings are informational: the quality contract declares no thresholds."""
    maps, warnings = {}, []
    for key, path in paths.items():
        try:
            with Image.open(path) as image:
                size = list(image.size)
                small = image.convert("RGB")
                small.thumbnail((256, 256))
        except Exception as exc:
            warnings.append(f"{key} map could not be measured: {exc}")
            continue
        pixels = list(zip(*[iter(small.tobytes())] * 3))
        near_black = sum(max(pixel) <= near_black_level for pixel in pixels) / len(pixels)
        maps[key] = {"dimensions": size, "near_black_fraction": round(near_black, 4),
                     "distinct_colors_sampled": len(set(pixels)), "thresholds": "undeclared"}
        if near_black >= 0.9 and key != "metallic":  # black metallic is valid non-metal
            warnings.append(f"{key} map is {near_black:.0%} near-black")
        if len(set(pixels)) == 1:
            warnings.append(f"{key} map is a single constant color")
        if key == "metallic":
            metal = sum(min(pixel) >= 230 for pixel in pixels) / len(pixels)
            maps[key]["near_full_metal_fraction"] = round(metal, 4)
            if metal >= 0.9:
                # TRELLIS.2 can decode glossy non-metal concepts as fully metallic (issue #43); confirm the asset is metal.
                warnings.append(f"metallic map is {metal:.0%} fully metallic; confirm the asset is metal "
                                "or revise the concept so the material reads as non-metal")
    if len({tuple(item["dimensions"]) for item in maps.values()}) > 1:
        warnings.append("material map dimensions differ: " +
                        ", ".join(f"{key}={item['dimensions']}" for key, item in maps.items()))
    return {"maps": maps, "warnings": warnings}


def validate_model_outputs(paths, inspection=None, face_budget=None, project_root=None,
                           max_components=None, max_nonmanifold_edges=None,
                           max_boundary_edges=None):
    errors, warnings, failure_codes = [], [], []
    root = Path(project_root).resolve() if project_root else None
    measured = {key: (Path(path).resolve().relative_to(root).as_posix()
                       if root and Path(path).resolve().is_relative_to(root)
                       else str(path))
                for key, path in paths.items()}

    def _add_err(code, msg):
        errors.append(msg)
        failure_codes.append(code)

    def _finite_nonnegative_number(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        try:
            return math.isfinite(value) and value >= 0
        except OverflowError:
            return False

    for key, path in paths.items():
        path = Path(path)
        if not path.is_file() or path.stat().st_size == 0:
            _add_err("missing_artifact", f"{key} is missing or empty: {path}")
    if not isinstance(inspection, dict):
        _add_err("inspection_invalid", "Blender mesh inspection did not run")
    else:
        if inspection.get("status") not in {"passed", "passed_with_warnings"}:
            _add_err("inspection_invalid", "Blender mesh inspection did not pass")
        report = inspection.get("measured")
        if not isinstance(report, dict):
            _add_err("inspection_invalid", "Blender inspection report has no measured metrics")
            report = {}
        measured.update(report)
        errors.extend(inspection.get("errors", []))
        failure_codes.extend(["inspection_invalid"] * len(inspection.get("errors", [])))
        warnings.extend(inspection.get("warnings", []))
        required = ("mesh_objects", "vertex_count", "face_count", "dimensions",
                    "uv_layers", "material_count", "image_texture_count",
                    "component_count", "nonmanifold_edge_count",
                    "transforms_applied", "missing_textures")
        for key in required:
            if key not in report:
                _add_err("inspection_invalid", f"inspection did not measure {key}")
        metrics = dict(report)
        for key in ("mesh_objects", "vertex_count", "face_count", "uv_layers",
                     "material_count", "image_texture_count",
                     "component_count", "nonmanifold_edge_count"):
            value = metrics.get(key)
            if not _finite_nonnegative_number(value):
                _add_err("metric_invalid", f"inspection reported invalid {key}")
                metrics[key] = 0
        if (metrics.get("mesh_objects", 0) < 1 or
                metrics.get("vertex_count", 0) < 3 or
                metrics.get("face_count", 0) < 1):
            _add_err("surface_invalid", "mesh has no usable surface geometry")
        if not isinstance(metrics.get("dimensions"), (list, tuple)) or len(metrics["dimensions"]) != 3:
            _add_err("bounds_invalid", "mesh bounds were not measured")
        elif any(not _finite_nonnegative_number(value)
                 or value <= 1e-5 for value in metrics["dimensions"]):
            _add_err("bounds_invalid", "mesh bounds are degenerate or non-finite")
        if metrics.get("uv_layers", 0) < 1:
            _add_err("uv_missing", "mesh has no UV map")
        if metrics.get("material_count", 0) < 1:
            _add_err("material_missing", "mesh has no material")
        if metrics.get("transforms_applied") is not True:
            _add_err("transform_invalid", "mesh rotation or scale is not applied")
        if metrics.get("missing_textures"):
            _add_err("texture_missing", "one or more referenced texture files are missing")
        face_count = metrics.get("face_count")
        if face_budget and isinstance(face_count, (int, float)) and face_count > face_budget:
            _add_err("face_budget", f"face count exceeds budget {face_budget}")
        component_count = report.get("component_count")
        if max_components is not None:
            if component_count is None:
                _add_err("metric_invalid", "component count was not measured")
            elif not isinstance(component_count, (int, float)):
                _add_err("metric_invalid", "inspection reported invalid component count")
            elif component_count > max_components:
                _add_err("component_budget", f"component count {component_count} exceeds budget {max_components}")
        nonmanifold_edge_count = report.get("nonmanifold_edge_count")
        if max_nonmanifold_edges is not None:
            if nonmanifold_edge_count is None:
                _add_err("metric_invalid", "non-manifold edge count was not measured")
            elif not isinstance(nonmanifold_edge_count, (int, float)):
                _add_err("metric_invalid", "inspection reported invalid non-manifold edge count")
            elif nonmanifold_edge_count > max_nonmanifold_edges:
                _add_err("nonmanifold_budget",
                         f"non-manifold edge count {nonmanifold_edge_count} exceeds budget {max_nonmanifold_edges}")
        boundary_edge_count = report.get("boundary_edge_count")
        if max_boundary_edges is not None:
            if boundary_edge_count is None:
                _add_err("metric_invalid", "boundary edge count was not measured")
            elif not _finite_nonnegative_number(boundary_edge_count):
                _add_err("metric_invalid", "inspection reported invalid boundary edge count")
            elif boundary_edge_count > max_boundary_edges:
                _add_err("boundary_budget",
                         f"boundary edge count {boundary_edge_count} exceeds budget {max_boundary_edges}")
    return {
        "status": "failed" if errors else "passed_with_warnings" if warnings else "passed",
        "errors": errors, "failure_codes": failure_codes,
        "warnings": warnings, "measured": measured,
        "limits": {
            "max_components": max_components,
            "max_nonmanifold_edges": max_nonmanifold_edges,
            "max_boundary_edges": max_boundary_edges,
        },
    }


def summarize_validation(result):
    lines = [f"Validation: {result['status'].replace('_', ' ')}"]
    lines.extend(f"FAIL: {item}" for item in result.get("errors", []))
    lines.extend(f"WARN: {item}" for item in result.get("warnings", []))
    if not result.get("errors") and not result.get("warnings"):
        lines.append("PASS: all configured checks ran")
    return "\n".join(lines)
