from pathlib import Path
import math

import numpy as np
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
            maps[key]["mean"] = round(sum(pixel[0] for pixel in pixels) / len(pixels) / 255, 4)
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
                           max_boundary_edges=None, min_uv_area=None):
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
        uv_area = report.get("uv_area_sum")
        if min_uv_area is not None:
            # A shattered reconstruction unwraps into tiny charts: 0.025 on a 2026-10-22 glass bottle, 0.22-0.63 whole.
            if not _finite_nonnegative_number(uv_area):
                _add_err("metric_invalid", "UV area was not measured")
            elif uv_area < min_uv_area:
                _add_err("uv_area_budget", f"UV area {uv_area:.3f} is below {min_uv_area}: the mesh is likely "
                                           "shattered into small pieces")
    return {
        "status": "failed" if errors else "passed_with_warnings" if warnings else "passed",
        "errors": errors, "failure_codes": failure_codes,
        "warnings": warnings, "measured": measured,
        "limits": {
            "max_components": max_components,
            "max_nonmanifold_edges": max_nonmanifold_edges,
            "max_boundary_edges": max_boundary_edges,
            "min_uv_area": min_uv_area,
        },
    }


# A sampled reconstruction can come out turned sideways (aspect error 0.69 on one realistic character)
# or with limbs missing, while good ones fit the front concept within about 0.035 and wide, stocky
# builds within 0.09.
MAX_CONCEPT_ASPECT_ERROR = 0.15


def apply_concept_silhouette(validation, projection, limit=MAX_CONCEPT_ASPECT_ERROR):
    """Fail a candidate whose front silhouette does not match its concept (retryable quality code)."""
    if (projection or {}).get("status") == "skipped":
        validation["warnings"] = [*validation.get("warnings", []),
            f"front concept projection skipped: {projection.get('reason', 'no reason recorded')}; "
            "the base color is the voxel bake only, so inspect face and fine detail"]
        if validation.get("status") == "passed":
            validation["status"] = "passed_with_warnings"
    error = (projection or {}).get("aspect_error")
    if isinstance(error, bool) or not isinstance(error, (int, float)) or not math.isfinite(error):
        return validation
    validation.setdefault("measured", {})["concept_aspect_error"] = error
    validation.setdefault("limits", {})["max_concept_aspect_error"] = limit
    if error > limit:
        validation["errors"] = [*validation.get("errors", []),
            f"reconstruction front silhouette differs from the concept by {error:.0%} (limit {limit:.0%}); "
            "the model is turned or missing parts, so another seed is tried"]
        validation["failure_codes"] = [*validation.get("failure_codes", []), "concept_silhouette"]
        validation["status"] = "failed"
    return validation


MIN_EMISSIVE_FRACTION = 0.0001  # the smallest fraction the report records (4 decimals): any emitter found


def apply_declared_emitter(validation, fraction, minimum=MIN_EMISSIVE_FRACTION):
    """Fail a candidate whose base color has no region for the brief's declared emitter (retryable quality code)."""
    measured = round(fraction, 4)
    validation.setdefault("measured", {})["emissive_fraction"] = measured
    validation.setdefault("limits", {})["min_emissive_fraction"] = minimum
    if measured < minimum:
        validation["errors"] = [*validation.get("errors", []),
            "brief declares an emissive region but no matching region was found in base color, so another seed "
            "is tried; if every seed misses it, choose a concept that shows the region as a flat opaque surface "
            "or declare its colour with emissive#rrggbb"]
        validation["failure_codes"] = [*validation.get("failure_codes", []), "emitter_missing"]
        validation["status"] = "failed"
    return validation



def apply_declared_glass(validation, fraction, minimum=MIN_EMISSIVE_FRACTION):
    """Fail a candidate whose base colour has no region for the brief's declared glass (retryable quality code)."""
    measured = round(fraction, 4)
    validation.setdefault("measured", {})["glass_fraction"] = measured
    validation.setdefault("limits", {})["min_glass_fraction"] = minimum
    if measured < minimum:
        validation["errors"] = [*validation.get("errors", []),
            "brief declares glass but no matching region was found in base color, so another seed is tried; if every "
            "seed misses it, approve a concept that shows the glass as a solid tinted surface or declare its tint with "
            "glass#rrggbb"]
        validation["failure_codes"] = [*validation.get("failure_codes", []), "glass_missing"]
        validation["status"] = "failed"
    return validation


def apply_concept_fit(validation, view, minimum):
    """Fail a candidate whose mesh no longer matches the concept's outline (retryable quality code).

    view is blender/concept_view.py's report: the best silhouette fit of the mesh to the approved concept. Shattered
    reconstructions fitted 0.71-0.75 and every whole prop 0.86-0.99 (2026-10-22); UV area no longer separates them.
    """
    fit = (view or {}).get("silhouette_iou")
    if fit is None:
        return validation  # not measured; the concept view report says why
    validation.setdefault("measured", {})["concept_fit"] = fit
    validation.setdefault("limits", {})["min_concept_fit"] = minimum
    if fit < minimum:
        validation["errors"] = [*validation.get("errors", []),
            f"mesh fits the concept's outline at {fit} (limit {minimum}): the reconstruction is likely shattered or "
            "turned, so another seed is tried"]
        validation["failure_codes"] = [*validation.get("failure_codes", []), "concept_fit"]
        validation["status"] = "failed"
    return validation

# A module declared as an L corner must leave one quarter of its footprint nearly empty. Real stone corners measured
# 0.00 there (others 0.69-0.92); one that reconstructed as a solid block measured 0.86 in every quarter (2026-10-22).
MAX_OPEN_QUADRANT = 0.15


def apply_module_footprint(validation, quadrants, footprint):
    """Fail a kit module whose footprint lacks its declared shape (retryable quality code)."""
    if footprint != "corner" or not quadrants:
        return validation
    opening = round(min(quadrants), 3)
    validation.setdefault("measured", {})["open_quadrant"] = opening
    validation.setdefault("limits", {})["max_open_quadrant"] = MAX_OPEN_QUADRANT
    if opening > MAX_OPEN_QUADRANT:
        validation["errors"] = [*validation.get("errors", []),
            f"the corner module has no open side (emptiest quarter of its footprint {opening}, limit "
            f"{MAX_OPEN_QUADRANT}): it reconstructed as a solid block, so another seed is tried"]
        validation["failure_codes"] = [*validation.get("failure_codes", []), "module_footprint"]
        validation["status"] = "failed"
    return validation


MIN_CONCEPT_CHROMA = 10  # CIELAB chroma below this is near-grey: the concept has no hue to keep


def _lab(rgb):
    """CIELAB (D65) of an (N, 3) array of sRGB 0-255 values."""
    c = rgb / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = c @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], -1)


def concept_colour_fidelity(cutout_path, basecolor_path, view_path=None, view_report=None):
    """How far the candidate's base colour drifted from the approved concept's dominant colour.

    Compares median CIELAB chromaticity of the concept's object pixels with the base colour as the concept shows
    it (view_path: the map rendered from the concept's fitted view), giving the CIE hue difference (dH*, weighted
    by both chromas) and the share of the concept's chroma kept. Without a view the whole map is used: hue agrees
    with the view within about 1, but hidden insides and bases lower the atlas's saturation, so it is not checked.
    The concept is lit and the map is albedo, so lightness is not compared.
    """
    with Image.open(cutout_path) as image:
        cut = np.asarray(image.convert("RGBA"), dtype=float)
    if view_path is not None:
        with Image.open(view_path) as image:
            view = np.asarray(image.convert("RGBA"), dtype=float)
        texture, source = view[..., :3][view[..., 3] > 200], "concept_view"
    else:
        with Image.open(basecolor_path) as image:
            step = max(1, image.width // 1024)  # a 4096 map at full size needs 400 MB of floats
            base = np.asarray(image.convert("RGB"), dtype=float)[::step, ::step].reshape(-1, 3)
        texture, source = base[base.sum(-1) > 15], "atlas"  # unused atlas texels are black
    concept = np.median(_lab(cut[..., :3][cut[..., 3] > 200])[:, 1:], 0)
    texture = np.median(_lab(texture)[:, 1:], 0)
    c1, c2 = float(np.hypot(*concept)), float(np.hypot(*texture))
    hue = math.atan2(concept[1], concept[0]) - math.atan2(texture[1], texture[0])
    fidelity = {"colour_source": source, "concept_chroma": round(c1, 2), "texture_chroma": round(c2, 2),
                "concept_hue_difference": round(abs(2 * math.sqrt(c1 * c2) * math.sin(hue / 2)), 2),
                "concept_chroma_ratio": round(c2 / c1, 3) if c1 else None}
    if view_report:
        fidelity["concept_view"] = {key: view_report.get(key) for key in ("status", "silhouette_iou", "reason")
                                    if view_report.get(key) is not None}
    return fidelity


def apply_concept_colour(validation, fidelity, max_hue_difference=None, min_chroma_ratio=None):
    """Fail a candidate whose base colour lost the concept's hue or saturation (retryable quality codes)."""
    validation.setdefault("measured", {}).update(fidelity)
    if fidelity["concept_chroma"] < MIN_CONCEPT_CHROMA:
        return validation
    limits = validation.setdefault("limits", {})
    checks = (("colour_hue_shift", "concept_hue_difference", "max_concept_hue_difference", max_hue_difference,
               lambda value, limit: value > limit, "shifted hue from the concept"),
              ("colour_desaturated", "concept_chroma_ratio", "min_concept_chroma_ratio", min_chroma_ratio,
               lambda value, limit: value < limit, "lost the concept's saturation"))
    for code, metric, limit_key, limit, fails, what in checks:
        if limit is None:
            continue
        if code == "colour_desaturated" and fidelity.get("colour_source") != "concept_view":
            validation["warnings"] = [*validation.get("warnings", []),
                "saturation against the concept was not checked: no view from the concept's side "
                f"({fidelity.get('concept_view', {}).get('reason', 'not rendered')}), and the whole map includes hidden parts"]
            if validation.get("status") == "passed":
                validation["status"] = "passed_with_warnings"
            continue
        limits[limit_key] = limit
        if fails(fidelity[metric], limit):
            validation["errors"] = [*validation.get("errors", []),
                f"base colour {what} ({metric} {fidelity[metric]}, limit {limit}), so another seed is tried"]
            validation["failure_codes"] = [*validation.get("failure_codes", []), code]
            validation["status"] = "failed"
    return validation
