"""Which way each texel of a model's texture sheet faces, for character_parts.py.

Usage: blender --background --python character_facing.py -- model.glb out.npz [size]

Saves size x size arrays per texel, rows from the top of the sheet: normal Y (facing), height and the texels in use.
"""
import sys

import bpy
import numpy as np

arguments = sys.argv[sys.argv.index("--") + 1:]
source, output, size = arguments[0], arguments[1], int(arguments[2]) if len(arguments) > 2 else 1024
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source)
mesh = max((item for item in bpy.data.objects if item.type == "MESH"), key=lambda item: len(item.data.polygons))
bpy.context.view_layer.update()
data = mesh.data
data.calc_loop_triangles()
uv = np.array([item.uv for item in data.uv_layers.active.data]) * size
world = np.array(mesh.matrix_world)
points = np.array([v.co for v in data.vertices]) @ world[:3, :3].T + world[:3, 3]
facing, height = (np.zeros((size, size), np.float32) for _ in range(2))
used = np.zeros((size, size), bool)
for triangle in data.loop_triangles:
    a, b, c = uv[list(triangle.loops)]
    low = np.clip(np.floor(np.min([a, b, c], 0)).astype(int), 0, size - 1)
    high = np.clip(np.ceil(np.max([a, b, c], 0)).astype(int), 0, size - 1)
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
    facing[rows, columns] = normal[1]
    weights = np.stack([first[inside], second[inside], 1 - first[inside] - second[inside]], 1)
    placed = weights @ corners
    height[rows, columns] = placed[:, 2]
    used[rows, columns] = True
np.savez_compressed(output, facing=facing[::-1], height=height[::-1], used=used[::-1])
