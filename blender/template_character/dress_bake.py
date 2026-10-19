"""Dress an MPFB template character in the look of a generated character.

Usage: blender --background --python dress_bake.py -- '<json>'
  template: dressed MPFB .blend (make_human.py), generated_rig: SkinTokens rig.fbx of the same concept,
  garments: library garment object names, textures: output folder, output: .blend,
  solver_python/solver: a Python with numpy+scipy running processing/template_nearest_solve.py,
  optional: mode "island_median", tints, saturation, grime, min_roughness, source_bones, tuck, recolor.

The template's limbs are posed onto the generated character only for the transfer, then returned to
MPFB's clean rest pose. Geometry, UVs, rig and fabric detail come from the library garments; colour
comes from the generated outfit (nearest-surface lookup), as one median colour per garment UV island
(mode island_median) so the generated texture's baked highlights and blotches are not copied.
"""
import bpy, sys, json, bmesh
import numpy as np
from mathutils import Matrix, Vector

a = json.loads(sys.argv[sys.argv.index("--") + 1])
bpy.ops.wm.open_mainfile(filepath=a["template"])
rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
body = bpy.data.objects["Human"]
parts = [o for o in bpy.data.objects if o.type == "MESH"]
garments = [bpy.data.objects[n] for n in a["garments"]]

before = set(bpy.data.objects)
bpy.ops.import_scene.fbx(filepath=a["generated_rig"])
imported = [o for o in bpy.data.objects if o not in before]
gen_rig = next(o for o in imported if o.type == "ARMATURE")
outfit = next(o for o in imported if o.type == "MESH")
G = {b.name: gen_rig.matrix_world @ b.head_local for b in gen_rig.data.bones}
T = {b.name: rig.matrix_world @ b.head_local for b in rig.data.bones}
scale = (T["neck_01"] - T["pelvis"]).length / (G["Neck"] - G["Hips"]).length
to_template = Matrix.Translation(T["pelvis"] - G["Hips"] * scale) @ Matrix.Diagonal((scale, scale, scale, 1))
outfit.parent = None
for m in list(outfit.modifiers):
    outfit.modifiers.remove(m)
outfit.matrix_world = to_template @ outfit.matrix_world
G = {k: to_template @ v for k, v in G.items()}
bpy.context.view_layer.update()

# Pose the template limbs onto the generated character: joint directions, then segment centroids.
gnames = {g.index: g.name for g in outfit.vertex_groups}
target = {}
for v in outfit.data.vertices:
    ws = [(g.weight, gnames[g.group]) for g in v.groups]
    if ws and max(ws)[0] > 0.6:
        c = target.setdefault(max(ws)[1], [Vector(), 0]); c[0] += outfit.matrix_world @ v.co; c[1] += 1
target = {n: c[0] / c[1] for n, c in target.items()}
masks = [m for m in body.modifiers if m.type == "MASK"]
for m in masks:
    m.show_viewport = False
def body_centroid(group):
    gi = body.vertex_groups[group].index
    ev = body.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    pts = [body.matrix_world @ ev.vertices[v.index].co for v in body.data.vertices
           if any(g.group == gi and g.weight > 0.6 for g in v.groups)]
    body.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
    return sum(pts, Vector()) / len(pts)
segments = [("upperarm_l", "lowerarm_l", "LeftUpperArm", "LeftLowerArm"), ("lowerarm_l", "hand_l", "LeftLowerArm", "LeftHand"),
            ("upperarm_r", "lowerarm_r", "RightUpperArm", "RightLowerArm"), ("lowerarm_r", "hand_r", "RightLowerArm", "RightHand"),
            ("thigh_l", "calf_l", "LeftUpperLeg", "LeftLowerLeg"), ("calf_l", "foot_l", "LeftLowerLeg", "LeftFoot"),
            ("thigh_r", "calf_r", "RightUpperLeg", "RightLowerLeg"), ("calf_r", "foot_r", "RightLowerLeg", "RightFoot")]
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="POSE")
def turn(bone, wanted_from, wanted_to):
    pose = rig.pose.bones[bone]; world = rig.matrix_world @ pose.matrix; head = world.translation
    r = wanted_from.rotation_difference(wanted_to).to_matrix().to_4x4()
    pose.matrix = rig.matrix_world.inverted() @ (Matrix.Translation(head) @ r @ Matrix.Translation(-head) @ world)
    bpy.context.view_layer.update()
for bone, child, gb, gc in segments:
    head = (rig.matrix_world @ rig.pose.bones[bone].matrix).translation
    turn(bone, (rig.matrix_world @ rig.pose.bones[child].matrix).translation - head, G[gc] - G[gb])
for _ in range(2):
    for bone, _, gb, _ in segments:
        if gb in target:
            head = (rig.matrix_world @ rig.pose.bones[bone].matrix).translation
            turn(bone, body_centroid(bone) - head, target[gb] - head)
bpy.ops.object.mode_set(mode="OBJECT")
for m in masks:
    m.show_viewport = True
# The fitted pose exists only for the bake (Cycles bakes the posed, evaluated meshes); the character
# keeps MPFB's clean rest pose and proportions afterwards.
bpy.context.view_layer.update()

# Bake source: the generated outfit without its head and hands.
neck_cut = G["Neck"].z + 0.35 * (G["Head"].z - G["Neck"].z)
drop = []
for v in outfit.data.vertices:
    ws = [(g.weight, gnames[g.group]) for g in v.groups]
    top = max(ws)[1] if ws else ""
    if top.startswith(("LeftHand", "RightHand", "LeftFinger", "RightFinger")) or (outfit.matrix_world @ v.co).z > neck_cut:
        drop.append(v.index)
mesh = bmesh.new(); mesh.from_mesh(outfit.data); mesh.verts.ensure_lookup_table()
bmesh.ops.delete(mesh, geom=[mesh.verts[i] for i in drop], context="VERTS"); mesh.to_mesh(outfit.data); mesh.free()
bpy.data.objects.remove(gen_rig, do_unlink=True)

source_material = outfit.data.materials[0]
src_tree = source_material.node_tree
src_bsdf = next(n for n in src_tree.nodes if n.type == "BSDF_PRINCIPLED")

scene = bpy.context.scene
scene.render.engine = "CYCLES"; scene.cycles.samples = 1
bake = scene.render.bake
# Only self-bakes (positions, island ids): colour transfer is a nearest-surface lookup, not ray casting,
# which smeared texture at grazing angles.
bake.use_selected_to_active = False

def pixels(image):
    p = np.empty(image.size[0] * image.size[1] * 4, np.float32); image.pixels.foreach_get(p)
    return p.reshape(image.size[1], image.size[0], 4)

outfit_mesh = outfit.data
outfit_mesh.calc_loop_triangles()
src_world = [outfit.matrix_world @ v.co for v in outfit_mesh.vertices]
tris = list(outfit_mesh.loop_triangles)
src_uv = outfit_mesh.uv_layers.active.data
# Dense source samples (about 1 mm apart) with their UVs, for nearest lookups outside Blender.
rng = np.random.default_rng(0)
tri_v = np.array([t.vertices[:] for t in tris]); tri_l = np.array([t.loops[:] for t in tris])
V = np.array([p[:] for p in src_world]); UVL = np.array([src_uv[i].uv[:] for i in range(len(src_uv))])
area = 0.5 * np.linalg.norm(np.cross(V[tri_v[:, 1]] - V[tri_v[:, 0]], V[tri_v[:, 2]] - V[tri_v[:, 0]]), axis=1)
counts = np.maximum(1, (area / 1e-6).astype(int))
owner = np.repeat(np.arange(len(tris)), counts)
r1, r2 = rng.random(len(owner)), rng.random(len(owner)); flip = r1 + r2 > 1; r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
w = np.stack([1 - r1 - r2, r1, r2], 1)
vertex_bone = []
for v in outfit_mesh.vertices:
    ws = [(g.weight, gnames.get(g.group, "")) for g in v.groups]
    vertex_bone.append(max(ws)[1] if ws else "")
SAMPLE_BONES = np.array([vertex_bone[i] for i in tri_v[owner, 0]])
SAMPLES = (V[tri_v[owner]] * w[..., None]).sum(1)
SAMPLE_UVS = (UVL[tri_l[owner]] * w[..., None]).sum(1)
print("SAMPLES", len(SAMPLES))
def linked_image(socket):
    if not socket.is_linked: return None
    node = socket.links[0].from_node
    while node.type != "TEX_IMAGE" and node.inputs and any(i.is_linked for i in node.inputs):
        node = next(i for i in node.inputs if i.is_linked).links[0].from_node
    return node.image if node.type == "TEX_IMAGE" else None
src_color = pixels(linked_image(src_bsdf.inputs["Base Color"]))
rough_image = linked_image(src_bsdf.inputs["Roughness"])
src_rough = pixels(rough_image) if rough_image else None
rough_channel = 1 if rough_image and rough_image.colorspace_settings.name and "metallic" in rough_image.name.lower() else 0

def nearest_transfer(garment, tree, holder, size):
    """Per texel: garment surface position -> nearest generated-outfit point -> its texture colour."""
    positions = bpy.data.images.new(f"{garment.name}_pos", size, size, alpha=True, float_buffer=True)
    positions.generated_color = (0, 0, 0, 0)
    emission = tree.nodes.new("ShaderNodeEmission"); geometry = tree.nodes.new("ShaderNodeNewGeometry")
    out = next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"); old = out.inputs["Surface"].links[0].from_socket
    tree.links.new(geometry.outputs["Position"], emission.inputs[0]); tree.links.new(emission.outputs[0], out.inputs["Surface"])
    holder.image = positions
    for o in bpy.data.objects: o.select_set(False)
    garment.select_set(True); bpy.context.view_layer.objects.active = garment
    bpy.ops.object.bake(type="EMIT", margin=2)
    tree.links.new(old, out.inputs["Surface"])
    P = pixels(positions)
    used = np.argwhere(P[..., 3] > 0.5)
    import subprocess, tempfile, os
    work = tempfile.mkdtemp()
    bones = a.get("source_bones", {}).get(garment.name)
    keep = np.isin(SAMPLE_BONES, bones) if bones else np.ones(len(SAMPLES), bool)
    np.savez(f"{work}/in.npz", positions=P[used[:, 0], used[:, 1], :3], used=used, samples=SAMPLES[keep], sample_uvs=SAMPLE_UVS[keep],
             color=src_color, rough=(src_rough[..., rough_channel] if src_rough is not None else np.zeros(0)),
             reach=a.get("reach", 0.12))
    subprocess.run([a["solver_python"], a["solver"], f"{work}/in.npz", f"{work}/out.npz"], check=True)
    result = np.load(f"{work}/out.npz")
    color = np.zeros((size, size, 4), np.float32); rough = np.zeros((size, size, 4), np.float32); hit = np.zeros((size, size, 1), np.float32)
    color[used[:, 0], used[:, 1]] = result["color"]
    r = result["rough"]; rough[used[:, 0], used[:, 1]] = np.stack([r, r, r, np.ones_like(r)], 1)
    hit[used[:, 0], used[:, 1], 0] = result["hit"]
    images = []
    for name, data in (("basecolor", color), ("roughness", rough)):
        image = bpy.data.images.new(f"{garment.name}_{name}", size, size, alpha=True)
        image.colorspace_settings.name = "sRGB" if name == "basecolor" else "Non-Color"
        image.pixels.foreach_set(data.ravel()); images.append(image)
    return images[0], images[1], hit

def island_map(garment, tree, holder, size):
    """Per-texel UV island index of a garment (-1 outside islands)."""
    mesh = bmesh.new(); mesh.from_mesh(garment.data)
    uv_layer = mesh.loops.layers.uv.active
    parent = list(range(len(mesh.faces)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    mesh.faces.ensure_lookup_table()
    for edge in mesh.edges:
        faces = edge.link_faces
        if len(faces) != 2:
            continue
        f0, f1 = faces
        def uvs(face):
            return {l.vert.index: tuple(round(c, 5) for c in l[uv_layer].uv) for l in face.loops if l.vert in edge.verts}
        if uvs(f0) == uvs(f1):
            parent[find(f0.index)] = find(f1.index)
    roots = {}
    ids = [roots.setdefault(find(f.index), len(roots)) for f in mesh.faces]
    mesh.free()
    attribute = garment.data.color_attributes.new("island_id", "FLOAT_COLOR", "CORNER")
    values = []
    for polygon, island in zip(garment.data.polygons, ids):
        value = (island + 1) / 65536.0
        values.extend([value, value, value, 1.0] * polygon.loop_total)
    attribute.data.foreach_set("color", values)
    image = bpy.data.images.new(f"{garment.name}_islands", size, size, alpha=True, float_buffer=True)
    image.generated_color = (0, 0, 0, 0)
    attr = tree.nodes.new("ShaderNodeAttribute"); attr.attribute_name = "island_id"
    emission = tree.nodes.new("ShaderNodeEmission"); out = next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL")
    old = out.inputs["Surface"].links[0].from_socket
    tree.links.new(attr.outputs["Color"], emission.inputs[0]); tree.links.new(emission.outputs[0], out.inputs["Surface"])
    holder.image = image
    for o in bpy.data.objects: o.select_set(False)
    garment.select_set(True); bpy.context.view_layer.objects.active = garment
    bpy.ops.object.bake(type="EMIT", margin=2)
    tree.links.new(old, out.inputs["Surface"])
    p = pixels(image)
    result = np.rint(p[..., 0] * 65536.0).astype(int) - 1
    result[p[..., 0] <= 0] = -1
    return result

report = {}
for garment in garments:
    material = garment.data.materials[0]
    tree = material.node_tree
    original = next((n.image for n in tree.nodes if n.type == "TEX_IMAGE" and n.image and
                     "normal" not in n.image.name.lower() and "_ao" not in n.image.name.lower()), None)
    original_normal = next((n.image for n in tree.nodes if n.type == "TEX_IMAGE" and n.image and
                            "normal" in n.image.name.lower()), None)
    size = a.get("size", 2048)
    holder = tree.nodes.new("ShaderNodeTexImage"); tree.nodes.active = holder
    color, rough, m = nearest_transfer(garment, tree, holder, size)
    normal = bpy.data.images.new(f"{garment.name}_normal", size, size); normal.colorspace_settings.name = "Non-Color"
    normal.pixels.foreach_set(np.tile([0.5, 0.5, 1.0, 1.0], size * size).astype(np.float32))
    def fallback(img, h, w):
        if img is None:
            return None
        if tuple(img.size) != (w, h):
            img = img.copy(); img.scale(w, h)
        return pixels(img)
    out = {}
    lib = fallback(original, size, size)
    if a.get("mode") == "island_median" and lib is not None:
        # Recolour the garment's own clean fabric per UV island with the island's median transferred
        # colour: concept colours, library detail, no blotches from the generated texture.
        islands = island_map(garment, tree, holder, size)
        transferred = pixels(color)[..., :3]
        lum = lib[..., :3] @ [0.3, 0.59, 0.11]
        flat = np.zeros_like(lib); flat[..., 3] = 1
        hits = m[..., 0] > 0.5
        island_colors = {}
        for island in np.unique(islands[islands >= 0]):
            sel = islands == island
            picked = transferred[sel & hits]
            if len(picked) < 20:
                continue
            island_colors[int(island)] = picked
            target_rgb = np.median(picked, axis=0)
            # Medians keep a texture's pure hue; its grey highlights had muted it on the source model.
            saturation = a.get("saturation", {}).get(garment.name, 1.0)
            target_rgb = target_rgb.mean() + saturation * (target_rgb - target_rgb.mean())
            lmean = max(lum[sel].mean(), 1e-3)
            flat[sel, :3] = (lum[sel] / lmean)[:, None] * target_rgb
        default = a.get("tints", {}).get(garment.name)
        missing = (islands < 0) | ~np.isin(islands, list(island_colors))
        if default is not None:
            flat[missing, :3] = (lum[missing] / max(lum.mean(), 1e-3))[:, None] * np.array(default)
        else:
            flat[missing, :3] = lib[missing, :3]
        color.pixels.foreach_set(flat.ravel()); m = np.ones_like(m)
    if lib is not None:
        # Misses keep the garment's fabric detail (luminance) but take the baked colour, or a configured
        # one where nothing was hit (gloves on generated hands that were removed).
        hit_px = pixels(color)[m[..., 0] > 0.5][:, :3]
        tint = np.array(a.get("tints", {}).get(garment.name) or (hit_px.mean(0) if len(hit_px) else (0.3, 0.3, 0.3)))
        lum = lib[..., :3] @ [0.3, 0.59, 0.11]
        lib = lib.copy(); lib[..., :3] = (lum / max(lum[lib[..., 3] > 0].mean(), 1e-3))[..., None] * tint
    # Depth and wear baked into base colour (engines get it without custom shaders): the garment's own
    # ambient-occlusion map, and low-frequency grime so new-looking cloth reads as used.
    ao_image = next((n.image for n in tree.nodes if n.type == "TEX_IMAGE" and n.image and "_ao" in n.image.name.lower()), None)
    shade = np.ones((size, size), np.float32)
    if ao_image is not None:
        ao = fallback(ao_image, size, size)[..., 0]
        shade *= 0.35 + 0.65 * ao
    grime = a.get("grime", {}).get(garment.name, 0.0)
    if grime:
        rng = np.random.default_rng(1)
        noise = np.zeros((size, size), np.float32)
        for cells, weight in ((8, 0.5), (32, 0.3), (128, 0.2)):
            coarse = rng.random((cells, cells)).astype(np.float32)
            noise += weight * np.kron(coarse, np.ones((size // cells, size // cells), np.float32))
        k = 9; kernel = np.ones(k, np.float32) / k
        noise = np.apply_along_axis(lambda r: np.convolve(r, kernel, mode="same"), 1, noise)
        noise = np.apply_along_axis(lambda c: np.convolve(c, kernel, mode="same"), 0, noise)
        shade *= 1 - grime * (noise - noise.min()) / (noise.max() - noise.min() + 1e-6)
    # Keep the average brightness: occlusion and grime add contrast, not an overall darkening.
    used_px = pixels(color)[..., 3] > 0.5
    shade /= max(float(shade[used_px].mean()) if used_px.any() else 1.0, 1e-3)
    if lib is not None:
        lib = lib.copy(); lib[..., :3] *= shade[..., None]
    shaded = pixels(color).copy(); shaded[..., :3] *= shade[..., None]; color.pixels.foreach_set(shaded.ravel())
    for name, image, base in (("basecolor", color, lib),
                              ("normal", normal, fallback(original_normal, size, size)),
                              ("roughness", rough, None)):
        p = pixels(image)
        if name == "normal":
            p = np.zeros_like(p)  # normal detail comes from the garment's own fabric map
        if base is None:
            base = np.zeros_like(p); base[..., :3] = (0.5, 0.5, 1.0) if name == "normal" else 0.7; base[..., 3] = 1
        weight = m if name != "normal" else np.zeros_like(m)
        mixed = p * weight + base * (1 - weight); mixed[..., 3] = 1
        if name == "roughness":
            mixed[..., :3] = np.maximum(mixed[..., :3], a.get("min_roughness", {}).get(garment.name, 0.0))
        image.pixels.foreach_set(mixed.ravel())
        image.filepath_raw = f"{a['textures']}/{garment.name}_{name}.png"; image.file_format = "PNG"; image.save()
        out[name] = image
    coverage = float((m > 0.5).mean())
    # Rebuild the garment material from the baked maps.
    new = bpy.data.materials.new(garment.name + "_baked"); new.use_nodes = True
    nt = new.node_tree; bsdf = nt.nodes["Principled BSDF"]
    def tex(image):
        n = nt.nodes.new("ShaderNodeTexImage"); n.image = image; return n
    nt.links.new(tex(out["basecolor"]).outputs[0], bsdf.inputs["Base Color"])
    nt.links.new(tex(out["roughness"]).outputs[0], bsdf.inputs["Roughness"])
    nm = nt.nodes.new("ShaderNodeNormalMap"); nt.links.new(tex(out["normal"]).outputs[0], nm.inputs["Color"])
    nt.links.new(nm.outputs[0], bsdf.inputs["Normal"])
    alpha = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED" and n.inputs["Alpha"].is_linked), None)
    garment.data.materials[0] = new
    report[garment.name] = {"hit_fraction_of_uv": round(coverage, 3)}

bpy.data.objects.remove(outfit, do_unlink=True)
for pose_bone in rig.pose.bones:
    pose_bone.matrix_basis.identity()
bpy.context.view_layer.update()

# Tuck trousers into tall boots: drop trouser faces below the boot tops, inside the boot outline.
if a.get("tuck"):
    suit, boots = bpy.data.objects[a["tuck"]["garment"]], bpy.data.objects[a["tuck"]["boots"]]
    boot_pts = [boots.matrix_world @ v.co for v in boots.data.vertices]
    top = sorted(p.z for p in boot_pts)[int(len(boot_pts) * 0.97)] - a["tuck"].get("overlap", 0.02)
    mesh = bmesh.new(); mesh.from_mesh(suit.data)
    gone = [f for f in mesh.faces if all((suit.matrix_world @ v.co).z < top for v in f.verts)]
    bmesh.ops.delete(mesh, geom=gone, context="FACES"); mesh.to_mesh(suit.data); mesh.free()
    report["tucked_faces"] = len(gone)
for name, tint in a.get("recolor", {}).items():
    # Hair cards: rebuild a clean material (strand texture x tint, matte, normal map, alpha) instead of
    # MPFB's legacy chain, which rendered fine grey strand textures as glossy black.
    obj = bpy.data.objects[name]
    for slot, material in enumerate(obj.data.materials):
        old_tree = material.node_tree
        images = {n.name: n.image for n in old_tree.nodes if n.type == "TEX_IMAGE" and n.image}
        diffuse = images.get("diffuseTexture"); normal_image = images.get("normalmapTexture")
        if diffuse is None:
            continue
        new = bpy.data.materials.new(material.name + "_clean"); new.use_nodes = True
        new.blend_method = "HASHED" if hasattr(new, "blend_method") else None
        nt = new.node_tree; bsdf = nt.nodes["Principled BSDF"]
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = diffuse
        bw = nt.nodes.new("ShaderNodeRGBToBW"); nt.links.new(tex.outputs[0], bw.inputs[0])
        mul = nt.nodes.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs["Factor"].default_value = 1
        nt.links.new(bw.outputs[0], mul.inputs[6]); mul.inputs[7].default_value = (*tint, 1)
        nt.links.new(mul.outputs[2], bsdf.inputs["Base Color"]); nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        bsdf.inputs["Roughness"].default_value = 0.7
        if normal_image is not None:
            ntex = nt.nodes.new("ShaderNodeTexImage"); ntex.image = normal_image; ntex.image.colorspace_settings.name = "Non-Color"
            nm = nt.nodes.new("ShaderNodeNormalMap"); nm.inputs["Strength"].default_value = 0.6
            nt.links.new(ntex.outputs[0], nm.inputs["Color"]); nt.links.new(nm.outputs[0], bsdf.inputs["Normal"])
        obj.data.materials[slot] = new
print("DRESSED", json.dumps(report))
bpy.ops.wm.save_as_mainfile(filepath=a["output"])
