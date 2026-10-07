"""Normalize a character GLB/FBX and bake its source materials onto new UVs."""

import json
import sys
from pathlib import Path

import bmesh
import bpy


def active_only(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def has_map(obj, channel):
    socket = {"base_color": "Base Color", "roughness": "Roughness",
              "metallic": "Metallic", "normal": "Normal"}[channel]
    return any(mat and mat.use_nodes and any(
        node.type == "BSDF_PRINCIPLED" and node.inputs[socket].is_linked
        for node in mat.node_tree.nodes) for mat in obj.data.materials)


def bake(source, target, image, channel):
    nodes = target.active_material.node_tree.nodes
    texture = nodes.get(f"BakeTarget_{channel}")
    texture.image = image
    nodes.active = texture
    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    settings = bpy.context.scene.render.bake
    settings.use_selected_to_active = True
    settings.cage_extrusion = 0.15
    settings.margin = 4
    if channel == "base_color":
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"})
    elif channel == "normal":
        bpy.ops.object.bake(type="NORMAL")
    else:
        # Copy materials so temporary emission wiring cannot change the source.
        originals = list(source.data.materials)
        copies = []
        try:
            for material in originals:
                duplicate = material.copy()
                copies.append(duplicate)
                tree = duplicate.node_tree
                principled = next(node for node in tree.nodes if node.type == "BSDF_PRINCIPLED")
                output = next(node for node in tree.nodes if node.type == "OUTPUT_MATERIAL")
                emission = tree.nodes.new("ShaderNodeEmission")
                socket = principled.inputs["Roughness" if channel == "roughness" else "Metallic"]
                if socket.is_linked:
                    tree.links.new(socket.links[0].from_socket, emission.inputs["Color"])
                else:
                    emission.inputs["Color"].default_value = (socket.default_value,) * 3 + (1,)
                tree.links.new(emission.outputs[0], output.inputs["Surface"])
            for index, duplicate in enumerate(copies):
                source.data.materials[index] = duplicate
            bpy.ops.object.bake(type="EMIT")
        finally:
            for index, material in enumerate(originals):
                source.data.materials[index] = material
            for duplicate in copies:
                bpy.data.materials.remove(duplicate)
    image.update()
    if not any(image.pixels[index] > 0.001 for index in range(3, len(image.pixels), 4)):
        raise RuntimeError(f"{channel} bake produced an empty image")


def main(request_path):
    request = json.loads(Path(request_path).read_text())
    source_path = Path(request["source"])
    output = Path(request["output"])
    report_path = Path(request["report"])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if source_path.suffix.lower() == ".glb":
        bpy.ops.import_scene.gltf(filepath=str(source_path))
    elif source_path.suffix.lower() == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(source_path))
    else:
        raise ValueError("Source must be GLB or FBX")
    sources = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not sources:
        raise ValueError("Source has no mesh components")
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.samples = 1
    components = []
    channel_results = {key: "absent" for key in ("base_color", "roughness", "metallic", "normal")}
    targets = []
    warnings = []
    for index, source in enumerate(sources):
        if not source.data.polygons:
            raise ValueError(f"Source component {source.name} has no faces")
        active_only(source)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        target = source.copy()
        target.data = source.data.copy()
        bpy.context.collection.objects.link(target)
        target.name = f"Normalized_{source.name}"
        active_only(target)
        dimensions = [max(value, 0.001) for value in source.dimensions]
        face_budget = request.get("face_budget", 60000)
        # GLB export triangulates remesh quads, so size against half the triangle face budget.
        target.data.remesh_voxel_size = max(dimensions) / ((face_budget / 2) ** 0.5) * 1.25
        bpy.ops.object.voxel_remesh()
        mesh = bmesh.new()
        mesh.from_mesh(target.data)
        bmesh.ops.dissolve_degenerate(mesh, edges=mesh.edges, dist=0.000001)
        bmesh.ops.delete(mesh, geom=[v for v in mesh.verts if not v.link_faces], context="VERTS")
        mesh.to_mesh(target.data)
        mesh.free()
        if not target.data.polygons:
            raise RuntimeError(f"Normalization removed component {source.name}")
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
        if not target.data.uv_layers.active:
            raise RuntimeError(f"UV atlas failed for {source.name}")
        target.data.materials.clear()
        material = bpy.data.materials.new(f"Normalized_{index}")
        material.use_nodes = True
        target.data.materials.append(material)
        face_counts = {}
        for polygon in source.data.polygons:
            face_counts[polygon.material_index] = face_counts.get(polygon.material_index, 0) + 1
        component = {"source": source.name, "output": target.name,
                     "source_vertices": len(source.data.vertices), "source_faces": len(source.data.polygons),
                     "source_materials": [mat.name for mat in source.data.materials],
                     "source_material_assignments": [
                         {"slot": slot, "material": source.data.materials[slot].name
                          if slot < len(source.data.materials) and source.data.materials[slot] else None,
                          "face_count": count}
                         for slot, count in sorted(face_counts.items())],
                     "output_vertices": len(target.data.vertices), "output_faces": len(target.data.polygons),
                     "textures": {}}
        for channel in channel_results:
            if channel != "base_color" and not has_map(source, channel):
                continue
            image = bpy.data.images.new(f"{target.name}_{channel}", width=256, height=256, alpha=True)
            if channel != "base_color":
                image.colorspace_settings.name = "Non-Color"
            texture = material.node_tree.nodes.new("ShaderNodeTexImage")
            texture.name = f"BakeTarget_{channel}"
            try:
                bake(source, target, image, channel)
                texture_path = output.parent / f"component_{index}_{channel}.png"
                image.filepath_raw = str(texture_path)
                image.file_format = "PNG"
                image.save()
                component["textures"][channel] = texture_path.name
                channel_results[channel] = "baked"
                principled = material.node_tree.nodes.get("Principled BSDF")
                if channel == "normal":
                    normal_map = material.node_tree.nodes.new("ShaderNodeNormalMap")
                    material.node_tree.links.new(texture.outputs["Color"], normal_map.inputs["Color"])
                    material.node_tree.links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])
                else:
                    input_name = {"base_color": "Base Color", "roughness": "Roughness",
                                  "metallic": "Metallic"}[channel]
                    material.node_tree.links.new(texture.outputs["Color"], principled.inputs[input_name])
            except Exception:
                channel_results[channel] = "failed"
                raise
        components.append(component)
        targets.append(target)
    bpy.ops.object.select_all(action="DESELECT")
    for target in targets:
        target.select_set(True)
    bpy.context.view_layer.objects.active = targets[0]
    bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB", use_selection=True)
    report = {"status": "pass", "components": components, "uv_status": "pass",
              "channels": channel_results, "warnings": warnings, "blender_version": bpy.app.version_string}
    report_path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1])
