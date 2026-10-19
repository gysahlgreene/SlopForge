"""Bake the warped concept face (converted to albedo) into the template body's skin texture."""
import bpy, sys, json
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
a = json.loads(sys.argv[sys.argv.index("--") + 1])
frame = json.load(open(a["frame"]))
body = bpy.data.objects["Human"]
material = body.data.materials[0]; tree = material.node_tree; N, L = tree.nodes, tree.links
skin = next(n for n in N if n.type == "TEX_IMAGE").image
def load(path, color=True):
    im = bpy.data.images.load(path); im.colorspace_settings.name = "sRGB" if color else "Non-Color"; return im
def pixels(im):
    p = np.empty(im.size[0] * im.size[1] * 4, np.float32); im.pixels.foreach_get(p); return p.reshape(im.size[1], im.size[0], 4)
lit, albedo, warped, mask = load(a["lit"]), load(a["albedo"]), load(a["warped"]), load(a["mask"], False)
m = pixels(mask)[:, :, 0] > 0.8
k = pixels(albedo)[m][:, :3].mean(axis=0) / pixels(lit)[m][:, :3].mean(axis=0)
face = pixels(warped)[m][:, :3].mean(axis=0) * k
tint = face / pixels(albedo)[m][:, :3].mean(axis=0)
print("BAKE k", k.round(3), "tint", tint.round(3))
# Visibility from the front camera (body only), per vertex.
dg = bpy.context.evaluated_depsgraph_get()
world = [body.matrix_world @ v.co for v in body.data.vertices]
# MPFB hides helper geometry (proxy shells around head, tights) with a MASK modifier; it must not occlude.
mask_mod = next(m for m in body.modifiers if m.type == "MASK")
keep_group = body.vertex_groups[mask_mod.vertex_group].index
kept = {v.index for v in body.data.vertices if any(g.group == keep_group and g.weight > 0.5 for g in v.groups)}
kept = kept if not mask_mod.invert_vertex_group else set(range(len(world))) - kept
tree3 = BVHTree.FromPolygons(world, [p.vertices[:] for p in body.data.polygons if all(i in kept for i in p.vertices)])
print("BAKE mask group", mask_mod.vertex_group, "invert", mask_mod.invert_vertex_group, "kept", len(kept))
vis = []
for p, v in zip(world, body.data.vertices):
    n = (body.matrix_world.to_3x3() @ v.normal).normalized()
    vis.append(0.0 if n.y > -0.2 or tree3.ray_cast(p + n * 1e-4, Vector((0, -1, 0)))[0] is not None else 1.0)
attr = body.data.color_attributes.new("front_vis", "FLOAT_COLOR", "POINT")
attr.data.foreach_set("color", [c for x in vis for c in (x, x, x, 1)])
out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
geo = N.new("ShaderNodeNewGeometry"); sep = N.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Position"], sep.inputs[0])
def lin(sock, scale, shift):
    n = N.new("ShaderNodeMath"); n.operation = "MULTIPLY_ADD"; L.new(sock, n.inputs[0]); n.inputs[1].default_value = scale; n.inputs[2].default_value = shift; return n.outputs[0]
cx, cy, cz = frame["center"]; size = frame["size"]
uv = N.new("ShaderNodeCombineXYZ"); L.new(lin(sep.outputs["X"], 1 / size, 0.5 - cx / size), uv.inputs["X"]); L.new(lin(sep.outputs["Z"], 1 / size, 0.5 - cz / size), uv.inputs["Y"])
def tex(image):
    n = N.new("ShaderNodeTexImage"); n.image = image; n.extension = "CLIP"; L.new(uv.outputs[0], n.inputs[0]); return n
proj, msk = tex(warped), tex(mask)
scale_face = N.new("ShaderNodeMix"); scale_face.data_type = "RGBA"; scale_face.blend_type = "MULTIPLY"; scale_face.inputs["Factor"].default_value = 1
L.new(proj.outputs[0], scale_face.inputs[6]); scale_face.inputs[7].default_value = (*k, 1)
base = N.new("ShaderNodeTexImage"); base.image = skin; L.new(N.new("ShaderNodeUVMap").outputs[0], base.inputs[0])
tinted = N.new("ShaderNodeMix"); tinted.data_type = "RGBA"; tinted.blend_type = "MULTIPLY"; tinted.inputs["Factor"].default_value = 1
L.new(base.outputs[0], tinted.inputs[6]); tinted.inputs[7].default_value = (*tint, 1)
vc = N.new("ShaderNodeVertexColor"); vc.layer_name = "front_vis"
w = N.new("ShaderNodeMath"); w.operation = "MULTIPLY"; L.new(msk.outputs[0], w.inputs[0]); L.new(vc.outputs[0], w.inputs[1])
mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; L.new(w.outputs[0], mix.inputs["Factor"]); L.new(tinted.outputs[2], mix.inputs[6]); L.new(scale_face.outputs[2], mix.inputs[7])
em = N.new("ShaderNodeEmission"); L.new(mix.outputs[2], em.inputs[0]); L.new(em.outputs[0], out.inputs["Surface"])
target = bpy.data.images.new("skin_face", 4096, 4096); tnode = N.new("ShaderNodeTexImage"); tnode.image = target; N.active = tnode
for o in bpy.data.objects: o.select_set(False)
body.select_set(True); bpy.context.view_layer.objects.active = body
bpy.context.scene.render.engine = "CYCLES"; bpy.context.scene.cycles.samples = 1
bpy.ops.object.bake(type="EMIT", margin=8)
target.filepath_raw = a["output"]; target.file_format = "PNG"; target.save()
print("BAKED", a["output"])
