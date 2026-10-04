import math


def _near_grid(value, grid, tolerance):
    return abs(value - round(value / grid) * grid) <= tolerance


def _pivot_target(bounds_min, bounds_max, pivot):
    center = [(low + high) / 2 for low, high in zip(bounds_min, bounds_max)]
    if pivot == "center":
        return center
    if pivot == "bottom_center":
        center[2] = bounds_min[2]
        return center
    if pivot == "origin":
        return [0.0, 0.0, 0.0]
    raise ValueError(f"Unsupported environment module pivot rule: {pivot!r}")


def validate_environment_kit(recipe_asset, manifest):
    """Check saved Blender measurements against the recipe's modular constraints."""
    instance = recipe_asset.get("recipe_instance", {})
    constraints = instance.get("definition", {}).get("kit_constraints", {})
    grid = constraints.get("grid_size", 1.0)
    snap_tolerance = constraints.get("snap_tolerance", 0.05)
    pivot_tolerance = constraints.get("pivot_tolerance", 0.05)
    default_max = constraints.get("max_dimension")
    module_rules = constraints.get("modules", {})
    results = {}
    pending = False
    failed = False

    for child_id, stage in instance.get("stages", {}).items():
        asset = manifest.get("assets", {}).get(stage.get("asset_key"))
        if asset is None:
            pending = True
            results[child_id] = {"status": "pending", "errors": ["recipe child asset is missing"]}
            continue
        if asset.get("type") not in {"architecture", "prop", "hero_prop"}:
            results[child_id] = {"status": "not_applicable", "asset_id": asset.get("id"), "errors": []}
            continue
        if asset.get("status") != "ready":
            pending = True
            results[child_id] = {"status": "pending", "asset_id": asset.get("id"), "errors": []}
            continue

        errors = []
        measured = asset.get("validation", {}).get("measured", {})
        dimensions = measured.get("dimensions", [])
        if len(dimensions) != 3 or any(not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
                                        for value in dimensions):
            errors.append("valid positive model dimensions are missing")
        else:
            rule = module_rules.get(child_id, {})
            maximum = rule.get("max_dimension", default_max)
            if maximum is not None and max(dimensions) > maximum:
                errors.append(f"maximum dimension {max(dimensions):.4g} exceeds {maximum}")
            for axis in rule.get("snap_axes", []):
                if axis not in (0, 1, 2):
                    errors.append(f"invalid snap axis {axis!r}; expected 0, 1, or 2")
                elif not _near_grid(dimensions[axis], grid, rule.get("snap_tolerance", snap_tolerance)):
                    errors.append(f"dimension axis {axis} ({dimensions[axis]:.4g}) is off the {grid:g} grid")
            vertical_axis = rule.get("vertical_axis")
            if vertical_axis is not None and (vertical_axis not in (0, 1, 2) or
                                              dimensions[vertical_axis] + snap_tolerance < max(dimensions)):
                errors.append(f"expected the module's vertical extent on axis {vertical_axis}")
            flat_axis = rule.get("flat_axis")
            if flat_axis is not None and (flat_axis not in (0, 1, 2) or
                                          dimensions[flat_axis] - snap_tolerance > min(dimensions)):
                errors.append(f"expected the module's thin extent on axis {flat_axis}")

        if measured.get("transforms_applied") is not True:
            errors.append("mesh orientation/scale transforms are not applied")
        objects = measured.get("objects") or []
        if objects:
            pivot = module_rules.get(child_id, {}).get("pivot", constraints.get("pivot", "center"))
            for obj in objects:
                target = _pivot_target(obj.get("bounds_min", []), obj.get("bounds_max", []), pivot)
                origin = obj.get("origin", [])
                if len(origin) != 3 or any(abs(actual - expected) > pivot_tolerance
                                           for actual, expected in zip(origin, target)):
                    errors.append(f"object pivot does not match {pivot} within {pivot_tolerance:g}")
                    break
        elif measured.get("origins"):
            # Older validation records do not contain per-object bounds; keep the
            # compatibility check to origins inside the aggregate module bounds.
            low, high = measured.get("bounds_min", []), measured.get("bounds_max", [])
            if len(low) == len(high) == 3 and any(
                    any(value < low[i] - pivot_tolerance or value > high[i] + pivot_tolerance
                        for i, value in enumerate(origin)) for origin in measured["origins"]):
                errors.append("one or more object pivots fall outside the module bounds")

        results[child_id] = {"status": "failed" if errors else "passed", "asset_id": asset.get("id"),
                             "dimensions": dimensions, "errors": errors}
        failed |= bool(errors)

    status = "failed" if failed else "partial" if pending else "passed"
    return {"schema_version": 1, "kit": recipe_asset.get("name"), "status": status,
            "constraints": constraints, "modules": results}
