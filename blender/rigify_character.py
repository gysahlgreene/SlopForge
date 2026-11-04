"""Blender 5.x Rigify humanoid fitting, skinning, evidence rendering, and FBX export."""
import json
import hashlib
import math
import statistics
import sys
import traceback
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector


POSES = {
    # FK rotations measured on the generated basic-human rig (front is -Y): +X on upper_arm_fk raises
    # each arm outward, +X on thigh_fk swings the leg forward, +X on forearm_fk bends the elbow forward.
    "t_pose": {},
    "raised_arms": {"upper_arm_fk.L": (1.3, 0.0, 0.0), "upper_arm_fk.R": (1.3, 0.0, 0.0)},
    "crouch": {"thigh_fk.L": (0.8, 0.0, 0.0), "thigh_fk.R": (0.8, 0.0, 0.0),
               "shin_fk.L": (-1.0, 0.0, 0.0), "shin_fk.R": (-1.0, 0.0, 0.0)},
    "leg_lift": {"thigh_fk.L": (0.9, 0.0, 0.0), "shin_fk.L": (-0.8, 0.0, 0.0)},
    "elbow_bend": {"forearm_fk.L": (1.2, 0.0, 0.0), "forearm_fk.R": (1.2, 0.0, 0.0)},
    "shoulder_rotation": {"upper_arm_fk.L": (0.0, 0.8, 0.0), "upper_arm_fk.R": (0.0, -0.8, 0.0)},
}


def fail(message):
    raise RuntimeError(message)


def imported_meshes(source):
    before = set(bpy.data.objects)
    suffix = source.suffix.lower()
    if suffix == ".glb":
        bpy.ops.import_scene.gltf(filepath=str(source))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(source))
    else:
        fail("Rigify provider accepts GLB or FBX character models")
    meshes = [obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH"]
    if not meshes:
        fail("Source model contains no mesh objects")
    return meshes


def bounds(objects):
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    low = Vector(tuple(min(point[axis] for point in points) for axis in range(3)))
    high = Vector(tuple(max(point[axis] for point in points) for axis in range(3)))
    if any(not math.isfinite(high[i] - low[i]) or high[i] - low[i] <= 1e-5 for i in range(3)):
        fail("Character mesh has degenerate bounds; cannot fit a humanoid metarig")
    return low, high


def fit_metarig(metarig, low, high, meshes):
    bpy.context.view_layer.objects.active = metarig
    metarig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = list(metarig.data.edit_bones)
    points = [point for bone in edit_bones for point in (bone.head.copy(), bone.tail.copy())]
    rig_low = Vector(tuple(min(point[axis] for point in points) for axis in range(3)))
    rig_high = Vector(tuple(max(point[axis] for point in points) for axis in range(3)))
    rig_span, mesh_span = rig_high - rig_low, high - low
    if min(rig_span) <= 1e-5:
        fail("Rigify human metarig has degenerate bounds")
    scale = Vector(tuple(mesh_span[axis] / rig_span[axis] for axis in range(3)))
    connections = [(bone, bone.use_connect) for bone in edit_bones]
    for bone, _ in connections:
        bone.use_connect = False
    for bone in edit_bones:
        for point in (bone.head, bone.tail):
            for axis in range(3):
                point[axis] = low[axis] + (point[axis] - rig_low[axis]) * scale[axis]
    surface_points = [metarig.matrix_world.inverted() @ (mesh.matrix_world @ vertex.co)
                      for mesh in meshes for vertex in mesh.data.vertices]
    sample_radius = max(mesh_span) * 0.04
    arm_depth_fit = {"strategy": "median mesh depth at the metarig arm-bone cross sections",
                     "sample_radius": sample_radius, "bones": []}
    for side in ("L", "R"):
        for part in ("shoulder", "upper_arm", "forearm", "hand"):
            bone = metarig.data.edit_bones.get(f"{part}.{side}")
            if bone is None:
                continue
            head, tail = bone.head.copy(), bone.tail.copy()
            original_y = (head.y, tail.y)
            segment = Vector((tail.x - head.x, 0.0, tail.z - head.z))
            if segment.length_squared <= 1e-12:
                continue
            samples = [[], []]
            for point in surface_points:
                delta = Vector((point.x - head.x, 0.0, point.z - head.z))
                t = max(0.0, min(1.0, delta.dot(segment) / segment.length_squared))
                if (delta - segment * t).length > sample_radius:
                    continue
                if t <= 0.25:
                    samples[0].append(point.y)
                if t >= 0.75:
                    samples[1].append(point.y)
            if samples[0]:
                bone.head.y = statistics.median(samples[0])
            if samples[1]:
                bone.tail.y = statistics.median(samples[1])
            arm_depth_fit["bones"].append({"bone": bone.name, "head_samples": len(samples[0]),
                "tail_samples": len(samples[1]), "head_depth_delta": bone.head.y - original_y[0],
                "tail_depth_delta": bone.tail.y - original_y[1]})
    for bone, connected in connections:
        bone.use_connect = connected
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm_depth_fit


def surface_points(meshes, count=80000):
    """Even samples over the surface. A sparse mesh's vertices leave gaps that read as gaps between body parts."""
    triangles = []
    for mesh in meshes:
        mesh.data.calc_loop_triangles()
        world = np.array(mesh.matrix_world)
        vertices = np.array([v.co for v in mesh.data.vertices]) @ world[:3, :3].T + world[:3, 3]
        triangles.append(vertices[np.array([t.vertices for t in mesh.data.loop_triangles])])
    triangles = np.concatenate(triangles)
    area = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1)
    random = np.random.default_rng(0)
    picked = triangles[random.choice(len(triangles), count, p=area / area.sum())]
    u, v = random.random(count), random.random(count)
    over = u + v > 1
    u[over], v[over] = 1 - u[over], 1 - v[over]
    return [Vector(p) for p in picked[:, 0] + u[:, None] * (picked[:, 1] - picked[:, 0]) + v[:, None] * (picked[:, 2] - picked[:, 0])]


def arm_weight_counts(mesh):
    """Vertices led by each side's forearm and hand: a misplaced arm shows as a lopsided or tiny count."""
    names = {group.index: group.name for group in mesh.vertex_groups}
    counts = {"L": 0, "R": 0}
    for vertex in mesh.data.vertices:
        best = max(vertex.groups, key=lambda item: item.weight, default=None)
        name = names.get(best.group, "") if best else ""
        if name.startswith(("DEF-forearm.", "DEF-hand.")):
            counts[name.split(".")[1]] += 1
    return counts


def fit_landmarks(metarig, meshes):
    """Place basic-human metarig joints from the character's own shape (front -Y, up +Z, A-pose).

    Bounds scaling left hands, forearms, shins and feet outside generated bodies, where bone heat
    cannot solve. Joints are taken from horizontal slices instead: the leg gap gives the crotch,
    gaps beside the torso give the arms, and every joint is snapped to the local limb centroid.
    Returns None when the arms cannot be separated from the torso.
    """
    points = surface_points(meshes)
    low = Vector([min(p[axis] for p in points) for axis in range(3)])
    high = Vector([max(p[axis] for p in points) for axis in range(3)])
    height = high.z - low.z
    cx, cy = (low.x + high.x) / 2, (low.y + high.y) / 2

    def band(z, half, side=0, near=None):
        found = [p for p in points if abs(p.z - (low.z + z * height)) <= half * height
                 and (side == 0 or (p.x - cx) * side > 0)]
        if near is not None:
            found = [p for p in found if (p - near).length <= near_radius]
        return found

    def centroid(found):
        return sum(found, Vector()) / len(found) if found else None

    near_radius = 0.05 * height
    # Looking from behind only: an apron's hem on the centre line isn't a crotch, and the default then sat hips at the belly.
    crotch = next((z / 100 for z in range(15, 60)
                   if any(abs(p.x - cx) < 0.012 * height and p.y > cy for p in band(z / 100, 0.006))), None)
    if crotch is None or not 0.3 <= crotch <= 0.6:
        crotch = 0.47

    def clusters(z):
        xs = sorted(p.x for p in band(z, 0.01))
        groups, start = [], 0
        for index in range(1, len(xs) + 1):
            if index == len(xs) or xs[index] - xs[index - 1] > 0.012 * height:
                groups.append((xs[start], xs[index - 1]))
                start = index
        return groups

    arms = {1: [], -1: []}
    torso_edge = {1: [], -1: []}
    torso_slices = []
    for z in [crotch + k * 0.01 for k in range(0, 40)]:
        groups = clusters(z)
        torso = next((g for g in groups if g[0] <= cx <= g[1]), None)
        if torso is None:
            continue
        # Only trust the width with an arm clear on both sides: one still merged widens the "torso"
        # over its sleeve, and cap_influences then strips that band of its arm weight, which tears it.
        if {g[0] > cx for g in groups if g is not torso} == {True, False}:
            torso_slices.append((low.z + z * height, torso[0], torso[1]))
        for side in (1, -1):
            outer = [g for g in groups if (g[0] - cx) * side > 0 and (g[1] - cx) * side > 0 and g is not torso]
            if outer:
                torso_edge[side].append(torso[1] if side > 0 else torso[0])
                lo, hi = min(g[0] for g in outer), max(g[1] for g in outer)
                arms[side].extend(p for p in band(z, 0.005) if lo <= p.x <= hi)
    if any(len(arms[side]) < 30 for side in (1, -1)):
        return None

    report = {"strategy": "mesh cross-section landmarks", "crotch_height": crotch, "joints": {},
              "torso_slices": [[round(value, 5) for value in item] for item in torso_slices],
              "slice_half_height": 0.005 * height}
    joints = {}
    shoulder_z = 0.80
    for side, suffix in ((1, "L"), (-1, "R")):
        edge = statistics.median(torso_edge[side])
        shoulder = Vector((edge - side * 0.02 * height, cy, low.z + shoulder_z * height))
        # The outermost part, not the lowest: in an A-pose that's the hand, where the lowest can be a coat flap beside the hip.
        reach = max((p.x - cx) * side for p in arms[side])
        tip = centroid([p for p in arms[side] if (p.x - cx) * side > reach - 0.03 * height])
        arm_points = arms[side]

        def snap(target):
            nearby = [p for p in arm_points if (p - target).length <= near_radius]
            return centroid(nearby) or target

        elbow = snap(shoulder.lerp(tip, 0.42))
        wrist = snap(shoulder.lerp(tip, 0.75))
        joints[f"shoulder.{suffix}"] = (Vector((cx + side * 0.01 * height, cy, low.z + 0.81 * height)), shoulder)
        joints[f"upper_arm.{suffix}"] = (shoulder, elbow)
        joints[f"forearm.{suffix}"] = (elbow, wrist)
        joints[f"hand.{suffix}"] = (wrist, tip)
        # Inside the torso's edge, because hands hanging at hip height pulled the joint out towards them.
        hip = (centroid([p for p in band(crotch - 0.03, 0.02, side) if (p.x - cx) * side < (edge - cx) * side])
               or Vector((cx + side * 0.05 * height, cy, 0)))
        hip.z = low.z + (crotch + 0.06) * height
        knee = centroid(band(0.27, 0.015, side)) or hip
        ankle = centroid(band(0.05, 0.012, side)) or knee
        foot_points = [p for p in band(0.03, 0.03, side)]
        toe_y = min((p.y for p in foot_points), default=ankle.y - 0.06 * height)
        ball = Vector((ankle.x, ankle.y + (toe_y - ankle.y) * 0.6, low.z + 0.01 * height))
        joints[f"thigh.{suffix}"] = (hip, knee)
        joints[f"shin.{suffix}"] = (knee, ankle)
        joints[f"foot.{suffix}"] = (ankle, ball)
        joints[f"toe.{suffix}"] = (ball, Vector((ankle.x, toe_y, low.z + 0.01 * height)))
        joints[f"heel.02.{suffix}"] = (Vector((ankle.x - 0.02 * height, ankle.y + 0.025 * height, low.z)),
                                      Vector((ankle.x + 0.02 * height, ankle.y + 0.025 * height, low.z)))
        joints[f"pelvis.{suffix}"] = (None, Vector((cx + side * 0.055 * height, cy - 0.05 * height,
                                                    low.z + (crotch + 0.11) * height)))
        joints[f"breast.{suffix}"] = (Vector((cx + side * 0.06 * height, cy, low.z + 0.74 * height)),
                                      Vector((cx + side * 0.06 * height, cy - 0.07 * height, low.z + 0.74 * height)))
    spine_heights = [crotch + 0.04, crotch + 0.11, 0.65, 0.74, 0.837, 0.869, 0.90, 1.0]
    spine = []
    for z in spine_heights:
        torso = [p for p in band(min(z, 0.99), 0.01) if abs(p.x - cx) < 0.08 * height]
        point = centroid(torso) or Vector((cx, cy, 0))
        spine.append(Vector((cx, point.y, low.z + z * height)))
    names = ["spine"] + [f"spine.{index:03d}" for index in range(1, 7)]
    for name, head, tail in zip(names, spine, spine[1:]):
        joints[name] = (head, tail)
    joints["pelvis.L"] = (spine[0], joints["pelvis.L"][1])
    joints["pelvis.R"] = (spine[0], joints["pelvis.R"][1])

    inverse = metarig.matrix_world.inverted()
    bpy.context.view_layer.objects.active = metarig
    metarig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bones = metarig.data.edit_bones
    connections = [(bone, bone.use_connect) for bone in bones]
    for bone, _ in connections:
        bone.use_connect = False
    for name, (head, tail) in joints.items():
        bone = bones.get(name)
        if bone is None:
            continue
        if head is not None:
            bone.head = inverse @ head
        bone.tail = inverse @ tail
        report["joints"][name] = [[round(v, 4) for v in bone.head], [round(v, 4) for v in bone.tail]]
    for bone, connected in connections:  # Rigify limb generators need their chains connected
        bone.use_connect = connected
    bpy.ops.object.mode_set(mode="OBJECT")
    return report


def smoothstep(start, end, value):
    t = min(max((value - start) / (end - start), 0), 1)
    return t * t * (3 - 2 * t)


def evaluated_points(meshes):
    bpy.context.view_layer.update()
    result = []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        result.extend(evaluated.matrix_world @ vertex.co for vertex in mesh.vertices)
        evaluated.to_mesh_clear()
    return result


def max_displacement(before, after):
    if len(before) != len(after):
        return float("inf")
    return max((a - b).length for a, b in zip(before, after)) if before else 0.0


NECK_SHARE = 0.15  # the part of a separate head, from its base, that bends with the neck: below the chin
BOOT_TOP = 0.5  # how far a long skirt's boot reaches from ankle to knee
SHIN_TOP = 0.74  # where the added shin stops: past this a leg swinging forward carries it through the apron
SKIRT_SPREAD = 0.4  # how much each side of a skirt favours its own thigh; higher keeps a striding leg inside it


def rigid_head(mesh, rig, components):
    """A head built as its own model follows the head bone rigidly, and only its bottom `NECK_SHARE` bends into the neck.

    It shares no volume with the collar around it, so bone heat can't be trusted on it. Blending up to the head bone
    itself left the mouth and chin half on the neck, and a 25 degree head turn slid them 2.5 cm across the face. Returns
    its vertices, or None when no separate piece spans the head bone's height.
    """
    world = mesh.matrix_world
    hip = (rig.matrix_world @ rig.data.bones["DEF-thigh.L"].head_local).z
    head_z = (rig.matrix_world @ rig.data.bones["DEF-spine.006"].head_local).z
    above = [vertices for vertices in components if min((world @ v.co).z for v in vertices) > hip]
    if not above:
        return None
    piece = max(above, key=lambda vertices: max((world @ v.co).z for v in vertices))
    heights = {v.index: (world @ v.co).z for v in piece}
    low, high = min(heights.values()), max(heights.values())
    if not low < head_z < high:
        return None
    groups = {group.name: group for group in mesh.vertex_groups}
    for name in ("DEF-spine.004", "DEF-spine.006"):
        if name not in groups:
            groups[name] = mesh.vertex_groups.new(name=name)
    indices = list(heights)
    for group in mesh.vertex_groups:
        group.remove(indices)
    for index, z in heights.items():
        share = smoothstep(low, low + NECK_SHARE * (high - low), z)
        groups["DEF-spine.006"].add([index], share, "REPLACE")
        if share < 1:
            groups["DEF-spine.004"].add([index], 1 - share, "REPLACE")
    return piece


def inside_leg_ring(points, axis, limit, band, bins=16):
    """Which points are the leg itself, at each height: the first surface seen looking out from the leg's bone.

    Generated bodies have closed legs inside a long skirt, often fused to its inner wall. `axis` gives the bone's x and
    y at a height. A band only counts as a leg if most directions hit a surface within `limit`; a skirt with nothing
    solid inside is hit far away on the far side, so it has no ring. Returns a mask over points.
    """
    x, y = axis(points[:, 2])
    dx, dy = points[:, 0] - x, points[:, 1] - y
    radius = np.hypot(dx, dy)
    sector = ((np.arctan2(dy, dx) + np.pi) / (2 * np.pi) * bins).astype(int) % bins
    inside = np.zeros(len(points), bool)
    low, high = points[:, 2].min(), points[:, 2].max()
    for centre in np.arange(low, high + band, band):
        here = np.abs(points[:, 2] - centre) <= band
        if not here.any():
            continue
        first = np.full(bins, np.inf)
        np.minimum.at(first, sector[here], radius[here])
        seen = np.isfinite(first)
        if seen.sum() < bins / 2 or (first[seen] < limit).sum() < 0.8 * seen.sum():
            continue
        known = np.where(seen)[0]
        reach = np.interp(np.arange(bins), known, first[known], period=bins)
        take = here & (radius <= reach[sector] * 1.1 + 0.05 * limit) & (radius < limit * 1.2)
        inside |= take
    return inside


def tidy_mask(mask, edges, passes=3):
    """A vertex takes the side most of its neighbours are on, which closes holes in a found region and drops its spikes.
    `edges` is an array of index pairs. Returns the new mask."""
    for _ in range(passes):
        counts = np.bincount(edges.ravel(), minlength=len(mask))
        inside = np.bincount(edges[mask[edges[:, 0]], 1], minlength=len(mask)) + np.bincount(edges[mask[edges[:, 1]], 0], minlength=len(mask))
        share = inside / np.maximum(counts, 1)
        mask = np.where(share > 0.6, True, np.where(share < 0.35, False, mask))
    return mask


def tube_skirt(mesh, rig, components):
    """Below the hips a long skirt follows the hips and an average of both thighs, so it moves as one tube.

    Heat gives each side to its own leg and the skirt tears down the middle as they part. A generated body's legs are
    fused to the skirt's pleats, and freeing them whole tears the pleats and pushes knees through the apron. So only
    the boot goes with the leg, up to `BOOT_TOP` of the way to the knee; the leg above it stays hidden and follows the
    skirt, and add_shins gives the boot a clean shin up inside the skirt. The skirt ends at its hem, the lowest height
    where the shell still surrounds the body. Returns the report, the boots' vertices,
    the skirt's, and for each boot its top ring: (side, centre, radius).
    """
    world = mesh.matrix_world
    bones = rig.data.bones
    at = lambda name: rig.matrix_world @ bones[name].head_local
    hip = at("DEF-thigh.L").z
    candidates = [vertices for vertices in components if min((world @ v.co).z for v in vertices) < hip]
    main = max(candidates, key=len)  # not the head, which can have as many vertices as the body
    indices = np.array([v.index for v in main])
    points = np.array([world @ v.co for v in main])
    unit = hip / 0.53
    wide = np.hypot(points[:, 0], points[:, 1])
    # Walk down from mid-skirt until the shell no longer surrounds the body: two legs cover at most about half the way
    # round, a skirt or an open coat nearly all of it. Width can't tell them apart, because toes reach as wide as a coat.
    step = 0.01 * unit
    sector = ((np.arctan2(points[:, 1], points[:, 0]) + np.pi) / (2 * np.pi) * 24).astype(int) % 24
    hem = 0.7 * hip
    while hem > 0 and len(np.unique(sector[np.abs(points[:, 2] - hem) < step])) >= 20:
        hem -= step
    groups = {group.name: group for group in mesh.vertex_groups}

    def group(name):
        if name not in groups:
            groups[name] = mesh.vertex_groups.new(name=name)
        return groups[name]

    position = {int(index): place for place, index in enumerate(indices)}
    edges = np.array([(position[e.vertices[0]], position[e.vertices[1]]) for e in mesh.data.edges
                      if e.vertices[0] in position and e.vertices[1] in position], int).reshape(-1, 2)
    boots = set()
    tops = []
    for side in ("L", "R"):
        chain = [at(f"DEF-thigh.{side}"), at(f"DEF-thigh.{side}.001"), at(f"DEF-shin.{side}"), at(f"DEF-shin.{side}.001"), at(f"DEF-foot.{side}")]
        ascending = sorted((joint.z, joint.x, joint.y) for joint in chain)
        zs, xs, ys = (np.array(values) for values in zip(*ascending))
        axis = lambda z, zs=zs, xs=xs, ys=ys: (np.interp(z, zs, xs), np.interp(z, zs, ys))
        ankle, knee = chain[4].z, chain[2].z
        top = ankle + BOOT_TOP * (knee - ankle)
        reach = (points[:, 2] > ankle + 0.01 * unit) & (points[:, 2] < top) & (points[:, 0] * (1 if side == "L" else -1) > 0)
        found = np.zeros(len(points), bool)
        found[reach] = inside_leg_ring(points[reach], axis, 0.065 * unit, 0.012 * unit)
        found = tidy_mask(found, edges) & reach
        names = (f"DEF-shin.{side}.001", f"DEF-shin.{side}")
        for index, point in zip(indices[found], points[found]):
            for name in [name for name in groups if name.startswith(("DEF-thigh", "DEF-shin", "DEF-foot", "DEF-toe", "DEF-pelvis", "DEF-spine"))]:
                groups[name].remove([int(index)])
            lower = smoothstep(ankle, knee, point[2])  # between the shin's two twist bones
            group(names[0]).add([int(index)], 1 - lower, "REPLACE")
            if lower > 0:
                group(names[1]).add([int(index)], lower, "REPLACE")
            boots.add(int(index))
        rim = points[found & (points[:, 2] > top - 0.02 * unit)]
        if len(rim) >= 8:
            centre = rim.mean(0)
            tops.append((side, centre, float(np.hypot(*(rim - centre)[:, :2].T).mean())))

    skirt = []
    half_width = wide[(points[:, 2] >= hem) & (points[:, 2] < hip)].max()
    legs = [name for name in groups if name.startswith(("DEF-thigh", "DEF-shin", "DEF-foot", "DEF-toe", "DEF-pelvis"))]
    arm_names = ("DEF-hand.", "DEF-forearm.", "DEF-upper_arm.")
    for index, point in zip(indices, points):
        index = int(index)
        if not hem <= point[2] < hip + 0.05 or index in boots:
            continue
        vertex = mesh.data.vertices[index]
        # A hand beside the skirt keeps its own arm.
        if any(mesh.vertex_groups[item.group].name.startswith(arm_names) and item.weight > 0.05 for item in vertex.groups):
            continue
        share = 0.15 + 0.5 * smoothstep(hip + 0.05, hem, point[2])
        across = max(min(point[0] / half_width, 1), -1)
        for name in legs:
            groups[name].remove([index])
        group("DEF-thigh.L").add([index], share * (0.5 + SKIRT_SPREAD * across), "REPLACE")
        group("DEF-thigh.R").add([index], share * (0.5 - SKIRT_SPREAD * across), "REPLACE")
        group("DEF-spine").add([index], 1 - share, "REPLACE")
        skirt.append(index)
    return {"skirt_vertices": len(skirt), "boot_vertices": len(boots), "hem_z": round(float(hem), 3),
            "hip_z": round(float(hip), 3)}, boots, set(skirt), tops


def add_shins(mesh, rig, tops):
    """A plain tube from each boot's top up inside the skirt, on the shin bones, in the boot's own colour.

    It's what shows between boot and hem when a foot lifts. It stops short of the knee, because the skirt doesn't follow
    a knee swinging forward. Returns the faces added.
    """
    world_inverse = mesh.matrix_world.inverted()
    for side, _, _ in tops:
        for name in (f"DEF-shin.{side}", f"DEF-shin.{side}.001"):
            if mesh.vertex_groups.get(name) is None:
                mesh.vertex_groups.new(name=name)
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    bm.verts.ensure_lookup_table()
    uv = bm.loops.layers.uv.verify()
    deform = bm.verts.layers.deform.verify()
    added = 0
    for side, centre, radius in tops:
        ankle = (rig.matrix_world @ rig.data.bones[f"DEF-foot.{side}"].head_local).z
        knee = rig.matrix_world @ rig.data.bones[f"DEF-shin.{side}"].head_local
        start = Vector(centre) - Vector((0, 0, 0.03 * (knee.z - ankle)))
        end = Vector((centre[0] + 0.3 * (knee.x - centre[0]), centre[1] + 0.3 * (knee.y - centre[1]), ankle + SHIN_TOP * (knee.z - ankle)))
        nearest = min((v for v in bm.verts if v.link_loops), key=lambda v: ((mesh.matrix_world @ v.co) - start).length_squared)
        colour = nearest.link_loops[0][uv].uv.copy()
        lower_index = mesh.vertex_groups[f"DEF-shin.{side}.001"].index
        upper_index = mesh.vertex_groups[f"DEF-shin.{side}"].index
        rings = []
        for step in range(5):
            t = step / 4
            middle = start.lerp(end, t)
            share = smoothstep(ankle, knee.z, middle.z)
            ring = []
            for corner in range(12):
                angle = 2 * math.pi * corner / 12
                vertex = bm.verts.new(world_inverse @ (middle + Vector((math.cos(angle), math.sin(angle), 0)) * radius * 0.75 * (1 - 0.45 * t)))
                vertex[deform][lower_index] = 1 - share
                vertex[deform][upper_index] = share
                ring.append(vertex)
            rings.append(ring)
        faces = [bm.faces.new((rings[r][c], rings[r][(c + 1) % 12], rings[r + 1][(c + 1) % 12], rings[r + 1][c])) for r in range(4) for c in range(12)]
        for face in faces:
            face.smooth = True
            for loop in face.loops:
                loop[uv].uv = colour
        added += len(faces)
    bm.to_mesh(mesh.data)
    bm.free()
    mesh.data.update()
    return added


def cut_faces_between(mesh, first, second, scraps=()):
    """Delete faces with vertices in both sets, and the scrap vertices. This rebuilds the mesh, so nothing may hold its
    vertices across a call."""
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    joined = [face for face in bm.faces if any(v.index in first for v in face.verts) and any(v.index in second for v in face.verts)]
    bmesh.ops.delete(bm, geom=joined, context="FACES_ONLY")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index in scraps], context="VERTS")
    bm.to_mesh(mesh.data)
    bm.free()
    mesh.data.update()
    return len(joined)


def cap_influences(mesh, rig, limit, torso_slices=(), slice_half=0.0, long_skirt=False):
    allowed = {bone.name for bone in rig.data.bones if bone.use_deform and
               (bone.name == "DEF-spine" or bone.name.startswith((
                   "DEF-spine.", "DEF-pelvis.", "DEF-thigh.", "DEF-shin.", "DEF-foot.",
                   "DEF-toe.", "DEF-shoulder.", "DEF-upper_arm.", "DEF-forearm.", "DEF-hand.")))}
    if not allowed:
        fail("Rigify armature has no supported body deform bones")
    destinations = {}
    for bone in rig.data.bones:
        ancestor = bone
        while ancestor and ancestor.name not in allowed:
            ancestor = ancestor.parent
        destinations[bone.name] = ancestor.name if ancestor else "DEF-spine.006"
    groups = {group.name: group for group in mesh.vertex_groups}
    for name in sorted(set(destinations.values())):
        if name not in groups:
            groups[name] = mesh.vertex_groups.new(name=name)
    parent = list(range(len(mesh.data.vertices)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for edge in mesh.data.edges:
        left, right = (find(index) for index in edge.vertices)
        if left != right:
            parent[right] = left
    components = {}
    for vertex in mesh.data.vertices:
        components.setdefault(find(vertex.index), []).append(vertex)
    largest = max(components, key=lambda root: len(components[root]))
    core_bones = [bone for bone in rig.data.bones if bone.name in allowed]

    def nearest_bone(vertices):
        points = [mesh.matrix_world @ vertex.co for vertex in vertices]
        best_name, best_distance = None, float("inf")
        for bone in core_bones:
            head, tail = rig.matrix_world @ bone.head_local, rig.matrix_world @ bone.tail_local
            segment = tail - head
            length_squared = max(segment.length_squared, 1e-12)
            distance = 0.0
            for point in points:
                t = max(0.0, min(1.0, (point - head).dot(segment) / length_squared))
                distance += (point - (head + t * segment)).length_squared
            distance /= len(points)
            if distance < best_distance:
                best_name, best_distance = bone.name, distance
        return best_name

    component_vertices = set()
    component_report = []
    for root, vertices in components.items():
        if root == largest:
            continue
        bound = {}
        for vertex in vertices:
            component_vertices.add(vertex.index)
            name = nearest_bone([vertex])
            bound[name] = bound.get(name, 0) + 1
        component_report.append({"vertices": len(vertices), "bound_bones": bound})

    # The voxel proxy can fuse A-pose hands with the hips/tunic beside them; forearm and hand weight
    # is only kept within a limb radius of that bone so clothing at the hip does not follow the hands.
    limb_segments = {}
    for bone in rig.data.bones:
        if bone.name.startswith(("DEF-forearm.", "DEF-hand.")) and bone.name in allowed:
            limb_segments[bone.name] = (rig.matrix_world @ bone.head_local, rig.matrix_world @ bone.tail_local)
    # A forearm is two twist bones, so add them up: 0.35 of one is under 5 cm on a 2 m figure, which
    # stripped forearm weight from a coat sleeve's surface and left it following the upper arm.
    forearm_lengths = {}
    for name, (head, tail) in limb_segments.items():
        if "forearm" in name:
            side = name.split(".")[1]
            forearm_lengths[side] = forearm_lengths.get(side, 0.0) + (tail - head).length
    limb_radius = 0.35 * max(forearm_lengths.values(), default=0.0)
    # Measured as well: a thick sleeve or forearm guard reached past that, and lost its forearm weight.
    if limb_radius > 0:
        positions = np.array([mesh.matrix_world @ vertex.co for vertex in mesh.data.vertices])
        reaches = []
        for bone in core_bones:
            head, tail = (np.array(rig.matrix_world @ end) for end in (bone.head_local, bone.tail_local))
            along = tail - head
            share = np.clip((positions - head) @ along / max(along @ along, 1e-12), 0, 1)
            reaches.append(np.linalg.norm(positions - (head + share[:, None] * along), axis=1))
        reaches = np.stack(reaches)
        nearest = reaches.argmin(0)
        forearm = [index for index, bone in enumerate(core_bones) if bone.name.startswith("DEF-forearm.")]
        own = reaches.min(0)[np.isin(nearest, forearm)]
        if own.size:
            limb_radius = max(limb_radius, 1.2 * float(np.percentile(own, 90)))

    def outside_limb(point, name):
        head, tail = limb_segments[name]
        segment = tail - head
        t = max(0.0, min(1.0, (point - head).dot(segment) / max(segment.length_squared, 1e-12)))
        return (point - (head + t * segment)).length > limb_radius

    # Forearm and hand weight is kept only on vertices connected to the arm along the surface: grow
    # from vertices on the forearm/hand bones through edges that stay within the limb radius. Clothing
    # beside a hanging A-pose hand is near it in space but only reachable through the torso.
    arm_reach = set()
    if limb_radius > 0:
        world = [mesh.matrix_world @ vertex.co for vertex in mesh.data.vertices]
        chain = {name: segment for name, segment in limb_segments.items()}
        for bone in rig.data.bones:
            if bone.name.startswith("DEF-upper_arm.") and bone.name in allowed:
                chain[bone.name] = (rig.matrix_world @ bone.head_local, rig.matrix_world @ bone.tail_local)

        def distance_to(point, segment):
            head, tail = segment
            delta = tail - head
            t = max(0.0, min(1.0, (point - head).dot(delta) / max(delta.length_squared, 1e-12)))
            return (point - (head + t * delta)).length

        near = [min(distance_to(point, segment) for segment in chain.values()) <= limb_radius for point in world]
        neighbours = [[] for _ in world]
        for edge in mesh.data.edges:
            a, b = edge.vertices
            if near[a] and near[b]:
                neighbours[a].append(b)
                neighbours[b].append(a)
        stack = [index for index, point in enumerate(world)
                 if min(distance_to(point, segment) for segment in limb_segments.values()) <= limb_radius * 0.5]
        arm_reach.update(stack)
        while stack:
            for other in neighbours[stack.pop()]:
                if other not in arm_reach:
                    arm_reach.add(other)
                    stack.append(other)

    # Loose pieces (pouches, buckles) whose centre is not on the arm never take arm weight; the proxy
    # can fuse a belt pouch with the hand hanging beside it, and the pouch then swings with the arm.
    loose_off_arm = set()
    if limb_radius > 0:
        for root, vertices in components.items():
            if root == largest:
                continue
            centre = sum((mesh.matrix_world @ vertex.co for vertex in vertices), Vector()) / len(vertices)
            if min(distance_to(centre, segment) for segment in chain.values()) > limb_radius:
                loose_off_arm.update(vertex.index for vertex in vertices)

    def in_torso(point):
        # Below the armpit, the landmark pass measured the torso's width per slice; vertices inside
        # it are body or clothing, never arm, even when the voxel proxy fused them with a hand.
        for z, lo, hi in torso_slices:
            if abs(point.z - z) <= slice_half * 1.5:
                return lo <= point.x <= hi
        return False

    maximum = 0
    for vertex in mesh.data.vertices:
        old_weights = [(item.group, item.weight) for item in vertex.groups]
        if True:  # loose pieces keep their transferred proxy weights; nearest-bone snapping dragged tunic flaps with the hands
            aggregated = {}
            for index, weight in old_weights:
                name = destinations.get(mesh.vertex_groups[index].name, "DEF-spine.006")
                aggregated[name] = aggregated.get(name, 0.0) + weight
            point = mesh.matrix_world @ vertex.co
            if limb_radius > 0:
                aggregated = {name: weight for name, weight in aggregated.items()
                              if name not in limb_segments or (vertex.index in arm_reach and not outside_limb(point, name))}
            if vertex.index in loose_off_arm:
                aggregated = {name: weight for name, weight in aggregated.items()
                              if not name.startswith(("DEF-upper_arm.", "DEF-forearm.", "DEF-hand."))}
            if in_torso(point):
                aggregated = {name: weight for name, weight in aggregated.items()
                              if not name.startswith(("DEF-upper_arm.", "DEF-forearm.", "DEF-hand."))}
            kept = sorted(aggregated.items(), key=lambda item: item[1], reverse=True)[:limit]
            total = sum(weight for _, weight in kept)
            if total <= 0:
                kept, total = [(nearest_bone([vertex]), 1.0)], 1.0
        for index, _ in old_weights:
            mesh.vertex_groups[index].remove([vertex.index])
        for name, weight in kept:
            groups[name].add([vertex.index], weight / total, "REPLACE")
        maximum = max(maximum, len(vertex.groups))
    # Loose pieces (pockets, buckles, glove fragments) ride rigidly on the nearest main-body point: each
    # takes that point's final weights. Proxy weights alone left fragments hanging in the air.
    from mathutils.kdtree import KDTree
    arm_names = ("DEF-upper_arm.", "DEF-forearm.", "DEF-hand.")
    # Before the loose pieces below copy their neighbours, or a scrap on the hem or in the hair is left behind.
    head = rigid_head(mesh, rig, components.values())
    skirt, boots, skirt_vertices, boot_tops = tube_skirt(mesh, rig, components.values()) if long_skirt else (None, (), (), ())
    # Every big piece, not just the largest: on a low-detail body the largest is the head, and boot scraps followed it.
    main = [vertex for vertices in components.values() if len(vertices) > 0.05 * len(mesh.data.vertices) for vertex in vertices]

    def dominant(vertex):
        best = max(vertex.groups, key=lambda item: item.weight, default=None)
        return mesh.vertex_groups[best.group].name if best else ""

    trees = {}
    for key, members in (("all", main), ("off_arm", [v for v in main if not dominant(v).startswith(arm_names)])):
        tree = KDTree(len(members))
        for index, vertex in enumerate(members):
            tree.insert(mesh.matrix_world @ vertex.co, index)
        tree.balance()
        trees[key] = (tree, members)
    attached = 0
    for root, vertices in components.items():
        if vertices is head or len(vertices) > 0.05 * len(mesh.data.vertices):
            continue  # large pieces keep their proxy weights; only small ones ride rigidly
        centre = sum((mesh.matrix_world @ vertex.co for vertex in vertices), Vector()) / len(vertices)
        tree, members = trees["off_arm" if vertices[0].index in loose_off_arm else "all"]
        _, index, _ = tree.find(centre)
        anchor = [(mesh.vertex_groups[item.group].name, item.weight) for item in members[index].groups]
        for vertex in vertices:
            # Read the indices first: removing a group moves the items of vertex.groups, so a list of them skips some.
            for index in [item.group for item in vertex.groups]:
                mesh.vertex_groups[index].remove([vertex.index])
            for name, weight in anchor:
                groups[name].add([vertex.index], weight, "REPLACE")
        attached += 1
    # Proxy bone heat now solves arm weights; the former arm-envelope override dragged hip and
    # tunic vertices near hanging A-pose hands along with the forearms.
    if skirt:
        # Slivers round a hem, too small to read, that a stride leaves hanging in the air.
        hip = (rig.matrix_world @ rig.data.bones["DEF-thigh.L"].head_local).z
        scraps = {v.index for root, vertices in components.items() if len(vertices) <= 12 and max((mesh.matrix_world @ v.co).z for v in vertices) < hip for v in vertices}
        skirt["scrap_vertices_removed"] = len(scraps)
        skirt["faces_cut"] = cut_faces_between(mesh, boots, skirt_vertices, scraps)
        skirt["shin_faces"] = add_shins(mesh, rig, boot_tops)
    return maximum, {"strategy": "proxy bone-heat weights capped and remapped to body deform bones; loose pieces copy the nearest main-body vertex weights",
                     "loose_pieces_attached": attached,
                     "separate_head_vertices": len(head) if head else 0,
                     "long_skirt": skirt,
                     "disconnected_islands": component_report}


def separate_contacts(mesh):
    """Delete faces fusing a hand/forearm to the thigh, pelvis or spine; returns the face count.

    Generated A-pose characters often weld a hanging hand to the thigh where they touch. Those
    faces stretch into sheets whenever the arm moves, whatever the weights, so they are cut.
    """
    groups = {group.index: group.name for group in mesh.vertex_groups}
    dominant = []
    for vertex in mesh.data.vertices:
        best = max(vertex.groups, key=lambda item: item.weight, default=None)
        dominant.append(groups.get(best.group, "") if best else "")
    arm, body = ("DEF-forearm.", "DEF-hand."), ("DEF-spine", "DEF-pelvis.", "DEF-thigh.")
    bridges = [poly.index for poly in mesh.data.polygons
               if any(dominant[i].startswith(arm) for i in poly.vertices)
               and any(dominant[i].startswith(body) for i in poly.vertices)]
    if bridges:
        bm = bmesh.new()
        bm.from_mesh(mesh.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.faces[index] for index in bridges], context="FACES_ONLY")
        bmesh.ops.delete(bm, geom=[edge for edge in bm.edges if not edge.link_faces], context="EDGES")
        bmesh.ops.delete(bm, geom=[vertex for vertex in bm.verts if not vertex.link_edges], context="VERTS")
        bm.to_mesh(mesh.data)
        bm.free()
        mesh.data.update()
    return len(bridges)


def solid_proxy(mesh, divisions):
    """The body filled solid: rasterise its triangles, flood from outside, and whatever the flood can't reach is solid.

    A voxel remesh keeps a hollow shell hollow and breaks up on inner layers (558 pieces on a long-coated
    body), whatever its normals say, and bone heat then finds no solution. Only the largest piece is kept,
    because a floating scrap no bone can see fails the whole solve. Returns the proxy and the scraps dropped.
    """
    me = mesh.data
    me.calc_loop_triangles()
    world = np.array(mesh.matrix_world)
    points = np.array([v.co for v in me.vertices]) @ world[:3, :3].T + world[:3, 3]
    triangles = points[np.array([t.vertices for t in me.loop_triangles])]
    low, high = points.min(0), points.max(0)
    size = (high - low)[2] / divisions
    low = low - 3 * size
    dims = np.ceil((high - low) / size).astype(int) + 4
    surface = np.zeros(dims, bool)
    for a, b, c in triangles:
        steps = int(np.ceil(max(np.linalg.norm(a - b), np.linalg.norm(b - c), np.linalg.norm(c - a)) / (size * 0.5))) + 1
        s, t = np.meshgrid(np.linspace(0, 1, steps + 1), np.linspace(0, 1, steps + 1))
        keep = s + t <= 1
        cells = ((a + np.outer(s[keep], b - a) + np.outer(t[keep], c - a) - low) / size).astype(int)
        surface[cells[:, 0], cells[:, 1], cells[:, 2]] = True

    def grow(cells):
        out = cells.copy()
        out[1:] |= cells[:-1]
        out[:-1] |= cells[1:]
        out[:, 1:] |= cells[:, :-1]
        out[:, :-1] |= cells[:, 1:]
        out[:, :, 1:] |= cells[:, :, :-1]
        out[:, :, :-1] |= cells[:, :, 1:]
        return out

    wall = grow(surface)  # seals gaps a voxel wide; the last line takes the thickness back
    outside = np.zeros(dims, bool)
    outside[0], outside[-1], outside[:, 0], outside[:, -1], outside[:, :, 0], outside[:, :, -1] = (True,) * 6
    outside &= ~wall
    while True:
        spread = grow(outside) & ~wall
        if spread.sum() == outside.sum():
            break
        outside = spread
    solid = ~grow(outside)

    corners, faces = {}, []
    axes = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    for axis, direction in enumerate(axes):
        u, v = (axes[i] for i in range(3) if i != axis)
        for sign in (1, -1):
            for cell in np.argwhere(solid & ~np.roll(solid, -sign, axis=axis)):
                base = cell + (np.array(direction) if sign > 0 else 0)
                quad = [tuple(int(x) for x in base + offset) for offset in
                        (np.zeros(3, int), np.array(u), np.array(u) + np.array(v), np.array(v))]
                faces.append([corners.setdefault(corner, len(corners)) for corner in (quad if sign > 0 else quad[::-1])])
    coordinates = np.array(sorted(corners, key=corners.get), float) * size + low
    data = bpy.data.meshes.new("SolidProxy")
    data.from_pydata(coordinates.tolist(), [], faces)
    data.update()
    proxy = bpy.data.objects.new("SolidProxy", data)
    bpy.context.scene.collection.objects.link(proxy)
    bm = bmesh.new()
    bm.from_mesh(data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=size * 1e-3)
    seen, pieces = set(), []
    for start in bm.verts:
        if start in seen:
            continue
        seen.add(start)
        stack, piece = [start], []
        while stack:
            vertex = stack.pop()
            piece.append(vertex)
            for edge in vertex.link_edges:
                other = edge.other_vert(vertex)
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        pieces.append(piece)
    pieces.sort(key=len)
    bmesh.ops.delete(bm, geom=[vertex for piece in pieces[:-1] for vertex in piece], context="VERTS")
    bmesh.ops.smooth_vert(bm, verts=list(bm.verts), factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    bm.to_mesh(data)
    bm.free()
    data.update()
    return proxy, len(pieces) - 1


def bind_with_proxy(rig, meshes, height, solid_only=False):
    """Bone-heat weights computed on a watertight voxel proxy, then transferred to each mesh.

    Generated characters are open, multi-shell surfaces where bone heat finds no solution
    ("failed to find solution for one or more bones"); a voxel proxy is closed, and weights
    only need the body's volume, not its surface detail.
    """
    report = {"method": "voxel_proxy_bone_heat", "meshes": []}
    for mesh in meshes:
        # A fine proxy keeps the raw double shells as separate hollow layers and bone heat fails;
        # coarser voxels close them into one solid. Use the finest voxel size that weights every vertex.
        attempts = []
        # A hollow proxy can weight every vertex and still be wrong: heat reached a coat's inner wall from the sleeve, and
        # 700 vertices of the coat followed the arm. A body built as a shell goes straight to the solid proxy.
        proxy = None
        for divisions in () if solid_only else (200, 160, 120, 90, 70):
            voxel_size = height / divisions
            proxy = mesh.copy()
            proxy.data = mesh.data.copy()
            proxy.modifiers.clear()
            bpy.context.scene.collection.objects.link(proxy)
            remesh = proxy.modifiers.new("WeightProxy", "REMESH")
            remesh.mode, remesh.voxel_size, remesh.use_smooth_shade = "VOXEL", voxel_size, True
            bpy.ops.object.select_all(action="DESELECT")
            proxy.select_set(True)
            bpy.context.view_layer.objects.active = proxy
            bpy.ops.object.modifier_apply(modifier=remesh.name)
            weighted = 0
            if proxy.data.polygons:
                bpy.ops.object.select_all(action="DESELECT")
                proxy.select_set(True)
                rig.select_set(True)
                bpy.context.view_layer.objects.active = rig
                try:
                    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
                except Exception:
                    pass
                weighted = sum(bool(vertex.groups) for vertex in proxy.data.vertices)
            attempts.append({"voxel_size": voxel_size, "proxy_vertices": len(proxy.data.vertices), "weighted": weighted})
            if proxy.data.vertices and weighted == len(proxy.data.vertices):
                break
            bpy.data.objects.remove(proxy, do_unlink=True)
            proxy = None
        if proxy is None:
            for divisions in (120, 90, 70):
                proxy, scraps = solid_proxy(mesh, divisions)
                bpy.ops.object.select_all(action="DESELECT")
                proxy.select_set(True)
                rig.select_set(True)
                bpy.context.view_layer.objects.active = rig
                try:
                    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
                except Exception:
                    pass
                weighted = sum(bool(vertex.groups) for vertex in proxy.data.vertices)
                attempts.append({"solid_divisions": divisions, "proxy_vertices": len(proxy.data.vertices),
                                 "weighted": weighted, "scraps_dropped": scraps})
                if proxy.data.vertices and weighted == len(proxy.data.vertices):
                    break
                bpy.data.objects.remove(proxy, do_unlink=True)
                proxy = None
        if proxy is None:
            fail(f"Automatic skin weighting found no solution on any voxel or solid proxy for {mesh.name}: {attempts}")
        for group in proxy.vertex_groups:
            if mesh.vertex_groups.get(group.name) is None:
                mesh.vertex_groups.new(name=group.name)
        transfer = mesh.modifiers.new("WeightTransfer", "DATA_TRANSFER")
        transfer.object, transfer.use_vert_data = proxy, True
        transfer.data_types_verts = {"VGROUP_WEIGHTS"}
        transfer.vert_mapping = "POLYINTERP_NEAREST"
        transfer.layers_vgroup_select_src, transfer.layers_vgroup_select_dst = "ALL", "NAME"
        bpy.ops.object.select_all(action="DESELECT")
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = mesh
        bpy.ops.object.modifier_apply(modifier=transfer.name)
        armature = mesh.modifiers.new("Armature", "ARMATURE")
        armature.object = rig
        mesh.parent = rig
        mesh.matrix_parent_inverse = rig.matrix_world.inverted()
        report["meshes"].append({"mesh": mesh.name, "proxy_attempts": attempts, "proxy_faces": len(proxy.data.polygons),
                                 "weighted_vertices": sum(bool(vertex.groups) for vertex in mesh.data.vertices),
                                 "vertices": len(mesh.data.vertices)})
        bpy.data.objects.remove(proxy, do_unlink=True)
    return report


def deform_only_skeleton(rig):
    """Leave only the deforming bones, joined into one tree.

    Rigify keeps them on separate branches under control bones, so Unity rejects the Humanoid: "Transform
    'DEF-spine' is not an ancestor of 'DEF-thigh.L'". The FBX exporter's deform-only option keeps those parents.
    """
    for bone in rig.pose.bones:
        for constraint in list(bone.constraints):
            bone.constraints.remove(constraint)
        bone.location, bone.scale = (0, 0, 0), (1, 1, 1)
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion = (1, 0, 0, 0)
    rig.animation_data_clear()
    rig.data.animation_data_clear()
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    bones = rig.data.edit_bones
    for child, parent in (("DEF-thigh.L", "DEF-spine"), ("DEF-thigh.R", "DEF-spine"),
                          ("DEF-pelvis.L", "DEF-spine"), ("DEF-pelvis.R", "DEF-spine"),
                          ("DEF-shoulder.L", "DEF-spine.003"), ("DEF-shoulder.R", "DEF-spine.003"),
                          ("DEF-upper_arm.L", "DEF-shoulder.L"), ("DEF-upper_arm.R", "DEF-shoulder.R")):
        bones[child].use_connect = False
        bones[child].parent = bones[parent]
    bones["DEF-spine"].use_connect = False
    bones["DEF-spine"].parent = None
    for bone in list(bones):
        if not bone.use_deform:
            bones.remove(bone)
    bpy.ops.object.mode_set(mode="OBJECT")


def weld_mesh(mesh, distance):
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=distance)
    merged = before - len(bm.verts)
    bm.to_mesh(mesh.data)
    boundary_edges = sum(edge.is_boundary for edge in bm.edges)
    nonmanifold_edges = sum(not edge.is_manifold and not edge.is_boundary for edge in bm.edges)
    bm.free()
    mesh.data.update()
    return {"merged_vertices": merged, "boundary_edges": boundary_edges,
            "nonmanifold_edges": nonmanifold_edges}


def setup_render(low, high):
    scene = bpy.context.scene
    center = (low + high) * 0.5
    height = (high - low).z
    camera_data = bpy.data.cameras.new("SlopForgeReviewCamera")
    camera = bpy.data.objects.new("SlopForgeReviewCamera", camera_data)
    scene.collection.objects.link(camera)
    # Three-quarter view: bends toward the camera (elbows, crouch, leg lift) are invisible from the front.
    camera.location = center + Vector((-height * 2.4, -height * 2.6, height * 0.35))
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = max((high - low).x, (high - low).y, height) * 1.45
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera
    # Key, fill and rim so dark materials and silhouettes stay readable in deformation review.
    for name, offset, energy in (("SlopForgeReviewKey", (-1.0, -2.0, 2.0), 900),
                                 ("SlopForgeReviewFill", (1.6, -1.6, 0.6), 350),
                                 ("SlopForgeReviewRim", (0.4, 2.0, 1.6), 450)):
        light_data = bpy.data.lights.new(name, "AREA")
        light = bpy.data.objects.new(name, light_data)
        scene.collection.objects.link(light)
        light.location = center + Vector(offset) * height
        light_data.energy = max(500, height * height * energy)
        light_data.shape = "DISK"
        light_data.size = height * 1.5
        light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.32, 0.32, 0.34)
    scene.view_settings.view_transform = "AgX"


def render_pose(rig, meshes, pose, controls, destination):
    use_ik = any(name.startswith("hand_ik.") for name in controls)
    for name in ("upper_arm_parent.L", "upper_arm_parent.R", "thigh_parent.L", "thigh_parent.R"):
        switch = rig.pose.bones.get(name)
        if switch is not None and "IK_FK" in switch:
            switch["IK_FK"] = 0.0 if use_ik and name.startswith("upper_arm_parent.") else 1.0
    for bone in rig.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0, 0, 0)
        bone.scale = (1, 1, 1)
    missing = []
    if pose == "t_pose":
        # A real T-pose: aim each upper arm horizontally outward, whatever the rest (A-pose) angle is.
        bpy.context.view_layer.update()
        for side in ("L", "R"):
            bone = rig.pose.bones.get(f"upper_arm_fk.{side}")
            if bone is None:
                missing.append(f"upper_arm_fk.{side}")
                continue
            direction = (bone.tail - bone.head).normalized()
            level = Vector((direction.x, direction.y, 0.0)).normalized()
            swing = direction.rotation_difference(level).to_matrix().to_4x4()
            bone.matrix = Matrix.Translation(bone.head) @ swing @ Matrix.Translation(-bone.head) @ bone.matrix
        bpy.context.view_layer.update()
    for name, rotation in controls.items():
        bone = rig.pose.bones.get(name)
        if bone is None:
            missing.append(name)
        elif name.startswith("hand_ik."):
            matrix = bone.matrix.copy()
            matrix.translation += Vector(rotation)
            bone.matrix = matrix
        else:
            bone.rotation_mode = "XYZ"
            bone.rotation_euler = rotation
    destination.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(destination)
    bpy.ops.render.render(write_still=True)
    report = {"missing_controls": missing}
    if pose == "t_pose":
        elevations = []
        for side in ("L", "R"):
            bone = rig.pose.bones.get(f"DEF-upper_arm.{side}")
            if bone is not None:
                direction = (bone.tail - bone.head).normalized()
                elevations.append(math.degrees(math.asin(max(-1.0, min(1.0, direction.z)))))
        report["upper_arm_elevation_degrees"] = [round(value, 2) for value in elevations]
    return report


def run(request):
    source = Path(request["source"]).resolve()
    export_path = Path(request["rigged_model"]).resolve()
    if not source.is_file() or not source.stat().st_size:
        fail(f"Character source is missing or empty: {source}")
    if export_path.exists():
        fail(f"Refusing to overwrite existing rigged model: {export_path}")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    meshes = imported_meshes(source)
    low, high = bounds(meshes)
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    bpy.ops.object.select_all(action="DESELECT")
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    weld_distance = max(high - low) * float(request.get("weld_relative_tolerance", 1e-5))
    mesh_reports = [weld_mesh(mesh, weld_distance) for mesh in meshes]
    nonmanifold_edges = sum(item["nonmanifold_edges"] for item in mesh_reports)
    boundary_edges = sum(item["boundary_edges"] for item in mesh_reports)
    topology_review_only = request.get("topology_policy") == "allow_for_review"
    if (nonmanifold_edges or boundary_edges) and not topology_review_only:
        fail(f"Character mesh has {nonmanifold_edges} non-manifold edges after welding; repair it before rigging")
    low, high = bounds(meshes)

    bpy.ops.preferences.addon_enable(module="rigify")
    # Basic human: no face rig or fingers, whose many small bones fell outside generated heads/hands.
    bpy.ops.object.armature_basic_human_metarig_add()
    metarig = bpy.context.object
    arm_depth_fit = fit_landmarks(metarig, meshes) or fit_metarig(metarig, low, high, meshes)
    bpy.context.view_layer.objects.active = metarig
    metarig.select_set(True)
    bpy.ops.pose.rigify_generate()
    rig = bpy.context.object
    if rig.type != "ARMATURE" or rig == metarig:
        fail("Rigify did not create a generated control rig")

    # Breast bones aren't in the delivered skeleton but took heat from the chest and upper arms, and
    # cap_influences then gave that weight to the head, which is what tore shoulders and sleeves.
    for bone in rig.data.bones:
        if bone.name.startswith("DEF-breast."):
            bone.use_deform = False

    skin_binding = bind_with_proxy(rig, meshes, high.z - low.z, solid_only=bool(request.get("solid_only")))
    for mesh in meshes:
        modifiers = [modifier for modifier in mesh.modifiers if modifier.type == "ARMATURE"]
        if not any(modifier.object == rig for modifier in modifiers):
            fail(f"Automatic skinning created no armature modifier for {mesh.name}")
        if not mesh.vertex_groups:
            fail(f"Automatic skinning created no vertex weights for {mesh.name}")
        if not any(vertex.groups for vertex in mesh.data.vertices):
            fail(f"Automatic skinning assigned no weighted vertices for {mesh.name}")

    influence_limit = int(request.get("max_influences", 4))
    if influence_limit <= 0:
        fail("Maximum skin influences must be positive")
    torso_slices = [tuple(item) for item in (arm_depth_fit or {}).get("torso_slices", [])]
    slice_half = (arm_depth_fit or {}).get("slice_half_height", 0.0)
    skin_weighting = [cap_influences(mesh, rig, influence_limit, torso_slices, slice_half,
                                     long_skirt=bool(request.get("long_skirt"))) for mesh in meshes]
    max_influences = max(item[0] for item in skin_weighting)
    contact_faces = 0 if request.get("keep_contacts") else sum(separate_contacts(mesh) for mesh in meshes)
    arm_counts = {side: sum(arm_weight_counts(mesh)[side] for mesh in meshes) for side in ("L", "R")}
    arms_suspect = min(arm_counts.values()) < 0.5 * max(arm_counts.values()) or min(arm_counts.values()) < 0.005 * sum(len(mesh.data.vertices) for mesh in meshes)

    deform_bones = [bone.name for bone in rig.data.bones if bone.use_deform]
    if not deform_bones:
        fail("Generated Rigify armature contains no deform bones")
    low, high = bounds(meshes)
    setup_render(low, high)
    evidence_metrics = {}
    baseline = evaluated_points(meshes)
    for pose_name, controls in POSES.items():
        control_report = render_pose(rig, meshes, pose_name, controls,
                                     Path(request["evidence"][pose_name]))
        posed = evaluated_points(meshes)
        evidence_metrics[pose_name] = {**control_report, "max_vertex_displacement": max_displacement(baseline, posed)}
    for bone in rig.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0, 0, 0)
        bone.scale = (1, 1, 1)
    bpy.context.view_layer.update()
    bpy.data.objects.remove(metarig, do_unlink=True)  # a clip retargets onto a file with one armature
    if request.get("rigged_blend"):  # with its controls, before the delivered skeleton strips them
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(request["rigged_blend"]).resolve()))
    deform_only_skeleton(rig)
    bpy.ops.object.select_all(action="DESELECT")
    for mesh in meshes:
        mesh.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    export_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(filepath=str(export_path), use_selection=True, object_types={"ARMATURE", "MESH"},
        use_armature_deform_only=True, add_leaf_bones=False, bake_anim=False,
        path_mode="COPY", embed_textures=True)
    if not export_path.is_file() or not export_path.stat().st_size:
        fail("Rigify FBX export is missing or empty")

    report = {"status": "complete", "provider": {"name": "Blender Rigify", "version": bpy.app.version_string,
        "source": "https://docs.blender.org/manual/en/5.1/addons/rigging/rigify/",
        "license": "GPL-2.0-or-later", "model": "Blender bundled human metarig",
        "model_license": "GPL-2.0-or-later"},
        "source": {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        "skeleton_mapping": {name: name for name in deform_bones},
        "unity_humanoid_mapping": {
            "Hips": "DEF-spine", "Spine": "DEF-spine.001", "Chest": "DEF-spine.003", "Neck": "DEF-spine.004",
            "Head": "DEF-spine.006", "LeftShoulder": "DEF-shoulder.L", "RightShoulder": "DEF-shoulder.R",
            "LeftUpperArm": "DEF-upper_arm.L", "LeftLowerArm": "DEF-forearm.L", "LeftHand": "DEF-hand.L",
            "RightUpperArm": "DEF-upper_arm.R", "RightLowerArm": "DEF-forearm.R", "RightHand": "DEF-hand.R",
            "LeftUpperLeg": "DEF-thigh.L", "LeftLowerLeg": "DEF-shin.L", "LeftFoot": "DEF-foot.L",
            "RightUpperLeg": "DEF-thigh.R", "RightLowerLeg": "DEF-shin.R", "RightFoot": "DEF-foot.R"},
        "deformation_evidence": evidence_metrics,
        "arm_depth_fit": arm_depth_fit,
        "arm_vertices": arm_counts,
        "skin_binding": skin_binding,
        "contact_separation": {"deleted_faces": contact_faces,
                               "rule": "faces joining forearm/hand-dominant and spine/pelvis/thigh-dominant vertices"},
        "max_influences": max_influences,
        "skin_weighting": [item[1] for item in skin_weighting],
        "mesh_repair": {"weld_tolerance": weld_distance, "meshes": mesh_reports,
                        "topology_policy": "allow_for_review" if topology_review_only else "strict",
                        "review_only": bool(topology_review_only and (nonmanifold_edges or boundary_edges))},
        "validation": {"status": "not_run", "warnings": [
            "Rigify joints come from mesh cross-section landmarks (bounds fallback when arms touch the body); inspect joint placement and all deformation poses.",
            "Automatic weights are candidates and are not a substitute for manual skin review.",
            *([f"Arm bones look misplaced: forearm and hand lead {arm_counts} vertices; inspect the arms before using this rig."] if arms_suspect else []),
            *([f"Review-only topology: {nonmanifold_edges} non-manifold and {boundary_edges} boundary edges remain; production eligibility is not established."
              ] if topology_review_only and (nonmanifold_edges or boundary_edges) else [])]}}
    Path(request["report"]).write_text(json.dumps(report, indent=2) + "\n")


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(args) != 1:
        raise SystemExit("Usage: blender --background --python rigify_character.py -- request.json")
    request = json.loads(Path(args[0]).read_text())
    try:
        run(request)
    except Exception as exc:
        traceback.print_exc()
        Path(request["report"]).write_text(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
