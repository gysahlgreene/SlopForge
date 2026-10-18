"""Render a lit turntable of a prepared asset .blend for review and showcase.

Usage: blender --background --python render_turntable.py -- <asset.blend> <frames_dir> [--frames 48] [--size 512] [--walk]

The asset rotates once about its vertical axis under fixed key, fill and rim lights so
highlights travel across its materials. Frames are written as frame_###.png; the scene in
the source .blend is not saved. With --walk, a rigged Rigify character also plays a procedural
in-place walk test cycle on its FK controls (two strides per turn); it shows deformation in motion
and is not production animation.
"""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse():
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) < 2:
        raise SystemExit("usage: render_turntable.py -- <asset.blend> <frames_dir> [--frames N] [--size PX]")
    options = {"--frames": 48, "--size": 512}
    for key in options:
        if key in args:
            options[key] = int(args[args.index(key) + 1])
    return Path(args[0]).resolve(), Path(args[1]).resolve(), options["--frames"], options["--size"], "--walk" in args


def area_light(name, location, target, energy, size):
    light = bpy.data.objects.new(name, bpy.data.lights.new(name, "AREA"))
    light.data.energy, light.data.size, light.data.shape = energy, size, "DISK"
    light.location = location
    light.rotation_euler = (Vector(target) - light.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(light)


def main():
    source, frames_dir, frames, size, walk = parse()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    scene = bpy.context.scene
    for obj in list(scene.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    if not meshes:
        raise SystemExit(f"No mesh in {source}")
    corners = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    low = Vector([min(point[axis] for point in corners) for axis in range(3)])
    high = Vector([max(point[axis] for point in corners) for axis in range(3)])
    center, extent = (low + high) / 2, high - low
    radius = max(math.hypot(extent.x, extent.y), extent.z)

    pivot = bpy.data.objects.new("TurntablePivot", None)
    pivot.location = (center.x, center.y, low.z)
    scene.collection.objects.link(pivot)
    for obj in scene.objects:
        if obj.parent is None and obj.type in {"MESH", "ARMATURE"} and obj is not pivot:
            obj.parent = pivot
            obj.matrix_parent_inverse = pivot.matrix_world.inverted()
    rig = next((obj for obj in scene.objects if obj.type == "ARMATURE" and obj.pose.bones.get("thigh_fk.L")), None)
    if walk and rig is None:
        raise SystemExit("--walk needs a Rigify character with FK leg controls")
    if walk:
        for name in ("upper_arm_parent.L", "upper_arm_parent.R", "thigh_parent.L", "thigh_parent.R"):
            switch = rig.pose.bones.get(name)
            if switch is not None and "IK_FK" in switch:
                switch["IK_FK"] = 1.0
        for bone in rig.pose.bones:
            bone.rotation_mode = "XYZ"

    floor_material = bpy.data.materials.new("TurntableFloor")
    floor_material.use_nodes = True
    floor_bsdf = floor_material.node_tree.nodes["Principled BSDF"]
    floor_bsdf.inputs["Base Color"].default_value = (0.035, 0.035, 0.04, 1)
    floor_bsdf.inputs["Roughness"].default_value = 0.6
    bpy.ops.mesh.primitive_circle_add(vertices=96, radius=radius * 30, fill_type="NGON", location=(center.x, center.y, low.z))
    bpy.context.object.data.materials.append(floor_material)

    if scene.world is None:
        scene.world = bpy.data.worlds.new("TurntableWorld")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.05, 0.055, 0.06, 1)
    background.inputs["Strength"].default_value = 0.35
    target = center
    area_light("Key", center + Vector((-1.6, -1.8, 1.8)) * radius, target, 220 * radius ** 2, 1.5 * radius)
    area_light("Fill", center + Vector((1.9, -1.0, 0.8)) * radius, target, 60 * radius ** 2, 2.0 * radius)
    area_light("Rim", center + Vector((0.4, 2.2, 1.6)) * radius, target, 260 * radius ** 2, 1.2 * radius)

    camera = bpy.data.objects.new("TurntableCamera", bpy.data.cameras.new("TurntableCamera"))
    camera.data.lens = 70
    distance = radius * (2.0 if walk else 2.7)  # tall walking characters need a closer frame
    elevation = 0.8 if extent.z < 0.35 * max(extent.x, extent.y) else 0.32  # look down at flat props
    camera.location = center + Vector((0, -distance * math.cos(elevation), distance * math.sin(elevation)))
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(camera)
    scene.camera = camera

    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for frame in range(frames):
        pivot.rotation_euler = (0, 0, 2 * math.pi * frame / frames)
        if walk:
            # Axes measured on the generated basic-human rig: +X on thigh_fk swings the leg forward,
            # -X on shin_fk bends the knee; arm swing is Z on upper_arm_fk, opposite to the same-side leg.
            phase = 4 * math.pi * frame / frames
            swing = math.sin(phase)
            for side, sign in (("L", 1), ("R", -1)):
                leg = sign * swing
                rig.pose.bones[f"thigh_fk.{side}"].rotation_euler = (0.42 * leg, 0, 0)
                rig.pose.bones[f"shin_fk.{side}"].rotation_euler = (-0.75 * max(0.0, -leg) - 0.1, 0, 0)
                arm = rig.pose.bones.get(f"upper_arm_fk.{side}")
                if arm is not None:
                    arm.rotation_euler = (0, 0, 0.35 * swing)
            # Plant the lowest foot: measure the posed mesh and lower the whole character onto the floor.
            pivot.location.z = low.z
            bpy.context.view_layer.update()
            depsgraph = bpy.context.evaluated_depsgraph_get()
            lowest = min(min((obj.matrix_world @ vertex.co).z
                             for vertex in obj.evaluated_get(depsgraph).to_mesh().vertices) for obj in meshes)
            for obj in meshes:
                obj.evaluated_get(depsgraph).to_mesh_clear()
            pivot.location.z = low.z - (lowest - low.z)
            bpy.context.view_layer.update()
        scene.render.filepath = str(frames_dir / f"frame_{frame:03d}.png")
        bpy.ops.render.render(write_still=True)


main()
