#!/usr/bin/env python3
"""Build a labelled concept → PBR maps → render strip for one material candidate.

Usage: material_showcase.py <project> <asset-name> <material-number> <out.png> [--size 256]

Writes <out.png> and <out.json> (hashes, map statistics, normal/emission sources and the
candidate's validation status) so published showcase images keep their provenance.
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slopforge.config import load_project  # noqa: E402
from slopforge.manifest import load_manifest  # noqa: E402
from slopforge.pipelines.model import material_candidate_paths  # noqa: E402
from slopforge.provenance import file_sha256  # noqa: E402
from slopforge.validation import measure_material_maps  # noqa: E402

PANELS = (("concept", "Concept"), ("basecolor", "Base color"), ("normal", "Normal"),
          ("roughness", "Roughness"), ("metallic", "Metallic"), ("emission", "Emission"),
          ("preview_front", "Front"), ("preview_three_quarter", "Three-quarter"))


def find_asset(manifest, name):
    for key, asset in manifest["assets"].items():
        if asset.get("name") == name:
            return key, asset
    raise SystemExit(f"No asset named {name!r} in the manifest")


def build(project, name, number, out, size=256):
    root = Path(project).resolve()
    config = load_project(root)
    manifest = load_manifest(root / config["asset_pipeline"]["manifest"])
    _, asset = find_asset(manifest, name)
    candidate = next((item for item in asset.get("material_candidates", {}).get("items", [])
                      if item.get("number") == number), None)
    if candidate is None:
        raise SystemExit(f"{name} has no material candidate {number}")
    paths = material_candidate_paths(root, config, name, number, asset.get("type", "prop"))
    selected = asset.get("candidates", {}).get("selected")
    concept = next((item for item in asset.get("candidates", {}).get("items", []) if item.get("number") == selected), None)
    paths["concept"] = root / concept["path"] if concept else None

    label_height = 28
    strip = Image.new("RGB", (size * len(PANELS), size + label_height), (245, 245, 245))
    draw = ImageDraw.Draw(strip)
    for index, (key, label) in enumerate(PANELS):
        path = paths.get(key)
        if path and Path(path).is_file():
            with Image.open(path) as image:
                tile = image.convert("RGB")
                tile.thumbnail((size, size))
            strip.paste(tile, (index * size + (size - tile.width) // 2, label_height + (size - tile.height) // 2))
        else:
            draw.text((index * size + 8, label_height + size // 2), "missing", fill=(160, 0, 0))
        draw.text((index * size + 8, 8), label, fill=(30, 30, 30))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    strip.save(out, optimize=True)

    validation = candidate.get("validation", {})
    stats = measure_material_maps({key: paths[key] for key in ("basecolor", "roughness", "metallic")})
    summary = {"asset": name, "material_candidate": number, "concept_candidate": selected,
               "materials": asset.get("materials", []), "normal_source": candidate.get("normal_source", "unknown"),
               "emission_source": candidate.get("emission_source", "unknown"),
               "workflow": candidate.get("generator", {}).get("workflow") if isinstance(candidate.get("generator"), dict) else None,
               "validation_status": validation.get("status"), "validation_warnings": validation.get("warnings", []),
               "map_statistics": stats["maps"],
               "sha256": {key: file_sha256(paths[key]) for key, _ in PANELS
                          if paths.get(key) and Path(paths[key]).is_file()}}
    out.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project")
    parser.add_argument("name")
    parser.add_argument("number", type=int)
    parser.add_argument("out")
    parser.add_argument("--size", type=int, default=256)
    args = parser.parse_args()
    summary = build(args.project, args.name, args.number, args.out, args.size)
    print(json.dumps({key: summary[key] for key in ("asset", "normal_source", "emission_source", "validation_status")}))


if __name__ == "__main__":
    main()
