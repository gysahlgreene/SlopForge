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


def repair_manifold_locally(mesh, merge_distance, rounds=6):
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
                else:
                    bmesh.ops.triangle_fill(bm, edges=list(loop), use_beauty=True, use_dissolve=False)
            except ValueError:
                pass  # face exists already or the loop is degenerate; the next round removes it

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
