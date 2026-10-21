"""Render a textured mesh along the view that best fits its concept: base colour and UV-coordinate passes.

Usage: blender --background --python concept_view.py -- request.json

request.json: {"model": textured.glb, "basecolor": texture.png, "concept": cutout.png (RGBA),
               "prefix": output path prefix, "report": report.json, "size": optional render size (2048)}

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
    if len(meshes) != 1:
        raise ValueError(f"Expected one mesh in {request['model']}, found {len(meshes)}")
    obj = meshes[0]
    world = np.array([obj.matrix_world @ vertex.co for vertex in obj.data.vertices])
    triangles = np.array([polygon.vertices[:3] for polygon in obj.data.polygons if len(polygon.vertices) == 3])
    if not len(triangles):
        raise ValueError("Mesh has no triangles")
    weights = np.random.default_rng(0).dirichlet((1, 1, 1), size=(len(triangles), 4))
    samples = np.concatenate([np.einsum("tsk,tkd->tsd", weights, world[triangles]).reshape(-1, 3), world])

    concept = bpy.data.images.load(request["concept"])
    width, height = concept.size
    pixels = np.empty(width * height * 4, np.float32)
    concept.pixels.foreach_get(pixels)
    rows, columns = np.nonzero(pixels.reshape(height, width, 4)[:, :, 3] > 0.5)  # Blender rows start at the bottom
    if not len(rows):
        raise ValueError("Concept cutout has no opaque pixels")
    target = silhouette(np.stack([columns, rows], 1).astype(float))

    best = (-1.0, 0, 0)
    for phi in range(0, 46, 5):
        for theta in range(-90, 91, 5):
            _, right, up = view_axes(math.radians(theta), math.radians(phi))
            fitted = silhouette(np.stack([samples @ np.array(right), samples @ np.array(up)], 1))
            iou = float((fitted & target).sum() / max((fitted | target).sum(), 1))
            if iou > best[0]:
                best = (iou, theta, phi)
    iou, theta, phi = best
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


main()
