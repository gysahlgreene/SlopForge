"""Prepare a weapon generated as parts (processing/part_model.py): reduce each part to its share of the face budget,
unwrap every part into one base-colour atlas with a metallic atlas by part, and export the parts as named nodes for
the final pass (prepare_model.py --parts-json), which tags, orients and separates them.

Usage: blender --background --python prepare_parts.py -- parts.glb processed.glb processed.blend
           --parts-json parts.json --face-budget N --basecolor-output atlas.png --metallic-output metal.png
           [--texture-size 2048] [--metal NAME=0|1 ...]
"""
import json
import sys
from pathlib import Path

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mesh_cleanup import remove_isolated_single_faces  # noqa: E402

MIN_SHARE = 0.02  # a trigger keeps at least this share of the budget whatever its area


def get_args():
    argv = sys.argv[sys.argv.index("--") + 1:]
    if len(argv) < 3:
        raise SystemExit("Expected: parts.glb processed.glb processed.blend --parts-json ... --face-budget ...")
    options = {"--texture-size": "2048"}
    metal = {}
    index = 3
    while index < len(argv):
        if argv[index] == "--metal":
            name, _, value = argv[index + 1].partition("=")
            metal[name] = float(value)
        else:
            options[argv[index]] = argv[index + 1]
        index += 2
    for key in ("--parts-json", "--face-budget", "--basecolor-output", "--metallic-output"):
        if key not in options:
            raise SystemExit(f"{key} is required")
    return (Path(argv[0]).resolve(), Path(argv[1]).resolve(), Path(argv[2]).resolve(), Path(options["--parts-json"]),
            int(options["--face-budget"]), Path(options["--basecolor-output"]), Path(options["--metallic-output"]),
            int(options["--texture-size"]), metal)


def reduce_part(obj, target):
    """Weld, drop stray faces and collapse-decimate to the target, with prepare_model's 0.95 ratio rule."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=max(obj.dimensions) * 1e-6)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    remove_isolated_single_faces(obj.data)
    faces = len(obj.data.polygons)
    while faces > target:
        modifier = obj.modifiers.new(name="PartDecimate", type="DECIMATE")
        modifier.decimate_type = "COLLAPSE"
        modifier.ratio = 0.95 * target / faces
        modifier.use_collapse_triangulate = True
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        reduced = len(obj.data.polygons)
        if reduced >= faces:
            raise SystemExit(f"Cannot reduce part {obj.name} to {target} faces")
        faces = reduced
    return faces


def surface_area(obj):
    return sum(polygon.area for polygon in obj.data.polygons)


def bake_atlases(objects, texture_size, basecolor_output, metallic_output, metal):
    """One atlas UV layout over every part; base colour baked from each part's own texture, metallic from each
    part's declared value."""
    for obj in objects:
        obj.data.uv_layers.new(name="atlas")
        obj.data.uv_layers["atlas"].active = True  # the bake target
        obj.data.uv_layers[0].active_render = True  # what the parts' own textures are read through
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    margin = 4 / texture_size
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=margin)
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(rotate=True, margin=margin, shape_method="CONCAVE")
    bpy.ops.object.mode_set(mode="OBJECT")
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.render.bake.margin = 4  # the islands are packed 4 texels apart: a wider margin bleeds one part's metallic into its neighbour's
    # Both atlases are emission bakes: a diffuse bake of a glTF material is black where it is metallic (glTF's
    # default metallicFactor is 1), so the part's base colour is wired straight into an emission shader instead.
    for kind, output in (("colour", basecolor_output), ("metal", metallic_output)):
        target = bpy.data.images.new(f"atlas_{kind}", width=texture_size, height=texture_size, alpha=False)
        if kind == "metal":
            target.colorspace_settings.name = "Non-Color"
        for obj in objects:
            for material in obj.data.materials:
                if material is None:
                    continue
                material.use_nodes = True
                nodes, links = material.node_tree.nodes, material.node_tree.links
                if kind == "colour":
                    principled = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
                    source = principled.inputs["Base Color"] if principled else None
                else:
                    source = None
                emission = nodes.new("ShaderNodeEmission")
                if source is not None and source.is_linked:
                    links.new(source.links[0].from_socket, emission.inputs["Color"])
                elif source is not None:
                    emission.inputs["Color"].default_value = source.default_value
                else:  # the metallic atlas: this part's declared value, flat
                    emission.inputs["Color"].default_value = (metal.get(obj.name, 1.0),) * 3 + (1.0,)
                out = next((node for node in nodes if node.type == "OUTPUT_MATERIAL"), None) or nodes.new("ShaderNodeOutputMaterial")
                links.new(emission.outputs["Emission"], out.inputs["Surface"])
                node = nodes.new("ShaderNodeTexImage")
                node.image = target
                nodes.active = node
        bpy.ops.object.bake(type="EMIT", use_selected_to_active=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        target.filepath_raw, target.file_format = str(output), "PNG"
        target.save()
    for obj in objects:
        while len(obj.data.uv_layers) > 1:
            obj.data.uv_layers.remove(obj.data.uv_layers[0])
        obj.data.uv_layers[0].name = "UVMap"
        obj.data.materials.clear()


(parts_glb, processed_glb, processed_blend, parts_json, face_budget, basecolor_output, metallic_output, texture_size,
 metal) = get_args()
table = json.loads(parts_json.read_text())["parts"]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(parts_glb))
objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
if not objects:
    raise SystemExit("No part meshes found.")
unknown = [obj.name for obj in objects if obj.name not in table]
if unknown:
    raise SystemExit(f"Parts GLB has nodes not in parts.json: {unknown}")
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
areas = {obj.name: surface_area(obj) for obj in objects}
total = sum(areas.values()) or 1.0
shares = {name: max(area / total, MIN_SHARE) for name, area in areas.items()}
scale = sum(shares.values())
for obj in objects:
    target = max(8, int(face_budget * shares[obj.name] / scale))
    faces = reduce_part(obj, target)
    print(f"Part {obj.name}: {faces} faces (target {target})")
bake_atlases(objects, texture_size, basecolor_output, metallic_output, metal)
print(f"Atlas: {basecolor_output}")
bpy.ops.object.select_all(action="DESELECT")
for obj in objects:
    obj.select_set(True)
processed_glb.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=str(processed_glb), export_format="GLB", use_selection=True)
bpy.ops.wm.save_as_mainfile(filepath=str(processed_blend))
print(f"GLB: {processed_glb}")
