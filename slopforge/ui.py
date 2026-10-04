import math
from pathlib import PurePosixPath


def make_sprite_import_metadata(image_path, dimensions, *, border=(0, 0, 0, 0), pivot=(0.5, 0.5),
                                pixels_per_unit=100):
    path = PurePosixPath(image_path) if isinstance(image_path, str) else None
    if path is None or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("UI image path must be project-relative")
    if (not isinstance(dimensions, (tuple, list)) or len(dimensions) != 2 or
            any(type(value) is not int or value < 1 for value in dimensions)):
        raise ValueError("UI sprite dimensions must be positive integers")
    if (not isinstance(border, (tuple, list)) or len(border) != 4 or
            any(type(value) is not int or value < 0 for value in border)):
        raise ValueError("9-slice borders must be four non-negative pixel values")
    if border[0] + border[2] > dimensions[0] or border[1] + border[3] > dimensions[1]:
        raise ValueError("9-slice borders exceed sprite dimensions")
    if (not isinstance(pivot, (tuple, list)) or len(pivot) != 2 or
            any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
                or not 0 <= value <= 1 for value in pivot)):
        raise ValueError("UI pivot coordinates must be between 0 and 1")
    if (not isinstance(pixels_per_unit, (int, float)) or isinstance(pixels_per_unit, bool)
            or not math.isfinite(pixels_per_unit) or pixels_per_unit <= 0):
        raise ValueError("pixels_per_unit must be positive")
    return {
        "schema_version": 1,
        "source_image": path.as_posix(),
        "dimensions": list(dimensions),
        "texture_type": "sprite",
        "sprite_mode": "single",
        "mesh_type": "full_rect",
        "pixels_per_unit": pixels_per_unit,
        "pivot": {"x": float(pivot[0]), "y": float(pivot[1])},
        "border": {"left": border[0], "bottom": border[1], "right": border[2], "top": border[3]},
    }
