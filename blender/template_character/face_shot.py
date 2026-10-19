import bpy, sys
from mathutils import Vector
out = sys.argv[sys.argv.index("--") + 1]
scene = bpy.context.scene
for o in list(scene.objects):
    if o.type in ("LIGHT", "CAMERA"): bpy.data.objects.remove(o, do_unlink=True)
rig = next(o for o in scene.objects if o.type == "ARMATURE" and "head" in o.data.bones)
head = rig.matrix_world @ rig.data.bones["head"].head_local
tgt = head + Vector((0, -0.02, 0.07))
world = bpy.data.worlds.new("w"); scene.world = world; world.color = (0.2, 0.2, 0.22)
for e, rot in ((3.5, (0.9, 0.2, -0.7)), (1.2, (1.2, 0, 2.4)), (2.0, (0.4, 0, 3.3))):
    l = bpy.data.objects.new("l", bpy.data.lights.new("l", "SUN")); l.data.energy = e; l.rotation_euler = rot; scene.collection.objects.link(l)
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); scene.collection.objects.link(cam); scene.camera = cam; cam.data.lens = 85
scene.render.engine = "BLENDER_EEVEE"; scene.render.resolution_x = scene.render.resolution_y = 700; scene.view_settings.view_transform = "AgX"
for name, d in (("front34", Vector((0.45, -1, 0.05))), ("side", Vector((1, -0.25, 0.05)))):
    cam.location = tgt + d.normalized() * 0.75; cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = f"{out}_{name}.png"; bpy.ops.render.render(write_still=True)
