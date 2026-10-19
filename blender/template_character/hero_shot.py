import bpy, sys
from mathutils import Vector
out = sys.argv[sys.argv.index("--") + 1]
scene = bpy.context.scene
for o in list(scene.objects):
    if o.type in ("LIGHT", "CAMERA"): bpy.data.objects.remove(o, do_unlink=True)
arm = next(o for o in scene.objects if o.type == "ARMATURE")
if arm.animation_data: arm.animation_data.action = None
for b in arm.pose.bones: b.matrix_basis.identity()
meshes = [o for o in scene.objects if o.type == "MESH" and o.visible_get()]
pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector([min(p[i] for p in pts) for i in range(3)]); hi = Vector([max(p[i] for p in pts) for i in range(3)]); c = (lo + hi) / 2; h = hi.z - lo.z
world = bpy.data.worlds.new("w"); scene.world = world; world.color = (0.2, 0.2, 0.22)
for e, rot in ((3.5, (0.9, 0.2, -0.7)), (1.2, (1.2, 0, 2.4)), (2.0, (0.4, 0, 3.3))):
    l = bpy.data.objects.new("l", bpy.data.lights.new("l", "SUN")); l.data.energy = e; l.rotation_euler = rot; scene.collection.objects.link(l)
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); scene.collection.objects.link(cam); scene.camera = cam; cam.data.lens = 70
scene.render.engine = "BLENDER_EEVEE"; scene.render.resolution_x, scene.render.resolution_y = 700, 900; scene.view_settings.view_transform = "AgX"
for name, tgt, dist in (("full", c, 2.3 * h), ("upper", Vector((c.x, c.y, lo.z + 0.8 * h)), 0.95 * h)):
    cam.location = tgt + Vector((0.5, -1, 0.12)).normalized() * dist; cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = f"{out}_{name}.png"; bpy.ops.render.render(write_still=True)
