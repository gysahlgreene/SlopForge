"""Procedural, clean accessories conformed to a dressed MPFB character (knee pads, belt with buckle)."""
import bpy, bmesh, sys, json, math
from mathutils import Vector, Matrix
a = json.loads(sys.argv[sys.argv.index("--") + 1])
bpy.ops.wm.open_mainfile(filepath=a["input"])
rig = next(o for o in bpy.data.objects if o.type == "ARMATURE")
suit = bpy.data.objects[a["garment"]]
W = rig.matrix_world
def joint(name, end="head"):
    b = rig.data.bones[name]; return W @ (b.head_local if end == "head" else b.tail_local)

def material(name, color, roughness, metallic=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1); b.inputs["Roughness"].default_value = roughness; b.inputs["Metallic"].default_value = metallic
    return m

def finish(obj, bone, thickness, bevel):
    """Conform to the garment, give thickness and bevel, smooth, rigidly bind to a bone."""
    wrap = obj.modifiers.new("Conform", "SHRINKWRAP"); wrap.target = suit; wrap.wrap_method = "NEAREST_SURFACEPOINT"
    wrap.wrap_mode = "OUTSIDE_SURFACE"; wrap.offset = 0.004
    solid = obj.modifiers.new("Thickness", "SOLIDIFY"); solid.thickness = thickness; solid.offset = 1
    bev = obj.modifiers.new("Bevel", "BEVEL"); bev.width = bevel; bev.segments = 3; bev.limit_method = "ANGLE"
    sub = obj.modifiers.new("Smooth", "SUBSURF"); sub.levels = 1; sub.render_levels = 1
    bpy.context.view_layer.objects.active = obj
    for m in list(obj.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)
    for p in obj.data.polygons: p.use_smooth = True
    obj.vertex_groups.new(name=bone).add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    obj.parent = rig
    obj.matrix_parent_inverse = rig.matrix_world.inverted()
    obj.modifiers.new("Armature", "ARMATURE").object = rig

made = []
pad_mat = material("KneePad", a.get("pad_color", (0.03, 0.03, 0.032)), 0.55)
for side in ("l", "r"):
    knee = joint(f"calf_{side}")
    # Front surface of the trousers at the knee.
    hit = None
    dg = bpy.context.evaluated_depsgraph_get()
    origin = suit.matrix_world.inverted() @ (knee + Vector((0, -0.3, 0)))
    ok, loc, normal, index = suit.evaluated_get(dg).ray_cast(origin, (suit.matrix_world.inverted().to_3x3() @ Vector((0, 1, 0))).normalized())
    centre = suit.matrix_world @ loc if ok else knee + Vector((0, -0.06, 0))
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1, location=centre)
    pad = bpy.context.object; pad.name = f"KneePad_{side}"
    pad.scale = (a.get("pad_width", 0.055), 0.03, a.get("pad_height", 0.075))
    bpy.ops.object.transform_apply(scale=True)
    mesh = bmesh.new(); mesh.from_mesh(pad.data)
    bmesh.ops.delete(mesh, geom=[v for v in mesh.verts if (v.co.y) > -0.004], context="VERTS")  # keep the front cap
    mesh.to_mesh(pad.data); mesh.free()
    pad.data.materials.append(pad_mat)
    finish(pad, f"calf_{side}", 0.012, 0.004)
    made.append(pad.name)

# Belt: a band around the trousers at the waist, with a metal buckle at the front.
if a.get("belt", True):
    hip_l, hip_r = joint("thigh_l"), joint("thigh_r")
    waist_z = (hip_l.z + joint("pelvis").z) / 2 + a.get("belt_raise", 0.06)
    dg = bpy.context.evaluated_depsgraph_get(); ev = suit.evaluated_get(dg)
    centre = (hip_l + hip_r) / 2; centre.z = waist_z
    ring = []
    for i in range(48):
        ang = 2 * math.pi * i / 48
        d = Vector((math.sin(ang), -math.cos(ang), 0))
        inv = suit.matrix_world.inverted()
        ok, loc, n, _ = ev.ray_cast(inv @ (centre + d * 0.4), (inv.to_3x3() @ -d).normalized())
        ring.append(suit.matrix_world @ loc if ok else centre + d * 0.17)
    mesh = bpy.data.meshes.new("Belt"); bm = bmesh.new()
    h = a.get("belt_height", 0.04)
    lower = [bm.verts.new(p - Vector((0, 0, h / 2))) for p in ring]; upper = [bm.verts.new(p + Vector((0, 0, h / 2))) for p in ring]
    for i in range(48):
        j = (i + 1) % 48
        bm.faces.new((lower[i], lower[j], upper[j], upper[i]))
    bm.normal_update(); bm.to_mesh(mesh); bm.free()
    belt = bpy.data.objects.new("Belt", mesh); bpy.context.collection.objects.link(belt)
    belt.data.materials.append(material("BeltLeather", a.get("belt_color", (0.035, 0.028, 0.022)), 0.5))
    finish(belt, "pelvis", 0.006, 0.0015)
    made.append("Belt")
    front = ring[0]
    bpy.ops.mesh.primitive_cube_add(size=1, location=front + Vector((0, -0.006, 0)))
    buckle = bpy.context.object; buckle.name = "Buckle"; buckle.scale = (0.05, 0.008, 0.045); bpy.ops.object.transform_apply(scale=True)
    bev = buckle.modifiers.new("Bevel", "BEVEL"); bev.width = 0.004; bev.segments = 2
    bpy.context.view_layer.objects.active = buckle; bpy.ops.object.modifier_apply(modifier="Bevel")
    buckle.data.materials.append(material("BuckleMetal", (0.55, 0.52, 0.48), 0.35, 1.0))
    buckle.vertex_groups.new(name="pelvis").add(list(range(len(buckle.data.vertices))), 1.0, "REPLACE")
    buckle.parent = rig; buckle.matrix_parent_inverse = rig.matrix_world.inverted(); buckle.modifiers.new("Armature", "ARMATURE").object = rig
    made.append("Buckle")
print("ACCESSORIES", made)
bpy.ops.wm.save_as_mainfile(filepath=a["output"])
