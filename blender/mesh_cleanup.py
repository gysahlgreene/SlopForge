import bmesh


def remove_isolated_single_faces(mesh):
    """Drop detached one-face fragments while keeping multi-face islands."""
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
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
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


def sweep_penetration(part, others, axis, low, high, samples=9, limit=400):
    """The share of `part`'s vertices inside `others` at the worst of `samples` points of its declared range, over
    the share at rest: a lid turned into its chest, a drawer through its housing. The part turns about its origin
    (its pivot) or slides along its axis; a point is inside when rays along two of three axes cross a mesh an odd
    number of times (generated meshes have holes, so one ray's parity lies). Unity repeats the check on the prefab."""
    import math
    import bpy
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree
    depsgraph = bpy.context.evaluated_depsgraph_get()
    trees = [BVHTree.FromObject(other, depsgraph) for other in others if other.type == "MESH"]
    step = max(1, len(part.data.vertices) // limit)
    rest = [part.matrix_world @ vertex.co for index, vertex in enumerate(part.data.vertices) if index % step == 0]
    if not trees or not rest:
        return 0.0

    def inside(point):
        for tree in trees:
            odd = 0
            for direction in (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))):
                hits, origin = 0, point.copy()
                for _ in range(64):
                    location = tree.ray_cast(origin, direction)[0]
                    if location is None:
                        break
                    hits += 1
                    origin = location + direction * 1e-5
                odd += hits % 2
            if odd >= 2:
                return True
        return False

    pivot = part.matrix_world.translation.copy()
    rest_share = sum(inside(point) for point in rest) / len(rest)
    far = low if abs(low) > abs(high) else high  # the range runs from rest to its far end
    worst = 0.0
    for sample in range(1, samples + 1):
        amount = far * sample / samples
        if part.get("slopforge_part") == "slide":
            move = Matrix.Translation(Vector(SLIDE_AXES[axis]) * amount)
        else:
            direction, sign = HINGE_AXES[axis]
            move = (Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(sign * amount), 4, Vector(direction))
                    @ Matrix.Translation(-pivot))
        share = sum(inside(move @ point) for point in rest) / len(rest)
        worst = max(worst, share - rest_share)
    return round(worst, 4)


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


def _simple_cycles(group):
    """An opening that touches itself (a figure of eight) as simple cycles: a cycle basis of its edge graph."""
    adjacency = {}
    for edge in group:
        a, b = edge.verts
        adjacency.setdefault(a, []).append((b, edge))
        adjacency.setdefault(b, []).append((a, edge))
    cycles, done = [], set()
    for root in adjacency:
        if root in done:
            continue
        parent, depth, stack, used = {root: (None, None)}, {root: 0}, [root], set()
        while stack:
            vertex = stack.pop()
            done.add(vertex)
            for other, edge in adjacency[vertex]:
                if other not in parent:
                    parent[other], depth[other] = (vertex, edge), depth[vertex] + 1
                    stack.append(other)
                elif edge is not parent[vertex][1] and edge not in used and depth[other] <= depth[vertex]:
                    used.add(edge)
                    left, right, cycle = vertex, other, [edge]
                    while left is not right:
                        if depth[left] >= depth[right]:
                            left, step = parent[left]
                        else:
                            right, step = parent[right]
                        cycle.append(step)
                    cycles.append(cycle)
    return cycles or [group]


def _bridge_chain(bm, group):
    """An opening that is a chain, not a loop, closed into a loop: where a cut crossed an edge with three faces (the
    generated surface's own non-manifold edges), that edge keeps two faces and is not a boundary edge, so the
    opening has loose ends (2026-10-25 pistol). Ends are paired nearest first and joined by the edge between them,
    or by a new edge when they are within a tenth of the opening's size. Returns (edges, bridges)."""
    degree = {}
    for edge in group:
        for vertex in edge.verts:
            degree[vertex] = degree.get(vertex, 0) + 1
    ends = [vertex for vertex, count in degree.items() if count % 2]
    if not ends:
        return list(group), set()
    points = [vertex.co for edge in group for vertex in edge.verts]
    low = [min(point[axis] for point in points) for axis in range(3)]
    high = [max(point[axis] for point in points) for axis in range(3)]
    limit = 0.1 * sum((h - l) ** 2 for l, h in zip(low, high)) ** 0.5
    bridges = set()
    while len(ends) >= 2:
        vertex = ends.pop()
        other = min(ends, key=lambda candidate: (candidate.co - vertex.co).length)
        ends.remove(other)
        shared = next((edge for edge in vertex.link_edges if edge.other_vert(vertex) is other), None)
        if shared is None:
            if (other.co - vertex.co).length > limit:
                continue
            shared = bm.edges.new((vertex, other))
        bridges.add(shared)
    return list(group) + list(bridges), bridges


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


def _cap_opening(bm, group, centroid):
    """A flat cap across an opening's convex outline in its plane (_opening_plane), recessed a little into the
    piece and facing away from it; not stitched to the rim, so the surface's topology around the opening does not
    matter. For an opening no fill could close: a rim that runs into a pistol's bore (2026-10-25). Returns faces."""
    import numpy as np
    middle, normal, u, v, flat, extent = _opening_plane(group, centroid)
    hull = _convex_hull_2d(flat)
    if len(hull) < 3:
        return []
    centre = np.mean([flat[i] for i in hull], axis=0)
    shrink = 0.015 * extent  # the outline a little inside the rim, so the cap's edge cannot show through the sheet
    outline = []
    for i in hull:
        offset = np.array(flat[i]) - centre
        length = np.linalg.norm(offset)
        outline.append(centre + offset * max(length - shrink, 0) / max(length, 1e-12))
    base = middle - normal * 0.005 * extent  # a little inside the piece: no flicker against its neighbour
    verts = [bm.verts.new(base + u * x + v * y) for x, y in outline]
    face = bm.faces.new(verts)
    face.normal_update()
    if face.normal.dot(normal) < 0:
        face.normal_flip()
    return bmesh.ops.triangulate(bm, faces=[face])["faces"]


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


def inside_test(bm):
    """A point-in-object test for a mesh as it is now (the unsplit surface): rays along two of the three axes
    crossing it an odd number of times (a generated surface has holes, so one ray's parity lies)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    tree = BVHTree.FromBMesh(bm)
    directions = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))

    def inside(point):
        odd = 0
        for direction in directions:
            hits, origin = 0, point.copy()
            for _ in range(64):
                location = tree.ray_cast(origin, direction)[0]
                if location is None:
                    break
                hits += 1
                origin = location + direction * 1e-6
            odd += hits % 2
        return odd >= 2
    return inside


def close_openings(bm, basecolor=None, lids=None, inside=None):
    """Close every opening of a piece split from a generated surface (docs/WEAPONS.md, Hybrid parts): each opening
    is filled flat in its best-fit plane (a triangle fill; the hole filler takes a loop that is not simple), the
    fill wound so its rim runs against the surface beside it (outwards), and textured with one texel, its ring's
    median colour: a mating surface such as a slide's underside. An opening under a hinged part (`lids`: their
    bounds) that covers most of the piece's outline is a container's and becomes a cavity (hollow_opening).
    Returns the fills."""
    import numpy as np
    from mathutils import Vector
    # the layer first: adding a layer once fills exist leaves their Python references dead
    marker = bm.faces.layers.int.get("slopforge_fill") or bm.faces.layers.int.new("slopforge_fill")
    uv = bm.loops.layers.uv.active
    fills = []
    capped = set()
    cycles = []
    for group in _boundary_groups(bm):
        if _container_opening(bm, group, lids):
            # a container's top under its lid: a cavity to look into, not a panel at the rim
            fills.extend(hollow_opening(bm, group, basecolor=basecolor))
            capped.update(fills)
            continue
        edges, bridges = _bridge_chain(bm, group)
        cycles.extend((cycle, bridges) for cycle in _simple_cycles(edges))
    for group, bridges in cycles:
        group = [edge for edge in group if edge.is_valid and (len(edge.link_faces) == 1 or edge in bridges)]
        if len(group) < 3:
            continue
        points = np.array([tuple(vertex.co) for edge in group for vertex in edge.verts])
        normal = Vector(np.linalg.svd(points - points.mean(0), full_matrices=False)[2][2])
        ring = [loop for edge in group if edge.link_faces for loop in edge.link_faces[0].loops]  # a new bridge has none
        texel = _typical_texel(ring, uv, basecolor) if uv is not None and ring else None
        before = set(bm.faces)
        bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=group, normal=normal)
        left = [edge for edge in group if edge.is_valid and len(edge.link_faces) == 1]
        if left and not [face for face in bm.faces if face not in before]:
            bmesh.ops.holes_fill(bm, edges=left, sides=0)
        new = [face for face in bm.faces if face not in before]
        if any(edge.is_valid and len(edge.link_faces) == 1 for edge in group):
            # neither fill closed it: drop what they made and cap the opening across its outline
            bmesh.ops.delete(bm, geom=[face for face in new if face.is_valid], context="FACES_ONLY")
            centroid = sum((vertex.co for vertex in bm.verts), Vector()) / max(len(bm.verts), 1)
            new = _cap_opening(bm, [edge for edge in group if edge.is_valid], centroid)
            capped.update(new)
        if not new:
            continue
        new = bmesh.ops.triangulate(bm, faces=new)["faces"]
        for face in new:
            face.smooth = False
            if texel is not None:
                for loop in face.loops:
                    loop[uv].uv = texel
        fills.extend(new)
    fill_set = set(fills)
    for piece in _face_pieces([face for face in fills if face not in capped]):  # caps face away from the piece already
        piece = list(piece)
        bmesh.ops.recalc_face_normals(bm, faces=piece)
        vote = 0
        for face in piece:
            for loop in face.loops:
                for twin in loop.edge.link_faces:
                    if twin is not face and twin not in fill_set:
                        twin_loop = next(other for other in twin.loops if other.edge is loop.edge)
                        vote += 1 if twin_loop.vert is loop.vert else -1
        if vote > 0:
            for face in piece:
                face.normal_flip()
    for face in fills:
        if face.is_valid:
            face[marker] = 1  # inspection leaves a piece made only of fills out of the component count
    if inside is not None:
        # a fill must lie inside the unsplit object: one outside it would show with nothing moved (a cap whose
        # outline overshot a concave opening stood up behind the 2026-10-25 chest's lid)
        outside = []
        for face in fills:
            if not face.is_valid:
                continue
            centre = face.calc_center_median()
            probes = [centre] + [centre + (vertex.co - centre) * 0.75 for vertex in face.verts]
            if not all(inside(point) for point in probes):
                outside.append(face)
        bmesh.ops.delete(bm, geom=outside, context="FACES_ONLY")
        fills = [face for face in fills if face.is_valid]
    return fills


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


def separate_tagged(obj, table, contact, anchors=None, close=False, basecolor=None):
    """Move each hinge or slide's tagged faces into a child of obj (see _attach). A slide pivots at its box centre;
    a hinge at the centroid of its vertices within `contact` of the rest of the weapon, or at its box centre when
    it touches nothing; a hinge with an anchor (faces of its own bounds: front -Y, back +Y, left -X, right +X,
    bottom -Z, top +Z) pivots on that edge of its box. With close (hybrid parts: pieces of one generated surface),
    every opening the separation leaves, on each part and on the body, is closed (close_openings). Returns the
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
    whole = inside_test(bm) if close else None  # the unsplit object: a fill outside it is dropped
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
            bound_of = {"front": (1, low), "back": (1, high), "left": (0, low), "right": (0, high),
                        "bottom": (2, low), "top": (2, high)}
            for word in anchors[name]:
                axis, bound = bound_of[word]
                pivot[axis] = bound[axis]
        elif kind == "hinge":
            touching = [vert.co for vert in verts
                        if tree.find_nearest(vert.co)[3] is not None and tree.find_nearest(vert.co)[3] <= contact]
            if touching:
                pivot = sum(touching, Vector()) / len(touching)
        piece = bm.copy()
        piece_layer = piece.faces.layers.int.get("slopforge_part")
        bmesh.ops.delete(piece, geom=[face for face in piece.faces if face[piece_layer] != part_id], context="FACES")
        if close:
            print(f"Part {name} ({kind}): closed {len(close_openings(piece, basecolor, inside=whole))} faces of openings")
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
        lids = []
        for child in children:
            if child.get("slopforge_part") == "hinge":
                corners = [child.location + vertex.co for vertex in child.data.vertices]  # the body's frame
                lids.append(([min(c[i] for c in corners) for i in range(3)], [max(c[i] for c in corners) for i in range(3)]))
        print(f"Body: closed {len(close_openings(bm, basecolor, lids=lids, inside=whole))} faces of openings")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return children
