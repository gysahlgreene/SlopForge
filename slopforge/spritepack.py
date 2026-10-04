import json
import os
import tempfile
from pathlib import Path

from PIL import Image

from .taxonomy import validate_asset_name


def package_sprite_sheet(source, output_directory, animation, *, columns, rows, fps, pivot=(0.5, 0.0), loop=False):
    source = Path(source).expanduser().resolve()
    destination = Path(output_directory).expanduser().resolve()
    validate_asset_name(animation)
    if not source.is_file():
        raise FileNotFoundError(f"Sprite sheet not found: {source}")
    if type(columns) is not int or type(rows) is not int or columns < 1 or rows < 1:
        raise ValueError("Sprite sheet rows and columns must be positive integers")
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or fps <= 0:
        raise ValueError("Sprite animation fps must be positive")
    if (not isinstance(pivot, (list, tuple)) or len(pivot) != 2 or
            any(not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1
                for value in pivot)):
        raise ValueError("Sprite pivot coordinates must be between 0 and 1")
    if destination.exists():
        raise FileExistsError(f"Sprite pack output already exists: {destination}")

    with Image.open(source) as image:
        sheet = image.convert("RGBA")
    if sheet.width % columns or sheet.height % rows:
        raise ValueError("Sprite sheet dimensions must be divisible by its rows and columns")
    frame_width, frame_height = sheet.width // columns, sheet.height // rows
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}.", dir=destination.parent) as temporary:
        staging = Path(temporary) / "pack"
        staging.mkdir()
        frames = []
        for index in range(columns * rows):
            column, row = index % columns, index // columns
            frame = sheet.crop((column * frame_width, row * frame_height,
                                (column + 1) * frame_width, (row + 1) * frame_height))
            path = staging / f"frame_{index:03d}.png"
            frame.save(path, format="PNG", optimize=False)
            frames.append(path.name)
        sheet.save(staging / "atlas.png", format="PNG", optimize=False)
        metadata = {
            "schema_version": 1,
            "animation": animation,
            "source": source.name,
            "frame_count": len(frames),
            "frame_size": [frame_width, frame_height],
            "columns": columns,
            "rows": rows,
            "fps": fps,
            "frame_duration_seconds": 1 / fps,
            "loop": bool(loop),
            "pivot": {"x": float(pivot[0]), "y": float(pivot[1])},
            "frames": frames,
        }
        (staging / "animation.json").write_text(json.dumps(metadata, indent=2) + "\n")
        os.replace(staging, destination)
    return {**metadata, "directory": destination, "atlas": destination / "atlas.png",
            "metadata": destination / "animation.json",
            "frame_paths": [destination / name for name in frames]}
