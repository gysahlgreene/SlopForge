import unittest

import numpy as np
from PIL import Image, ImageDraw

from slopforge.emitters import concept_emitter_mask, project_to_texture
from slopforge.unity_material import emitter_colour_mask

AMBER = (224, 160, 48)


def _concept():
    # rembg keeps the backdrop colour under transparent pixels; the object is a graphite box with a lens whose
    # body is a darker amber than declared and whose highlight matches it, plus a copper glint on another part.
    image = Image.new("RGBA", (200, 200), (215, 215, 215, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 50, 160, 150), fill=(60, 60, 60, 255))
    draw.ellipse((80, 80, 120, 120), fill=(170, 110, 20, 255))
    draw.ellipse((86, 86, 104, 104), fill=(226, 162, 50, 255))
    draw.rectangle((44, 56, 52, 64), fill=(220, 150, 60, 255))
    return image


class EmitterProjectionTests(unittest.TestCase):
    def test_concept_lens_reaches_its_texels_and_glints_on_other_parts_do_not(self):
        concept = _concept()
        flat = Image.alpha_composite(Image.new("RGBA", concept.size, (0, 0, 0, 255)), concept).convert("RGB")
        seed = np.asarray(emitter_colour_mask(flat, AMBER)) > 127
        self.assertTrue(seed[60, 48])  # the colour rule alone also takes the copper glint
        emitter = concept_emitter_mask(concept, AMBER, seed)
        # A render that shows the concept's view one to one, with UVs that address a 200 x 200 texture likewise.
        y, x = np.mgrid[0:200, 0:200]
        alpha = np.asarray(concept)[..., 3] > 127
        uv = np.stack([(x + 0.5) / 200, 1 - (y + 0.5) / 200, np.zeros_like(x, float), alpha.astype(float)], -1)
        texture = np.asarray(project_to_texture(concept, emitter, concept, uv, (200, 200))) > 127
        lens_mask = (x - 100) ** 2 + (y - 100) ** 2 <= 19 ** 2
        self.assertGreater(texture[lens_mask].mean(), 0.9)
        self.assertFalse(texture[56:65, 44:53].any())
        self.assertFalse(texture[~alpha].any())

    def test_nothing_is_projected_when_the_concept_has_no_emitter(self):
        concept = _concept()
        empty = np.zeros((200, 200), bool)
        uv = np.zeros((200, 200, 4))
        self.assertEqual(project_to_texture(concept, empty, concept, uv, (64, 64)).getbbox(), None)


import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"
FIXTURE = """import bpy, math, sys
from pathlib import Path
from mathutils import Vector
out = Path(sys.argv[-1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1)
cube = bpy.context.object
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.subdivide(number_cuts=12)
bpy.ops.uv.smart_project(island_margin=0.02)
bpy.ops.object.mode_set(mode="OBJECT")

def disc_material(name, colour):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    geometry = nodes.new("ShaderNodeNewGeometry")
    distance = nodes.new("ShaderNodeVectorMath")
    distance.operation = "DISTANCE"
    distance.inputs[1].default_value = (0, -0.5, 0)  # centre of the front face
    links.new(geometry.outputs["Position"], distance.inputs[0])
    inside = nodes.new("ShaderNodeMath")
    inside.operation = "LESS_THAN"
    inside.inputs[1].default_value = 0.18
    links.new(distance.outputs["Value"], inside.inputs[0])
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs[6].default_value = (0.04, 0.04, 0.045, 1)
    mix.inputs[7].default_value = colour
    links.new(inside.outputs[0], mix.inputs["Factor"])
    emission = nodes.new("ShaderNodeEmission")
    links.new(mix.outputs[2], emission.inputs["Color"])
    links.new(emission.outputs[0], nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    return material, nodes

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.view_settings.view_transform = "Standard"
# The bake keeps the lens dark brown, as TRELLIS.2 baked the relay's amber lens.
material, nodes = disc_material("Bake", (0.08, 0.016, 0.004, 1))
cube.data.materials.append(material)
image = bpy.data.images.new("bake", 512, 512)
target = nodes.new("ShaderNodeTexImage")
target.image = image
nodes.active = target
scene.cycles.samples = 1
bpy.context.view_layer.objects.active = cube
cube.select_set(True)
bpy.ops.object.bake(type="EMIT", margin=8)
image.filepath_raw, image.file_format = str(out / "bake.png"), "PNG"
image.save()
bpy.ops.export_scene.gltf(filepath=str(out / "mesh.glb"), export_format="GLB", use_selection=True)
# The concept: a perspective three-quarter view with the lens in its declared amber.
cube.data.materials.clear()
cube.data.materials.append(disc_material("Concept", (0.745, 0.352, 0.03, 1))[0])
camera = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
bpy.context.collection.objects.link(camera)
theta, phi = math.radians(-30), math.radians(15)
towards = Vector((math.sin(theta) * math.cos(phi), -math.cos(theta) * math.cos(phi), math.sin(phi)))
camera.location = towards * 4
camera.rotation_euler = (-towards).to_track_quat("-Z", "Y").to_euler()
scene.camera = camera
scene.render.resolution_x = scene.render.resolution_y = 512
scene.render.film_transparent = True
scene.cycles.samples = 4
scene.render.filepath = str(out / "concept.png")
bpy.ops.render.render(write_still=True)
"""


class PaleEmitterProjectionTests(unittest.TestCase):
    def test_pale_emitters_keep_the_colour_rule_and_skip_the_render(self):
        # Live lantern 2026-10-21: the pale rule on the concept took granite highlights, and 90% of the
        # projected texels were stone, while paper bakes pale enough for the colour rule on the bake.
        from unittest.mock import patch
        from slopforge.pipelines.model import _project_concept_emitters
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _concept().save(root / "concept.png")
            with patch("slopforge.pipelines.model.subprocess.run", side_effect=AssertionError("no render")):
                masks, report = _project_concept_emitters(root, {}, root / "concept.png", root / "mesh.glb",
                                                          {"directory": root, "basecolor": root / "base.png"},
                                                          [(None, (255, 178, 102))])
        self.assertIsNone(masks)
        self.assertEqual(report["status"], "skipped")
        self.assertIn("pale", report["reason"])


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class ConceptEmitterBlenderTests(unittest.TestCase):
    def test_lens_baked_dark_is_found_through_the_concept_and_lands_on_its_texels(self):
        from slopforge.pipelines.model import _project_concept_emitters
        from slopforge.unity_material import derive_emission
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture.py").write_text(FIXTURE)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(root / "fixture.py"),
                            "--", str(root)], check=True, capture_output=True, text=True)
            targets = [(AMBER, AMBER)]
            self.assertEqual(derive_emission(root / "bake.png", root / "colour_only.png", targets), 0)
            config = {"asset_pipeline": {"tools": {"blender": BLENDER}}}
            masks, report = _project_concept_emitters(root, config, root / "concept.png", root / "mesh.glb",
                                                      {"directory": root, "basecolor": root / "bake.png"}, targets)
            self.assertEqual(report["status"], "rendered", report)
            self.assertGreater(report["silhouette_iou"], 0.9)
            self.assertFalse((root / "concept_view_uv.npy").exists())
            fraction = derive_emission(root / "bake.png", root / "emission.png", targets, extra_masks=masks)
            self.assertGreater(fraction, 0.001)
            mask = np.asarray(masks[0]) > 127
            lens = np.asarray(Image.open(root / "bake.png").convert("RGB")).astype(int)
            lens = (lens[..., 0] > 40) & (lens[..., 1] < 40)  # the baked dark-brown disc
            self.assertGreater(lens[mask].mean(), 0.6, json.dumps(report))
            self.assertGreater(mask[lens].mean(), 0.5)


if __name__ == "__main__":
    unittest.main()
