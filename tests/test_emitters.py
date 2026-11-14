import unittest

import numpy as np
from PIL import Image, ImageDraw

from slopforge.emitters import concept_emitter_mask, project_to_texture
from slopforge.unity_material import emitter_colour_mask

AMBER = (224, 160, 48)


def _concept():
    # rembg keeps the backdrop colour under transparent pixels; the object is a graphite box with a lens whose
    # body is a darker amber than declared and whose highlight matches it, plus a copper glint on another part in
    # the colour measured on the relay concept's glints (mean 184, 122, 93: within the colour distance, hue 20).
    image = Image.new("RGBA", (200, 200), (215, 215, 215, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 50, 160, 150), fill=(60, 60, 60, 255))
    draw.ellipse((80, 80, 120, 120), fill=(170, 110, 20, 255))
    draw.ellipse((86, 86, 104, 104), fill=(226, 162, 50, 255))
    draw.rectangle((44, 56, 52, 64), fill=(184, 122, 93, 255))
    return image


class EmitterProjectionTests(unittest.TestCase):
    def test_concept_lens_reaches_its_texels_and_glints_on_other_parts_do_not(self):
        concept = _concept()
        flat = Image.alpha_composite(Image.new("RGBA", concept.size, (0, 0, 0, 255)), concept).convert("RGB")
        seed = np.asarray(emitter_colour_mask(flat, AMBER)) > 127
        self.assertFalse(seed[60, 48])  # the colour rule's hue check drops the copper glint
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

    @unittest.expectedFailure  # known limit: only the largest blob is projected (docs/MATERIALS.md)
    def test_every_emitter_of_a_declared_colour_is_projected(self):
        # Round 24's canopy: 12 lenses and a floor disc of one declared colour, foreshortened lenses down to 0.03 of
        # the largest; keeping only the largest blob left 12 dark (2026-11-09). Keeping every blob put the glow on
        # its roof instead, through the bounding-box registration, so it waits for better registration.
        image = Image.new("RGBA", (200, 200), (215, 215, 215, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 40, 180, 160), fill=(60, 60, 60, 255))
        lenses = [(60, 100, 20), (120, 100, 9), (160, 100, 5)]
        for x, y, r in lenses:
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(173, 63, 100, 255))
        flat = Image.alpha_composite(Image.new("RGBA", image.size, (0, 0, 0, 255)), image).convert("RGB")
        emitter = concept_emitter_mask(image, (173, 63, 100), np.asarray(emitter_colour_mask(flat, (173, 63, 100))) > 127)
        for x, y, r in lenses:
            self.assertTrue(emitter[y, x], (x, y, r))

    def test_a_small_emitter_keeps_its_spots_and_every_one_of_them(self):
        # Round 25's automata: two red eyes of about 25 pixels each on an 832-wide concept. The fleck filter
        # (a 7-pixel opening there) removed both, and only the largest blob was kept, so no eye could glow
        # (round 22 refused emissive eyes on all 26 takes). A small emitter is opened by 3 pixels and keeps each blob.
        image = Image.new("RGBA", (832, 400), (215, 215, 215, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((300, 100, 520, 300), fill=(70, 100, 90, 255))  # a verdigris head
        draw.rectangle((383, 176, 410, 190), fill=(76, 40, 22, 255))  # dark rust near the eye's hue, touching it
        for x in (380, 440):
            draw.ellipse((x - 3, 180, x + 3, 186), fill=(140, 20, 10, 255))
        flat = Image.alpha_composite(Image.new("RGBA", image.size, (0, 0, 0, 255)), image).convert("RGB")
        eye = (132, 16, 3)
        self.assertFalse((np.asarray(emitter_colour_mask(flat, eye)) > 127).any())
        seed = np.asarray(emitter_colour_mask(flat, eye, small=True)) > 127
        emitter = concept_emitter_mask(image, eye, seed, every_blob=True)
        self.assertTrue(emitter[183, 380] and emitter[183, 440])
        self.assertFalse(emitter[250, 400])
        self.assertFalse(emitter[183, 400])  # not grown over the rust beside it (round 25's furnace heart)

    def test_a_low_resolution_concept_covers_its_emitter_on_a_larger_texture(self):
        # Round 25's brute: its firebox, ~100 concept pixels across, reached a 4096 texture as scattered dim specks
        # (0.045% of the map), one texel per concept pixel. Here a 50 px concept, a 100 px render and a 400 texture.
        concept = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
        ImageDraw.Draw(concept).rectangle((5, 5, 44, 44), fill=(60, 60, 60, 255))
        emitter = np.zeros((50, 50), bool)
        emitter[15:35, 15:35] = True
        render = concept.resize((100, 100), Image.NEAREST)
        y, x = np.mgrid[0:100, 0:100]
        alpha = np.asarray(render)[..., 3] > 127
        uv = np.stack([(x + 0.5) / 100, 1 - (y + 0.5) / 100, np.zeros_like(x, float), alpha.astype(float)], -1)
        texture = np.asarray(project_to_texture(concept, emitter, render, uv, (400, 400))) > 127
        self.assertGreater(texture[130:270, 130:270].mean(), 0.95)
        self.assertFalse(texture[:100].any())

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


class SideColourProjectionTests(unittest.TestCase):
    def test_a_side_concepts_colour_reaches_both_sides_and_glass_is_kept(self):
        import tempfile
        from pathlib import Path
        from slopforge.emitters import project_side_colours
        from slopforge.validation import _lab
        # A stock drawn walnut (left half) and an iron barrel (right half), baked tan and pale grey. The near render
        # shows the texture's left half, the far one its right half mirrored, so each side has its own texels.
        concept = np.zeros((100, 200, 4), float)
        concept[30:70, 10:100] = (74, 38, 24, 255)
        concept[30:70, 100:190] = (40, 40, 44, 255)
        y, x = np.mgrid[0:100, 0:200]
        inside = (concept[..., 3] > 0).astype(float)
        near_uv = np.stack([(x + 0.5) / 400, 1 - (y + 0.5) / 100, np.zeros_like(x, float), inside], -1)
        far_uv = np.stack([1 - (x + 0.5) / 400, 1 - (y + 0.5) / 100, np.zeros_like(x, float), inside], -1)
        mirrored = concept[:, ::-1]
        texture = np.zeros((100, 400, 4), np.uint8)
        texture[30:70, :] = (170, 130, 90, 255)
        texture[30:70, 190:200] = (170, 130, 90, 90)  # see-through glass at the near side's end
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "basecolor.png"
            Image.fromarray(texture, "RGBA").save(path)
            changed = project_side_colours(path, [(concept, concept, near_uv), (mirrored, mirrored, far_uv)])
            result = np.asarray(Image.open(path).convert("RGBA")).astype(float)
        self.assertGreater(changed, 0.7)
        walnut, iron = _lab(np.array([[74, 38, 24], [40, 40, 44]], float))
        for column in (50, 250):  # the stock on both sides (the far side mirrored onto texels 210-300)
            stock = _lab(result[50:51, column, :3])[0]
            self.assertLess(np.hypot(*(stock[1:] - walnut[1:])), 3)
            self.assertLess(abs(stock[0] - walnut[0]), abs(_lab(np.array([[170, 130, 90]], float))[0][0] - walnut[0]))
        for column in (150, 350):
            self.assertLess(np.hypot(*(_lab(result[50:51, column, :3])[0][1:] - iron[1:])), 3)
        self.assertEqual(tuple(result[50, 195]), (170, 130, 90, 90))  # glass untouched
        self.assertEqual(result[10, 50, 3], 0)  # nothing painted outside the object
