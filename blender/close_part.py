"""Close a part generated open: an open chest's lid turned shut onto its body and fitted to its opening.

A chest generated from its open picture has an inside to show (docs/superpowers/specs/2026-10-26-open-state-hinged-
parts-design.md); its lid is shut here, before the final pass. The hinge line is where the lid touches the body. Each
piece's open face is the flat face through that line that rays from the piece's middle pass through; the lid turns
about the line until its open face meets the body's, then stretches along the opening's depth to its length
(TRELLIS.2 made a tilted lid ~9% short from one view, OPEN1). A search over the turn and an offset across the hinge
then seals the box: rays from the cavity must not escape between lid and body, few lid points may go deep into the
walls, the lid may not sink into the opening below the rim, and no back of a face may show. A gap weighs ten times a
lid edge hidden in a wall top (OPEN2: weighed the other way, with every lid point inside counted, the search stopped
at 37 degrees with 1.8% of the rays escaping, a slit; the seal formed at 43). Without the sinking term a sealed lid
tipped on into the hollow (a test box's lid closed 74 degrees for 70, its front edge 6% of the box low). The stretch
stays the face match's: searched too, it ran to the bound (OPEN2: 1.15 where the face match measured 1.0095) to push
the lid's front out past the wall, a lid drooping over the front. It is clamped to max_stretch (the owner's 15%,
2026-10-26), and the candidate is gated on the face match's own stretch (validation.apply_part_fit).

Request (JSON): surface (GLB, one node per part), part (its node name), out (GLB), report (JSON), max_stretch.
"""
import json
import math
import sys
import time
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mesh_cleanup import gltf_name, visible_backfaces, winding_numbers  # noqa: E402


def world_bmesh(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    return bm


def main_piece(obj, weld):
    """The points and ray tree of the object's largest connected piece: loose specks labelled with a piece skewed
    the hinge line (OPEN1: 1% of the body's vertices, up by the open lid, stopped the lid at 61 degrees)."""
    bm = world_bmesh(obj)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=weld)
    seen, best = set(), []
    for face in bm.faces:
        if face.index in seen:
            continue
        stack, piece = [face], []
        seen.add(face.index)
        while stack:
            current = stack.pop()
            piece.append(current)
            for edge in current.edges:
                for other in edge.link_faces:
                    if other.index not in seen:
                        seen.add(other.index)
                        stack.append(other)
        if len(piece) > len(best):
            best = piece
    verts = sorted({v for f in best for v in f.verts}, key=lambda v: v.index)
    index = {v: i for i, v in enumerate(verts)}
    points = np.array([tuple(v.co) for v in verts])
    tree = BVHTree.FromPolygons([Vector(p) for p in points], [[index[v] for v in f.verts] for f in best])
    bm.free()
    return points, tree


def triangles(obj):
    bm = world_bmesh(obj)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    result = np.array([[tuple(v.co) for v in f.verts] for f in bm.faces])
    bm.free()
    return result


def tree_of(tris):
    return BVHTree.FromPolygons([Vector(p) for p in tris.reshape(-1, 3)],
                                [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(tris))])


def hinge_line(body_tree, lid_points, size):
    """A point on the hinge line and its direction: the lid's points touching the body (generated objects stand
    axis-aligned, so the direction is the coordinate axis nearest their principal direction)."""
    gaps = np.array([body_tree.find_nearest(Vector(p))[3] for p in lid_points])
    contact = lid_points[gaps <= max(0.004 * size, float(np.percentile(gaps, 2)))]
    centre = contact.mean(0)
    principal = np.linalg.svd(contact - centre, full_matrices=False)[2][0]
    axis = np.eye(3)[int(np.argmax(np.abs(principal)))]
    return centre, axis, len(contact), float(gaps.min())


def open_face(points, tree, centre, axis, frame, size, snap=False):
    """The piece's flat open face through the hinge line: the support plane with the most points on it that rays
    from the piece's middle pass through unblocked, a little beyond it: an opening, not a wall (a ray stopped short
    of the plane took a thin front wall for the opening). Returns (outward normal, the face's end at the hinge, its
    far end)."""
    e1, e2 = frame
    tol = 0.01 * size
    relative = points - centre
    rows = []
    for k in range(720):
        normal = math.cos(math.radians(k / 2)) * e1 + math.sin(math.radians(k / 2)) * e2
        height = float(np.percentile(relative @ normal, 98))
        rows.append((int((np.abs(relative @ normal - height) < tol).sum()), normal, height))
    counts = np.array([row[0] for row in rows])
    peaks = [i for i in range(720) if counts[i] == max(counts[(i + j) % 720] for j in range(-20, 21))]
    middle = points.mean(0)
    chosen = None
    for i in sorted(peaks, key=lambda i: -counts[i]):
        _count, normal, height = rows[i]
        reach = max(height - float((middle - centre) @ normal), 0.0) + tol
        blocked = sum(tree.ray_cast(Vector(middle + axis * dx * size), Vector(normal), reach)[0] is not None
                      for dx in (-0.2, 0.0, 0.2))
        if blocked == 0:
            chosen = normal
            break
    if chosen is None:
        raise ValueError("no open face: every flat face of the piece is blocked from its middle")
    if snap:  # the body stands as generated, axis-aligned: its open face is a coordinate plane
        k = int(np.argmax(np.abs(chosen)))
        chosen = np.eye(3)[k] * np.sign(chosen[k])
    along = relative @ chosen
    # the face's height: the most populated in the piece's outer tenth (knuckles and a hasp stand above a rim)
    heights = np.linspace(np.percentile(along, 90), along.max(), 200)
    height = float(max(heights, key=lambda h: (int((np.abs(along - h) < tol / 2).sum()), h)))  # ties: outermost
    on = relative[np.abs(along - height) < tol / 2]
    across = np.cross(axis, chosen)
    ends = [centre + on[np.argmin(np.abs(on @ across - np.percentile(on @ across, q)))] for q in (1, 99)]
    ends = [centre + (end - centre) - ((end - centre) @ axis) * axis for end in ends]
    hinge, far = sorted(ends, key=lambda end: np.linalg.norm(end - centre))
    return chosen, hinge, far


def pose(params, centre, axis, frame, depth_dir, hinge_end):
    """The lid's world transform (A, b) for a turn about the hinge line, a shift across it and a stretch along the
    opening's depth about the body's hinge end."""
    theta, d1, d2, stretch = params
    rotation = np.array(Matrix.Rotation(theta, 3, Vector(axis)))
    scale = np.eye(3) + (stretch - 1) * np.outer(depth_dir, depth_dir)
    shift = d1 * frame[0] + d2 * frame[1]
    return scale @ rotation, scale @ (centre - rotation @ centre + shift - hinge_end) + hinge_end


def main(request):
    started = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(request["surface"]))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    lid = next(obj for obj in objects if gltf_name(obj) == request["part"])
    body = [obj for obj in objects if obj is not lid]
    if len(body) != 1:
        raise ValueError(f"expected one body node beside {request['part']}, found {len(body)}")
    body = body[0]
    everything = np.concatenate([np.array([obj.matrix_world @ v.co for v in obj.data.vertices]) for obj in objects])
    size = float(np.ptp(everything, 0).max())
    body_points, body_tree = main_piece(body, 1e-5 * size)
    lid_points, lid_tree = main_piece(lid, 1e-5 * size)
    centre, axis, contact, gap = hinge_line(body_tree, lid_points, size)
    e1 = np.cross(axis, [0, 0, 1.0]) if abs(axis[2]) < 0.9 else np.cross(axis, [1.0, 0, 0])
    e1 /= np.linalg.norm(e1)
    frame = (e1, np.cross(axis, e1))
    body_normal, body_hinge, body_far = open_face(body_points, body_tree, centre, axis, frame, size, snap=True)
    lid_normal, lid_hinge, lid_far = open_face(lid_points, lid_tree, centre, axis, frame, size)
    # the face match: turn until the lid's open face faces the body's, move its hinge end onto the body's, stretch
    theta = math.atan2(float(np.dot(np.cross(lid_normal, -body_normal), axis)), float(np.dot(lid_normal, -body_normal)))
    rotation = np.array(Matrix.Rotation(theta, 3, Vector(axis)))
    turned_hinge, turned_far = rotation @ (lid_hinge - centre) + centre, rotation @ (lid_far - centre) + centre
    shift = body_hinge - turned_hinge
    depth_dir = (body_far - body_hinge) / np.linalg.norm(body_far - body_hinge)
    needed = float(np.linalg.norm(body_far - body_hinge) / np.linalg.norm(turned_far - turned_hinge))
    bound = float(request.get("max_stretch", 1.15))
    start = np.array([theta, float(shift @ frame[0]), float(shift @ frame[1]), min(max(needed, 1 / bound), bound)])

    # the seal: cavity points below the opening (outside the body's solid), rays from them in 64 directions
    body_tris, lid_tris = triangles(body), triangles(lid)
    other = np.cross(body_normal, depth_dir)
    width = body_points @ other
    grid = np.array([body_hinge + t * (body_far - body_hinge) + (x - body_hinge @ other) * other - d * body_normal
                     for x in np.linspace(-0.4, 0.4, 7) * float(np.ptp(width)) + float(np.median(width))
                     for t in np.linspace(0.15, 0.85, 6)
                     for d in np.linspace(0.15, 0.6, 4) * float(np.ptp(body_points @ body_normal))])
    cavity = grid[np.abs(winding_numbers(grid, body_tris)) < 0.2]
    golden = math.pi * (3 - math.sqrt(5))
    directions = [Vector((math.cos(golden * i) * math.sqrt(1 - z * z), math.sin(golden * i) * math.sqrt(1 - z * z), z))
                  for i, z in enumerate(np.linspace(1 - 1 / 64, -1 + 1 / 64, 64))]
    # lid points counted as the final pass counts penetration: newly inside the body and deeper than 0.5% of its size
    sample = lid_tris.reshape(-1, 3)[::max(1, len(lid_tris) * 3 // 3000)]
    already = np.abs(winding_numbers(sample, body_tris)) > 0.5
    rim_level, low, high = float(body_hinge @ body_normal), body_points.min(0), body_points.max(0)
    rest = lid.matrix_world.copy()

    def place(params):
        A, b = pose(params, centre, axis, frame, depth_dir, body_hinge)
        lid.matrix_world = Matrix([[*A[0], b[0]], [*A[1], b[1]], [*A[2], b[2]], [0, 0, 0, 1]]) @ rest
        bpy.context.view_layer.update()
        return A, b

    def measure(params):
        A, b = place(params)
        moved = tree_of((lid_tris.reshape(-1, 3) @ A.T + b).reshape(-1, 3, 3))
        escaped = sum(1 for p in cavity for direction in directions
                      if body_tree.ray_cast(Vector(p), direction)[0] is None
                      and moved.ray_cast(Vector(p), direction)[0] is None)
        placed = sample @ A.T + b
        solid = np.abs(winding_numbers(placed, body_tris)) > 0.5
        candidates = np.flatnonzero(solid & ~already)  # the nearest-surface query only where it can count
        deep = np.zeros(len(placed), bool)
        deep[candidates] = [body_tree.find_nearest(Vector(placed[i]))[3] > 0.005 * size for i in candidates]
        # in the hollow: below the rim, within the body's footprint, not in its walls
        sunk = ((placed @ body_normal < rim_level - 0.01 * size) & np.all((placed > low) & (placed < high), axis=1)
                & ~solid)
        return {"escape": escaped / max(len(cavity) * len(directions), 1),
                "inside": float(np.mean(solid & ~already & deep)), "sunk": float(np.mean(sunk)),
                "backs": float(visible_backfaces([body, lid]))}

    def cost(params):
        seal = measure(params)
        return 10 * seal["escape"] + seal["inside"] + seal["sunk"] + seal["backs"]

    # a coarse scan of the turn first: from the face match alone the local search stalled in a pocket (OPEN2)
    scan = [(cost(trial), trial) for trial in (start + np.array([math.radians(k), 0, 0, 0]) for k in range(-6, 11, 2))]
    best, params = min(scan, key=lambda item: item[0])
    steps = np.array([math.radians(2), 0.02 * size, 0.02 * size])
    while steps[1] > 0.002 * size:
        for i in range(3):  # turn and offset; the stretch stays the face match's
            improved = False
            for sign in (1, -1):
                trial = params.copy()
                trial[i] += sign * steps[i]
                value = cost(trial)
                if value < best - 1e-5:
                    params, best, improved = trial, value, True
                    break
            if improved:
                break
        else:
            steps /= 2
    seal = measure(params)
    place(params)
    bpy.ops.object.select_all(action="DESELECT")
    lid.select_set(True)
    bpy.context.view_layer.objects.active = lid
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=str(request["out"]), export_format="GLB", export_yup=True)
    report = {"part": request["part"], "contact_points": contact, "gap": round(gap / size, 5),
              "hinge": {"point": [round(float(v), 4) for v in centre], "axis": [int(v) for v in axis]},
              "face_match": {"turn_degrees": round(math.degrees(theta), 2), "stretch": round(needed, 4)},
              "turn_degrees": round(math.degrees(float(params[0])), 2), "stretch": round(float(params[3]), 4),
              "needed_stretch": round(needed, 4), "max_stretch": bound, "cavity_points": int(len(cavity)),
              "seal": {key: round(value, 5) for key, value in seal.items()}, "seconds": round(time.time() - started)}
    Path(request["report"]).write_text(json.dumps(report, indent=2) + "\n")
    print("CLOSE_PART " + json.dumps(report))


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text()))
