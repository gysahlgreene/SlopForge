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
    for _ in range(3):
        moved = False
        for side in (True, False):
            faces = [face for face in bm.faces if (face in part) == side]
            pieces = _face_pieces(faces)
            for piece in pieces[1:]:
                if any((other in part) != side for face in piece for edge in face.edges for other in edge.link_faces):
                    part = (part - piece) if side else (part | piece)
                    moved = True
        if not moved:
            break
    if len(part) < min_faces or len(part) == len(bm.faces):
        bm.free()
        return None
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
    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()
    mesh = bpy.data.meshes.new(name)
    piece.to_mesh(mesh)
    piece.free()
    for material in obj.data.materials:
        mesh.materials.append(material)
    child = bpy.data.objects.new(name, mesh)
    for collection in obj.users_collection:
        collection.objects.link(child)
    child.parent = obj
    child.matrix_parent_inverse = Matrix.Identity(4)
    if kind == "hinge":
        pivot = sum(cut, Vector()) / len(cut) if cut else Vector()
    else:
        low = Vector([min(vertex.co[axis] for vertex in mesh.vertices) for axis in range(3)])
        high = Vector([max(vertex.co[axis] for vertex in mesh.vertices) for axis in range(3)])
        pivot = (low + high) / 2
    mesh.transform(Matrix.Translation(-pivot))
    mesh.update()
    child.location = pivot
    child["slopforge_part"] = kind
    return child


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
    caps = [face for face in bm.faces if face not in before]
    caps = bmesh.ops.triangulate(bm, faces=caps)["faces"]
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
