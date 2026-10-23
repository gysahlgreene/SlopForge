"""Procedural trees and shrubs: tapered branching trunks with bark UVs in metres, and crossed leaf cards that each
show one quarter of a 2 x 2 leaf atlas. Leaf-card normals point out from the crown, so Unity lights a canopy as one
volume rather than as flat cards (2026-10-23 prototype).

Usage: blender --background --python vegetation.py -- <out.fbx> <report.json> <species> <height m> <seed>
"""
import json
import math
import random
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

out, report, species, height, seed = sys.argv[sys.argv.index("--") + 1:][:5]
height, rng = float(height), random.Random(int(seed))
BARK_TILE, SIDES = 1.5, 12  # metres per bark repeat; sides of each branch tube
SPECIES = {
    # reach: main-branch length factor; trunk: share of height; radius: trunk radius per metre of height;
    # main/twigs: branch counts; pitch: main-branch angle from the trunk (radians); droop: twig gravity;
    # card: leaf card size range (m); cards: cards per twig point; depth: branching levels.
    "oak": dict(reach=1.25, trunk=0.75, radius=0.034, main=(6, 8), twigs=(4, 6), pitch=(0.6, 1.05), droop=0.0,
                card=(0.45, 0.7), cards=8, depth=2),
    "birch": dict(reach=0.62, trunk=0.92, radius=0.018, main=(7, 9), twigs=(3, 4), pitch=(0.35, 0.65), droop=0.12,
                  card=(0.45, 0.7), cards=5, depth=2),
}
if species not in ("oak", "birch", "pine", "shrub"):
    raise SystemExit(f"Unknown species {species!r}: oak, birch, pine or shrub")

bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new()
uv = bm.loops.layers.uv.new()
leaf_faces = []


def perpendicular(direction):
    other = Vector((1, 0, 0)) if abs(direction.z) > 0.9 else Vector((0, 0, 1))
    return direction.cross(other).normalized()


def tube(points, radii):
    rings = []
    for i, (point, radius) in enumerate(zip(points, radii)):
        direction = (points[min(i + 1, len(points) - 1)] - points[max(i - 1, 0)]).normalized()
        a = perpendicular(direction)
        b = direction.cross(a)
        rings.append([bm.verts.new(point + (a * math.cos(t) + b * math.sin(t)) * radius)
                      for t in (2 * math.pi * k / SIDES for k in range(SIDES))])
    lengths = [0.0]
    for i in range(1, len(points)):
        lengths.append(lengths[-1] + (points[i] - points[i - 1]).length)
    for i in range(len(rings) - 1):
        circumference = 2 * math.pi * max(radii[i], 0.05)
        for k in range(SIDES):
            k2 = (k + 1) % SIDES
            face = bm.faces.new((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
            face.material_index = 0
            for loop, (kk, ii) in zip(face.loops, ((k, i), (k + 1, i), (k + 1, i + 1), (k, i + 1))):
                loop[uv].uv = (kk / SIDES * circumference / BARK_TILE, lengths[ii] / BARK_TILE)


def card(centre, size):
    """Two crossed quads showing one random quarter of the leaf atlas."""
    yaw = rng.uniform(0, math.pi)
    for turn in (0.0, math.pi / 2):
        normal = Vector((math.cos(yaw + turn), math.sin(yaw + turn), rng.uniform(-0.4, 0.4))).normalized()
        right = perpendicular(normal)
        up = normal.cross(right)
        tilt = Matrix.Rotation(rng.uniform(-0.5, 0.5), 3, normal)
        right, up = tilt @ right, tilt @ up
        corners = [centre + (right * sx + up * sy) * size * 0.5 for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        face = bm.faces.new([bm.verts.new(c) for c in corners])
        face.material_index = 1
        leaf_faces.append(face)
        qx, qy = rng.choice((0.0, 0.5)), rng.choice((0.0, 0.5))
        for loop, coord in zip(face.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
            loop[uv].uv = (qx + coord[0] * 0.5, qy + coord[1] * 0.5)


def branch(start, direction, length, radius, depth, cfg):
    segments = max(4, int(length / 0.45))
    step = length / segments
    points, d = [start], direction.normalized()
    for _ in range(segments):
        jitter = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))) * (0.1 if depth == 0 else 0.28)
        d = (d + jitter + Vector((0, 0, (0.08 if depth else 0.0) - cfg["droop"] * depth))).normalized()
        points.append(points[-1] + d * step)
    radii = [radius * (1 - 0.72 * i / segments) for i in range(len(points))]
    tube(points, radii)
    if depth == cfg["depth"]:
        for i in range(int(len(points) * 0.3), len(points)):
            for _ in range(cfg["cards"]):
                offset = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-0.6, 1))) * 0.55
                card(points[i] + offset, rng.uniform(*cfg["card"]))
        return
    count = rng.randint(*cfg["main"]) if depth == 0 else rng.randint(*cfg["twigs"])
    first = 0.35 if depth == 0 else 0.25
    for c in range(count):
        at = first + (1 - first) * (c + rng.uniform(0.2, 0.8)) / count
        i = min(int(at * segments), segments - 1)
        axis = (points[i + 1] - points[i]).normalized()
        out_dir = Matrix.Rotation(rng.uniform(0, 2 * math.pi), 3, axis) @ perpendicular(axis)
        pitch = rng.uniform(*cfg["pitch"]) if depth == 0 else rng.uniform(0.5, 0.9)
        child = (axis * math.cos(pitch) + out_dir * math.sin(pitch)).normalized()
        branch(points[i], child, length * rng.uniform(0.45, 0.6) * (cfg["reach"] if depth == 0 else 1.0) * (1 - 0.35 * at),
               radii[i] * 0.55, depth + 1, cfg)


def pine():
    """A straight trunk with whorls of near-level branches shortening to a conical top, needle cards along them."""
    trunk = [Vector((rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03), -0.3 + height * i / 24)) for i in range(25)]
    radius = height * 0.022
    tube(trunk, [radius * (1 - 0.85 * i / 24) for i in range(25)])
    z = height * 0.3
    while z < height * 0.97:
        frac = (z - height * 0.3) / (height * 0.7)
        reach = (1 - frac) * height * 0.2 + 0.4
        for k in range(rng.randint(4, 6)):
            a = 2 * math.pi * k / 5 + rng.uniform(-0.3, 0.3)
            d = Vector((math.cos(a), math.sin(a), rng.uniform(-0.35, 0.05))).normalized()
            start = Vector((0, 0, z))
            along = lambda t: start + d * reach * t + Vector((0, 0, -0.25 * reach * t * t))
            tube([along(t) for t in (0, 0.33, 0.66, 1.0)],
                 [radius * (1 - frac) * 0.35 * (1 - 0.7 * t) + 0.01 for t in (0, 0.33, 0.66, 1.0)])
            for t in (0.3, 0.5, 0.7, 0.9, 1.0):
                for _ in range(2):
                    card(along(t) + Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-0.3, 0.5))) * 0.25,
                         rng.uniform(0.7, 1.0))
        z += rng.uniform(0.55, 0.8)


if species == "pine":
    pine()
elif species == "shrub":
    # Several short stems from the ground, leafy along their length.
    cfg = dict(SPECIES["oak"], droop=0.05, card=(0.35, 0.55), cards=6, depth=1)
    for _ in range(rng.randint(6, 9)):
        d = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0.9, 1.8)))
        branch(Vector((rng.uniform(-0.15, 0.15), rng.uniform(-0.15, 0.15), -0.1)), d, height * rng.uniform(0.75, 1.05),
               0.03, 1, cfg)
else:
    cfg = SPECIES[species]
    branch(Vector((0, 0, -0.3)), Vector((0, 0, 1)), height * cfg["trunk"], height * cfg["radius"], 0, cfg)

leaf_verts = {v for face in leaf_faces for v in face.verts}
centre = sum((v.co for v in leaf_verts), Vector()) / max(len(leaf_verts), 1)
if species == "shrub":
    centre = Vector((0, 0, height * 0.35))
# The plant is scaled to the requested height: branches and leaf cards spread past the trunk's length, and a 1.5 m
# shrub came out 2.5 m tall.
low = min(v.co.z for v in bm.verts)
extent = max(v.co.z for v in bm.verts) - low
factor = height / extent
bmesh.ops.translate(bm, verts=bm.verts[:], vec=Vector((0, 0, -low)))
bmesh.ops.scale(bm, vec=Vector((factor, factor, factor)), verts=bm.verts[:])
centre = (centre - Vector((0, 0, low))) * factor
mesh = bpy.data.meshes.new(species)
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new(species, mesh)
bpy.context.collection.objects.link(obj)
for name in ("Bark", "Leaves"):
    obj.data.materials.append(bpy.data.materials.new(name))
for poly in mesh.polygons:
    poly.use_smooth = True
normals = []
for poly in mesh.polygons:
    for index in poly.loop_indices:
        vertex = mesh.vertices[mesh.loops[index].vertex_index]
        if poly.material_index == 1:
            n = vertex.co - centre
            n.z = n.z * 0.6 + 0.3 * n.length
            normals.append(n.normalized())
        else:
            normals.append(Vector(vertex.normal))
mesh.normals_split_custom_set(normals)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.export_scene.fbx(filepath=out, use_selection=True, object_types={"MESH"}, axis_forward="-Z", axis_up="Y",
                         apply_unit_scale=True, add_leaf_bones=False)
leaves = sum(1 for poly in mesh.polygons if poly.material_index == 1)
with open(report, "w") as handle:
    json.dump({"species": species, "seed": int(seed), "height": height, "faces": len(mesh.polygons),
               "leaf_cards": leaves, "dimensions": [round(v, 3) for v in obj.dimensions]}, handle)
print("VEGETATION", species, len(mesh.polygons), "faces")
