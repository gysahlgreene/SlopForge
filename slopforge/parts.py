"""Declared parts of a model asset (a weapon's grip, a trigger that hinges, a slide), and their concept masks.

Each part is masked on the approved concept by processing/part_masks.py: Florence-2 (MIT) detects it from its
description and SAM 2.1 (Apache-2.0) cuts it. That runs in its own environment, on tools.parts_host over SSH like
SkinTokens, or locally when no host is set. Mesh preparation later splits the parts from the one generated mesh along
these masks, so their colour and placement match the body by construction (docs/WEAPONS.md).
"""
import json
import re
import shlex
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

import numpy as np
from PIL import Image

from .failures import StageFailure
from .paths import tool_root

PART_KINDS = ("grip", "hinge", "slide")
PART_AXES = ("x", "y", "z")
_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
DEFAULT_MODELS = {"florence": "florence-community/Florence-2-large", "sam": "facebook/sam2.1-hiera-large"}
# A mask under this share of the object found nothing usable; the lantern's carrying ring was 0.0034 (2026-10-24).
MIN_PART_SHARE = 0.001


def parse_part_spec(spec):
    """'name=grip[: text]' or 'name=hinge|slide:axis:min..max[: text]' -> a part record.

    The axis is in the weapon's frame as Unity shows it (x right, y up, z forward along the blade or barrel); a
    hinge's range is in degrees, a slide's in metres. The text is what the part is called in the concept.
    """
    name, separator, rest = spec.partition("=")
    fields = rest.split(":")
    kind = fields[0].strip().lower()
    usage = ("--part must be 'name=grip[: description]' or 'name=hinge|slide:x|y|z:min..max[: description]', "
             f"got {spec!r}")
    if not separator or not _NAME.match(name.strip()) or kind not in PART_KINDS:
        raise ValueError(usage)
    part = {"name": name.strip(), "kind": kind}
    if kind == "grip":
        text = ":".join(fields[1:])
    else:
        if len(fields) < 3 or fields[1].strip().lower() not in PART_AXES:
            raise ValueError(usage)
        low, dots, high = fields[2].strip().partition("..")
        try:
            low, high = float(low), float(high)
        except ValueError:
            raise ValueError(usage) from None
        if not dots or low >= high:
            raise ValueError(usage)
        part.update({"axis": fields[1].strip().lower(), "min": low, "max": high})
        text = ":".join(fields[3:])
    part["text"] = text.strip() or part["name"].replace("_", " ")
    return part


def parse_part_box(spec):
    """'name=x0,y0,x1,y1' -> (name, box): where a part lies on the approved concept, as fractions of its width and
    height from the top left. Given at approval, once the concept is chosen."""
    name, separator, rest = spec.partition("=")
    try:
        box = [float(value) for value in rest.split(",")]
    except ValueError:
        box = []
    if (not separator or not _NAME.match(name.strip()) or len(box) != 4 or not all(0 <= value <= 1 for value in box)
            or box[0] >= box[2] or box[1] >= box[3]):
        raise ValueError(f"--part-box must be 'name=x0,y0,x1,y1' as fractions of the concept (0-1, top left first), "
                         f"got {spec!r}")
    return name.strip(), box


def set_part_boxes(parts, boxes):
    """Copy approval-time boxes onto the declared parts; an unknown part name is an error."""
    names = {part["name"] for part in parts}
    unknown = sorted(name for name, _ in boxes if name not in names)
    if unknown:
        raise ValueError(f"--part-box names undeclared part(s) {', '.join(unknown)}; declared: {', '.join(sorted(names))}")
    given = dict(boxes)
    return [{**part, "box": given[part["name"]]} if part["name"] in given else part for part in parts]


def validate_parts(parts):
    """Part names are unique, and at most one part is the grip."""
    names = [part["name"] for part in parts]
    if len(set(names)) != len(names):
        raise ValueError(f"Part names must be unique, got {', '.join(names)}")
    if sum(part["kind"] == "grip" for part in parts) > 1:
        raise ValueError("Declare at most one grip part")
    return parts


def part_settings(config, parts):
    """What the conditioning stage's identity records for declared parts: changing a part or a model re-masks."""
    return {"parts": parts, "models": _tools(config)[2], "tool": "part_masks.py"}


def _tools(config):
    tools = config.get("asset_pipeline", {}).get("tools", {})
    host = tools.get("parts_host") if isinstance(tools.get("parts_host"), str) and tools.get("parts_host") else None
    return host, tools.get("parts_python"), {**DEFAULT_MODELS, **(tools.get("parts_models") or {})}


def _run_remote(host, python, request, cutout, out_dir):
    ssh = ["ssh", "-o", "BatchMode=yes", host]
    made = subprocess.run(ssh + ["mktemp", "-d", "/tmp/slopforge-parts-XXXXXX"], capture_output=True, text=True,
                          check=False)
    # Shell start-up files may print first; cleanup runs `rm -rf` on this path, so accept only mktemp's line.
    work = (made.stdout.strip().splitlines() or [""])[-1].strip()
    if made.returncode != 0 or not re.fullmatch(r"/tmp/slopforge-parts-[A-Za-z0-9]+", work):
        raise RuntimeError(f"Could not create a part-mask work directory on {host}")
    work = PurePosixPath(work)
    try:
        with tempfile.TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "request.json"
            request_path.write_text(json.dumps({**request, "image": str(work / "concept.png"),
                                                "out_dir": str(work / "masks")}))
            for local, remote in ((cutout, work / "concept.png"), (request_path, work / "request.json")):
                if subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(local), f"{host}:{remote}"],
                                  check=False).returncode != 0:
                    raise RuntimeError(f"Could not upload {local.name} to {host}")
        completed = subprocess.run(ssh + [shlex.join([python, "-", str(work / "request.json")])],
                                   input=(tool_root() / "processing/part_masks.py").read_text(),
                                   capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"Part masks on {host} failed: "
                               + (completed.stderr.strip().splitlines() or ["no output"])[-1])
        out_dir.mkdir(parents=True, exist_ok=True)
        if subprocess.run(["scp", "-q", "-r", "-o", "BatchMode=yes", f"{host}:{work / 'masks'}/.", str(out_dir)],
                          check=False).returncode != 0:
            raise RuntimeError(f"Could not download the part masks from {host}")
    finally:
        subprocess.run(ssh + ["rm", "-rf", "--", str(work)], check=False)


def make_part_masks(config, cutout, parts, out_dir):
    """Mask every declared part on the concept cutout; returns masks.json's report and writes an overlay image."""
    host, python, models = _tools(config)
    if not python:
        raise StageFailure("configuration", "Declared parts are masked by Florence-2 and SAM 2.1, and no Python for "
                           "them is configured", operation="part_mask_preflight",
                           remedy="set tools.parts_python (and tools.parts_host for a GPU host); see docs/WEAPONS.md")
    out_dir = Path(out_dir)
    request = {"parts": [{key: part[key] for key in ("name", "text", "box") if key in part} for part in parts],
               **models}
    if host:
        _run_remote(host, python, request, Path(cutout), out_dir)
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "request.json"
            request_path.write_text(json.dumps({**request, "image": str(cutout), "out_dir": str(out_dir)}))
            subprocess.run([python, str(tool_root() / "processing/part_masks.py"), str(request_path)], check=True)
    report = json.loads((out_dir / "masks.json").read_text())
    overlay(cutout, out_dir, parts)
    return report


def check_part_masks(report, parts):
    """Stop before mesh inference when a declared part was not found on the concept: every seed would miss it."""
    missing = [part["name"] for part in parts
               if (report.get("parts", {}).get(part["name"]) or {}).get("share", 0) < MIN_PART_SHARE]
    if missing:
        raise StageFailure(
            "configuration", f"Declared part(s) {', '.join(missing)} were not found on the approved concept",
            operation="part_mask_preflight",
            remedy="describe each part as the concept draws it (--part 'name=kind...: description'), or approve a "
                   "concept that shows every part as a distinct piece")


def overlay(cutout, out_dir, parts):
    """The concept with each part's mask tinted, for review (parts_overlay.png)."""
    colours = ((230, 70, 50), (60, 140, 255), (60, 200, 90), (240, 190, 40), (190, 80, 220))
    with Image.open(cutout) as image:
        image = image.convert("RGBA")
    base = Image.new("RGBA", image.size, (128, 128, 128, 255))
    base.alpha_composite(image)
    pixels = np.asarray(base.convert("RGB"), dtype=float)
    for index, part in enumerate(parts):
        path = Path(out_dir) / f"{part['name']}.png"
        if path.is_file():
            with Image.open(path) as mask:
                inside = np.asarray(mask.convert("L")) > 127
            pixels[inside] = pixels[inside] * 0.35 + np.array(colours[index % len(colours)]) * 0.65
    Image.fromarray(pixels.round().astype(np.uint8)).save(Path(out_dir) / "parts_overlay.png")
