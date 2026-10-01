import bpy
import sys
from pathlib import Path
from mathutils import Vector


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
        textures[i] = Path(value).resolve()

    face_budget = TARGET_FACES
    if "--face-budget" in args:
        index = args.index("--face-budget")
        try:
            face_budget = int(args[index + 1])
        except (IndexError, ValueError):
            raise SystemExit("--face-budget must be followed by a positive integer")
        if face_budget <= 0:
            raise SystemExit("--face-budget must be a positive integer")

    return (
        input_glb,
        output_fbx,
        output_blend,
        face_budget,
        *textures,
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
    node.image = bpy.data.images.load(str(path), check_existing=True)

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


(
    input_glb,
    output_fbx,
    output_blend,
    target_faces,
    basecolor_path,
    normal_path,
    roughness_path,
    metallic_path,
    emission_path,
) = get_args()


if not input_glb.exists():
    raise SystemExit(f"Input GLB missing: {input_glb}")


output_fbx.parent.mkdir(parents=True, exist_ok=True)
output_blend.parent.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------
# START CLEAN
# -------------------------------------------------

bpy.ops.wm.read_factory_settings(use_empty=True)


# -------------------------------------------------
# IMPORT GLB
# -------------------------------------------------

bpy.ops.import_scene.gltf(filepath=str(input_glb))

mesh_objects = [
    obj
    for obj in bpy.context.scene.objects
    if obj.type == "MESH"
]

if not mesh_objects:
    raise SystemExit("No mesh objects found.")


# -------------------------------------------------
# JOIN MESHES
# -------------------------------------------------

bpy.ops.object.select_all(action="DESELECT")

for obj in mesh_objects:
    obj.select_set(True)

bpy.context.view_layer.objects.active = mesh_objects[0]

if len(mesh_objects) > 1:
    bpy.ops.object.join()

obj = bpy.context.view_layer.objects.active


# -------------------------------------------------
# APPLY INITIAL TRANSFORMS
# -------------------------------------------------

bpy.ops.object.transform_apply(
    location=False,
    rotation=True,
    scale=True,
)


# -------------------------------------------------
# CENTER + NORMALIZE SCALE
# -------------------------------------------------

minimum, maximum = combined_bounds([obj])

size = maximum - minimum
max_dimension = max(size.x, size.y, size.z, 1e-6)

offset = Vector((
    -(minimum.x + maximum.x) / 2.0,
    -(minimum.y + maximum.y) / 2.0,
    -minimum.z,
))

obj.location += offset

obj.scale *= 1.0 / max_dimension

bpy.ops.object.transform_apply(
    location=False,
    rotation=False,
    scale=True,
)


# -------------------------------------------------
# GAME-READY DECIMATION
# -------------------------------------------------

face_count = len(obj.data.polygons)

print(f"Input faces: {face_count}")

if face_count > target_faces:
    ratio = target_faces / face_count

    modifier = obj.modifiers.new(
        name="GameReadyDecimate",
        type="DECIMATE",
    )

    modifier.decimate_type = "COLLAPSE"
    modifier.ratio = ratio
    modifier.use_collapse_triangulate = True

    bpy.context.view_layer.objects.active = obj

    bpy.ops.object.modifier_apply(
        modifier=modifier.name
    )

print(f"Output faces: {len(obj.data.polygons)}")


# -------------------------------------------------
# SMOOTH SHADING
# -------------------------------------------------

for polygon in obj.data.polygons:
    polygon.use_smooth = True


# -------------------------------------------------
# UV UNWRAP
# -------------------------------------------------

bpy.context.view_layer.objects.active = obj
obj.select_set(True)

bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")

bpy.ops.uv.smart_project(
    angle_limit=1.15192,
    island_margin=0.025,
)

bpy.ops.object.mode_set(mode="OBJECT")


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


# Base Color

tex = load_texture(
    nodes,
    basecolor_path,
    non_color=False,
)

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
