import bpy, sys, json
a = json.loads(sys.argv[sys.argv.index("--") + 1])
body = bpy.data.objects["Human"]
skin = bpy.data.images.load(a["skin"])
for n in body.data.materials[0].node_tree.nodes:
    if n.type == "TEX_IMAGE":
        n.image = skin
for o in bpy.data.objects:
    if o.type == "MESH" and "eyebrow" in o.name:
        bpy.data.objects.remove(o, do_unlink=True)
hair = next(o for o in bpy.data.objects if o.type == "MESH" and "hair" in o.name.lower() or "short" in o.name)
for m in hair.data.materials:
    tree = m.node_tree
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    image = next((n for n in tree.nodes if n.type == "TEX_IMAGE" and n.image and "diffuse" in n.image.name), None)
    if bsdf and image:
        mul = tree.nodes.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs["Factor"].default_value = 1
        tree.links.new(image.outputs[0], mul.inputs[6]); mul.inputs[7].default_value = tuple(a["hair_tint"]) + (1,)
        tree.links.new(mul.outputs[2], bsdf.inputs["Base Color"])
bpy.ops.wm.save_as_mainfile(filepath=a["output"])

eye_tint = a.get("eye_tint")
if eye_tint:
    eyes = next(o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith("high-poly"))
    for m in eyes.data.materials:
        tree = m.node_tree; bsdf = next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED")
        image = next(n for n in tree.nodes if n.type == "TEX_IMAGE")
        mix = tree.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs["Factor"].default_value = 1
        mix.inputs[7].default_value = (*eye_tint, 1); tree.links.new(image.outputs[0], mix.inputs[6]); tree.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    bpy.ops.wm.save_as_mainfile(filepath=a["output"])
