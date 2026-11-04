"""Flat renders of a head from fixed angles, and each texel's position and normal, for repainting what the front can't see.

Usage: blender --background --python character_view.py -- model.glb colour.png out_dir size angle [angle ...]

Angles are degrees round the model from the front (0). Each view is orthographic and unlit, so the painting that comes
back can be projected straight onto the sheet. Writes view_<angle>.png, and views.json with the frame the views share,
and texels.npz with position, normal and in-use arrays at the sheet's size / 2.
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

arguments = sys.argv[sys.argv.index("--") + 1:]
source, colour, out, size, angles = arguments[0], arguments[1], Path(arguments[2]), int(arguments[3]), [float(a) for a in arguments[4:]]
out.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
mesh = max((item for item in bpy.data.objects if item.type == "MESH"), key=lambda item: len(item.data.polygons))
bpy.context.view_layer.update()
data = mesh.data
data.calc_loop_triangles()
world = np.array(mesh.matrix_world)
points = np.array([v.co for v in data.vertices]) @ world[:3, :3].T + world[:3, 3]
centre, extent = (points.max(0) + points.min(0)) / 2, (points.max(0) - points.min(0)).max() * 1.1

image = bpy.data.images.load(colour)
material = bpy.data.materials.new("flat")
material.use_nodes = True
tree = material.node_tree
for node in list(tree.nodes):
    tree.nodes.remove(node)
texture, emission, output = (tree.nodes.new(kind) for kind in ("ShaderNodeTexImage", "ShaderNodeEmission", "ShaderNodeOutputMaterial"))
texture.image = image
tree.links.new(texture.outputs[0], emission.inputs[0])
tree.links.new(emission.outputs[0], output.inputs[0])
data.materials.clear()
data.materials.append(material)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.view_settings.view_transform, scene.view_settings.look = "Standard", "None"
scene.render.resolution_x = scene.render.resolution_y = size
world_settings = bpy.data.worlds.new("grey")
scene.world = world_settings
world_settings.use_nodes = True
world_settings.node_tree.nodes["Background"].inputs[0].default_value = (0.22, 0.22, 0.22, 1)
camera = bpy.data.objects.new("view", bpy.data.cameras.new("view"))
scene.collection.objects.link(camera)
scene.camera = camera
camera.data.type, camera.data.ortho_scale = "ORTHO", extent
for angle in angles:
    radians = math.radians(angle)
    towards = Vector((math.sin(radians), -math.cos(radians), 0))
    camera.location = Vector(centre) + towards * extent * 3
    camera.rotation_euler = (-towards).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(out / f"view_{int(angle)}.png")
    bpy.ops.render.render(write_still=True)
(out / "views.json").write_text(json.dumps({"centre": centre.tolist(), "extent": float(extent), "size": size, "angles": angles}))

sheet = image.size[0] // 2
uv = np.array([item.uv for item in data.uv_layers.active.data]) * sheet
position, normals, used = np.zeros((sheet, sheet, 3), np.float32), np.zeros((sheet, sheet, 3), np.float32), np.zeros((sheet, sheet), bool)
for triangle in data.loop_triangles:
    a, b, c = uv[list(triangle.loops)]
    low = np.clip(np.floor(np.min([a, b, c], 0)).astype(int), 0, sheet - 1)
    high = np.clip(np.ceil(np.max([a, b, c], 0)).astype(int), 0, sheet - 1)
    area = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
    if abs(area) < 1e-9:
        continue
    x, y = np.meshgrid(np.arange(low[0], high[0] + 1) + 0.5, np.arange(low[1], high[1] + 1) + 0.5)
    first = ((b[0] - x) * (c[1] - y) - (c[0] - x) * (b[1] - y)) / area
    second = ((c[0] - x) * (a[1] - y) - (a[0] - x) * (c[1] - y)) / area
    inside = (first >= -0.02) & (second >= -0.02) & (first + second <= 1.02)
    if not inside.any():
        continue
    corners = points[list(triangle.vertices)]
    normal = np.cross(corners[1] - corners[0], corners[2] - corners[0])
    normal /= max(np.linalg.norm(normal), 1e-9)
    rows, columns = y[inside].astype(int), x[inside].astype(int)
    weights = np.stack([first[inside], second[inside], 1 - first[inside] - second[inside]], 1)
    position[rows, columns] = weights @ corners
    normals[rows, columns] = normal
    used[rows, columns] = True
np.savez_compressed(out / "texels.npz", position=position[::-1], normal=normals[::-1], used=used[::-1])
