"""Render a textured mesh along the view that best fits its concept: base colour and UV-coordinate passes.

Usage: blender --background --python concept_view.py -- request.json

request.json: {"model": textured.glb, "basecolor": texture.png, "concept": cutout.png (RGBA),
               "prefix": output path prefix, "report": report.json, "size": optional render size (2048),
               "full_turn": optional, also search views from behind (weapons)}

TRELLIS.2 rebuilds a prop facing front, not posed as its three-quarter concept shows it, so the view is found by
comparing the concept silhouette with orthographic silhouettes of surface samples over the front half of the view
sphere. The passes let slopforge/emitters.py carry concept pixels onto the texture through the surface the render
shows; the UV pass is float (<prefix>_uv.npy, rows from the top) because 8-bit UVs land 16 texels off at 4096.
"""
import json
import math
import sys
import traceback

import bpy
import numpy as np
from mathutils import Vector

GRID = 128
MIN_SILHOUETTE_IOU = 0.9  # fits on 2026-10-20 relay bakes scored 0.970-0.975; a poor fit maps onto wrong parts


def silhouette(points):
    """Filled GRID x GRID silhouette of 2D points (y up), fitted to their bounding box with the aspect kept."""
    lo, hi = points.min(0), points.max(0)
    size = (hi - lo).max()
    span = (hi - lo) / size * (GRID - 9)
    cells = np.clip(np.round((points - lo) / size * (GRID - 9) + 4 + ((GRID - 9) - span) / 2).astype(int), 0, GRID - 1)
    mask = np.zeros((GRID, GRID), bool)
    mask[cells[:, 1], cells[:, 0]] = True
    filled = np.zeros_like(mask)
    for row in range(GRID):  # rows filled between their extremes, for concept and mesh alike
        columns = np.flatnonzero(mask[row])
        if len(columns):
            filled[row, columns[0]:columns[-1] + 1] = True
    return filled


def view_axes(theta, phi):
    """Towards-camera, right and up vectors; theta 0 looks at the front (-Y), phi raises the camera."""
    towards = Vector((math.sin(theta) * math.cos(phi), -math.cos(theta) * math.cos(phi), math.sin(phi)))
    right = Vector((math.cos(theta), math.sin(theta), 0.0))
    return towards, right, towards.cross(right)


def image_mask(path, channel=3):
    """A Blender-loaded image's mask (rows from the bottom): alpha for a cut-out, red for an L mask."""
    image = bpy.data.images.load(str(path))
    width, height = image.size
    pixels = np.empty(width * height * 4, np.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    return pixels.reshape(height, width, 4)[:, :, channel] > 0.5


def surface_samples(obj):
    """World-space vertices plus four random points per triangle, so thin faces still cover the silhouette."""
    world = np.array([obj.matrix_world @ vertex.co for vertex in obj.data.vertices])
    triangles = np.array([polygon.vertices[:3] for polygon in obj.data.polygons if len(polygon.vertices) == 3])
    if not len(triangles):
        raise ValueError("Mesh has no triangles")
    weights = np.random.default_rng(0).dirichlet((1, 1, 1), size=(len(triangles), 4))
    return world, np.concatenate([np.einsum("tsk,tkd->tsd", weights, world[triangles]).reshape(-1, 3), world])


def area_samples(obj, count=20000):
    """World-space points spread over the surface by area: a frame found from them is not leaned by a small part
    meshed finely (surface_samples weighs every triangle alike, and a chest's dense hasp turned its frame 6-9 degrees
    on OPEN3 and OPEN4, 2026-10-26)."""
    world = np.array([obj.matrix_world @ vertex.co for vertex in obj.data.vertices])
    triangles = world[np.array([polygon.vertices[:3] for polygon in obj.data.polygons if len(polygon.vertices) == 3])]
    areas = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1)
    rng = np.random.default_rng(0)
    chosen = rng.choice(len(triangles), count, p=areas / areas.sum())
    weights = rng.dirichlet((1, 1, 1), size=count)
    return np.einsum("sk,skd->sd", weights, triangles[chosen])


def footprint_axes(points, top):
    """The two axes across `top` of the points' smallest enclosing rectangle, the longer side's first: a box-like
    prop's own edges, whatever crowds its samples."""
    from mathutils import Vector
    from mathutils.geometry import convex_hull_2d
    top = np.asarray(top, float)
    u = np.cross(top, [1.0, 0.0, 0.0] if abs(top[0]) < 0.9 else [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    v = np.cross(top, u)
    flat = np.stack([points @ u, points @ v], 1)
    hull = flat[convex_hull_2d([Vector(point) for point in flat])]
    best = None
    for a, b in zip(hull, np.roll(hull, -1, 0)):
        edge = (b - a) / max(float(np.linalg.norm(b - a)), 1e-12)
        normal = np.array([-edge[1], edge[0]])
        sides = (float(np.ptp(hull @ edge)), float(np.ptp(hull @ normal)))
        if best is None or sides[0] * sides[1] < best[0]:
            best = (sides[0] * sides[1], edge, normal, sides)
    _, edge, normal, (along, beside) = best
    first, second = (edge, normal) if along >= beside else (normal, edge)
    return np.array([first[0] * u + first[1] * v, second[0] * u + second[1] * v])


def fit_view(samples, concept, full_turn=False):
    """(silhouette IoU, theta, phi in degrees) of the view whose mesh silhouette best fits the concept mask.

    full_turn also searches the back half, front-facing views first so they win ties: TRELLIS.2 rebuilt three of four
    side-profile swords turned to face the other way, which only a view from behind fits (2026-10-24, weapons).
    """
    rows, columns = np.nonzero(concept)
    if not len(rows):
        raise ValueError("Concept cutout has no opaque pixels")
    target = silhouette(np.stack([columns, rows], 1).astype(float))
    fits = []
    for phi in range(0, 46, 5):
        for theta in (sorted(range(-180, 180, 5), key=abs) if full_turn else range(-90, 91, 5)):
            _, right, up = view_axes(math.radians(theta), math.radians(phi))
            fitted = silhouette(np.stack([samples @ np.array(right), samples @ np.array(up)], 1))
            fits.append((float((fitted & target).sum() / max((fitted | target).sum(), 1)), theta, phi))
    return least_elevated(fits)


VIEW_MARGIN = 0.01  # silhouette overlap an elevation must add before it is taken


def least_elevated(fits, margin=VIEW_MARGIN):
    """Of (iou, theta, phi) fits in search order: the best fit, seen from the least elevated view within `margin` of
    it (the best of those, the first among equals). The fit says how well the shape matches the concept, which
    callers gate on; the view is where to look from. A side-profile pistol's silhouette barely changes from a little
    above: three seeds fitted best at 20, 15 and 5 degrees by under 0.01 over the flat side, and at 20 its far side
    stopped voting and its trigger's mask was dropped (2026-10-25); a longsword whose flat mesh fitted 0.92 at 30
    degrees against 0.83 at 0 keeps its 30."""
    best = max(fit[0] for fit in fits)
    close = [fit for fit in fits if fit[0] >= best - margin]
    lowest = min(fit[2] for fit in close)
    _iou, theta, phi = max((fit for fit in close if fit[2] == lowest), key=lambda fit: fit[0])
    return best, theta, phi


def to_concept_pixels(points, concept):
    """Map 2D view coordinates of mesh points onto concept pixels (column, row from the bottom), matching bounds
    with the aspect kept, as silhouette() does for both."""
    rows, columns = np.nonzero(concept)
    concept_low = np.array([columns.min(), rows.min()], float)
    concept_span = np.array([columns.max(), rows.max()], float) - concept_low
    low, span = points.min(0), points.max(0) - points.min(0)
    scale = concept_span.max() / max(span.max(), 1e-9)
    return np.round(concept_low + (concept_span - span * scale) / 2 + (points - low) * scale).astype(int)


def emission_material(name, image=None):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    emission = nodes.new("ShaderNodeEmission")
    links.new(emission.outputs[0], nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    uv = nodes.new("ShaderNodeUVMap")
    if image is None:
        links.new(uv.outputs[0], emission.inputs["Color"])  # (u, v, 0)
    else:
        texture = nodes.new("ShaderNodeTexImage")
        texture.image, texture.interpolation = image, "Closest"
        links.new(uv.outputs[0], texture.inputs[0])
        links.new(texture.outputs["Color"], emission.inputs["Color"])
    return material


def run(request):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=request["model"])
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    if not meshes:
        raise ValueError(f"Expected a mesh in {request['model']}, found none")
    # A weapon generated as parts is one mesh object per part (2026-10-25); the view is of the whole weapon, and
    # every part's UV layer is named UVMap, so the join keeps one map for the base colour.
    bpy.ops.object.select_all(action="DESELECT")
    for item in meshes:
        item.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    world, samples = surface_samples(obj)
    iou, theta, phi = fit_view(samples, image_mask(request["concept"]), request.get("full_turn", False))
    report = {"theta": theta, "phi": phi, "silhouette_iou": round(iou, 4)}
    # Colour comparison only needs the concept's side of the model, not texel registration.
    min_iou = float(request.get("min_iou", MIN_SILHOUETTE_IOU))
    if iou < min_iou:
        return {**report, "status": "skipped", "reason": f"best silhouette fit {iou:.3f} is below {min_iou}"}

    towards, right, up = view_axes(math.radians(theta), math.radians(phi))
    centre = Vector(world.mean(0))
    extent = max(float(np.abs((world - np.array(centre)) @ np.array(axis)).max()) for axis in (right, up))
    camera_data = bpy.data.cameras.new("ConceptView")
    camera_data.type, camera_data.ortho_scale = "ORTHO", extent * 2.2
    camera_data.clip_end = extent * 40
    camera = bpy.data.objects.new("ConceptView", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = centre + towards * extent * 10
    camera.rotation_euler = (-towards).to_track_quat("-Z", "Y").to_euler()
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    size = int(request.get("size") or 2048)
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "Standard"

    obj.data.materials.clear()
    obj.data.materials.append(emission_material("ConceptViewBase", bpy.data.images.load(request["basecolor"])))
    scene.render.image_settings.file_format, scene.render.image_settings.color_mode = "PNG", "RGBA"
    scene.render.filepath = request["prefix"] + "_base.png"
    bpy.ops.render.render(write_still=True)
    if not request.get("uv", True):
        return {**report, "status": "rendered", "size": size}

    obj.data.materials.clear()
    obj.data.materials.append(emission_material("ConceptViewUV"))
    scene.view_settings.view_transform = "Raw"
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.filepath = request["prefix"] + "_uv.exr"
    bpy.ops.render.render(write_still=True)
    rendered = bpy.data.images.load(request["prefix"] + "_uv.exr")
    uv = np.empty(size * size * 4, np.float32)
    rendered.pixels.foreach_get(uv)
    np.save(request["prefix"] + "_uv.npy", uv.reshape(size, size, 4)[::-1])
    return {**report, "status": "rendered", "size": size}


def main():
    request = json.loads(open(sys.argv[sys.argv.index("--") + 1]).read())
    try:
        result = run(request)
    except Exception as exc:
        result = {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
    with open(request["report"], "w") as stream:
        json.dump(result, stream, indent=2)
    if result["status"] == "failed":
        raise SystemExit(result["error"])


if __name__ == "__main__":  # prepare_model.py imports the fitting helpers
    main()
