import json
import os
import tempfile
from pathlib import Path

from PIL import Image

from .taxonomy import validate_asset_name


def _edge_difference(first, second):
    pixels = zip(first.convert("RGBA").get_flattened_data(), second.convert("RGBA").get_flattened_data())
    values = [abs(left - right) for a, b in pixels for left, right in zip(a, b)]
    return round(sum(values) / (len(values) * 255), 6) if values else 0.0


def package_tileset(source, output_directory, name, *, columns, rows, tile_size, margin, padding, layout,
                    collider="none", transition_masks=None):
    source = Path(source).expanduser().resolve()
    destination = Path(output_directory).expanduser().resolve()
    validate_asset_name(name)
    if not source.is_file():
        raise FileNotFoundError(f"Tile sheet not found: {source}")
    if type(columns) is not int or type(rows) is not int or columns < 1 or rows < 1:
        raise ValueError("Tileset columns and rows must be positive integers")
    if (not isinstance(tile_size, (tuple, list)) or len(tile_size) != 2 or
            any(type(value) is not int or value < 1 for value in tile_size)):
        raise ValueError("Tile width and height must be positive integers")
    if type(margin) is not int or type(padding) is not int or margin < 0 or padding < 0:
        raise ValueError("Tile margin and padding must be non-negative integers")
    if layout not in {"orthogonal", "isometric"}:
        raise ValueError("Tileset layout must be orthogonal or isometric")
    if collider not in {"none", "grid", "sprite"}:
        raise ValueError("Tile collider must be none, grid, or sprite")
    if transition_masks is not None:
        if (not isinstance(transition_masks, (tuple, list)) or len(transition_masks) != columns * rows or
                any(type(mask) is not int or not 0 <= mask <= 15 for mask in transition_masks) or
                len(set(transition_masks)) != len(transition_masks)):
            raise ValueError("Transition masks must be unique integers 0-15, one per tile")
    if destination.exists():
        raise FileExistsError(f"Tileset output already exists: {destination}")

    with Image.open(source) as image:
        sheet = image.convert("RGBA")
    tile_width, tile_height = tile_size
    expected = (2 * margin + columns * tile_width + (columns - 1) * padding,
                2 * margin + rows * tile_height + (rows - 1) * padding)
    if sheet.size != expected:
        raise ValueError(f"Tile sheet dimensions are {sheet.size}; expected {expected} from grid and spacing")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}.", dir=destination.parent) as temporary:
        staging = Path(temporary) / "tileset"
        staging.mkdir()
        tiles, images = [], []
        for index in range(columns * rows):
            column, row = index % columns, index // columns
            left = margin + column * (tile_width + padding)
            top = margin + row * (tile_height + padding)
            tile = sheet.crop((left, top, left + tile_width, top + tile_height))
            filename = f"tile_{index:03d}.png"
            tile.save(staging / filename, format="PNG", optimize=False)
            rgba = tile.convert("RGBA")
            images.append(rgba)
            alpha_pixels = list(rgba.getchannel("A").get_flattened_data())
            edges = {
                "left": sum(value > 0 for value in rgba.getchannel("A").crop((0, 0, 1, tile_height)).get_flattened_data()),
                "right": sum(value > 0 for value in rgba.getchannel("A").crop((tile_width - 1, 0, tile_width, tile_height)).get_flattened_data()),
                "top": sum(value > 0 for value in rgba.getchannel("A").crop((0, 0, tile_width, 1)).get_flattened_data()),
                "bottom": sum(value > 0 for value in rgba.getchannel("A").crop((0, tile_height - 1, tile_width, tile_height)).get_flattened_data()),
            }
            tiles.append({"id": f"{name}_{index:03d}", "index": index, "x": column, "y": row,
                          "path": filename, "alpha_coverage": round(sum(value > 0 for value in alpha_pixels) /
                                                                        len(alpha_pixels), 6),
                          "edge_alpha_pixels": edges})

        atlas = Image.new("RGBA", (columns * tile_width, rows * tile_height), (0, 0, 0, 0))
        for index, tile in enumerate(images):
            atlas.paste(tile, ((index % columns) * tile_width, (index // columns) * tile_height))
        atlas.save(staging / "atlas.png", format="PNG", optimize=False)

        comparisons = []
        for row in range(rows):
            for column in range(columns):
                index = row * columns + column
                if column + 1 < columns:
                    delta = _edge_difference(images[index].crop((tile_width - 1, 0, tile_width, tile_height)),
                                             images[index + 1].crop((0, 0, 1, tile_height)))
                    comparisons.append({"from": index, "to": index + 1, "axis": "horizontal",
                                        "mean_absolute_difference": delta})
                if row + 1 < rows:
                    below = index + columns
                    delta = _edge_difference(images[index].crop((0, tile_height - 1, tile_width, tile_height)),
                                             images[below].crop((0, 0, tile_width, 1)))
                    comparisons.append({"from": index, "to": below, "axis": "vertical",
                                        "mean_absolute_difference": delta})

        metadata = {"schema_version": 1, "name": name, "source": source.name, "layout": layout,
                    "columns": columns, "rows": rows, "tile_count": len(tiles),
                    "tile_size": [tile_width, tile_height], "margin": margin, "padding": padding,
                    "collider": collider, "tile_order": "row_major", "tiles": tiles,
                    "edges": comparisons,
                    "max_edge_difference": max((edge["mean_absolute_difference"] for edge in comparisons), default=0.0)}
        if transition_masks is not None:
            metadata["transition_rules"] = {str(mask): tiles[index]["id"]
                                            for index, mask in enumerate(transition_masks)}
        (staging / "tileset.json").write_text(json.dumps(metadata, indent=2) + "\n")
        os.replace(staging, destination)
    return {**metadata, "directory": destination, "atlas": destination / "atlas.png",
            "metadata": destination / "tileset.json",
            "tile_paths": [destination / tile["path"] for tile in tiles]}
