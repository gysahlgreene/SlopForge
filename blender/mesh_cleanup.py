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
