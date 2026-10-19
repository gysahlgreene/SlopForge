"""Project the front concept image onto a generated character's base color.

Usage: blender --background --python project_concept.py -- request.json

request.json: {"model": textured.glb, "basecolor": in.png, "concept": cutout.png (RGBA),
               "output": out.png, "report": report.json, "size": optional, default the base color's}

TRELLIS bakes base color from its voxel field, which blurs faces and fine print (eyes become
slits). Character concepts are front views in an A-pose, so the concept itself can be projected
orthographically along the model's front axis (-Y) onto surfaces that face the camera and are not
hidden behind other geometry; the voxel color stays everywhere else. The concept silhouette is
fitted to the model's bounds; a reconstruction whose proportions differ from the concept is left
unprojected and reported, because projection would paint features onto the wrong surfaces.
"""
import json
import sys
import traceback

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

MAX_ASPECT_ERROR = 0.05
SMOOTHING_ROUNDS = 4


def run(request):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=request["model"])
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    if len(meshes) != 1:
        raise ValueError(f"Expected one mesh in {request['model']}, found {len(meshes)}")
    obj = meshes[0]
    mesh = obj.data
    world = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    low = Vector([min(point[axis] for point in world) for axis in range(3)])
    high = Vector([max(point[axis] for point in world) for axis in range(3)])

    concept = bpy.data.images.load(request["concept"])
    width, height = concept.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    concept.pixels.foreach_get(pixels)
    mask = pixels.reshape(height, width, 4)[:, :, 3] > 0.5
    rows, columns = np.where(mask.any(axis=1))[0], np.where(mask.any(axis=0))[0]
    if not len(rows):
        raise ValueError("Concept cutout has no opaque pixels")
    x0, x1, y0, y1 = columns[0], columns[-1], rows[0], rows[-1]  # Blender pixel rows start at the bottom
    model_aspect = (high.x - low.x) / (high.z - low.z)
    concept_aspect = ((x1 - x0) / width) / ((y1 - y0) / height) * width / height
    aspect_error = abs(model_aspect / concept_aspect - 1)
    report = {"model_aspect": round(model_aspect, 4), "concept_aspect": round(concept_aspect, 4),
              "aspect_error": round(aspect_error, 4)}
    if aspect_error > MAX_ASPECT_ERROR:
        return {**report, "status": "skipped",
                "reason": f"model and concept proportions differ by {aspect_error:.1%} (> {MAX_ASPECT_ERROR:.0%})"}

    # Visibility from the front: a vertex is seen when a ray towards the camera (-Y) escapes the mesh.
    tree = BVHTree.FromPolygons(world, [polygon.vertices[:] for polygon in mesh.polygons])
    offset = (high - low).length * 1e-4
    visible = [0.0] * len(mesh.vertices)
    for index, (point, vertex) in enumerate(zip(world, mesh.vertices)):
        normal = (obj.matrix_world.to_3x3() @ vertex.normal).normalized()
        if normal.y < 0:
            hit = tree.ray_cast(point + normal * offset, Vector((0, -1, 0)))
            visible[index] = 0.0 if hit[0] is not None else 1.0
    # Soften the per-vertex test over mesh neighbours so transitions do not follow triangle edges;
    # only ever lower a value, so the projection never bleeds onto surfaces hidden from the front.
    neighbours = [[] for _ in mesh.vertices]
    for edge in mesh.edges:
        a, b = edge.vertices
        neighbours[a].append(b)
        neighbours[b].append(a)
    for _ in range(SMOOTHING_ROUNDS):
        visible = [min(value, (value + sum(visible[other] for other in near)) / (1 + len(near)))
                   for value, near in zip(visible, neighbours)]
    attribute = mesh.color_attributes.new("front_visible", "FLOAT_COLOR", "POINT")
    attribute.data.foreach_set("color", [value for item in visible for value in (item, item, item, 1.0)])

    material = bpy.data.materials.new("ConceptProjection")
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    geometry = nodes.new("ShaderNodeNewGeometry")
    position = nodes.new("ShaderNodeSeparateXYZ")
    links.new(geometry.outputs["Position"], position.inputs[0])

    def linear(socket, scale, shift):
        node = nodes.new("ShaderNodeMath")
        node.operation = "MULTIPLY_ADD"
        links.new(socket, node.inputs[0])
        node.inputs[1].default_value, node.inputs[2].default_value = scale, shift
        return node.outputs[0]

    scale_x = (x1 - x0) / width / (high.x - low.x)
    scale_z = (y1 - y0) / height / (high.z - low.z)
    coordinates = nodes.new("ShaderNodeCombineXYZ")
    links.new(linear(position.outputs["X"], scale_x, x0 / width - scale_x * low.x), coordinates.inputs["X"])
    links.new(linear(position.outputs["Z"], scale_z, y0 / height - scale_z * low.z), coordinates.inputs["Y"])
    projected = nodes.new("ShaderNodeTexImage")
    projected.image, projected.extension, projected.interpolation = concept, "CLIP", "Cubic"
    links.new(coordinates.outputs[0], projected.inputs[0])
    base = nodes.new("ShaderNodeTexImage")
    base.image = bpy.data.images.load(request["basecolor"])
    base.image.colorspace_settings.name = "sRGB"
    links.new(nodes.new("ShaderNodeUVMap").outputs[0], base.inputs[0])
    # Weight: surfaces facing the camera (normal.y from -0.45 to -0.8 ramps 0 -> 1), seen from the
    # front, inside the concept silhouette. Grazing surfaces keep the voxel color, which avoids smears.
    normal = nodes.new("ShaderNodeSeparateXYZ")
    links.new(geometry.outputs["Normal"], normal.inputs[0])
    facing = nodes.new("ShaderNodeMapRange")
    facing.inputs["From Min"].default_value, facing.inputs["From Max"].default_value = -0.45, -0.8
    links.new(normal.outputs["Y"], facing.inputs["Value"])
    seen = nodes.new("ShaderNodeVertexColor")
    seen.layer_name = "front_visible"
    weight = facing.outputs[0]
    for socket in (projected.outputs["Alpha"], seen.outputs["Color"]):
        product = nodes.new("ShaderNodeMath")
        product.operation = "MULTIPLY"
        links.new(weight, product.inputs[0])
        links.new(socket, product.inputs[1])
        weight = product.outputs[0]
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    links.new(weight, mix.inputs["Factor"])
    links.new(base.outputs["Color"], mix.inputs[6])
    links.new(projected.outputs["Color"], mix.inputs[7])
    links.new(mix.outputs[2], emission.inputs["Color"])
    links.new(emission.outputs[0], output.inputs["Surface"])
    size = int(request.get("size") or base.image.size[0])
    target = bpy.data.images.new("ProjectedBaseColor", size, size, alpha=False)
    target_node = nodes.new("ShaderNodeTexImage")
    target_node.image = target
    nodes.active = target_node
    mesh.materials.clear()
    mesh.materials.append(material)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.bake(type="EMIT", margin=16)
    target.filepath_raw, target.file_format = request["output"], "PNG"
    target.save()
    return {**report, "status": "projected", "front_visible_vertex_fraction": round(sum(visible) / len(visible), 4)}


def main():
    request = json.loads(open(sys.argv[sys.argv.index("--") + 1]).read())
    try:
        result = run(request)
    except Exception as exc:
        result = {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
    with open(request["report"], "w") as stream:
        json.dump(result, stream, indent=2)
    if result["status"] == "failed":
        raise SystemExit(result["error"])


main()
