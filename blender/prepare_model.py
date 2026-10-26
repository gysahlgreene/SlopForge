import bpy
import json
import math
import sys
from pathlib import Path
from mathutils import Matrix, Vector
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mesh_cleanup import (remove_enclosed_components, remove_isolated_single_faces, repair_manifold_locally,
                          gltf_name, motion_matrix, remove_hidden_faces, separate_part, separate_tagged,
                          sweep_penetration, tag_parts, visible_backfaces)
from inspect_model import corner_profile, footprint_quadrants, topology_edge_counts


TARGET_FACES = 30000


def part_specs():
    """(name, kind, mask) for each --part NAME KIND MASK: a weapon's hinge or slide to split along its concept mask."""
    specs = []
    for index, value in enumerate(sys.argv):
        if value == "--part":
            if len(sys.argv) < index + 4 or sys.argv[index + 2] not in ("hinge", "slide"):
                raise SystemExit("--part needs NAME KIND MASK, with KIND hinge or slide")
            specs.append((sys.argv[index + 1], sys.argv[index + 2], Path(sys.argv[index + 3])))
    return specs


def get_args():
    argv = sys.argv

    if "--" not in argv:
        raise SystemExit(
            "Expected: -- input.glb output.fbx output.blend "
            "[basecolor normal roughness metallic emission]"
        )

    args = argv[argv.index("--") + 1:]

    if len(args) < 3:
        raise SystemExit(
            "Expected: input.glb output.fbx output.blend "
            "[basecolor normal roughness metallic emission]"
        )

    input_glb = Path(args[0]).resolve()
    output_fbx = Path(args[1]).resolve()
    output_blend = Path(args[2]).resolve()

    textures = [None] * 5

    for i, value in enumerate(args[3:8]):
        if value.startswith("--"):
            break
        textures[i] = Path(value).resolve()

    face_budget = TARGET_FACES
    voxel_resolution = 256
    options = {}
    if "--face-budget" in args:
        index = args.index("--face-budget")
        try:
            face_budget = int(args[index + 1])
        except (IndexError, ValueError):
            raise SystemExit("--face-budget must be followed by a positive integer")
        if face_budget <= 0:
            raise SystemExit("--face-budget must be a positive integer")
    if "--voxel-resolution" in args:
        index = args.index("--voxel-resolution")
        try:
            voxel_resolution = int(args[index + 1])
        except (IndexError, ValueError):
            raise SystemExit("--voxel-resolution must be a positive integer")
        if voxel_resolution <= 0:
            raise SystemExit("--voxel-resolution must be a positive integer")
    for option in ("--surface-source", "--preview-dir", "--material-scale", "--stage-mesh-output", "--normal-output", "--texture-size"):
        if option in args:
            index = args.index(option)
            try:
                options[option] = args[index + 1]
            except IndexError:
                raise SystemExit(f"{option} requires a value")

    texture_size = int(options.get("--texture-size", 2048))
    if not 64 <= texture_size <= 8192:
        raise SystemExit("--texture-size must be between 64 and 8192")
    return (
        input_glb,
        output_fbx,
        output_blend,
        face_budget,
        voxel_resolution,
        *textures,
        Path(options["--surface-source"]).resolve() if options.get("--surface-source") else None,
        Path(options["--preview-dir"]).resolve() if options.get("--preview-dir") else None,
        float(options.get("--material-scale", 3.0)),
        Path(options["--stage-mesh-output"]).resolve() if options.get("--stage-mesh-output") else None,
        "--reuse-stage-mesh" in args,
        "--preserve-uvs" in args,
        "--mesh-only" in args,
        Path(options["--normal-output"]).resolve() if options.get("--normal-output") else None,
        texture_size,
    )


def get_socket(bsdf, *names):
    for name in names:
        socket = bsdf.inputs.get(name)
        if socket is not None:
            return socket
    return None


def load_texture(nodes, path, non_color=False):
    if path is None or not path.exists():
        return None

    node = nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(str(path), check_existing=False)

    if non_color:
        node.image.colorspace_settings.name = "Non-Color"

    return node


def glass_faces(mesh, image_path):
    """Faces whose UV centre falls on declared glass: base colour alpha below 0.5 (unity_material.apply_glass)."""
    import numpy as np
    image = bpy.data.images.load(str(image_path), check_existing=True)
    width, height = image.size
    if image.channels < 4 or not mesh.uv_layers.active or not len(mesh.polygons):
        return []
    pixels = np.empty(width * height * 4, np.float32)
    image.pixels.foreach_get(pixels)
    alpha = pixels.reshape(height, width, 4)[:, :, 3]  # rows start at the bottom, as UV v does
    uv = np.empty(len(mesh.loops) * 2, np.float32)
    mesh.uv_layers.active.data.foreach_get("uv", uv)
    starts = np.empty(len(mesh.polygons), np.int64)
    mesh.polygons.foreach_get("loop_start", starts)
    counts = np.empty(len(mesh.polygons), np.int64)
    mesh.polygons.foreach_get("loop_total", counts)
    centre = np.add.reduceat(uv.reshape(-1, 2), starts) / counts[:, None]
    x = np.clip((centre[:, 0] % 1.0) * width, 0, width - 1).astype(int)
    y = np.clip((centre[:, 1] % 1.0) * height, 0, height - 1).astype(int)
    return np.nonzero(alpha[y, x] < 0.5)[0].tolist()


def combined_bounds(objects):
    points = []

    for obj in objects:
        for corner in obj.bound_box:
            points.append(obj.matrix_world @ Vector(corner))

    minimum = Vector((
        min(p.x for p in points),
        min(p.y for p in points),
        min(p.z for p in points),
    ))

    maximum = Vector((
        max(p.x for p in points),
        max(p.y for p in points),
        max(p.z for p in points),
    ))

    return minimum, maximum


def bake_basecolor(obj, material, surface_path, destination, material_scale, surface_maps):
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    coordinates = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (material_scale,) * 3
    links.new(coordinates.outputs["Object"], mapping.inputs["Vector"])

    surface = nodes.new("ShaderNodeTexImage")
    surface.image = bpy.data.images.load(str(surface_path), check_existing=True)
    surface.projection = "BOX"
    surface.projection_blend = 0.15
    surface.extension = "REPEAT"
    links.new(mapping.outputs["Vector"], surface.inputs["Vector"])

    links.new(surface.outputs["Color"], bsdf.inputs["Base Color"])

    width, height = (max(2048, value) for value in surface.image.size)
    target = bpy.data.images.new("Baked Base Color", width=width, height=height, alpha=False)
    bake_node = nodes.new("ShaderNodeTexImage")
    bake_node.image = target
    nodes.active = bake_node
    for node in nodes:
        node.select = node == bake_node

    obj.data.materials.clear()
    obj.data.materials.append(material)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.render.bake.margin = 8
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_clear=True, margin=8)
    target.filepath_raw = str(destination)
    target.file_format = "PNG"
    target.save()

    # Every channel must follow the same projection into the mesh's UV atlas.
    output = nodes.get("Material Output")
    emission = nodes.new("ShaderNodeEmission")
    for key in ("roughness", "metallic", "emission"):
        path = surface_maps[key]
        if path is None or not path.is_file():
            continue
        source = load_texture(nodes, path, non_color=key != "emission")
        source.projection = "BOX"
        source.projection_blend = surface.projection_blend
        source.extension = "REPEAT"
        links.new(mapping.outputs["Vector"], source.inputs["Vector"])
        links.new(source.outputs["Color"], emission.inputs["Color"])
        links.new(emission.outputs[0], output.inputs["Surface"])
        target = bpy.data.images.new(f"Baked {key}", width=width, height=height, alpha=False)
        if key != "emission":
            target.colorspace_settings.name = "Non-Color"
        bake_node.image = target
        nodes.active = bake_node
        bpy.ops.object.bake(type="EMIT", use_clear=True, margin=8)
        target.filepath_raw, target.file_format = str(path), "PNG"
        target.save()

    normal_path = surface_maps["normal"]
    if normal_path is not None:
        # ponytail: luminance bump estimates grain; native PBR uses geometry-baked normals.
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.1
        bump.inputs["Distance"].default_value = 0.01
        links.new(surface.outputs["Color"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
        links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
        target = bpy.data.images.new("Baked Normal", width=width, height=height, alpha=False)
        target.colorspace_settings.name = "Non-Color"
        bake_node.image = target
        nodes.active = bake_node
        bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", use_clear=True, margin=8)
        target.filepath_raw, target.file_format = str(normal_path), "PNG"
        target.save()

    nodes.clear()
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    output = nodes.new("ShaderNodeOutputMaterial")
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return bsdf


def render_previews(obj, output_dir, prefix):
    output_dir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Preview World")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.18, 0.18, 0.18, 1.0)
    background.inputs["Strength"].default_value = 0.5

    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    bounds_min = Vector(tuple(min(point[axis] for point in corners) for axis in range(3)))
    bounds_max = Vector(tuple(max(point[axis] for point in corners) for axis in range(3)))
    target = (bounds_min + bounds_max) * 0.5
    size = bounds_max - bounds_min
    # The three-quarter view sees the footprint diagonal, which is wider than any single side.
    frame_scale = max(math.hypot(size.x, size.y), size.z) * 1.15
    bpy.ops.object.camera_add(location=(0, -3, 1.5))
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = frame_scale
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera

    for offset, energy, size in (((-3, -4, 4), 450, 4), ((3, -1, 2), 220, 3), ((0, 2, 3), 300, 3)):
        location = target + Vector(offset)
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = size
        light.rotation_euler = (target - light.location).to_track_quat("-Z", "Y").to_euler()

    extent = bounds_max - bounds_min
    # Flat props (keys, coins, lying weapons) are unreadable edge-on; look down at them instead.
    elevation = 2.5 if extent.z < 0.35 * max(extent.x, extent.y) else 0
    views = {"front": Vector((0, -3, elevation)), "side": Vector((3, 0, elevation)), "rear": Vector((0, 3, elevation)),
             "three_quarter": Vector((2, -2, elevation))}
    for name, direction in views.items():
        camera.location = target + direction
        camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
        scene.render.filepath = str(output_dir / f"{prefix}_{name}.png")
        bpy.ops.render.render(write_still=True)


(
    input_glb,
    output_fbx,
    output_blend,
    target_faces,
    voxel_resolution,
    basecolor_path,
    normal_path,
    roughness_path,
    metallic_path,
    emission_path,
    surface_source_path,
    preview_dir,
    material_scale,
    stage_mesh_output,
    reuse_stage_mesh,
    preserve_uvs,
    mesh_only,
    normal_output,
    texture_size,
) = get_args()


if not input_glb.exists():
    raise SystemExit(f"Input GLB missing: {input_glb}")


output_fbx.parent.mkdir(parents=True, exist_ok=True)
output_blend.parent.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------
# START CLEAN / REUSE PROCESSED MESH
# -------------------------------------------------

if reuse_stage_mesh:
    bpy.ops.wm.open_mainfile(filepath=str(input_glb))
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
else:
    if not input_glb.exists():
        raise SystemExit(f"Input GLB missing: {input_glb}")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_glb))
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]

if not mesh_objects:
    raise SystemExit("No mesh objects found.")

parts_table = None
if "--parts-json" in sys.argv:
    # A weapon generated as parts (OmniPart, prepare_parts.py): one node per part, tagged before the join below
    # and separated again after orientation and scaling (MOVING PARTS).
    parts_info = json.loads(Path(sys.argv[sys.argv.index("--parts-json") + 1]).read_text())
    parts_table = parts_info["parts"]
    if not reuse_stage_mesh:
        tag_parts(mesh_objects, parts_table)


# -------------------------------------------------
# JOIN MESHES
# -------------------------------------------------

if not reuse_stage_mesh:
    bpy.ops.object.select_all(action="DESELECT")

    for obj in mesh_objects:
        obj.select_set(True)

    # The join keeps the active object's name; on the parts route that must be the body, or a moving part listed
    # first would lose its name to the root (review 2026-10-25).
    bpy.context.view_layer.objects.active = next(
        (item for item in mesh_objects if parts_table is not None and gltf_name(item) == "body"), mesh_objects[0])

    if len(mesh_objects) > 1:
        bpy.ops.object.join()

    obj = bpy.context.view_layer.objects.active
else:
    obj = mesh_objects[0]


# -------------------------------------------------
# APPLY INITIAL TRANSFORMS
# -------------------------------------------------

if not reuse_stage_mesh:
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


# -------------------------------------------------
# ORIENT FROM THE CONCEPT (weapons)
# -------------------------------------------------

oriented = "--concept" in sys.argv and not reuse_stage_mesh and not mesh_only
if oriented:
    # A weapon is drawn tip or muzzle right. Turn its tip to -Y (forward in Unity once exported) and its top to +Z,
    # and mark the faces under the grip mask, seen from the view that best fits the concept.
    import numpy as np
    from concept_view import (area_samples, fit_view, footprint_axes, image_mask, surface_samples, to_concept_pixels,
                              view_axes)
    concept = image_mask(sys.argv[sys.argv.index("--concept") + 1])
    world, samples = surface_samples(obj)
    fit, theta, phi = fit_view(samples, concept, full_turn=True)  # a weapon can be rebuilt facing the other way
    _, right, up = view_axes(math.radians(theta), math.radians(phi))
    pixels = to_concept_pixels(np.stack([world @ np.array(right), world @ np.array(up)], 1), concept)

    def under(mask):
        """Which vertices the fitted view projects onto the mask's pixels."""
        inside = ((pixels[:, 0] >= 0) & (pixels[:, 0] < mask.shape[1]) & (pixels[:, 1] >= 0) &
                  (pixels[:, 1] < mask.shape[0]))
        result = np.zeros(len(world), bool)
        result[inside] = mask[pixels[inside, 1], pixels[inside, 0]]
        return result

    held = None
    if "--grip-mask" in sys.argv:
        grip = image_mask(sys.argv[sys.argv.index("--grip-mask") + 1], channel=0)
        # Widened by 1.5% of the concept so vertices on the grip's edge count: the fitted view is 5 degrees coarse.
        for _ in range(max(1, round(0.015 * max(grip.shape)))):
            grip = grip | np.roll(grip, 1, 0) | np.roll(grip, -1, 0) | np.roll(grip, 1, 1) | np.roll(grip, -1, 1)
        held = under(grip)
        group = obj.vertex_groups.new(name="slopforge_grip")
        group.add([int(index) for index in np.flatnonzero(held)], 1.0, "REPLACE")
        print(f"Grip: {int(held.sum())} of {len(world)} vertices under the grip mask")
    part_coverage, part_overflow = {}, {}
    for name, kind, mask_path in part_specs():
        mask = image_mask(mask_path, channel=0)
        if parts_table is not None and name in parts_table:
            # A generated part against its mask: the share of the mask's cells (32 across its longer side) that one
            # of the part's vertices projects into. The gate (part_coverage) retries a seed that misplaced a part.
            values = [0] * len(obj.data.polygons)
            obj.data.attributes["slopforge_part"].data.foreach_get("value", values)
            part_id = int(parts_table[name]["id"])
            rows, cols = np.nonzero(mask)
            cell = max(1, int(math.ceil(max(rows.max() - rows.min() + 1, cols.max() - cols.min() + 1) / 32)))
            wanted = set(zip((rows // cell).tolist(), (cols // cell).tolist()))
            hit = set()
            for polygon, value in zip(obj.data.polygons, values):  # each face fills the cells its projection spans
                if value != part_id:
                    continue
                corners = pixels[list(polygon.vertices)]
                (c0, r0), (c1, r1) = corners.min(0) // cell, corners.max(0) // cell
                hit.update((row, col) for row in range(int(r0), int(r1) + 1) for col in range(int(c0), int(c1) + 1))
            part_coverage[name] = round(len(wanted & hit) / len(wanted), 4) if wanted else 0.0
            # Recorded, not enforced (review 2026-10-25): how much of the part lies outside its mask (one cell of
            # slack), and how many pieces it is in, for calibration before a gate.
            slack = {(row + dr, col + dc) for row, col in wanted for dr in (-1, 0, 1) for dc in (-1, 0, 1)}
            part_overflow[name] = round(len(hit - slack) / len(hit), 4) if hit else 0.0
            print(f"Part {name} ({kind}): covers {part_coverage[name]:.2f} of its mask, "
                  f"{part_overflow[name]:.2f} of it outside")
        if kind == "hinge":
            # Widened by 1% of the concept: SAM masked a pistol trigger's blade alone, and the cut left its root in
            # the frame (2026-10-24). A slide's mask is not widened; its cut is snapped to a plane when separated.
            for _ in range(max(1, round(0.01 * max(mask.shape)))):
                mask = mask | np.roll(mask, 1, 0) | np.roll(mask, -1, 0) | np.roll(mask, 1, 1) | np.roll(mask, -1, 1)
        moving = under(mask)
        group = obj.vertex_groups.new(name=f"slopforge_part_{name}")
        group.add([int(index) for index in np.flatnonzero(moving)], 1.0, "REPLACE")
        print(f"Part {name} ({kind}): {int(moving.sum())} of {len(world)} vertices under its mask")
    # Levelled from the weapon's own shape, not the fitted view (2026-10-24, docs/WEAPONS.md, Orientation): TRELLIS
    # rebuilds a weapon upright and lengthwise whatever the concept's camera, Pixal3D keeps the concept's pose (a
    # crossbow drawn from above came back tilted 21 degrees), and tilting by the fitted view rolled a flat longsword
    # 30 degrees about its length, since its outline barely changes with tilt. A weapon whose thinnest axis is nearer
    # vertical than horizontal lies flat in its concept, like that crossbow, and the axis is its top; a side-on
    # weapon's top is +Z. Its length is its longest axis across the top (the full 3D one leans 19-25 degrees towards
    # a pistol's grip), pointed at the end the concept draws on the right. Of the two axes across the top, the length
    # is the one whose line through the centre passes nearest the grip: a crossbow's bow can spread almost as far as
    # its stock (2026-10-24: variances 0.051 and 0.063).
    centred = samples - samples.mean(0)
    thinnest = np.linalg.eigh(centred.T @ centred)[1][:, 0]
    top = thinnest * np.sign(thinnest[2]) if abs(thinnest[2]) > math.sqrt(0.5) else np.array([0.0, 0.0, 1.0])
    across = centred - np.outer(centred @ top, top)
    axes = np.linalg.eigh(across.T @ across)[1][:, ::-1][:, :2].T  # longest first
    length = axes[0]
    if held is not None and held.any():
        offset = world[held].mean(0) - samples.mean(0)
        offset -= (offset @ top) * top
        length = min(axes, key=lambda axis: np.linalg.norm(offset - (offset @ axis) * axis))
    # How far the length runs along the concept's right; near 0 the view looks along it and the tip's end is a guess,
    # which validation rejects (weapon_orientation) so another seed is tried.
    towards_tip = float(length @ np.array(right))
    if held is None:
        # A prop with parts (a chest): its width (the longer horizontal axis) along X, its depth along Y with the
        # front, the side the concept's camera sees, towards -Y, so a lid's "back" edge is away from the viewer. Its
        # frame comes from points spread by area and its footprint's smallest rectangle: a dense hasp leaned the
        # sample axes 6-9 degrees, and the lid then turned about X swung crooked (OPEN3, OPEN4, 2026-10-26).
        even = area_samples(obj)
        spread = even - even.mean(0)
        thinnest = np.linalg.eigh(spread.T @ spread)[1][:, 0]
        top = thinnest * np.sign(thinnest[2]) if abs(thinnest[2]) > math.sqrt(0.5) else np.array([0.0, 0.0, 1.0])
        axes = footprint_axes(even, top)
        hinge = ((parts_info.get("open_state") or {}).get("hinge") if parts_table is not None else None)
        if hinge is not None:
            # generated open, the lid touched the body along its back (blender/close_part.py): the silhouette fit
            # cannot tell a chest's front from its back (theta 45 on OPEN2, -140 on OPEN3 and OPEN4: lock behind)
            depth = axes[1] * (1.0 if float(axes[1] @ (np.array(hinge) - even.mean(0))) > 0 else -1.0)
        else:
            towards, _right, _up = view_axes(math.radians(theta), math.radians(phi))
            depth = axes[1] * (-1.0 if float(axes[1] @ np.array(towards)) > 0 else 1.0)  # +Y away from the camera
        depth, top = Vector(depth), Vector(top)
        source = Matrix((depth.cross(top), depth, top)).transposed()
        obj.data.transform(source.inverted().to_4x4())
        towards_tip = 1.0
        frame = "width to X, front to -Y, top to +Z"
    else:
        forward, top = Vector(length * (1.0 if towards_tip >= 0 else -1.0)), Vector(top)
        source = Matrix((forward, top, forward.cross(top))).transposed()
        target = Matrix(((0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0))).transposed()
        obj.data.transform((target @ source.inverted()).to_4x4())
        frame = "tip to -Y, top to +Z"
    obj.data.update()
    obj["slopforge_concept_view"] = [round(fit, 4), theta, phi, round(abs(towards_tip), 4)]
    if part_coverage:
        obj["slopforge_part_coverage"] = json.dumps(part_coverage)  # a string survives the FBX round trip
        obj["slopforge_part_overflow"] = json.dumps(part_overflow)
    print(f"Oriented from the concept view theta {theta} phi {phi} (fit {fit:.3f}): {frame}")


# -------------------------------------------------
# CENTER + NORMALIZE SCALE
# -------------------------------------------------

if not reuse_stage_mesh and not mesh_only:
    minimum, maximum = combined_bounds([obj])
    size = maximum - minimum
    max_dimension = max(size.x, size.y, size.z, 1e-6)
    offset = Vector((-(minimum.x + maximum.x) / 2.0, -(minimum.y + maximum.y) / 2.0, -minimum.z))
    obj.location += offset
    obj.scale *= 1.0 / max_dimension
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if "--target-size" in sys.argv:
        # Kit modules declare real sizes, e.g. "3,-,3" for a wall; "-" keeps proportion on that axis.
        target = [None if value == "-" else float(value)
                  for value in sys.argv[sys.argv.index("--target-size") + 1].split(",")]
        if len(target) != 3 or all(value is None for value in target) or any(value is not None and value <= 0 for value in target):
            raise SystemExit("--target-size needs three comma-separated positive sizes or '-', e.g. 3,-,3")
        # Transform mesh data directly: the transform_apply operator did not take effect here.
        coords = [vertex.co for vertex in obj.data.vertices]
        size = Vector([max(co[axis] for co in coords) - min(co[axis] for co in coords) for axis in range(3)])
        # A declared horizontal size marks the long side when the other is free (a wall is 3,-,3).
        x_long = None if target[0] is None and target[1] is None else (
            target[1] is None or (target[0] is not None and target[0] >= target[1]))
        # Not for a weapon already oriented from its concept: a crossbow whose bow spread wider than its stock was long
        # was turned 90 degrees, putting the bow along its length (2026-10-24).
        if not oriented and x_long is not None and x_long != (size.x >= size.y):
            obj.data.transform(Matrix.Rotation(math.pi / 2, 4, "Z"))
            size = Vector((size.y, size.x, size.z))
        factors = [None if value is None else value / max(size[axis], 1e-6) for axis, value in enumerate(target)]
        fixed = [factor for factor in factors if factor is not None]
        factors = [factor if factor is not None else sum(fixed) / len(fixed) for factor in factors]
        obj.data.transform(Matrix.Diagonal((*factors, 1.0)))
        obj.data.update()
        coords = [vertex.co for vertex in obj.data.vertices]
        low = Vector([min(co[axis] for co in coords) for axis in range(3)])
        high = Vector([max(co[axis] for co in coords) for axis in range(3)])
        recentre = Vector((-(low.x + high.x) / 2.0, -(low.y + high.y) / 2.0, -low.z))
        obj.data.transform(Matrix.Translation(recentre))
        obj.data.update()
        obj.location = Vector((0.0, 0.0, 0.0))  # geometry is now bottom-centred in its own space
        # The arm rescale below reads these bounds: from before recentring, an off-centre corner's open side was
        # missed and its arms were left as generated (M2-v1 timber corner, 2026-10-23).
        low, high = low + recentre, high + recentre
        bpy.context.view_layer.update()
        print(f"Scaled to target size {[round(v, 4) for v in high - low]}; "
              f"axis stretch ratio {max(factors) / min(factors):.3f}")
        # Kept on the object so inspection can report it: a large stretch means the concept's proportions did not
        # fit the module (issue #91). Only the axes that shape its face count: a wall's declared thickness squeezes
        # its depth on purpose (2026-10-22: wall 1.36 over all axes, 1.19 over its face).
        sizes = high - low
        face = [factor for axis, factor in enumerate(factors) if sizes[axis] >= 0.5 * max(sizes)]
        obj["slopforge_axis_stretch"] = round(max(face) / min(face), 4)
        if "--arm-thickness" in sys.argv:
            # A kit corner's arms take the kit's declared wall thickness, so walls continue them flush; the outer
            # bounds stay exact. 2026-10-22: generated arms were about 1 m against 0.74 m walls (issue #90).
            wanted = float(sys.argv[sys.argv.index("--arm-thickness") + 1])
            bounds = ([low.x, low.y, low.z], [high.x, high.y, high.z])
            corner = corner_profile([vertex.co.copy() for vertex in obj.data.vertices],
                                    footprint_quadrants([obj], *bounds), *bounds)
            if corner is None:
                print("--arm-thickness: no open side found, so the corner is left as is")
            else:
                (ox, oy), (arm_x, arm_y) = corner
                outer = (low.x if ox > 0 else high.x, low.y if oy > 0 else high.y)
                spans = (high.x - low.x, high.y - low.y)

                def rescale(distance, current, span):
                    # Piecewise linear across the side: the arm takes the wanted thickness, the rest fills the span.
                    if distance <= current:
                        return distance * wanted / current
                    return wanted + (distance - current) * (span - wanted) / (span - current)
                for vertex in obj.data.vertices:
                    vertex.co.x = outer[0] + ox * rescale(abs(vertex.co.x - outer[0]), arm_x, spans[0])
                    vertex.co.y = outer[1] + oy * rescale(abs(vertex.co.y - outer[1]), arm_y, spans[1])
                obj.data.update()
                print(f"Corner arms {arm_x:.3f} and {arm_y:.3f} set to {wanted:g}")


# -------------------------------------------------
# GAME-READY DECIMATION
# -------------------------------------------------

detail_source = None
if mesh_only:
    remove_isolated_single_faces(obj.data)
    minimum, maximum = combined_bounds([obj])
    if normal_output and "--detail-mesh" in sys.argv:
        # Full-detail remesh from the generator, in the same frame as this (reduced) mesh.
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=sys.argv[sys.argv.index("--detail-mesh") + 1])
        details = [item for item in bpy.data.objects if item not in before and item.type == "MESH"]
        if not details:
            raise SystemExit("--detail-mesh contains no mesh")
        bpy.ops.object.select_all(action="DESELECT")
        for item in details:
            item.select_set(True)
        bpy.context.view_layer.objects.active = details[0]
        if len(details) > 1:
            bpy.ops.object.join()
        detail_source = bpy.context.view_layer.objects.active
        detail_source.select_set(False)
        bpy.context.view_layer.objects.active = obj
    elif normal_output:
        detail_source = obj.copy()
        detail_source.data = obj.data.copy()
        bpy.context.collection.objects.link(detail_source)
        detail_source.select_set(False)
    # Hidden inner components cost budget and atlas space on props too: on six 2026-10-20 H100 props they held
    # 7-39% of the triangles, and removing them changed no pixel in eight views (issue #64).
    removed = remove_enclosed_components(obj.data, max(maximum - minimum) * 1e-5)
    if removed:
        print(f"Removed enclosed inner-shell vertices: {removed}")
    boundary, nonmanifold = topology_edge_counts(obj.data, max(maximum - minimum) * 1e-7)
    # A voxel remesh needs closed volumes; it erases thin open parts (planks, handles, lattices).
    # Workflows that already ran a UDF remesh on the GPU pass --no-voxel-repair.
    if (boundary or nonmanifold) and "--local-repair" in sys.argv:
        # Characters need a closed body for rigging; repair locally so modelled detail survives.
        boundary, nonmanifold = repair_manifold_locally(obj.data, max(maximum - minimum) * 1e-5)
        print(f"Local manifold repair left boundary={boundary} non_manifold={nonmanifold}")
    if (boundary or nonmanifold) and "--no-voxel-repair" not in sys.argv:
        modifier = obj.modifiers.new(name="CleanReconstruction", type="REMESH")
        modifier.mode = "VOXEL"
        modifier.voxel_size = max(maximum - minimum) / voxel_resolution
        modifier.use_smooth_shade = True
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    # After any repair, which an opening would set off: the double skin and the shells inside it take most of the
    # faces and of the texture otherwise (mesh_cleanup.remove_hidden_faces)
    if "--remove-hidden-faces" in sys.argv:
        print(f"Removed hidden faces: {remove_hidden_faces(obj.data, float(max(maximum - minimum)))}")

# Exports use triangles; counting remeshed quads underestimates the budget.
if any(len(polygon.vertices) > 3 for polygon in obj.data.polygons):
    modifier = obj.modifiers.new(name="ExportTriangles", type="TRIANGULATE")
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)
face_count = len(obj.data.polygons)
print(f"Input faces: {face_count}")
while face_count > target_faces:
    modifier = obj.modifiers.new(name="GameReadyDecimate", type="DECIMATE")
    modifier.decimate_type = "COLLAPSE"
    # Collapse ratios are approximate on reconstructed meshes; check the result.
    modifier.ratio = 0.95 * target_faces / face_count
    modifier.use_collapse_triangulate = True
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    reduced_count = len(obj.data.polygons)
    if reduced_count >= face_count:
        raise SystemExit(f"Cannot reduce this mesh to its {target_faces}-face budget")
    face_count = reduced_count
print(f"Output faces: {face_count}")

removed_faces = remove_isolated_single_faces(obj.data)
if removed_faces:
    print(f"Removed isolated single-face fragments: {removed_faces}")


# -------------------------------------------------
# SMOOTH SHADING
# -------------------------------------------------

if not reuse_stage_mesh:
    for polygon in obj.data.polygons:
        polygon.use_smooth = True


# -------------------------------------------------
# UV UNWRAP
# -------------------------------------------------

if not reuse_stage_mesh and not preserve_uvs:
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    # Pad islands by about 4 texels. A 0.003 margin (12 texels at 4096) spent an organic prop's atlas on padding:
    # a tree stump unwrapped into 10,600 islands used 4.4% of its map. 4 texels and a concave repack gave 19%, and a
    # crate 0.30 -> 0.55, a jug 0.54 -> 0.65, with unchanged stretch (2026-10-22).
    margin = 4 / texture_size
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=margin)
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(rotate=True, margin=margin, shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")
if mesh_only:
    if detail_source is not None:
        material = bpy.data.materials.new("NormalBake")
        material.use_nodes = True
        obj.data.materials.clear()
        obj.data.materials.append(material)
        target = bpy.data.images.new("Source Normal", width=texture_size, height=texture_size, alpha=False)
        target.colorspace_settings.name = "Non-Color"
        node = material.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = target
        material.node_tree.nodes.active = node
        bpy.context.scene.render.engine = "CYCLES"
        bpy.context.scene.cycles.samples = 1
        bpy.ops.object.select_all(action="DESELECT")
        detail_source.select_set(True)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        # ponytail: a 1% cage fits typical reconstructions; thin overlapping surfaces need visual review.
        bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", use_selected_to_active=True,
                            cage_extrusion=max(maximum - minimum) * 0.01, margin=16)
        normal_output.parent.mkdir(parents=True, exist_ok=True)
        target.filepath_raw, target.file_format = str(normal_output), "PNG"
        target.save()
        bpy.data.objects.remove(detail_source, do_unlink=True)
        obj.data.materials.clear()
    # Keep the generator's coordinate frame so its voxel material field still aligns.
    bpy.ops.export_scene.gltf(filepath=str(output_fbx), export_format="GLB")
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    raise SystemExit(0)

if stage_mesh_output:
        stage_mesh_output.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(stage_mesh_output))


# -------------------------------------------------
# MATERIAL
# -------------------------------------------------

material = bpy.data.materials.new(
    name=f"{input_glb.stem}_PBR"
)

material.use_nodes = True

nodes = material.node_tree.nodes
links = material.node_tree.links

bsdf = nodes.get("Principled BSDF")

if bsdf is None:
    raise SystemExit("Principled BSDF was not created.")


if surface_source_path:
    if not surface_source_path.is_file():
        raise SystemExit(f"Surface material image missing: {surface_source_path}")
    if basecolor_path and surface_source_path.resolve() == basecolor_path.resolve():
        # The swatch is tiled and baked into the base colour path; given the base colour map itself, it overwrote a
        # candidate's map with its own tiling (2026-10-24). Native textures pass no --surface-source.
        raise SystemExit("--surface-source must not be the base colour map it is baked into")
    bsdf = bake_basecolor(obj, material, surface_source_path, basecolor_path, material_scale,
                         {"normal": normal_path, "roughness": roughness_path,
                          "metallic": metallic_path, "emission": emission_path})
tex = load_texture(nodes, basecolor_path, non_color=False)

if tex is not None:
    socket = get_socket(bsdf, "Base Color")
    if socket:
        links.new(tex.outputs["Color"], socket)
    # Declared glass carries base colour alpha (slopforge.unity_material.apply_glass); maps without it read 1.
    links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])


# Roughness

tex = load_texture(
    nodes,
    roughness_path,
    non_color=True,
)

if tex is not None:
    socket = get_socket(bsdf, "Roughness")
    if socket:
        links.new(tex.outputs["Color"], socket)


# Metallic

tex = load_texture(
    nodes,
    metallic_path,
    non_color=True,
)

if tex is not None:
    socket = get_socket(bsdf, "Metallic")
    if socket:
        links.new(tex.outputs["Color"], socket)


# Normal

tex = load_texture(
    nodes,
    normal_path,
    non_color=True,
)

if tex is not None:
    normal_node = nodes.new("ShaderNodeNormalMap")

    links.new(
        tex.outputs["Color"],
        normal_node.inputs["Color"],
    )

    socket = get_socket(bsdf, "Normal")

    if socket:
        links.new(
            normal_node.outputs["Normal"],
            socket,
        )


# Emission

tex = load_texture(
    nodes,
    emission_path,
    non_color=False,
)

if tex is not None:
    socket = get_socket(
        bsdf,
        "Emission Color",
        "Emission",
    )

    if socket:
        links.new(
            tex.outputs["Color"],
            socket,
        )

    strength = get_socket(
        bsdf,
        "Emission Strength",
    )

    if strength:
        strength.default_value = 3.0


obj.data.materials.clear()
obj.data.materials.append(material)
# Declared glass gets its own material, so the engine can draw it transparent and keep the rest opaque with
# depth writes (issue #44); it shares the maps, whose alpha marks the glass.
glass = glass_faces(obj.data, basecolor_path) if basecolor_path and basecolor_path.exists() else []
if glass:
    glass_material = material.copy()
    glass_material.name = f"{input_glb.stem}_Glass"
    obj.data.materials.append(glass_material)
    for index in glass:
        obj.data.polygons[index].material_index = 1
    print(f"Glass faces: {len(glass)} of {len(obj.data.polygons)}")


# -------------------------------------------------
# ORIGIN
# -------------------------------------------------

bpy.context.view_layer.objects.active = obj

bpy.ops.object.origin_set(
    type="ORIGIN_GEOMETRY",
    center="BOUNDS",
)
if "--pivot" in sys.argv:
    # Kit modules: walls stand on their origin (bottom_center); a floor's walkable top sits at it (top_center).
    pivot = sys.argv[sys.argv.index("--pivot") + 1]
    if pivot not in ("center", "bottom_center", "top_center", "grip"):
        raise SystemExit(f"--pivot must be center, bottom_center, top_center or grip, got {pivot!r}")
    if pivot == "grip":
        # A weapon is held at its origin: the centre of the vertices under the concept's grip mask.
        group = obj.vertex_groups.get("slopforge_grip")
        held = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices
                if group and any(item.group == group.index for item in vertex.groups)]
        if not held:
            raise SystemExit("--pivot grip needs --concept and a --grip-mask that covers part of the mesh")
        bpy.context.scene.cursor.location = sum(held, Vector()) / len(held)
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    elif pivot != "center":
        heights = [(obj.matrix_world @ Vector(corner)).z for corner in obj.bound_box]
        bpy.context.scene.cursor.location = Vector((obj.location.x, obj.location.y,
                                                    min(heights) if pivot == "bottom_center" else max(heights)))
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")

# -------------------------------------------------
# MOVING PARTS (weapons)
# -------------------------------------------------

if not mesh_only and parts_table is not None:
    anchors = {value.split("=")[0]: value.split("=")[1].split("-") for index, value in enumerate(sys.argv)
               if index and sys.argv[index - 1] == "--anchor"}
    # Hybrid parts are pieces of one generated surface: the separation leaves them open where they were cut apart,
    # closed here by the interface between them within what the face budget leaves (separate_tagged)
    close = bool(json.loads(Path(sys.argv[sys.argv.index("--parts-json") + 1]).read_text()).get("close_openings"))
    basecolor_image = next((image for image in bpy.data.images if basecolor_path and
                            Path(bpy.path.abspath(image.filepath)).resolve() == Path(basecolor_path).resolve()), None)
    children = separate_tagged(obj, parts_table, contact=0.01 * max(obj.dimensions), anchors=anchors, close=close,
                               basecolor=basecolor_image, face_budget=target_faces)
    for child in children:
        print(f"Part {child.name} ({child['slopforge_part']}): {len(child.data.polygons)} faces, "
              f"pivot {[round(v, 4) for v in child.location]}")
    # --motion name=axis:low..high: each part swept through its declared range against the rest of the model; the
    # gate (part_penetration) retries a seed whose part turns or slides into the body (docs/WEAPONS.md, Axes).
    motions = {value.split("=")[0]: value.split("=")[1] for index, value in enumerate(sys.argv)
               if index and sys.argv[index - 1] == "--motion"}
    penetration = {}
    for child in children:
        if child.name in motions:
            axis, span = motions[child.name].split(":")
            low, high = (float(bound) for bound in span.split(".."))
            others = [obj, *[other for other in children if other is not child]]
            penetration[child.name] = sweep_penetration(child, others, axis, low, high)
            print(f"Part {child.name} ({child['slopforge_part']}): {penetration[child.name]:.3f} of its vertices "
                  f"deep inside the body through {axis} {low:g}..{high:g}")
    if penetration:
        obj["slopforge_part_penetration"] = json.dumps(penetration)
    # The model seen from 14 directions, at rest and with each part at the far end of its range: the share of what
    # is seen that is the back of a face, a hole a moved part uncovers (gate part_open; docs/WEAPONS.md)
    if motions:
        model = [obj, *children]
        holes = {"rest": visible_backfaces(model)}
        for child in children:
            if child.name in motions:
                axis, span = motions[child.name].split(":")
                low, high = (float(bound) for bound in span.split(".."))
                far = low if abs(low) > abs(high) else high
                holes[child.name] = visible_backfaces(model, {child.name: motion_matrix(child, axis, far)})
        print(f"Backs of faces seen: {holes}")
        obj["slopforge_visible_backfaces"] = json.dumps(holes)
elif not mesh_only:
    for name, kind, _mask in part_specs():
        part = separate_part(obj, name, kind, basecolor=next(
            (image for image in bpy.data.images if basecolor_path and Path(bpy.path.abspath(image.filepath)).resolve()
             == basecolor_path), None))
        if part is None:
            print(f"Part {name} ({kind}): too few faces under its mask; not separated")
        else:
            print(f"Part {name} ({kind}): {len(part.data.polygons)} faces, pivot {[round(v, 4) for v in part.location]}")

if preview_dir:
    render_previews(obj, preview_dir, output_fbx.stem)


# -------------------------------------------------
# SAVE BLEND
# -------------------------------------------------

bpy.ops.wm.save_as_mainfile(
    filepath=str(output_blend)
)

print(f"BLEND: {output_blend}")


# -------------------------------------------------
# EXPORT FBX
# -------------------------------------------------

bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
for child in obj.children:  # a weapon's moving parts
    child.select_set(True)

bpy.context.view_layer.objects.active = obj

bpy.ops.export_scene.fbx(
    filepath=str(output_fbx),
    use_selection=True,
    object_types={"MESH"},
    axis_forward="-Z",
    axis_up="Y",
    apply_unit_scale=True,
    bake_space_transform=False,
    add_leaf_bones=False,
    path_mode="COPY",
    embed_textures=True,
    use_custom_props=True,  # a moving part's kind (slopforge_part) reaches the engine and FBX inspection
)

print(f"FBX: {output_fbx}")
