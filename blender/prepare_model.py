import bpy
import sys
from pathlib import Path
from mathutils import Vector
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mesh_cleanup import remove_isolated_single_faces


TARGET_FACES = 30000


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
    for option in ("--surface-source", "--preview-dir", "--material-scale", "--stage-mesh-output"):
        if option in args:
            index = args.index(option)
            try:
                options[option] = args[index + 1]
            except IndexError:
                raise SystemExit(f"{option} requires a value")

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
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Preview World")
    scene.world.color = (0.42, 0.48, 0.55)

    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    bounds_min = Vector(tuple(min(point[axis] for point in corners) for axis in range(3)))
    bounds_max = Vector(tuple(max(point[axis] for point in corners) for axis in range(3)))
    target = (bounds_min + bounds_max) * 0.5
    frame_scale = max(bounds_max - bounds_min) * 1.25
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

    views = {"front": Vector((0, -3, 0)), "side": Vector((3, 0, 0)), "rear": Vector((0, 3, 0)),
             "three_quarter": Vector((2, -2, 0))}
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


# -------------------------------------------------
# JOIN MESHES
# -------------------------------------------------

if not reuse_stage_mesh:
    bpy.ops.object.select_all(action="DESELECT")

    for obj in mesh_objects:
        obj.select_set(True)

    bpy.context.view_layer.objects.active = mesh_objects[0]

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


# -------------------------------------------------
# GAME-READY DECIMATION
# -------------------------------------------------

if mesh_only:
    minimum, maximum = combined_bounds([obj])
    modifier = obj.modifiers.new(name="CleanReconstruction", type="REMESH")
    modifier.mode = "VOXEL"
    modifier.voxel_size = max(maximum - minimum) / voxel_resolution
    modifier.use_smooth_shade = True
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
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.003)
    bpy.ops.object.mode_set(mode="OBJECT")
if mesh_only:
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
    bsdf = bake_basecolor(obj, material, surface_source_path, basecolor_path, material_scale,
                         {"normal": normal_path, "roughness": roughness_path,
                          "metallic": metallic_path, "emission": emission_path})

tex = load_texture(nodes, basecolor_path, non_color=False)

if tex is not None:
    socket = get_socket(bsdf, "Base Color")
    if socket:
        links.new(tex.outputs["Color"], socket)


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


# -------------------------------------------------
# ORIGIN
# -------------------------------------------------

bpy.context.view_layer.objects.active = obj

bpy.ops.object.origin_set(
    type="ORIGIN_GEOMETRY",
    center="BOUNDS",
)

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
)

print(f"FBX: {output_fbx}")
