"""Join a body that ends in a neck stump and a separately built head into one figure on one material. The stump is cut
down to fit the head.

Usage: blender --background --python join_character_parts.py -- request.json

Request: {"body": glb, "head": glb, "height": metres, "collar_share": the body's share of the height, "skull_share": the skull's width as a share of it, "maps": {"base", "normal", "rough",
"metal"}, "output": glb, "report": json}. The maps are the sheet character_parts.py composed: the body in the bottom
left two thirds, the head in the top right third. On one body the texture stage gave the head 1.9% of the sheet.
"""
import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from bpy_extras import mesh_utils
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mesh_cleanup import unwrap_without_folds

HEAD_FACES = 15000
FACE_SHEET_SCALE = 2.2  # how much wider a face's islands are drawn on the sheet than the rest of the head
NAPE_RISE = 0.045  # how much higher a stump is cut at the nape than under the chin, as a share of the figure's height. Level left a gap beside the jaw; 0.07 left stump wall standing beside it


def load(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [item for item in bpy.data.objects if item not in before]
    mesh = max((item for item in new if item.type == "MESH"), key=lambda item: len(item.data.polygons))
    bpy.context.view_layer.update()
    world = mesh.matrix_world.copy()
    for item in new:
        if item is not mesh:
            bpy.data.objects.remove(item)
    mesh.parent = None
    mesh.matrix_world = world
    return mesh


def points(mesh):
    world = np.array(mesh.matrix_world)
    return np.array([v.co for v in mesh.data.vertices]) @ world[:3, :3].T + world[:3, 3]


def select(mesh):
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = mesh


def apply_transform(mesh):
    select(mesh)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def scale_by(mesh, factor):
    mesh.scale = [value * factor for value in mesh.scale]
    bpy.context.view_layer.update()


def neck_height(found):
    """The narrowest height in a head model's lower part. Below it the model flares into a bust, which pokes out above a
    collar with a ragged edge, so a head is cut just under this."""
    low, high = found[:, 2].min(), found[:, 2].max()
    heights = np.linspace(low + 0.03 * (high - low), low + 0.45 * (high - low), 30)
    step = heights[1] - heights[0]
    # Across and front to back: a bust flares forwards first, and cutting there left a blade under the chin.
    def section(z):
        band = found[np.abs(found[:, 2] - z) < step]
        return np.ptp(band[:, 0]) * np.ptp(band[:, 1]) if len(band) else np.inf

    return float(heights[int(np.argmin([section(z) for z in heights]))])


def skull_width(found, neck):
    """A head model's width the way head_measures takes a concept's: the median across the rows just under the crown. The widest point
    above the neck counted a scarf's tail and loose hair as skull, and shrank the head."""
    top = found[:, 2].max()
    rows = np.linspace(top - 0.77 * (top - neck), top - 0.23 * (top - neck), 16)
    step = rows[1] - rows[0]
    bands = [found[np.abs(found[:, 2] - row) < step, 0] for row in rows]
    return float(np.median([np.ptp(band) for band in bands if len(band)]))


def smooth_surface(item, passes):
    """Takes the generator's small lumps out of a surface and keeps its size (Taubin smoothing, which doesn't shrink it). Lit, those lumps read
    as a chewed coat with bitten buttons, and cast the marks on its back, whatever the paint did. A glTF's vertices are split along UV seams,
    so neighbours are found by position, and a seam stays closed."""
    data = item.data
    found = np.zeros(len(data.vertices) * 3)
    data.vertices.foreach_get("co", found)
    found = found.reshape(-1, 3)
    grain = np.ptp(found, axis=0).max() / 200000
    places, first, place = np.unique(np.round(found / grain).astype(np.int64), axis=0, return_index=True, return_inverse=True)
    place = place.ravel()
    ends = np.zeros(len(data.edges) * 2, np.int64)
    data.edges.foreach_get("vertices", ends)
    pairs = place[ends.reshape(-1, 2)]
    pairs = np.unique(np.sort(pairs[pairs[:, 0] != pairs[:, 1]], axis=1), axis=0)
    neighbours = np.bincount(pairs.ravel(), minlength=len(places))[:, None]
    now = found[first]
    for _ in range(passes):
        for step in (0.5, -0.53):
            total = np.zeros_like(now)
            np.add.at(total, pairs[:, 0], now[pairs[:, 1]])
            np.add.at(total, pairs[:, 1], now[pairs[:, 0]])
            now = now + step * np.where(neighbours > 0, total / np.maximum(neighbours, 1) - now, 0)
    data.vertices.foreach_set("co", now[place].ravel())
    # A glTF import stores its normals, so the lumps would stay in the lighting after they'd left the shape.
    with bpy.context.temp_override(object=item, active_object=item, selected_objects=[item]):
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    data.shade_smooth()
    data.update()


def place_on_stump(body, head, height, collar_share, skull_share):
    """The body to its share of the height, and the head to the concept's size with its crown at the top and its neck over
    the stump. The stump's own height says nothing about the head: an edit leaves it far above where the chin was."""
    top = height * collar_share
    scale_by(body, top / np.ptp(points(body)[:, 2]))
    found = points(body)
    body.location += Vector((-(found[:, 0].max() + found[:, 0].min()) / 2, 0, -found[:, 2].min()))
    bpy.context.view_layer.update()
    apply_transform(body)
    found = points(body)
    stump = found[found[:, 2] > top - 0.015 * height]
    centre = (stump[:, 0].max() + stump[:, 0].min()) / 2, (stump[:, 1].max() + stump[:, 1].min()) / 2
    raw = points(head)
    neck = neck_height(raw)
    scale = skull_share * height / skull_width(raw, neck)
    scale_by(head, scale)
    raw = points(head)
    neck = neck_height(raw)
    band = raw[np.abs(raw[:, 2] - neck) < 0.01 * height]
    head.location += Vector((centre[0] - (band[:, 0].max() + band[:, 0].min()) / 2, centre[1] - (band[:, 1].max() + band[:, 1].min()) / 2,
                             height - raw[:, 2].max()))
    bpy.context.view_layer.update()
    apply_transform(head)
    return {"body_top": round(float(top), 3), "head_scale": round(float(scale), 4), "seat": round(float(top), 3),
            "collar_centre": [round(float(value), 3) for value in centre],
            "stump": [float(centre[0]), float(centre[1]), float(np.ptp(stump[:, 0])) / 2, float(np.ptp(stump[:, 1])) / 2]}


def skin_like(colours, reference):
    """Which RGB rows have the reference skin's hue, in light or shadow: dark leather shares the hue, so it needs brightness too."""
    hue = lambda rgb: rgb / np.maximum(rgb.sum(-1, keepdims=True), 1e-6)
    return (np.linalg.norm(hue(colours) - hue(reference), axis=-1) < 0.06) & (colours.sum(-1) > 0.5 * reference.sum())


def cut_stump(body, cut_z, stump, sheet, rise):
    """Take a neck stump's skin off above a plane that starts at cut_z under the chin and rises by `rise` to the nape, as a neckline
    does. Hidden faces are gone from behind the stump, so a level cut left a gap beside the jaw that looked straight through the
    figure. Its colour finds it, because a stump flares and an outline measured at its top missed pieces. The cap fans from the
    cut's centre through its points in order round it, because the ring the skin leaves isn't always closed. Only the body's own
    sheet area is sampled, where the join composes it. Returns the cap's faces, the half width and depth of the cut, and its centre."""
    x, y, half_x, half_y = stump
    slope = rise / max(2 * half_y, 1e-3)
    front = y - half_y  # the concept's camera is at -Y
    over = lambda point: point.z - cut_z - slope * (point.y - front)
    image = bpy.data.images.load(str(sheet))
    width, height = image.size
    pixels = np.zeros(width * height * 4, np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)[..., :3]
    near = lambda point: ((point.x - x) / (half_x * 1.6)) ** 2 + ((point.y - y) / (half_y * 1.6)) ** 2 < 1
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    layer = bm.loops.layers.uv.active

    def colour(face):
        uv = np.mean([np.array(loop[layer].uv) for loop in face.loops], 0) * 2 / 3
        return pixels[min(int(uv[1] * height), height - 1), min(int(uv[0] * width), width - 1)]

    top = max(vert.co.z for vert in bm.verts)
    crown = [colour(face) for face in bm.faces if face.calc_center_median().z > top - 0.01 and near(face.calc_center_median())]
    reference = np.median(crown, 0) if crown else np.array((0.7, 0.5, 0.4))
    skin = lambda face: near(face.calc_center_median()) and skin_like(colour(face)[None], reference)[0]
    spanning = [face for face in bm.faces if over(face.calc_center_median()) > -0.02 and skin(face)]
    edges = list({edge for face in spanning for edge in face.edges})
    verts = list({vert for face in spanning for vert in face.verts})
    bmesh.ops.bisect_plane(bm, geom=verts + edges + spanning, plane_co=(x, front, cut_z), plane_no=(0, -slope, 1))
    bm.faces.ensure_lookup_table()
    above = [face for face in bm.faces if over(face.calc_center_median()) > 0 and skin(face)]
    bmesh.ops.delete(bm, geom=above, context="FACES")
    ring = [vert for vert in bm.verts if abs(over(vert.co)) < 2e-4 and vert.link_loops and near(vert.co)]
    caps = 0
    extent = (0.0, 0.0)
    centre = (x, y)
    if len(ring) > 2:
        points_x, points_y = [vert.co.x for vert in ring], [vert.co.y for vert in ring]
        centre = ((max(points_x) + min(points_x)) / 2, (max(points_y) + min(points_y)) / 2)
        extent = ((max(points_x) - min(points_x)) / 2, (max(points_y) - min(points_y)) / 2)
        order = sorted(ring, key=lambda vert: np.arctan2(vert.co.y - centre[1], vert.co.x - centre[0]))
        # One texel for the whole cap, the ring's median. Ring points can sit on different UV islands, and a triangle spanning two sampled
        # the sheet between them: dark slivers under the chin. One per triangle made a dark ring point a dark tooth at the nape.
        texel = lambda vert: vert.link_loops[0][layer].uv.copy()
        shade = lambda vert: pixels[min(int(texel(vert)[1] * 2 / 3 * height), height - 1), min(int(texel(vert)[0] * 2 / 3 * width), width - 1)].sum()
        skin_uv = texel(sorted(ring, key=shade)[len(ring) // 2])
        middle = bm.verts.new((centre[0], centre[1], cut_z + slope * (centre[1] - front)))
        for first, second in zip(order, order[1:] + order[:1]):
            face = bm.faces.new((middle, first, second))
            face.smooth = True
            face.normal_update()
            if face.normal.z < 0:
                face.normal_flip()
            for loop in face.loops:
                loop[layer].uv = skin_uv
            caps += 1
    bm.to_mesh(body.data)
    bm.free()
    body.data.update()
    bpy.data.images.remove(image)
    return caps, extent, centre


def widen_neck(head, cut_z, extent, centre, height):
    """A head's neck out to the stump it joins, full at the cut and fading out by the jaw, or a gap shows beside it above the collar. Never
    narrowed here: hair at this height reads as neck, and narrowing it pinched a jaw. Returns the larger widening."""
    found = points(head)
    band = found[np.abs(found[:, 2] - cut_z) < 0.015 * height]
    if not len(band) or not extent[0]:
        return 1.0
    grow = np.clip([extent[0] / max(np.ptp(band[:, 0]) / 2, 1e-6), extent[1] / max(np.ptp(band[:, 1]) / 2, 1e-6)], 1.0, 1.6)
    fade = np.clip((cut_z + 0.06 * height - found[:, 2]) / (0.06 * height), 0, 1)
    for axis, middle in enumerate(centre):
        found[:, axis] = middle + (found[:, axis] - middle) * (1 + (grow[axis] - 1) * fade)
    set_points(head, found)
    return float(grow.max())


def tuck_neck(head, cut_z, stump, plane, top, height):
    """Bring what is under the stump's sloping cut inside the stump's own outline (centre x and y, half width and depth), so a head's neck
    goes into its collar. A neck runs wider and deeper than a stump, and its cut edge hung outside the collar. It fades out from the level
    of the cut to just above the stump's top, because pulling rows in at one height stretched teeth to the row above. `plane` is the
    cut's slope and front y. A jaw above the plane and hair far outside the stump are left alone."""
    found = points(head)
    reach = np.hypot((found[:, 0] - stump[0]) / stump[2], (found[:, 1] - stump[1]) / stump[3])
    high = top + 0.015 * height
    level = np.clip((high - found[:, 2]) / max(high - cut_z, 1e-6), 0, 1)
    below = np.clip((cut_z + plane[0] * (found[:, 1] - plane[1]) - found[:, 2]) / (0.015 * height), 0, 1)
    weight = level * level * (3 - 2 * level) * below * ((found[:, 2] < cut_z) | (reach < 2.0))
    scale = 1 + (np.minimum(1, 0.92 / np.maximum(reach, 1e-6)) - 1) * weight
    middle = np.array(stump[:2])
    found[:, :2] = middle + (found[:, :2] - middle) * scale[:, None]
    set_points(head, found)


def set_points(item, found):
    inverse = np.linalg.inv(np.array(item.matrix_world))
    local = found @ inverse[:3, :3].T + inverse[:3, 3]
    item.data.vertices.foreach_set("co", local.ravel())
    item.data.update()


def trim_head(head, cut_z):
    # A GLB splits vertices along UV seams, so weld first or every seam reads as an open edge.
    bm = bmesh.new()
    bm.from_mesh(head.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    # Cut across the triangles: deleting whole ones leaves a torn edge, which shows above an open collar.
    bmesh.ops.bisect_plane(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces), plane_co=(0, 0, cut_z), plane_no=(0, 0, 1), clear_inner=True)
    open_edges = sum(len(e.link_faces) != 2 for e in bm.edges)  # left open: filling the edge made a blade, and the collar hides it
    bm.to_mesh(head.data)
    bm.free()
    head.data.update()
    if len(head.data.polygons) > HEAD_FACES:
        # A plain reduction spends triangles where the surface is busiest: one man's goggles and cap kept 9,400 of 15,000 and his smooth
        # face went from 4,667 to 1,009, a low-poly mannequin. In this modifier a lower weight holds on harder: 0 never reduces at all
        # and starved the cap, and 0.9 kept 44% on a face that got 7% without it.
        band = face_band(head)
        free = head.vertex_groups.new(name="free_to_reduce")
        found = points(head)
        inside = np.array([in_face_band(point, band) for point in found])
        free.add(np.where(~inside)[0].tolist(), 1.0, "REPLACE")
        free.add(np.where(inside)[0].tolist(), 0.9, "REPLACE")
        reduce = head.modifiers.new("reduce", "DECIMATE")
        reduce.ratio = HEAD_FACES / len(head.data.polygons)
        reduce.vertex_group = free.name
        select(head)
        bpy.ops.object.modifier_apply(modifier=reduce.name)
        head.vertex_groups.remove(head.vertex_groups["free_to_reduce"])
    return open_edges


def face_band(head):
    """Where a head's face is: the front half of the model, from its lowest point to 62% of the way to its crown. Nothing here tells skin
    from a cap's rim, and it needn't: this only decides what keeps its detail. Returns the middle's y and the band's lowest and highest z."""
    found = points(head)
    low, high = found[:, 2].min(), found[:, 2].max()
    return float(np.median(found[:, 1])), float(low), float(low + 0.62 * (high - low))


def in_face_band(point, band):
    return point[1] < band[0] and band[1] <= point[2] <= band[2]


def on_face(head, polygon, band=None):
    return in_face_band(np.array(head.matrix_world @ polygon.center), band or face_band(head))


def uv_area(data, polygon):
    """The share of a sheet one face takes, on the active UV layer."""
    layer = data.uv_layers.active.data
    corners = np.array([layer[index].uv for index in polygon.loop_indices])
    return 0.5 * abs(np.dot(corners[:, 0], np.roll(corners[:, 1], 1)) - np.dot(corners[:, 1], np.roll(corners[:, 0], 1)))


def relay_head(head, base, normal, size, colour_space="sRGB"):
    """Unwrap a trimmed head again, with its face drawn larger, and bake its colour and normal maps onto the new layout. Its sheet was laid
    out in the 3D step, for a bust and shirt the join has since cut away, and thin shards take thousands of islands with a margin each:
    one face had 5% of its sheet. Returns the baked images, `size` square, and leaves the new layout as the head's only UV layer."""
    data = head.data
    old = data.uv_layers.active.name
    data.uv_layers.active = data.uv_layers.new(name="relaid")
    margin = 2 / size
    select(head)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    unwrap_without_folds([head], margin)
    band = face_band(head)
    layer = data.uv_layers.active.data
    for island in mesh_utils.mesh_linked_uv_islands(data):
        if sum(on_face(head, data.polygons[index], band) for index in island) * 2 < len(island):
            continue
        loops = [loop for index in island for loop in data.polygons[index].loop_indices]
        corners = np.array([layer[loop].uv for loop in loops])
        middle = corners.mean(0)
        for loop, corner in zip(loops, corners):
            layer[loop].uv = tuple(middle + (corner - middle) * FACE_SHEET_SCALE)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    # A margin fixed in texels: the default grows with each island, and thousands of scraps left a head's face 5% of its sheet, against 21%.
    bpy.ops.uv.pack_islands(rotate=True, margin=margin, margin_method="FRACTION", shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")

    kept = list(data.materials)
    material = bpy.data.materials.new("Relay")
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    coordinates = tree.nodes.new("ShaderNodeUVMap")
    coordinates.uv_map = old
    source = tree.nodes.new("ShaderNodeTexImage")
    tree.links.new(coordinates.outputs[0], source.inputs["Vector"])
    target = tree.nodes.new("ShaderNodeTexImage")
    tree.nodes.active = target
    for slot in range(len(data.materials) or 1):
        if slot < len(data.materials):
            data.materials[slot] = material
        else:
            data.materials.append(material)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    baked = {}

    def bake(key, path, space, kind, **options):
        source.image = bpy.data.images.load(str(path))
        source.image.colorspace_settings.name = space
        target.image = bpy.data.images.new(f"Relaid {key}", size, size, alpha=False)
        target.image.colorspace_settings.name = space
        select(head)
        bpy.ops.object.bake(type=kind, use_clear=True, margin=8, uv_layer="relaid", **options)
        baked[key] = target.image

    emission = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(source.outputs[0], emission.inputs["Color"])
    tree.links.new(emission.outputs[0], output.inputs["Surface"])
    bake("base", base, colour_space, "EMIT")
    shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
    bent = tree.nodes.new("ShaderNodeNormalMap")
    bent.uv_map = old
    tree.links.new(source.outputs[0], bent.inputs["Color"])
    tree.links.new(bent.outputs[0], shader.inputs["Normal"])
    tree.links.new(shader.outputs[0], output.inputs["Surface"])
    bake("normal", normal, "Non-Color", "NORMAL", normal_space="TANGENT")
    for slot, kept_material in enumerate(kept):
        data.materials[slot] = kept_material
    if not kept:
        data.materials.clear()
    bpy.data.materials.remove(material)
    data.uv_layers.remove(data.uv_layers[old])
    data.uv_layers["relaid"].name = old
    data.uv_layers.active = data.uv_layers[old]
    return baked


def paste_head(sheet, image):
    """A baked image into the head's corner of a sheet on disk, the top right third."""
    canvas = bpy.data.images.load(str(sheet))
    width, height = canvas.size
    pixels = np.zeros(width * height * 4, np.float32)
    canvas.pixels.foreach_get(pixels)
    pixels = pixels.reshape(height, width, 4)
    size = image.size[0]
    patch = np.zeros(size * size * 4, np.float32)
    image.pixels.foreach_get(patch)
    pixels[height - size:, width - size:] = patch.reshape(size, size, 4)
    canvas.pixels.foreach_set(pixels.ravel())
    canvas.save()
    bpy.data.images.remove(canvas)


def set_map(material, socket, path, colour_space):
    tree = material.node_tree
    shader = next(node for node in tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled")
    target = shader.inputs[socket]
    for link in list(target.links):
        tree.links.remove(link)
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = colour_space
    node = tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    if socket == "Normal":
        normal = tree.nodes.new("ShaderNodeNormalMap")
        tree.links.new(node.outputs[0], normal.inputs["Color"])
        tree.links.new(normal.outputs[0], target)
    else:
        tree.links.new(node.outputs[0], target)


def run(request):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    body, head = load(request["body"]), load(request["head"])
    if request.get("body_smooth"):
        smooth_surface(body, int(request["body_smooth"]))
    height = float(request["height"])
    placed = place_on_stump(body, head, height, float(request["collar_share"]), float(request["skull_share"]))
    # The head stays at its crown and the stump comes down to the neck's narrowest point, with the neck running on down inside it.
    stump_cut = neck_height(points(head)) + 0.006 * height
    cut = stump_cut - 0.02 * height
    open_edges = trim_head(head, cut)
    stump_rise = NAPE_RISE * height
    stump = placed.pop("stump")
    cap_faces, extent, centre = cut_stump(body, stump_cut, stump, request["maps"]["base"], stump_rise)
    widened = widen_neck(head, stump_cut, extent, centre, height)
    collar_top = float(points(body)[:, 2].max())
    tuck_neck(head, stump_cut, stump, (stump_rise / max(2 * stump[3], 1e-3), stump[1] - stump[3]), collar_top, height)
    if request.get("head_maps"):
        third = bpy.data.images.load(str(request["maps"]["base"])).size[0] // 3
        baked = relay_head(head, request["head_maps"]["base"], request["head_maps"]["normal"], third)
        paste_head(request["maps"]["base"], baked["base"])
        paste_head(request["maps"]["normal"], baked["normal"])
    body_faces, head_faces = len(body.data.polygons), len(head.data.polygons)

    select(head)
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    body.name = request.get("name", "character")
    uv = body.data.uv_layers.active
    for polygon in body.data.polygons:
        scale, offset = (2 / 3, 0.0) if polygon.material_index == 0 else (1 / 3, 2 / 3)
        for index in polygon.loop_indices:
            value = uv.data[index].uv
            uv.data[index].uv = (value.x * scale + offset, value.y * scale + offset)
        polygon.material_index = 0
    while len(body.data.materials) > 1:
        body.data.materials.pop(index=1)
    material = body.data.materials[0]
    material.name = body.name
    maps = request["maps"]
    set_map(material, "Base Color", maps["base"], "sRGB")
    set_map(material, "Roughness", maps["rough"], "Non-Color")
    set_map(material, "Metallic", maps["metal"], "Non-Color")
    set_map(material, "Normal", maps["normal"], "Non-Color")
    select(body)
    bpy.ops.export_scene.gltf(filepath=str(request["output"]), export_format="GLB", use_selection=True, export_tangents=False)
    found = points(body)
    Path(request["report"]).write_text(json.dumps({
        "status": "complete", **placed, "neck_cut": round(float(cut), 3), "height": round(float(found[:, 2].max()), 3), "body_faces": body_faces,
        "head_faces": head_faces, "head_open_edges": open_edges, "cap_faces": cap_faces,
        "stump_cut": round(stump_cut, 3), "stump_nape": round(stump_cut + stump_rise, 3), "collar_top": round(collar_top, 3),
        "neck_widened": round(widened, 3), "stump_half_width": round(float(extent[0]), 3)},
        indent=2) + "\n")


def main():
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(arguments) != 1:
        raise SystemExit("Usage: blender --background --python join_character_parts.py -- request.json")
    run(json.loads(Path(arguments[0]).read_text()))


if __name__ == "__main__":
    main()
