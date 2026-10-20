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
