"""Render a prop concept's shape guide: a depth map of a primitive envelope (near white, far dark, background black).

Usage: blender --background --python shape_guide.py -- <out.png> <width> <height> <cylinder|box> <height_over_width>

The concept graph's ControlNet reads it as depth and holds the concept's main mass to the declared proportion,
which wording alone did not do for priors such as a tall tree stump (docs/media/concept-proportion-2026-10).
"""
import math
import sys

import bpy
from mathutils import Vector

ELEVATION = math.radians(18)  # a slightly raised three-quarter view, like the concepts it guides


def main():
    out, width, height, shape, ratio = sys.argv[sys.argv.index("--") + 1:]
    width, height, ratio = int(width), int(height), float(ratio)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    if shape == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=0.5, depth=ratio, location=(0, 0, ratio / 2))
    elif shape == "box":
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, ratio / 2))
        bpy.context.object.scale = (1, 1, ratio)
        bpy.context.object.rotation_euler = (0, 0, math.radians(35))  # front and one side visible
    else:
        raise SystemExit(f"Unknown shape guide {shape!r}; use cylinder or box")
    envelope = bpy.context.object

    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    camera.data.lens = 50
    target = Vector((0, 0, ratio / 2))
    distance = 3.2 * max(1.0, ratio)  # leaves the margin the concept prompt asks for
    camera.location = target + Vector((0, -distance * math.cos(ELEVATION), distance * math.sin(ELEVATION)))
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(camera)
    scene.camera = camera

    material = bpy.data.materials.new("Depth")
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    depth = nodes.new("ShaderNodeCameraData")
    remap = nodes.new("ShaderNodeMapRange")
    # The envelope's depth span, nearest surface white; a flatter range read as a flat disc (2026-10-22).
    remap.inputs["From Min"].default_value, remap.inputs["From Max"].default_value = distance - 0.6, distance + 0.6
    remap.inputs["To Min"].default_value, remap.inputs["To Max"].default_value = 1.0, 0.15
    emission = nodes.new("ShaderNodeEmission")
    output = nodes.new("ShaderNodeOutputMaterial")
    links.new(depth.outputs["View Z Depth"], remap.inputs["Value"])
    links.new(remap.outputs["Result"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    envelope.data.materials.append(material)

    scene.world = bpy.data.worlds.new("World")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0, 0, 0, 1)
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Raw"
    # Exact black background, and no date, time or file-path metadata: the same request gives the same bytes,
    # so the guide's hash in the concept identity is stable and no machine path is written.
    scene.render.dither_intensity = 0
    for option in [name for name in dir(scene.render) if name.startswith("use_stamp_")]:
        setattr(scene.render, option, False)
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)


main()
