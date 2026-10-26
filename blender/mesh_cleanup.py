import bmesh


def remove_isolated_single_faces(mesh):
    """Drop detached one-face fragments while keeping multi-face islands. The other faces keep their orientation:
    recomputing it turned half of a pistol inside out on the open surface hidden-face removal leaves (2026-10-26)."""
    parent = list(range(len(mesh.vertices)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    positions = {}
    for vertex in mesh.vertices:
        other = positions.setdefault(tuple(vertex.co), vertex.index)
        left, right = find(other), find(vertex.index)
        if left != right:
            parent[right] = left

    face_roots = []
    for polygon in mesh.polygons:
        if not polygon.vertices:
            face_roots.append(None)
            continue
        root = find(polygon.vertices[0])
        for vertex in polygon.vertices[1:]:
            other = find(vertex)
            if root != other:
                parent[other] = root
        face_roots.append(root)

    face_counts = {}
    for root in face_roots:
        if root is not None:
            root = find(root)
            face_counts[root] = face_counts.get(root, 0) + 1
    remove_indices = [index for index, root in enumerate(face_roots)
                      if root is not None and face_counts[find(root)] == 1]
    if not remove_indices:
        return 0

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[index] for index in remove_indices], context="FACES_ONLY")
    bmesh.ops.delete(bm, geom=[edge for edge in bm.edges if not edge.link_faces], context="EDGES")
    bmesh.ops.delete(bm, geom=[vertex for vertex in bm.verts if not vertex.link_edges], context="VERTS")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return len(remove_indices)


def repair_manifold_locally(mesh, merge_distance, rounds=10):
    """Close holes and remove non-manifold spots without remeshing the whole surface.

    A full voxel remesh makes a watertight mesh but melts modelled detail (pockets, folds, faces)
    into clay. Here only faces around non-manifold edges and pinched vertices are removed and
    every boundary loop is refilled; the rest of the surface is untouched. Returns the remaining
    (boundary, non_manifold) edge counts so the caller can fall back to a voxel repair.
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)

    def counts():
        return (sum(edge.is_boundary for edge in bm.edges),
                sum(not edge.is_manifold and not edge.is_boundary for edge in bm.edges))

    def fill_loops():
        boundary = {edge for edge in bm.edges if edge.is_boundary}
        while boundary:
            loop, frontier = set(), [boundary.pop()]
            loop.add(frontier[0])
            while frontier:
                for vertex in frontier.pop().verts:
                    for other in vertex.link_edges:
                        if other in boundary:
                            boundary.discard(other)
                            loop.add(other)
                            frontier.append(other)
            vertices = {vertex for edge in loop for vertex in edge.verts}
            try:
                if len(loop) <= 4 and len(vertices) == len(loop):
                    bm.faces.new(list(vertices))
                elif not bmesh.ops.triangle_fill(bm, edges=list(loop), use_beauty=True, use_dissolve=False)["geom"]:
                    fan_fill(loop)
            except ValueError:
                pass  # face exists already or the loop is degenerate; the next round removes it

    def fan_fill(loop):
        """Close a boundary loop with a centre vertex; works for non-planar loops triangle_fill rejects."""
        ordered, edges = [], set(loop)
        start = next(iter(edges))
        current, previous = start.verts[0], None
        while True:
            ordered.append(current)
            step = next((edge for edge in current.link_edges if edge in edges and edge is not previous), None)
            if step is None:
                return
            previous, current = step, step.other_vert(current)
            if current is ordered[0]:
                break
            if len(ordered) > len(edges):
                return  # not a simple cycle (pinched); a later round opens it wider
        centre = bm.verts.new(sum((vertex.co for vertex in ordered), ordered[0].co * 0) / len(ordered))
        for a, b in zip(ordered, ordered[1:] + ordered[:1]):
            try:
                bm.faces.new((a, b, centre))
            except ValueError:
                pass

    previous = None
    for round_index in range(rounds):
        bad = [edge for edge in bm.edges if not edge.is_manifold and not edge.is_boundary]
        pinched = [vertex for vertex in bm.verts if not vertex.is_manifold and vertex.link_faces]
        faces = {face for edge in bad for vertex in edge.verts for face in vertex.link_faces}
        faces |= {face for vertex in pinched for face in vertex.link_faces}
        if previous is not None and counts() == previous and counts()[0]:
            # A hole that refilling cannot close (degenerate or self-touching): open a wider ring and retry.
            ring = {vertex for edge in bm.edges if edge.is_boundary for vertex in edge.verts}
            for _ in range(1 + round_index // 2):
                ring |= {other for vertex in ring for edge in vertex.link_edges for other in edge.verts}
            faces |= {face for vertex in ring for face in vertex.link_faces}
        previous = counts()
        if faces:
            bmesh.ops.delete(bm, geom=list(faces), context="FACES")
            bmesh.ops.delete(bm, geom=[vertex for vertex in bm.verts if not vertex.link_edges], context="VERTS")
        bmesh.ops.holes_fill(bm, edges=[edge for edge in bm.edges if edge.is_boundary], sides=0)
        fill_loops()
        bmesh.ops.triangulate(bm, faces=[face for face in bm.faces if len(face.verts) > 3])
        if counts() == (0, 0):
            break
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    remaining = counts()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return remaining


def remove_enclosed_components(mesh, merge_distance, sample=200, inside_share=0.8):
    """Delete components that lie inside the largest component (hidden inner shells).

    Image-to-3D meshes often contain an inner duplicate of the body just under the visible
    surface. It is invisible, doubles the face count and, rigged, pokes through when the body
    bends. A component counts as enclosed when most of its sampled vertices are inside the main
    surface by ray-cast parity. Returns the number of vertices removed.
    """
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)
    bm.verts.ensure_lookup_table()
    seen, components = set(), []
    for vertex in bm.verts:
        if vertex.index in seen:
            continue
        stack, members = [vertex], []
        seen.add(vertex.index)
        while stack:
            current = stack.pop()
            members.append(current)
            for edge in current.link_edges:
                other = edge.other_vert(current)
                if other.index not in seen:
                    seen.add(other.index)
                    stack.append(other)
        components.append(members)
    if len(components) < 2:
        bm.free()
        return 0
    components.sort(key=len, reverse=True)
    main_faces = {face for vertex in components[0] for face in vertex.link_faces}
    tree = BVHTree.FromPolygons([vertex.co.copy() for vertex in bm.verts],
                                [[v.index for v in face.verts] for face in main_faces])
    direction = Vector((0.0, 0.0, 1.0))

    def inside(point):
        hits, origin = 0, point.copy()
        while True:
            location, _, _, _ = tree.ray_cast(origin, direction)
            if location is None:
                return hits % 2 == 1
            hits += 1
            origin = location + direction * 1e-6

    doomed = []
    for members in components[1:]:
        step = max(1, len(members) // sample)
        probes = members[::step]
        if sum(inside(vertex.co) for vertex in probes) >= inside_share * len(probes):
            doomed.extend(members)
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context="VERTS")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return len(doomed)


def separate_part(obj, name, kind, smoothing=4, min_faces=8, basecolor=None):
    """Split a weapon's moving part from its mesh along the vertex group slopforge_part_<name>; returns the part.

    The group holds the vertices under the part's concept mask (prepare_model.py). A face belongs to the part when
    most of its corners do, then takes the majority of itself and its neighbours for `smoothing` rounds: on a live
    pistol slide, misregistration left spikes along the cut that four rounds removed (2026-10-24). Vertices are
    welded by position first, because a textured GLB splits them along UV seams and every seam would read as a cut.
    Both sides of the cut are closed with flat caps that take one texel of the surface beside them, so a cap shows a
    plain colour instead of a smear: the texel of basecolor (a Blender image, or None) nearest the median colour
    along the cut, since a single boundary texel can be a pale outlier (a live pistol's caps came out white). The part becomes a child of obj: a slide pivots at its bounding box centre, a
    hinge at the centre of its cut. Returns None when too few faces fall under the mask.
    """
    import bpy
    from mathutils import Matrix, Vector
    group = obj.vertex_groups.get(f"slopforge_part_{name}")
    if group is None:
        return None
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    # Every layer exists before any face is collected: adding a layer afterwards renews the element references, and
    # a face set built earlier then matches nothing.
    deform = bm.verts.layers.deform.verify()
    for layers, layer_name in ((bm.verts.layers.int, "slopforge_cut"), (bm.faces.layers.int, "slopforge_part")):
        if layers.get(layer_name) is not None:  # never carried over: removed before the meshes are written
            layers.remove(layers.get(layer_name))
    cut_layer = bm.verts.layers.int.new("slopforge_cut")
    label = bm.faces.layers.int.new("slopforge_part")
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=max(obj.dimensions) * 1e-6)
    inside = {vertex: vertex[deform].get(group.index, 0.0) > 0.5 for vertex in bm.verts}
    part = {face for face in bm.faces if sum(inside[vertex] for vertex in face.verts) * 2 > len(face.verts)}
    for _ in range(smoothing):
        labels = {}
        for face in bm.faces:
            near = {other for edge in face.edges for other in edge.link_faces} | {face}
            labels[face] = sum(other in part for other in near) * 2 > len(near)
        part = {face for face, belongs in labels.items() if belongs}
    # Islands: a strip of either side enclosed by the other, left where a ragged mask crossed the surface (a live
    # pistol body came out in 12-19 pieces). Any piece of a side that is not its largest, and touches the cut, joins
    # the side around it; pre-existing separate pieces touch no cut and stay.
    # Only strips along the cut flip, pieces whose every face lies within two rings of the other side: a pistol's
    # magazine, an interior plate of 421 faces joined to the body only through inner surfaces, had followed the
    # slide out of the grip (2026-10-24).
    for _ in range(3):
        moved = False
        for side in (True, False):
            faces = [face for face in bm.faces if (face in part) == side]
            border = {vertex for face in faces for vertex in face.verts
                      if any((other in part) != side for other in vertex.link_faces)}
            for _ring in range(2):
                border |= {other for vertex in border for edge in vertex.link_edges for other in edge.verts}
            for piece in _face_pieces(faces)[1:]:
                if all(any(vertex in border for vertex in face.verts) for face in piece):
                    part = (part - piece) if side else (part | piece)
                    moved = True
        if not moved:
            break
    if len(part) < min_faces or len(part) == len(bm.faces):
        bm.free()
        return None
    seam = [edge for edge in bm.edges
            if any(face in part for face in edge.link_faces) and not all(face in part for face in edge.link_faces)]
    plane = _seam_plane(seam, max(obj.dimensions))
    if plane is not None:
        # Cut the surface on the fitted plane near the seam, and give each face there the side of the plane it lies
        # on, so the cut is one straight line and its caps are flat: a ragged mask leaves teeth of either side
        # across it, and the muzzle face's body faces had carried the frame's cap to the muzzle (2026-10-24).
        for face in bm.faces:
            face[label] = int(face in part)
        near = {vertex for edge in seam for vertex in edge.verts}
        for _ in range(2):
            near |= {other for vertex in near for edge in vertex.link_edges for other in edge.verts}
        faces = [face for face in bm.faces if any(vertex in near for vertex in face.verts)]
        centre, normal = plane
        inward = 1.0 if sum(_side(face, centre, normal) for face in part) >= 0 else -1.0
        geometry = list(near) + [edge for face in faces for edge in face.edges] + faces
        bmesh.ops.bisect_plane(bm, geom=list(dict.fromkeys(geometry)), dist=1e-6, plane_co=centre, plane_no=normal)
        bm.verts.ensure_lookup_table()
        near = {vertex for vertex in near if vertex.is_valid}
        for _ in range(2):  # the new vertices on the plane, and the teeth beyond them
            near |= {other for vertex in near for edge in vertex.link_edges for other in edge.verts}
        for face in bm.faces:
            if any(vertex in near for vertex in face.verts):
                face[label] = int(_side(face.calc_center_median(), centre, normal) * inward > 0)
        part = {face for face in bm.faces if face[label]}
        seam = [edge for edge in bm.edges
                if any(face in part for face in edge.link_faces) and not all(face in part for face in edge.link_faces)]
    for edge in seam:
        for vertex in edge.verts:
            vertex[cut_layer] = 1
    cut = [vertex.co.copy() for vertex in {vertex for edge in seam for vertex in edge.verts}]
    for face in bm.faces:
        face[label] = int(face in part)
    bmesh.ops.split_edges(bm, edges=seam)
    piece = bm.copy()
    for target, keep in ((piece, 1), (bm, 0)):
        layer = target.faces.layers.int["slopforge_part"]
        bmesh.ops.delete(target, geom=[face for face in target.faces if face[layer] != keep], context="FACES")
        _cap_cut(target, basecolor)
        target.verts.layers.int.remove(target.verts.layers.int["slopforge_cut"])
        target.faces.layers.int.remove(target.faces.layers.int["slopforge_part"])
    barrel = None
    if kind == "slide" and plane is not None:
        # shortcut: every slide gets a barrel; a slide that is not a gun's (a bolt handle) would get a spurious one.
        barrel = _barrel_mesh(bm, piece, plane, name)
    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()
    if barrel is not None:
        _attach(obj, barrel, "barrel", sum((Vector(vertex.co) for vertex in barrel.vertices), Vector()) / len(barrel.vertices))
    mesh = bpy.data.meshes.new(name)
    piece.to_mesh(mesh)
    piece.free()
    if kind == "hinge":
        pivot = sum(cut, Vector()) / len(cut) if cut else Vector()
    else:
        low = Vector([min(vertex.co[axis] for vertex in mesh.vertices) for axis in range(3)])
        high = Vector([max(vertex.co[axis] for vertex in mesh.vertices) for axis in range(3)])
        pivot = (low + high) / 2
    return _attach(obj, mesh, kind, pivot)


# Declared ranges are in the published (Unity) frame, x right, y up, z forward (docs/WEAPONS.md, Axes); the export
# maps Blender (x, y, z) to Unity (-x, z, -y). About x the turn's sense is the same in both (Unity's left-handed
# convention and the mirror cancel: a positive turn sinks a back-hinged lid's front in both, 2026-10-25 chest);
# y and z follow the same change of basis and are not yet checked live.
HINGE_AXES = {"x": ((1, 0, 0), 1), "y": ((0, 0, 1), -1), "z": ((0, 1, 0), 1)}
SLIDE_AXES = {"x": (-1, 0, 0), "y": (0, 0, 1), "z": (0, -1, 0)}


def remove_hidden_faces(mesh, size, directions=32):
    """Delete the faces no ray from outside reaches; returns how many. Each face casts rays from its centre along
    `directions` evenly spread directions (a Fibonacci sphere) and is seen when one leaves the object; a face beside a
    seen one and facing within 60 degrees of it stays too, so a crevice's edge is not left ragged. TRELLIS.2 surfaces
    are a double skin (an outer face and an inner one about half a percent of the object inside) with shells inside:
    of a delivered pistol's 26,000 faces 9% could be seen, of a chest's 20%, and the reduction spent the budget and the
    texture on the rest. On that pistol's 1.26 million-face detail mesh 28% were seen (40 s); reduced to the same
    budget, the slide's step, the hammer and the grip panels came out crisp instead of lumpy (2026-10-25)."""
    import math
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=size * 1e-6)
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    bm.normal_update()
    tree = BVHTree.FromBMesh(bm)
    golden = math.pi * (3 - math.sqrt(5))
    rays = []
    for index in range(directions):
        z = 1 - 2 * (index + 0.5) / directions
        radius = math.sqrt(1 - z * z)
        rays.append(Vector((math.cos(golden * index) * radius, math.sin(golden * index) * radius, z)))
    seen = [any(tree.ray_cast(face.calc_center_median() + ray * size * 1e-4, ray, size * 4)[0] is None for ray in rays)
            for face in bm.faces]
    keep = list(seen)
    for face in bm.faces:
        if seen[face.index]:
            for edge in face.edges:
                for other in edge.link_faces:
                    if not seen[other.index] and face.normal.dot(other.normal) >= 0.5:
                        keep[other.index] = True
    keep = bridge_hidden_paths(bm, keep)
    hidden = [face for face in bm.faces if not keep[face.index]]
    bmesh.ops.delete(bm, geom=hidden, context="FACES")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return len(hidden)


def bridge_hidden_paths(bm, keep, rings=128):
    """`keep` (one flag per face, by index) with the hidden faces on the shortest path from each kept piece to the
    largest, through at most `rings` hidden faces, kept too. Seen patches joined to the rest only through hidden faces
    (a crevice's walls, under the skin) became pieces of their own: a pistol's surface went from 1 piece to 71, its
    body failed the component budget, and a patch at the muzzle stayed with the body while the slide around it moved
    (HP10 seed 1, 2026-10-26). A piece reached joins the sources, so pieces can join through each other. On that
    pistol's 1.3 million-face detail mesh, faces under a millimetre: 8 rings left 50 pieces, 32 left 32, 128 one,
    keeping 1.4% more faces, all hidden."""
    from collections import deque
    keep = list(keep)
    piece = [-1] * len(keep)
    sizes = []
    for face in bm.faces:
        if keep[face.index] and piece[face.index] < 0:
            piece[face.index], stack, count = len(sizes), [face], 0
            while stack:
                current = stack.pop()
                count += 1
                for edge in current.edges:
                    for other in edge.link_faces:
                        if keep[other.index] and piece[other.index] < 0:
                            piece[other.index] = len(sizes)
                            stack.append(other)
            sizes.append(count)
    if len(sizes) < 2:
        return keep
    members = [[] for _ in sizes]
    for face in bm.faces:
        if piece[face.index] >= 0:
            members[piece[face.index]].append(face)
    depth, came, queue, joined = {}, {}, deque(), set()

    def join(label):
        joined.add(label)
        for face in members[label]:
            depth[face.index] = 0
            queue.append(face)
    join(max(range(len(sizes)), key=sizes.__getitem__))
    while queue:
        current = queue.popleft()
        for edge in current.edges:
            for other in edge.link_faces:
                if other.index in depth:
                    continue
                if keep[other.index]:
                    if piece[other.index] not in joined:
                        step = current.index
                        while depth[step] > 0:
                            keep[step] = True
                            step = came[step]
                        join(piece[other.index])
                elif depth[current.index] < rings:
                    depth[other.index] = depth[current.index] + 1
                    came[other.index] = current.index
                    queue.append(other)
    return keep


def winding_numbers(points, triangles, chunk=16):
    """The generalized winding number of each point (n, 3) about `triangles` (m, 3, 3): about 1 inside a closed
    surface and 0 outside it, and still near that where the surface has holes, where a ray's parity is not (a hybrid
    pistol's open body read half its slide inside by parity, 2026-10-25). The triangles' signed solid angles over
    4 pi (Jacobson, Kavan and Sorkine-Hornung 2013); the sign follows the winding, so callers take its size."""
    import numpy as np
    points = np.asarray(points, float).reshape(-1, 3)
    triangles = np.asarray(triangles, float).reshape(-1, 3, 3)
    numbers = np.zeros(len(points))
    dot = lambda x, y: np.einsum("nmi,nmi->nm", x, y)
    for start in range(0, len(points), chunk):
        corners = triangles[None] - points[start:start + chunk, None, None, :]
        a, b, c = corners[..., 0, :], corners[..., 1, :], corners[..., 2, :]
        la, lb, lc = (np.linalg.norm(corner, axis=-1) for corner in (a, b, c))
        det = dot(a, np.cross(b, c))
        den = la * lb * lc + dot(a, b) * lc + dot(b, c) * la + dot(c, a) * lb
        numbers[start:start + chunk] = np.arctan2(det, den).sum(1) / (2 * np.pi)
    return numbers


def world_triangles(objects):
    """The triangles (m, 3, 3) of the objects' evaluated meshes in world space."""
    import bpy
    import numpy as np
    depsgraph = bpy.context.evaluated_depsgraph_get()
    found = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        matrix = np.array(obj.matrix_world)
        vertices = np.array([vertex.co[:] for vertex in mesh.vertices]).reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
        indices = np.array([triangle.vertices[:] for triangle in mesh.loop_triangles], int).reshape(-1, 3)
        found.append(vertices[indices])
        evaluated.to_mesh_clear()
    return np.concatenate(found) if found else np.zeros((0, 3, 3))


def sweep_penetration(part, others, axis, low, high, samples=9, limit=400, depth=0.005):
    """The share of `part`'s vertices that go inside `others` at the worst of `samples` points of its declared range
    and were not inside at rest: a lid turned into its chest, a drawer through its housing. The part turns about its
    origin (its pivot) or slides along its axis. A point is inside where the others' winding number is over a half
    (generated meshes are open, so a ray's parity lies) and counts when it is deeper than `depth` of the model's
    size: a hybrid slide and frame are one surface cut along a zigzag, and moved back the slide's edge dips a
    fraction of a millimetre under the frame's along the whole seam (6% of a pistol's slide newly inside, 0.14%
    deeper than half a percent; a chest lid turned the wrong way 18% and 7.4%, 2026-10-25). A slide's point that
    enters through its seat (the others' triangles within `depth` of the part at rest) is the part going into its
    housing and does not count: a pistol's trigger cut from the frame it was fused to enters the solid frame there
    by its whole travel (2026-10-26). A hinge has no housing: a lid rests on its chest's whole top, and turned the
    wrong way it enters through that seat. Everything is in world space: the body of a weapon stands at its grip,
    away from the origin. Unity repeats the check on the prefab."""
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    triangles = world_triangles(others)
    step = max(1, len(part.data.vertices) // limit)
    rest = [part.matrix_world @ vertex.co for index, vertex in enumerate(part.data.vertices) if index % step == 0]
    if not len(triangles) or not rest:
        return 0.0
    corners = triangles.reshape(-1, 3)
    tree = BVHTree.FromPolygons([Vector(c) for c in corners], [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(triangles))])
    points = np.array([tuple(p) for p in rest])
    size = float(np.ptp(np.concatenate([corners, points]), 0).max())
    own = world_triangles([part]).reshape(-1, 3)
    part_tree = BVHTree.FromPolygons([Vector(c) for c in own], [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(own) // 3)])
    seat = np.array([part.get("slopforge_part") == "slide" and
                     min(part_tree.find_nearest(Vector(p))[3] for p in (*triangle, triangle.mean(0))) <= depth * size
                     for triangle in triangles])
    inside = lambda pts: np.abs(winding_numbers(pts, triangles)) > 0.5
    at_rest = inside(points)
    far = low if abs(low) > abs(high) else high  # the range runs from rest to its far end
    path = [points]
    worst = 0.0
    for sample in range(1, samples + 1):
        move = np.array(motion_matrix(part, axis, far * sample / samples))
        moved = points @ move[:3, :3].T + move[:3, 3]
        path.append(moved)
        entered = np.nonzero(inside(moved) & ~at_rest)[0]
        deep = sum(1 for index in entered if tree.find_nearest(Vector(moved[index]))[3] > depth * size
                   and not _entered_through(tree, seat, [step[index] for step in path]))
        worst = max(worst, deep / len(points))
    return round(worst, 4)


def _entered_through(tree, seat, positions):
    """Whether a point's path (its positions in order) first crosses the others' surface at a seat triangle."""
    from mathutils import Vector
    for start, end in zip(positions, positions[1:]):
        direction = Vector(end) - Vector(start)
        if direction.length == 0:
            continue
        hit = tree.ray_cast(Vector(start), direction.normalized(), direction.length)
        if hit[0] is not None:
            return bool(seat[hit[2]])
    return False


def motion_matrix(part, axis, amount):
    """The world-space move of a part `amount` along its declared axis (Unity's frame, see HINGE_AXES): a slide
    along it, a hinge turned about its origin (its pivot)."""
    import math
    from mathutils import Matrix, Vector
    if part.get("slopforge_part") == "slide":
        return Matrix.Translation(Vector(SLIDE_AXES[axis]) * amount)
    pivot = part.matrix_world.translation.copy()
    direction, sign = HINGE_AXES[axis]
    return (Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(sign * amount), 4, Vector(direction))
            @ Matrix.Translation(-pivot))


def visible_backfaces(objects, moves=None, resolution=96):
    """The share of what a camera sees of `objects` that is the back of a face, from the six axes and the eight
    diagonals (orthographic): a hole in a piece shows the inside of its far walls. `moves` maps an object's name to a
    world-space matrix (motion_matrix), to look at the model with a part moved. A hybrid pistol's pieces left open
    showed holes on 3.6% of its pixels with the slide back and the trigger pulled, 0.4% closed (2026-10-25)."""
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    corners = []
    for obj in objects:
        triangles = world_triangles([obj])
        if moves and obj.name in moves and len(triangles):
            matrix = np.array(moves[obj.name])
            triangles = triangles @ matrix[:3, :3].T + matrix[:3, 3]
        corners.append(triangles)
    corners = np.concatenate(corners) if corners else np.zeros((0, 3, 3))
    if not len(corners):
        return 0.0
    tree = BVHTree.FromPolygons([Vector(c) for c in corners.reshape(-1, 3)],
                                [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(corners))])
    points = corners.reshape(-1, 3)
    centre = Vector(((points.min(0) + points.max(0)) / 2).tolist())
    radius = float(np.linalg.norm(points.max(0) - points.min(0))) / 2
    directions = [Vector(d) for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))]
    directions += [Vector((x, y, z)).normalized() for x in (1, -1) for y in (1, -1) for z in (1, -1)]
    offsets = np.linspace(-radius, radius, resolution)
    hits = backs = 0
    for direction in directions:
        u = direction.orthogonal().normalized()
        v = direction.cross(u)
        start = centre - direction * 2 * radius
        for x in offsets:
            for y in offsets:
                location, normal, _index, _distance = tree.ray_cast(start + u * x + v * y, direction, 4 * radius)
                if location is not None:
                    hits += 1
                    backs += normal.dot(direction) > 0
    return round(backs / max(hits, 1), 4)


def _attach(obj, mesh, kind, pivot):
    """A child object of obj for the mesh, with obj's materials, its origin at pivot and its kind recorded."""
    import bpy
    from mathutils import Matrix
    for material in obj.data.materials:
        mesh.materials.append(material)
    child = bpy.data.objects.new(mesh.name, mesh)
    for collection in obj.users_collection:
        collection.objects.link(child)
    child.parent = obj
    child.matrix_parent_inverse = Matrix.Identity(4)
    mesh.transform(Matrix.Translation(-pivot))
    mesh.update()
    child.location = pivot
    child["slopforge_part"] = kind
    return child


def _side(point, centre, normal):
    """Signed distance of a point (or a face's centre) from the plane."""
    from mathutils import Vector
    point = point if isinstance(point, Vector) else point.calc_center_median() if hasattr(point, "calc_center_median") else Vector(point)
    return (point - Vector(centre)).dot(Vector(normal))


def _seam_plane(seam, size, tolerance=0.05):
    """The plane that fits the seam's vertices, as (point, normal), when they lie within tolerance of the seam's own
    extent from it (RMS); None when the seam is not flat. A live pistol slide's seam fitted within 1% of its extent;
    its trigger's, a small curved loop, only within 9%, and bisecting it left openings the caps could not close, so a
    hinge like that keeps its ragged cut (2026-10-24)."""
    import numpy as np
    vertices = list({vertex for edge in seam for vertex in edge.verts})
    if len(vertices) < 3:
        return None
    points = np.array([vertex.co for vertex in vertices])
    centre = points.mean(0)
    normal = np.linalg.eigh((points - centre).T @ (points - centre))[1][:, 0]
    extent = float((points.max(0) - points.min(0)).max())
    rms = float(np.sqrt((((points - centre) @ normal) ** 2).mean()))
    print(f"Seam of {len(vertices)} vertices: extent {extent:.4f}, off-plane RMS {rms:.4f}"
          f"{'' if rms <= tolerance * extent else ', not flat: cut as masked'}")
    if rms > tolerance * extent:
        return None
    return centre, normal


def _barrel_mesh(bm, slide, plane, name, radius_share=0.3):
    """A cylinder along the weapon's length (-Y forward) in the slide's cavity, as a mesh named <name>_barrel: a
    slide drawn back then shows a barrel rather than the frame's cut face. It runs between the slide's ends, half
    way up the slide's height above the cut plane, with radius radius_share of that height, and takes the body's
    cap colour. It becomes its own static child: a real barrel is a separate part, and a floating cylinder inside
    the body would count as a stray piece."""
    import bpy
    import numpy as np
    coordinates = np.array([vertex.co for vertex in slide.verts])
    if not len(coordinates):
        return None
    centre, normal = plane
    normal = np.array(normal) * np.sign(((coordinates - centre) @ normal).mean() or 1.0)  # towards the slide
    height = float(((coordinates - centre) @ normal).max())
    if height <= 0:
        return None
    axis = centre + normal * height / 2
    low, high = coordinates.min(0), coordinates.max(0)
    radius = radius_share * height
    print(f"Barrel for {name}: height {height:.4f}, radius {radius:.4f}, axis {np.round(axis, 4).tolist()}")
    uv = bm.loops.layers.uv.active
    cap_uv = next((loop[uv].uv.copy() for face in bm.faces if not face.smooth for loop in face.loops), None) if uv else None
    barrel = bmesh.new()
    barrel_uv = barrel.loops.layers.uv.new(uv.name) if uv else None  # the body's layer name, which the material maps
    ring = 24
    angles = np.linspace(0, 2 * np.pi, ring, endpoint=False)
    # Set back one radius from the slide's front: a muzzle's crown is recessed, and a flush barrel poked through.
    front = [barrel.verts.new((axis[0] + radius * np.cos(t), low[1] + radius, axis[2] + radius * np.sin(t))) for t in angles]
    back = [barrel.verts.new((axis[0] + radius * np.cos(t), high[1], axis[2] + radius * np.sin(t))) for t in angles]
    sides = [barrel.faces.new((front[i], front[(i + 1) % ring], back[(i + 1) % ring], back[i])) for i in range(ring)]
    ends = bmesh.ops.triangulate(barrel, faces=[barrel.faces.new(front[::-1]), barrel.faces.new(back)])["faces"]
    bmesh.ops.recalc_face_normals(barrel, faces=sides + ends)
    for face in sides + ends:
        face.smooth = face not in ends
        if cap_uv is not None:
            for loop in face.loops:
                loop[barrel_uv].uv = cap_uv
    mesh = bpy.data.meshes.new(f"{name}_barrel")
    barrel.to_mesh(mesh)
    barrel.free()
    return mesh


def _face_pieces(faces):
    """Connected pieces of a set of faces (joined over shared edges), largest first."""
    remaining, pieces = set(faces), []
    while remaining:
        stack, piece = [remaining.pop()], set()
        while stack:
            face = stack.pop()
            piece.add(face)
            for edge in face.edges:
                for other in edge.link_faces:
                    if other in remaining:
                        remaining.remove(other)
                        stack.append(other)
        pieces.append(piece)
    return sorted(pieces, key=len, reverse=True)


def _cap_cut(bm, basecolor=None):
    """Close the openings a cut left (boundary edges between cut vertices) with flat triangulated caps."""
    cut = bm.verts.layers.int["slopforge_cut"]
    edges = [edge for edge in bm.edges if edge.is_boundary and all(vertex[cut] for vertex in edge.verts)]
    if not edges:
        return []
    before = set(bm.faces)
    bmesh.ops.holes_fill(bm, edges=edges, sides=0)
    # A loop that is not a simple cycle (a vertex the plane grazed joins two loops) is left open by holes_fill; a
    # triangle fill closes those too (a live pistol's bisected slide left 104 edges open, 2026-10-24).
    left = [edge for edge in edges if edge.is_valid and edge.is_boundary]
    if left:
        bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=left)
    caps = [face for face in bm.faces if face not in before]
    caps = bmesh.ops.triangulate(bm, faces=caps)["faces"]
    left = sum(edge.is_valid and edge.is_boundary for edge in edges)
    if left:
        print(f"Cut left {left} open edges that the caps could not close")
    uv = bm.loops.layers.uv.active
    if uv is not None and caps:
        cap_set = set(caps)
        for cap in _face_pieces(caps):  # each opening takes its own texel
            loops = [loop for face in cap for vertex in face.verts for loop in vertex.link_loops
                     if loop.face not in cap_set]
            source = _typical_texel(loops, uv, basecolor)
            for face in cap:
                for loop in face.loops:
                    loop[uv].uv = source
    for face in caps:
        face.smooth = False
    return caps


_PIXELS = {}


def _typical_texel(loops, uv, basecolor):
    """The UV among the loops whose base colour is nearest their median colour; the first loop without an image."""
    if basecolor is None or not loops:
        return loops[0][uv].uv.copy()
    import numpy as np
    width, height = basecolor.size
    if basecolor.name not in _PIXELS:  # read once: a 4096 map is 200 MB of floats
        pixels = np.empty(width * height * basecolor.channels, np.float32)
        basecolor.pixels.foreach_get(pixels)
        _PIXELS[basecolor.name] = pixels.reshape(height, width, basecolor.channels)[..., :3]
    coordinates = np.array([[loop[uv].uv.x, loop[uv].uv.y] for loop in loops]) % 1.0
    columns = np.clip((coordinates[:, 0] * width).astype(int), 0, width - 1)
    rows = np.clip((coordinates[:, 1] * height).astype(int), 0, height - 1)
    colours = _PIXELS[basecolor.name][rows, columns]
    nearest = int(np.argmin(np.abs(colours - np.median(colours, 0)).sum(1)))
    return loops[nearest][uv].uv.copy()


def _boundary_groups(bm):
    """The openings of a mesh: its boundary edges grouped by connectivity through shared vertices."""
    edges = {edge for edge in bm.edges if len(edge.link_faces) == 1}
    groups = []
    while edges:
        seed = edges.pop()
        group, stack = [seed], [seed]
        while stack:
            for vertex in stack.pop().verts:
                for other in vertex.link_edges:
                    if other in edges:
                        edges.discard(other)
                        group.append(other)
                        stack.append(other)
        groups.append(group)
    return groups


def _convex_hull_2d(points):
    """Indices of the 2D points on their convex hull, counter-clockwise (Andrew's monotone chain)."""
    order = sorted(range(len(points)), key=lambda i: (points[i][0], points[i][1]))
    cross = lambda o, a, b: ((points[a][0] - points[o][0]) * (points[b][1] - points[o][1])
                             - (points[a][1] - points[o][1]) * (points[b][0] - points[o][0]))
    lower, upper = [], []
    for i in order:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], i) <= 0:
            lower.pop()
        lower.append(i)
    for i in reversed(order):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], i) <= 0:
            upper.pop()
        upper.append(i)
    return lower[:-1] + upper[:-1]


def _opening_plane(group, centroid):
    """The plane most of an opening's rim lies in (RANSAC on rim length: a rim that dips into the surface's tubes,
    a pistol's bore, is an outlier), its normal away from `centroid` (the piece). Returns (middle, normal, u, v,
    the in-plane rim points as (u, v) coordinates, the opening's size)."""
    import numpy as np
    from mathutils import Vector
    starts = np.array([tuple(edge.verts[0].co) for edge in group])
    ends = np.array([tuple(edge.verts[1].co) for edge in group])
    points, weights = (starts + ends) / 2, np.linalg.norm(ends - starts, axis=1) + 1e-12
    extent = float(np.ptp(np.concatenate([starts, ends]), 0).max())
    rng = np.random.default_rng(0)
    best, tolerance = None, 0.015 * extent
    for _ in range(300 if len(points) >= 3 else 0):  # a sliver of one or two edges: all its points are in plane
        a, b, c = points[rng.choice(len(points), 3, replace=False, p=weights / weights.sum())]
        normal = np.cross(b - a, c - a)
        if np.linalg.norm(normal) < 1e-12:
            continue
        normal /= np.linalg.norm(normal)
        inliers = np.abs((points - a) @ normal) < tolerance
        score = weights[inliers].sum()
        if best is None or score > best[0]:
            best = (score, inliers)
    inliers = best[1] if best is not None else np.ones(len(points), bool)
    chosen = np.concatenate([starts[inliers], ends[inliers]])
    middle = chosen.mean(0)
    _, _, axes = np.linalg.svd(chosen - middle, full_matrices=False)
    normal = Vector(axes[2])
    if normal.dot(Vector(middle) - centroid) < 0:
        normal = -normal  # away from the piece
    u, v = axes[0], axes[1]
    return Vector(middle), normal, Vector(u), Vector(v), [((p - middle) @ u, (p - middle) @ v) for p in chosen], extent


def _inset_polygon(polygon, distance):
    """A convex counter-clockwise polygon with every edge moved `distance` inwards."""
    import numpy as np
    points = [np.array(p, float) for p in polygon]
    lines = []
    for a, b in zip(points, points[1:] + points[:1]):
        direction = (b - a) / max(np.linalg.norm(b - a), 1e-12)
        inward = np.array([-direction[1], direction[0]])  # left of a counter-clockwise edge is inside
        lines.append((a + inward * distance, direction))
    out = []
    for (p1, d1), (p2, d2) in zip(lines[-1:] + lines[:-1], lines):
        cross = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(cross) < 1e-9:
            out.append(p2)
            continue
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cross
        out.append(p1 + d1 * t)
    return out


def hollow_opening(bm, group, wall=0.04, depth=0.85, basecolor=None):
    """A container's opening under its lid as a cavity a player sees into when the lid opens: a rim `wall` thick
    (a share of the opening's size) at the opening's plane, inner walls down `depth` of the container's height
    below that plane, and a floor; one texel of the rim's median colour. Not stitched to the surface, like a cap.
    Returns the faces."""
    import numpy as np
    from mathutils import Vector
    uv = bm.loops.layers.uv.active
    ring = [loop for edge in group if edge.link_faces for loop in edge.link_faces[0].loops]
    texel = _typical_texel(ring, uv, basecolor) if uv is not None and ring else None
    centroid = sum((vertex.co for vertex in bm.verts), Vector()) / max(len(bm.verts), 1)
    middle, normal, u, v, flat, extent = _opening_plane(group, centroid)
    hull = _convex_hull_2d(flat)
    if len(hull) < 3:
        return []
    outer = [np.array(flat[i], float) for i in hull]
    inner = _inset_polygon(outer, wall * extent)
    height = max(0.0, max(-(vertex.co - middle).dot(normal) for vertex in bm.verts))
    top = middle - normal * 0.002 * extent
    bottom = middle - normal * depth * height
    place = lambda base, point: base + u * float(point[0]) + v * float(point[1])
    outer_top = [bm.verts.new(place(top, p)) for p in outer]
    inner_top = [bm.verts.new(place(top, p)) for p in inner]
    inner_bottom = [bm.verts.new(place(bottom, p)) for p in inner]
    centre = place(middle, np.mean(inner, axis=0))
    faces, count = [], len(outer)
    for i in range(count):
        j = (i + 1) % count
        rim = bm.faces.new((outer_top[i], outer_top[j], inner_top[j], inner_top[i]))
        rim.normal_update()
        if rim.normal.dot(normal) < 0:
            rim.normal_flip()
        side = bm.faces.new((inner_top[i], inner_top[j], inner_bottom[j], inner_bottom[i]))
        side.normal_update()
        if side.normal.dot(centre - side.calc_center_median()) < 0:
            side.normal_flip()  # inner walls face into the cavity
        faces.extend((rim, side))
    floor = bm.faces.new(inner_bottom)
    floor.normal_update()
    if floor.normal.dot(normal) < 0:
        floor.normal_flip()
    faces.append(floor)
    faces = bmesh.ops.triangulate(bm, faces=faces)["faces"]
    for face in faces:
        face.smooth = False
        if texel is not None:
            for loop in face.loops:
                loop[uv].uv = texel
    return faces


def _container_opening(bm, group, lids):
    """Whether an opening is a container's under a lid: its middle lies in a hinged part's bounds (`lids`, each
    (low, high) widened by 5%) and its outline covers at least half of the piece's own outline in that plane (a
    chest's top; a trigger's slot in a frame is a small share of it)."""
    import numpy as np
    from mathutils import Vector
    if not lids or len(group) < 3:
        return False
    centroid = sum((vertex.co for vertex in bm.verts), Vector()) / max(len(bm.verts), 1)
    middle, normal, u, v, flat, extent = _opening_plane(group, centroid)
    inside = False
    for low, high in lids:
        pad = 0.05 * max(high[i] - low[i] for i in range(3))
        if all(low[i] - pad <= middle[i] <= high[i] + pad for i in range(3)):
            inside = True
    if not inside:
        return False

    def area(points):
        hull = _convex_hull_2d(points)
        return 0.5 * abs(sum(points[a][0] * points[b][1] - points[b][0] * points[a][1]
                             for a, b in zip(hull, hull[1:] + hull[:1])))
    piece = [((vertex.co - middle).dot(u), (vertex.co - middle).dot(v)) for vertex in bm.verts]
    return area(flat) >= 0.5 * area(piece)


def solid_component_count(mesh):
    """Connected pieces of a mesh (vertices joined by position, as glTF splits them along seams) that are not made
    only of fill faces (slopforge_fill: caps and cavities closing a hybrid split's openings, not stitched to the
    surface by design)."""
    attribute = mesh.attributes.get("slopforge_fill")
    fill = [0] * len(mesh.polygons)
    if attribute is not None:
        attribute.data.foreach_get("value", fill)
    parent = {}

    def find(item):
        while parent.setdefault(item, item) != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item
    keys = [tuple(round(c, 7) for c in vertex.co) for vertex in mesh.vertices]
    for polygon in mesh.polygons:
        first = find(keys[polygon.vertices[0]])
        for index in polygon.vertices[1:]:
            other = find(keys[index])
            if other != first:
                parent[other] = first
    solid = {find(keys[polygon.vertices[0]]) for polygon, value in zip(mesh.polygons, fill) if not value}
    return len(solid)


# ---------------------------------------------------------------------------
# Closing hybrid pieces: the interface between a part's region of the solid and the rest
# ---------------------------------------------------------------------------

MAX_GRID_CELLS = 2_500_000
INTERFACE_CELLS = 240  # grid cells along the object's longest side; at 100 the rim stood off the cut and a moved
# pistol showed 1.8% of its pixels as holes, at 240 0.4% (2026-10-25)


def _grow(mask):
    """A boolean grid grown by one cell along each axis."""
    import numpy as np
    out = mask.copy()
    for axis in range(3):
        for shift in (1, -1):
            moved = np.roll(mask, shift, axis)
            edge = [slice(None)] * 3
            edge[axis] = 0 if shift == 1 else -1
            moved[tuple(edge)] = False
            out |= moved
    return out


def solid_grid(bm, cells=INTERFACE_CELLS):
    """The solid a surface encloses, on a grid of `cells` along its longest side: (occupied, low corner, cell size).
    Walls are the cells that scanlines along two of the three axes find inside by parity; the solid is everything the
    outside cannot reach through them, the walls thickened a cell so small holes do not leak. TRELLIS.2 makes thin
    hollow shells (an inner wall a few millimetres inside the outer one): their hollow is solid here."""
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    verts = [vertex.co.copy() for vertex in bm.verts]
    bm.verts.index_update()
    tree = BVHTree.FromPolygons(verts, [[vertex.index for vertex in face.verts] for face in bm.faces])
    points = np.array([tuple(v) for v in verts])
    extent = np.ptp(points, 0)
    # at most MAX_GRID_CELLS: a boxy chest at 240 cells along its width is 8 million cells, a pistol 2 million
    size = max(float(extent.max()) / cells, float(np.prod(extent + 1e-9) / MAX_GRID_CELLS) ** (1 / 3))
    low = points.min(0) - 2 * size
    shape = np.ceil((points.max(0) + 2 * size - low) / size).astype(int)
    centres = [low[axis] + (np.arange(shape[axis]) + 0.5) * size for axis in range(3)]
    votes = np.zeros(shape, np.int8)
    for axis in range(3):
        a, b = [other for other in range(3) if other != axis]
        inside = np.zeros(shape, bool)
        direction = Vector([1.0 if other == axis else 0.0 for other in range(3)])
        for j, ca in enumerate(centres[a]):
            for k, cb in enumerate(centres[b]):
                start = [0.0, 0.0, 0.0]
                start[axis], start[a], start[b] = low[axis] - size, ca, cb
                origin, hits = Vector(start), []
                for _ in range(64):
                    location = tree.ray_cast(origin, direction)[0]
                    if location is None:
                        break
                    hits.append(location[axis])
                    origin = location + direction * 1e-6
                for first in range(0, len(hits) - 1, 2):
                    i0 = int(np.ceil((hits[first] - low[axis]) / size - 0.5))
                    i1 = int(np.floor((hits[first + 1] - low[axis]) / size - 0.5))
                    if i1 >= i0:
                        index = [slice(None)] * 3
                        index[axis], index[a], index[b] = slice(i0, i1 + 1), j, k
                        inside[tuple(index)] = True
        votes += inside
    walls = _grow(votes >= 2)
    outside = np.zeros(shape, bool)
    outside[0] = outside[-1] = outside[:, 0] = outside[:, -1] = outside[:, :, 0] = outside[:, :, -1] = True
    outside &= ~walls
    while True:
        grown = _grow(outside) & ~walls
        if grown.sum() == outside.sum():
            break
        outside = grown
    return ~outside, low, size


def surface_nets(field, low, size):
    """The zero set of a grid field (NaN where undefined; cell centres at low + (index + 0.5) * size) as vertices
    and quads, each quad facing towards +field (naive surface nets: a vertex per cell the sign changes in, at the
    mean of its edges' crossings, and a quad around each grid edge it changes along)."""
    import numpy as np
    finite = np.isfinite(field)
    values = np.where(finite, field, 0.0)
    corners = [(dx, dy, dz) for dx in (0, 1) for dy in (0, 1) for dz in (0, 1)]
    nx, ny, nz = field.shape
    corner = np.stack([values[dx:nx - 1 + dx, dy:ny - 1 + dy, dz:nz - 1 + dz] for dx, dy, dz in corners], -1)
    defined = np.stack([finite[dx:nx - 1 + dx, dy:ny - 1 + dy, dz:nz - 1 + dz] for dx, dy, dz in corners], -1).all(-1)
    positive = corner > 0
    active = defined & positive.any(-1) & (~positive).any(-1)
    total = np.zeros(active.shape + (3,))
    count = np.zeros(active.shape)
    for p in range(8):
        for q in range(p + 1, 8):
            if sum(abs(np.subtract(corners[p], corners[q]))) != 1:
                continue
            fp, fq = corner[..., p], corner[..., q]
            crossing = (fp > 0) != (fq > 0)
            t = np.where(crossing, fp / np.where(crossing, fp - fq, 1), 0)
            point = np.array(corners[p], float) + t[..., None] * np.subtract(corners[q], corners[p])
            total += np.where(crossing[..., None], point, 0)
            count += crossing
    cells = np.argwhere(active)
    index = -np.ones(active.shape, int)
    index[tuple(cells.T)] = np.arange(len(cells))
    vertices = low + (cells + 0.5 + total[tuple(cells.T)] / np.maximum(count[tuple(cells.T)], 1)[:, None]) * size
    quads = []
    for axis, (a, b) in ((0, (1, 2)), (1, (2, 0)), (2, (0, 1))):
        first, second = [slice(None)] * 3, [slice(None)] * 3
        first[axis], second[axis] = slice(0, field.shape[axis] - 1), slice(1, field.shape[axis])
        f0, f1 = field[tuple(first)], field[tuple(second)]
        changes = np.isfinite(f0) & np.isfinite(f1) & ((f0 > 0) != (f1 > 0))
        for edge in np.argwhere(changes):
            ring = []
            for da, db in ((-1, -1), (0, -1), (0, 0), (-1, 0)):
                cell = list(edge)
                cell[a] += da
                cell[b] += db
                if min(cell) < 0 or any(cell[x] >= index.shape[x] for x in range(3)) or index[tuple(cell)] < 0:
                    ring = None
                    break
                ring.append(int(index[tuple(cell)]))
            if ring is None:
                continue
            if f0[tuple(edge)] > 0:  # +field lies back along the axis: the quad faces the other way
                ring.reverse()
            quads.append(ring)
    return vertices, quads


def _rim(polygons):
    """The vertices on a polygon soup's open edges."""
    uses = {}
    for polygon in polygons:
        for u, w in zip(polygon, list(polygon[1:]) + [polygon[0]]):
            key = (min(u, w), max(u, w))
            uses[key] = uses.get(key, 0) + 1
    return {vertex for key, used in uses.items() if used == 1 for vertex in key}


def _decimate(vertices, polygons, target):
    """A polygon soup collapse-decimated to about `target` triangles: (vertices, triangles)."""
    import bpy
    import numpy as np
    mesh = bpy.data.meshes.new("_interface")
    mesh.from_pydata([tuple(v) for v in vertices], [], [tuple(polygon) for polygon in polygons])
    mesh.update()
    obj = bpy.data.objects.new("_interface", mesh)
    bpy.context.scene.collection.objects.link(obj)
    modifier = obj.modifiers.new("decimate", "DECIMATE")
    modifier.decimate_type = "COLLAPSE"
    modifier.ratio = min(1.0, target / max(sum(len(polygon) - 2 for polygon in polygons), 1))
    modifier.use_collapse_triangulate = True
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    reduced = evaluated.to_mesh()
    out = (np.array([tuple(v.co) for v in reduced.vertices]).reshape(-1, 3),
           [list(polygon.vertices) for polygon in reduced.polygons])
    evaluated.to_mesh_clear()
    bpy.data.objects.remove(obj)
    bpy.data.meshes.remove(mesh)
    return out


def part_interface(bm, layer, part_id, solid, target=None, band=0.1):
    """The surface that closes a part cut from a generated surface, and the rest where it was cut from: inside the
    solid (solid_grid), where a point is as far from the part's faces as from the rest's, counting only faces within
    `band` of the object's size from the cut, so the surface carries the cut across instead of sagging towards
    distant walls; facing away from the part, collapse-decimated to about `target` triangles, its rim snapped onto
    the cut. A hybrid split's cut zigzags and crosses itself; no fill in a plane closed it, and a moved pistol showed
    holes on 3.6% of its pixels against 0.4% with this surface (2026-10-25). Returns (vertices, polygons)."""
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree
    occupied, low, size = solid
    samples = []
    for edge in bm.edges:
        if len({face[layer] == part_id for face in edge.link_faces}) == 2:
            a, b = edge.verts[0].co, edge.verts[1].co
            steps = max(1, int((b - a).length / (size / 4)))
            samples.extend(a.lerp(b, step / steps) for step in range(steps + 1))
    if not samples:
        return np.zeros((0, 3)), []
    kd = KDTree(len(samples))
    for index, point in enumerate(samples):
        kd.insert(point, index)
    kd.balance()
    reach = band * size * max(occupied.shape)
    bm.verts.index_update()
    verts = [vertex.co.copy() for vertex in bm.verts]
    near = [face for face in bm.faces if kd.find(face.calc_center_median())[2] <= reach]
    part = [[vertex.index for vertex in face.verts] for face in near if face[layer] == part_id]
    rest = [[vertex.index for vertex in face.verts] for face in near if face[layer] != part_id]
    if not part or not rest:
        return np.zeros((0, 3)), []
    tree_part, tree_rest = BVHTree.FromPolygons(verts, part), BVHTree.FromPolygons(verts, rest)
    points = np.array([tuple(point) for point in samples])
    first = np.clip(np.floor((points.min(0) - reach - low) / size).astype(int), 0, None)
    last = np.minimum(np.ceil((points.max(0) + reach - low) / size).astype(int), occupied.shape)
    box = occupied[first[0]:last[0], first[1]:last[1], first[2]:last[2]]
    field = np.full(box.shape, np.nan)
    value = lambda cell: (tree_part.find_nearest(Vector(low + (np.asarray(cell) + first + 0.5) * size))[3]
                          - tree_rest.find_nearest(Vector(low + (np.asarray(cell) + first + 0.5) * size))[3])
    # Coarse to fine: the field is a difference of two distances, so it changes by at most twice the distance moved;
    # a cell whose coarse neighbour reads more than that from zero is far from the surface and not measured.
    step = 4
    coarse = {tuple(cell): value(cell) for cell in np.argwhere(box) if not (cell % step).any()}
    reach_cells = 2 * np.sqrt(3) * step + 2
    near = np.zeros(box.shape, bool)
    for cell, measured in coarse.items():
        if abs(measured) <= reach_cells * size:
            lo_cell = np.maximum(np.array(cell) - step, 0)
            hi_cell = np.minimum(np.array(cell) + step + 1, box.shape)
            near[lo_cell[0]:hi_cell[0], lo_cell[1]:hi_cell[1], lo_cell[2]:hi_cell[2]] = True
    for i, j, k in np.argwhere(box & near):
        field[i, j, k] = coarse.get((i, j, k)) if (i, j, k) in coarse else value((i, j, k))
    vertices, polygons = surface_nets(field, low + first * size, size)
    if not polygons:
        return vertices, polygons
    if target:
        vertices, polygons = _decimate(vertices, polygons, target)
    for vertex in _rim(polygons):
        location, _index, distance = kd.find(Vector(vertices[vertex]))
        if distance < 2.5 * size:
            vertices[vertex] = tuple(location)
    return vertices, polygons


def add_interface(bm, vertices, polygons, flip=False, texel=None):
    """Add an interface (part_interface) to a piece: flipped for the rest's side, triangulated, smooth, marked
    slopforge_fill (not stitched to the surface, so not a piece of its own for the component budget), every loop
    on one texel. Returns the faces."""
    from mathutils import Vector
    marker = bm.faces.layers.int.get("slopforge_fill") or bm.faces.layers.int.new("slopforge_fill")
    uv = bm.loops.layers.uv.active
    new = [bm.verts.new(Vector(tuple(v))) for v in vertices]
    faces = []
    for polygon in polygons:
        ring = [new[index] for index in (reversed(polygon) if flip else polygon)]
        if len(ring) >= 3 and len(set(ring)) == len(ring):
            try:
                faces.append(bm.faces.new(ring))
            except ValueError:  # the same corners twice after the rim's snapping
                pass
    used = {vertex for face in faces for vertex in face.verts}
    bmesh.ops.delete(bm, geom=[vertex for vertex in new if vertex not in used], context="VERTS")
    faces = bmesh.ops.triangulate(bm, faces=faces)["faces"] if faces else []
    for face in faces:
        face.smooth = True
        face[marker] = 1
        if uv is not None and texel is not None:
            for loop in face.loops:
                loop[uv].uv = texel
    return faces


def _cut_texel(bm, layer, part_id, side, basecolor):
    """The texel for an interface: the typical colour of the faces along the cut on one side (the part's, or the
    rest's when `side` is False)."""
    uv = bm.loops.layers.uv.active
    if uv is None:
        return None
    loops = [loop for edge in bm.edges if len({face[layer] == part_id for face in edge.link_faces}) == 2
             for face in edge.link_faces if (face[layer] == part_id) == side for loop in face.loops]
    return _typical_texel(loops, uv, basecolor) if loops else None


# ---------------------------------------------------------------------------
# Moving parts generated as separate meshes (OmniPart): tag by node name, separate after the join
# ---------------------------------------------------------------------------

def gltf_name(obj):
    """The glTF node name an imported object was made from: Blender appends .001 to a clashing name."""
    import re
    return re.sub(r"\.\d{3}$", "", obj.name)


def tag_parts(objects, table):
    """A FACE int attribute `slopforge_part` on every object: its part's id from the table (0 when unknown), so the
    parts survive the final pass's join and are separated again after orientation (separate_tagged)."""
    for obj in objects:
        attribute = obj.data.attributes.get("slopforge_part") or obj.data.attributes.new("slopforge_part", "INT", "FACE")
        value = int(table.get(gltf_name(obj), {}).get("id", 0))
        attribute.data.foreach_set("value", [value] * len(obj.data.polygons))


def separate_tagged(obj, table, contact, anchors=None, close=False, basecolor=None, face_budget=None):
    """Move each hinge or slide's tagged faces into a child of obj (see _attach). A slide pivots at its box centre;
    a hinge at the centroid of its vertices within `contact` of the rest of the weapon, or at its box centre when
    it touches nothing; a hinge with an anchor (faces of its own bounds: front -Y, back +Y, left -X, right +X,
    bottom -Z, top +Z) pivots on that edge of its box, each face after the first measured along the edge before it. With close (hybrid parts: pieces of one generated surface),
    each part and the body are closed where they were cut apart by the interface between them (part_interface),
    the faces left under `face_budget` shared between the parts by the length of their cuts; an opening under a
    hinged part that is a container's (a chest's top) becomes a cavity instead (hollow_opening). Returns the
    children."""
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    layer = bm.faces.layers.int.get("slopforge_part")
    if layer is None:
        bm.free()
        return []
    # The GLB split its vertices along UV seams; welded, each part is closed again and its seam edges are not open.
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=max(obj.dimensions) * 1e-6)
    # Generated parts are hard-surface: an edge over 30 degrees stays sharp instead of shading as a gradient.
    # Only after the weld do faces share edges, so the angle can be measured here and not before.
    import math
    for edge in bm.edges:
        if len(edge.link_faces) == 2 and edge.calc_face_angle(0.0) > math.radians(30):
            edge.smooth = False
    # Every part but the body becomes a child, static ones too (a grip, a slide's rear): the body stays one piece
    # for the component budget, and the moving parts get their pivots.
    parts = {entry["id"]: (name, entry["kind"]) for name, entry in table.items() if entry["kind"] != "body"}
    moving = {part_id for part_id, (_name, kind) in parts.items() if kind in ("hinge", "slide")}
    # Distance to the rest of the weapon's surface, not its vertices: a trigger under a flat underside has no
    # body vertex near it.
    rest = bm.copy()
    rest_layer = rest.faces.layers.int.get("slopforge_part")
    bmesh.ops.delete(rest, geom=[face for face in rest.faces if face[rest_layer] in moving], context="FACES")
    tree = BVHTree.FromBMesh(rest)
    rest.free()
    interfaces, texels = {}, {}
    if close:
        bm.faces.layers.int.get("slopforge_fill") or bm.faces.layers.int.new("slopforge_fill")
        solid = solid_grid(bm)
        cut_edges = {part_id: {edge for edge in bm.edges
                               if len({face[layer] == part_id for face in edge.link_faces}) == 2} for part_id in parts}
        cuts = {part_id: sum(edge.calc_length() for edge in edges) for part_id, edges in cut_edges.items()}
        # each interface is added twice, to its part and (flipped) to the body; about four triangles per edge of its
        # cut is enough to keep its rim on the cut (a pistol's slide: 1,500 for 365 edges, holes on 0.4% of a moved
        # view's pixels; 800, 1.6%)
        spare = max(0, int(0.98 * face_budget) - len(bm.faces)) if face_budget else None
        for part_id in parts:
            target = (max(200, min(4 * len(cut_edges[part_id]),
                                   int(spare / 2 * cuts[part_id] / max(sum(cuts.values()), 1e-12))))
                      if spare is not None else None)
            interfaces[part_id] = part_interface(bm, layer, part_id, solid, target=target)
            texels[part_id] = (_cut_texel(bm, layer, part_id, True, basecolor),
                               _cut_texel(bm, layer, part_id, False, basecolor))
    children = []
    for part_id, (name, kind) in parts.items():
        faces = [face for face in bm.faces if face[layer] == part_id]
        if not faces:
            print(f"Part {name} ({kind}): no faces were generated for it")
            continue
        verts = {vert for face in faces for vert in face.verts}
        low = Vector([min(vert.co[axis] for vert in verts) for axis in range(3)])
        high = Vector([max(vert.co[axis] for vert in verts) for axis in range(3)])
        pivot = (low + high) / 2
        if kind == "hinge" and (anchors or {}).get(name):
            bound_of = {"front": (1, min), "back": (1, max), "left": (0, min), "right": (0, max),
                        "bottom": (2, min), "top": (2, max)}
            # each face after the first is measured along the edge the ones before it name: back-bottom is the bottom
            # of the lid's back edge, not below a latch at its front (OPEN3: a pivot 8 cm under the seam swung the lid
            # up off the chest, 2026-10-26)
            edge = list(verts)
            for word in anchors[name]:
                axis, extreme = bound_of[word]
                pivot[axis] = extreme(vert.co[axis] for vert in edge)
                edge = [vert for vert in edge if abs(vert.co[axis] - pivot[axis]) <= 0.1 * (high[axis] - low[axis])]
        elif kind == "hinge":
            touching = [vert.co for vert in verts
                        if tree.find_nearest(vert.co)[3] is not None and tree.find_nearest(vert.co)[3] <= contact]
            if touching:
                pivot = sum(touching, Vector()) / len(touching)
        piece = bm.copy()
        piece_layer = piece.faces.layers.int.get("slopforge_part")
        bmesh.ops.delete(piece, geom=[face for face in piece.faces if face[piece_layer] != part_id], context="FACES")
        if close:
            closed = add_interface(piece, *interfaces[part_id], texel=texels[part_id][0])
            print(f"Part {name} ({kind}): closed by {len(closed)} interface faces")
        # The join left the imported part's mesh as an orphan under this name; the child takes the exact name
        for block in (bpy.data.meshes, bpy.data.objects):
            taken = block.get(name)
            if taken is not None and taken.users == 0:
                block.remove(taken)
        mesh = bpy.data.meshes.new(name)
        piece.to_mesh(mesh)
        piece.free()
        child = _attach(obj, mesh, kind, pivot)
        child.name = mesh.name = name
        children.append(child)
        bmesh.ops.delete(bm, geom=faces, context="FACES")
    if close and children:
        ids = {name: part_id for part_id, (name, _kind) in parts.items()}
        lids = {}
        for child in children:
            if child.get("slopforge_part") == "hinge":
                corners = [child.location + vertex.co for vertex in child.data.vertices]  # the body's frame
                lids[ids[child.name]] = ([min(c[i] for c in corners) for i in range(3)],
                                         [max(c[i] for c in corners) for i in range(3)])
        marker = bm.faces.layers.int["slopforge_fill"]
        containers, cavity = set(), 0
        for group in _boundary_groups(bm):
            # a container's opening is its own lid's cut: a pistol's trigger cut touches the slide's, and the opening
            # along both, its middle in the trigger's bounds, became a cavity hanging under the pistol (2026-10-25)
            under = [part_id for part_id, bounds in lids.items()
                     if sum(edge in cut_edges[part_id] for edge in group) >= 0.5 * len(group)
                     and _container_opening(bm, group, [bounds])]
            if under:
                containers.update(under)
                for face in hollow_opening(bm, group, basecolor=basecolor):
                    face[marker] = 1
                    cavity += 1
        closed = sum(len(add_interface(bm, *interfaces[part_id], flip=True, texel=texels[part_id][1]))
                     for part_id in interfaces if part_id not in containers)
        print(f"Body: closed by {closed} interface faces and a {cavity}-face cavity")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return children
