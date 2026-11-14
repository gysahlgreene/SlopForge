"""Delivery for Unreal Engine: the FBX in Unreal's axes, PBR maps as Unreal reads them, and, for a model that breaks
apart when killed, its rigid parts each with its origin on its joint (docs/UNREAL.md).

A project chooses Unreal with `project.engine: unreal` in ai/project.yaml; `approve-texture` then publishes this
instead of Unity's material, metadata and prefab.
"""
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops

from .failures import StageFailure
from .parts import make_part_masks, parse_part_box
from .paths import tool_root

VIEWS = ("front", "back")  # blender/export_unreal.py's VIEWS


def engine(config):
    return str((config.get("project") or {}).get("engine") or "unity").lower()


def unreal_maps(normal, roughness, metallic, orm, normal_out):
    """Unreal's packed occlusion-roughness-metallic map (R 1, G roughness, B metallic: no occlusion is baked) and the
    normal map with its green channel flipped, since Unreal reads DirectX normals and the bake is OpenGL's."""
    with Image.open(roughness) as rough, Image.open(metallic) as metal:
        rough, metal = rough.convert("L"), metal.convert("L").resize(rough.size)
        Image.merge("RGB", (Image.new("L", rough.size, 255), rough, metal)).save(orm)
    with Image.open(normal) as image:
        red, green, blue = image.convert("RGB").split()
        Image.merge("RGB", (red, ImageChops.invert(green), blue)).save(normal_out)


def load_break_parts(path):
    """A break-apart declaration: {"body": part, "parents": {part: parent}, "views": {"front"|"back": {part: box}}},
    boxes as fractions of break-views' renders from the top left. A part may give a list of boxes, masked one by one
    and joined: one box round a diagonal rifle took the whole robot (round 25). Every part other than the body needs a
    parent, and a box in at least one view. "over": [part, ...] lists parts lying in front of others (a rifle slung
    across the chest), whose masks win where masks overlap."""
    spec = json.loads(Path(path).read_text())
    views = spec.get("views") or {}
    if not views or set(views) - set(VIEWS):
        raise ValueError(f"--break-parts needs boxes under views {', '.join(VIEWS)}")
    names = {name for boxes in views.values() for name in boxes}
    for boxes in views.values():
        for name, box in boxes.items():
            for one in _boxes(box):
                parse_part_box(f"{name}={','.join(str(value) for value in one)}")
    body, parents = spec.get("body"), spec.get("parents") or {}
    if body not in names:
        raise ValueError(f"--break-parts body {body!r} has no box")
    missing = sorted(name for name in names - {body} if parents.get(name) not in names)
    if missing:
        raise ValueError(f"--break-parts: part(s) {', '.join(missing)} need a parent that has a box")
    over = spec.get("over") or []
    if set(over) - names:
        raise ValueError(f"--break-parts over names part(s) with no box: {', '.join(sorted(set(over) - names))}")
    return {"body": body, "parents": parents, "views": views, "over": over}


def _boxes(box):
    return box if box and isinstance(box[0], (list, tuple)) else [box]


def mask_views(config, views_dir, break_parts, work_dir):
    """Each part's SAM masks on the break views: {part: {view: mask path}}, a part's several boxes joined."""
    import numpy as np
    work_dir, masks = Path(work_dir), {}
    for view in VIEWS:
        boxes = break_parts["views"].get(view)
        if not boxes:
            continue
        pieces = [(name, f"{name}__{number}" if len(_boxes(box)) > 1 else name, one)
                  for name, box in boxes.items() for number, one in enumerate(_boxes(box))]
        folder = work_dir / f"masks_{view}"
        report = make_part_masks(config, Path(views_dir) / f"view_{view}.png",
                                 [{"name": key, "text": name.replace("_", " "), "box": one} for name, key, one in pieces],
                                 folder)
        for name in boxes:
            found = [folder / f"{key}.png" for part, key, _one in pieces
                     if part == name and (report.get("parts", {}).get(key) or {}).get("share", 0) > 0]
            if not found:
                continue
            if len(found) > 1 or found[0].stem != name:
                union = np.any([np.asarray(Image.open(path).convert("L")) > 127 for path in found], axis=0)
                Image.fromarray((union * 255).astype(np.uint8)).save(folder / f"{name}.png")
            masks.setdefault(name, {})[view] = str(folder / f"{name}.png")
    return masks


def run_export(blender, request, directory):
    """blender/export_unreal.py on a request; returns its report."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "unreal_request.json"
    path.write_text(json.dumps(request, indent=2))
    result = subprocess.run([blender, "--background", "--python-exit-code", "1", "--python",
                             str(tool_root() / "blender/export_unreal.py"), "--", str(path)], capture_output=True, text=True)
    if result.returncode or not Path(request["report"]).is_file():
        raise StageFailure("processing_validation", "Unreal export failed: " + (result.stdout + result.stderr)[-800:],
                           operation="unreal_export", remedy="see the Blender output above")
    return json.loads(Path(request["report"]).read_text())


def render_break_views(blender, blend, name, directory):
    """The model's front and back as orthographic renders (view_front.png, view_back.png), to box its parts on."""
    directory = Path(directory)
    run_export(blender, {"blend": str(blend), "name": name, "out_dir": str(directory), "render_views": str(directory),
                         "report": str(directory / "views.json")}, directory)
    return [directory / f"view_{view}.png" for view in VIEWS]


def export_unreal(config, blender, blend, name, out_dir, work_dir, break_parts=None, moving=None, keep_origin=False):
    """<out_dir>/<name>.fbx, and with break_parts (load_break_parts) its parts in <out_dir>/Parts; returns the report.
    moving: the declared hinges and slides a weapon's final pass split off, each written to Parts with its origin on
    its pivot and its axis and range in Unreal's frame. keep_origin: a held weapon keeps its grip as its origin.

    The part masks are cut by SAM 2.1 on the views' renders from the declared boxes (slopforge.parts), then the cut
    is made on the same renders' camera (blender/export_unreal.py)."""
    work_dir = Path(work_dir)
    request = {"blend": str(blend), "name": name, "out_dir": str(out_dir), "report": str(work_dir / "unreal.json"),
               "moving": moving or [], "keep_origin": keep_origin}
    if break_parts:
        render_break_views(blender, blend, name, work_dir / "views")
        masks = mask_views(config, work_dir / "views", break_parts, work_dir)
        lost = sorted({part for boxes in break_parts["views"].values() for part in boxes} - set(masks))
        if lost:
            raise StageFailure("configuration", f"Part(s) {', '.join(lost)} were not found in their boxes",
                               operation="part_mask_preflight", remedy="check the boxes against break-views' renders")
        request.update({"body": break_parts["body"],
                        "parts": [{"name": part, "masks": views_, "over": part in break_parts.get("over", []),
                                   **({"parent": break_parts["parents"][part]} if part in break_parts["parents"] else {})}
                                  for part, views_ in masks.items()]})
    return run_export(blender, request, work_dir)
