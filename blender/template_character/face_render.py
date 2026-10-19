"""Render the template head front-on (orthographic) for landmark alignment; record the camera frame."""
import bpy, sys, json
from mathutils import Vector
out = sys.argv[sys.argv.index("--") + 1]
scene = bpy.context.scene
body = bpy.data.objects["Human"]
rig = next(o for o in bpy.data.objects if o.type == "ARMATURE" and "head" in o.data.bones)
head = rig.matrix_world @ rig.data.bones["head"].head_local
top = max((body.matrix_world @ v.co).z for v in body.data.vertices)
for o in bpy.data.objects:
    if o.type == "MESH" and (o.name.startswith("Mesh") or "short" in o.name or "eyebrow" in o.name):
        o.hide_render = True
chin = head.z - 0.07
center = Vector((head.x, head.y, (top + chin) / 2))
size = (top - chin) * 1.1
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); scene.collection.objects.link(cam); scene.camera = cam
cam.data.type, cam.data.ortho_scale = "ORTHO", size
cam.location = center - Vector((0, 2, 0)); cam.rotation_euler = (1.5708, 0, 0)
world = bpy.data.worlds.new("w"); scene.world = world; world.color = (0.6, 0.6, 0.6)
light = bpy.data.objects.new("l", bpy.data.lights.new("l", "SUN")); light.data.energy = 2.5
light.rotation_euler = (1.4, 0, 0.3); scene.collection.objects.link(light)
scene.render.engine = "BLENDER_EEVEE"; scene.render.resolution_x = scene.render.resolution_y = 1024
scene.view_settings.view_transform = "Standard"
scene.render.filepath = out + ".png"; bpy.ops.render.render(write_still=True)
# Unlit albedo render: the skin texture alone, to convert projected (lit) colours back to albedo.
for material in body.data.materials:
    tree = material.node_tree
    image = next(n for n in tree.nodes if n.type == "TEX_IMAGE")
    output = next(n for n in tree.nodes if n.type == "OUTPUT_MATERIAL")
    emission = tree.nodes.new("ShaderNodeEmission")
    tree.links.new(image.outputs[0], emission.inputs[0]); tree.links.new(emission.outputs[0], output.inputs[0])
scene.render.filepath = out + "_albedo.png"; bpy.ops.render.render(write_still=True)
json.dump({"center": list(center), "size": size, "pixels": 1024}, open(out + ".json", "w"))
