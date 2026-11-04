import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"
spec = importlib.util.spec_from_file_location("character_parts", ROOT / "processing/character_parts.py")
parts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parts)

BRIEF = {"name": "miner", "person": "woman", "their": "her", "they_are": "she is", "who": "a square tired face",
         "hair": "Cropped dark hair.", "eyes": "Small tired eyes.", "clothes": "the jacket and boots",
         "surfaces": "the leather is matte", "style": "A woodcut look with bold lines.", "height": 1.7}

PROBE = """import bpy, json, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=sys.argv[-2])
mesh = next(o for o in bpy.data.objects if o.type == "MESH")
loops = mesh.data.uv_layers.active.data
inside = sum((l.uv.x <= 2/3 + 1e-3 and l.uv.y <= 2/3 + 1e-3) or (l.uv.x >= 2/3 - 1e-3 and l.uv.y >= 2/3 - 1e-3) for l in loops)
json.dump({"materials": len(mesh.data.materials), "uv_inside": inside / len(loops)}, open(sys.argv[-1], "w"))
"""


class PartsTests(unittest.TestCase):
    def test_brass_is_told_from_leather_by_colour(self):
        pixels = np.array([[[200, 160, 70], [54, 38, 27], [120, 120, 120]]], float)
        self.assertEqual(parts.brass_mask(pixels).tolist(), [[True, False, False]])

    def test_only_surfaces_facing_away_from_the_concept_lose_its_painting(self):
        facing = np.array([[-1.0, -0.05, 1.0, 1.0]])
        used = np.array([[True, True, True, False]])
        self.assertEqual(parts.rear_weight(facing, used).tolist(), [[0.0, 1.0, 1.0, 0.0]])

    def test_a_head_keeps_its_own_detail_in_the_paintings_tone(self):
        size = 64
        voxel = np.full((size, size, 3), 100.0)
        voxel[32, 32] = 200.0  # a detail that sits on the shape
        painted = np.full((size, size, 3), (150.0, 100.0, 50.0))
        painted[10:20, 40:44] = 10.0  # a misplaced dark band the painting would bring with it
        out = parts.aligned_colour(painted, voxel, np.ones((size, size), bool), radius=12)
        self.assertGreater(out[32, 32, 0], out[28, 28, 0] * 1.5)
        self.assertGreater(out[5, 5, 0], out[5, 5, 2] * 2)
        self.assertGreater(out[15, 42, 0], 60)

    def test_flattening_a_normal_map_keeps_flat_flat_and_softens_the_rest(self):
        normal = np.array([[[128, 128, 255], [200, 128, 200]]], np.uint8)
        out = parts.flatten_normals(normal, 0.5)
        self.assertLess(abs(int(out[0, 0, 0]) - 128), 2)
        self.assertLess(out[0, 1, 0], 200)
        self.assertGreater(out[0, 1, 2], 200)

    def test_a_covered_heads_leather_counts_and_a_whole_figure_paints_everywhere(self):
        position = np.array([[[0.0, 0.5, 0.25], [0.0, -0.5, 0.25]]], np.float32)
        normal = np.array([[[0.0, 1.0, 0.0], [0.0, -1.0, 0.0]]], np.float32)
        texels = {"position": position, "normal": normal, "used": np.ones((1, 2), bool)}
        colour = np.full((1, 2, 3), 10, np.uint8)
        brown = np.full((8, 8, 3), (120, 70, 40), np.uint8)
        views = {"centre": [0, 0, 0], "extent": 2.0}
        self.assertEqual(parts.project_head_views(colour, texels, views, {180: brown})[1].tolist(), [[True, False]])
        self.assertEqual(parts.project_views(colour, texels, views, {180: brown, 0: brown})[1].tolist(), [[True, True]])
        # A front view stops at the middle: it can't reach a back, even with that back's normal flipped towards it.
        flipped = {"position": np.array([[[0.0, 0.1, 0.25]]], np.float32), "normal": np.array([[[0.0, -1.0, 0.0]]], np.float32), "used": np.ones((1, 1), bool)}
        self.assertEqual(parts.project_views(colour[:, :1], flipped, views, {0: brown})[1].tolist(), [[False]])

    def test_a_body_view_skips_what_something_in_front_hides(self):
        # A hand in front of a coat, one behind the other from this view: tan hands printed on the coat behind them.
        position = np.array([[[0.0, -0.4, 0.25], [0.0, -0.1, 0.25]]], np.float32)
        texels = {"position": position, "normal": np.array([[[0.0, -1.0, 0.0]] * 2], np.float32), "used": np.ones((1, 2), bool)}
        tan = np.full((64, 64, 3), (200, 150, 110), np.uint8)
        self.assertEqual(parts.project_views(np.full((1, 2, 3), 10, np.uint8), texels, {"centre": [0, 0, 0], "extent": 2.0}, {0: tan})[1].tolist(), [[True, False]])

    def test_a_body_view_does_not_paint_its_background(self):
        # The painted figure's outline moves a little from the render's, so texels at the edge landed on the backdrop.
        position = np.array([[[0.0, -0.2, 0.0], [0.8, -0.2, 0.8]]], np.float32)
        texels = {"position": position, "normal": np.array([[[0.0, -1.0, 0.0]] * 2], np.float32), "used": np.ones((1, 2), bool)}
        painting = np.full((64, 64, 3), 128, np.uint8)
        painting[20:44, 20:44] = (60, 40, 30)
        out, changed = parts.project_views(np.full((1, 2, 3), 10, np.uint8), texels, {"centre": [0, 0, 0], "extent": 2.0}, {0: painting})
        self.assertEqual(changed.tolist(), [[True, False]])
        self.assertEqual(out[0, 1].tolist(), [10, 10, 10])

    def test_grey_inside_a_painted_figure_is_not_its_backdrop(self):
        # A highlight on leather can be the backdrop's own grey: taken for backdrop, it left flakes of raw colour on sleeves and lapels.
        painting = np.full((64, 64, 3), 128, np.uint8)
        painting[16:48, 16:48] = (60, 40, 30)
        painting[28:36, 28:36] = 128
        found = parts.backdrop(painting)
        self.assertTrue(found[2, 2])
        self.assertFalse(found[32, 32])
        self.assertFalse(found[22, 22])

    def test_painting_a_body_leaves_its_bare_neck_alone(self):
        # The paintings show an empty collar, so they have no neck to give: it came back in blocks.
        position = np.array([[[0, 0, 0.95], [0, 0, 0.5], [0, 0, 0.96]]], np.float32)
        texels = {"position": position, "used": np.ones((1, 3), bool)}
        colour = np.array([[(225, 150, 90), (225, 150, 90), (40, 35, 30)]], np.uint8)
        position[0, 2, 2] = 1.0  # the top of the figure
        self.assertEqual(parts.neck_skin(colour, texels).tolist(), [[True, False, False]])

    def test_a_smoothed_body_drops_the_generators_normal_map_with_its_lumps(self):
        with tempfile.TemporaryDirectory() as folder:
            body = Path(folder)
            (body / "native_material").mkdir()
            Image.new("RGB", (8, 8), (90, 170, 200)).save(body / "native_material/normal.png")
            self.assertEqual(parts.body_normal(body, {}).getpixel((0, 0)), (90, 170, 200))
            flat = parts.body_normal(body, {"body_smooth": 20})
            self.assertEqual((flat.size, flat.getpixel((0, 0))), ((8, 8), (128, 128, 255)))

    def test_smoothing_a_body_takes_out_small_lumps_keeps_its_size_and_seams(self):
        # Lit, the generator's small lumps read as a chewed coat, and cast the marks on its back, whatever the paint did (2026-11-04).
        script = f"""import sys
import bmesh
import bpy
import numpy as np
sys.path.insert(0, {str(ROOT / "blender")!r})
import join_character_parts as j
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5, radius=1.0)
item = bpy.context.object
editing = bmesh.new(); editing.from_mesh(item.data)
bmesh.ops.split_edges(editing, edges=editing.edges[:400])
editing.to_mesh(item.data); editing.free()
def read():
    found = np.zeros(len(item.data.vertices) * 3); item.data.vertices.foreach_get("co", found); return found.reshape(-1, 3)
points = read()
# Lumps that depend on position alone, so a seam's two copies start together.
lumps = 1 + 0.02 * np.sin(np.round(points, 5) @ np.array([97.0, 61.0, 41.0]))[:, None]
item.data.vertices.foreach_set("co", (points * lumps).ravel()); item.data.update()
before = read(); places = len(np.unique(np.round(before, 5), axis=0))
item.data.normals_split_custom_set_from_vertices([(0.0, 0.0, 1.0)] * len(item.data.vertices))  # as a glTF import leaves them
assert item.data.has_custom_normals
j.smooth_surface(item, 20)
after = read()
radius = np.linalg.norm(after, axis=1)
assert np.linalg.norm(before, axis=1).std() > 3 * radius.std(), (np.linalg.norm(before, axis=1).std(), radius.std())
assert abs(radius.mean() - 1) < 0.02, radius.mean()
assert len(np.unique(np.round(after, 5), axis=0)) == places, "a seam opened"
assert not item.data.has_custom_normals, "the old lumps stay in the normals a glTF brought with it"
print("SMOOTHED", len(before), places)
"""
        done = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script], capture_output=True, text=True, timeout=240)
        self.assertEqual(done.returncode, 0, done.stdout[-1500:] + done.stderr[-800:])
        self.assertIn("SMOOTHED", done.stdout)

    def test_neighbouring_body_views_blend_by_the_angle_round_the_body_not_the_normal(self):
        # Neighbouring texels whose generated normals disagree took different paintings, which made streaks of two different coats.
        around = np.radians(10)
        position = np.array([[[0.4 * np.sin(around), -0.4 * np.cos(around), 0.0], [0.4 * np.sin(around), -0.4 * np.cos(around), 0.02]]], np.float32)
        facing_60 = (np.sin(np.radians(60)), -np.cos(np.radians(60)), 0.0)
        texels = {"position": position, "normal": np.array([[[0.0, -1.0, 0.0], facing_60]], np.float32), "used": np.ones((1, 2), bool)}
        paintings = {0: np.full((64, 64, 3), (200, 30, 30), np.uint8), 60: np.full((64, 64, 3), (30, 30, 200), np.uint8)}
        out, _ = parts.project_views(np.full((1, 2, 3), 10, np.uint8), texels, {"centre": [0, 0, 0], "extent": 2.0}, paintings)
        self.assertEqual(out[0, 0].astype(int).tolist(), out[0, 1].astype(int).tolist())
        self.assertGreater(out[0, 0, 0], 190)

    def test_each_view_says_which_side_it_shows(self):
        self.assertIn("no face", parts.view_note(180))
        self.assertIn("no face", parts.view_note(-135))
        self.assertIn("profile", parts.view_note(90))
        self.assertIn("eyes are open", parts.view_note(40))
        self.assertIn("apron", parts.view_note(180, body=True))
        self.assertEqual(parts.view_note(60, body=True), "")

    def test_paint_grows_over_the_gaps_beside_it(self):
        painted = np.zeros((1, 6, 3))
        painted[0, 2] = 200.0
        changed = np.array([[False, False, True, False, False, False]])
        colour, mask = parts.grow_paint(painted, changed, passes=1)
        self.assertEqual(mask.tolist(), [[False, True, True, True, False, False]])
        self.assertEqual(colour[0, 1, 0], 200.0)

    def test_neighbouring_head_paintings_blend_by_the_angle_round_the_head(self):
        # Each painting draws its own hairline. Taking one view per texel by the generated normal, which flips strand by strand, tore it.
        angles = np.radians([5.0, 20.0, 35.0, 80.0])
        position = np.stack([np.sin(angles), -np.cos(angles), np.full(4, 0.1)], 1)[None].astype(np.float32) * 0.5
        normal = np.array([[[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]], np.float32)  # noisy on purpose
        texels = {"position": position, "normal": normal, "used": np.ones((1, 4), bool)}
        colour = np.full((1, 4, 3), 10, np.uint8)
        views = {"centre": [0, 0, 0], "extent": 2.0}
        paintings = {0: np.full((8, 8, 3), 100, np.uint8), 40: np.full((8, 8, 3), 200, np.uint8)}
        out, changed = parts.project_head_views(colour, texels, views, paintings, face=True)
        self.assertTrue(changed.all())
        self.assertLess(out[0, 0, 0], 110)
        self.assertLess(abs(float(out[0, 1, 0]) - 150), 10)
        self.assertGreater(out[0, 2, 0], 190)
        self.assertGreater(out[0, 3, 0], 190)  # past the last view, the nearest one still paints it

    def test_the_rear_painting_fades_in_across_the_middle_over_the_face(self):
        # A hard split at the middle left a line down the side of a leather cap and the neck under it.
        position = np.array([[[0.0, 0.0, 0.25], [0.0, 0.5, 0.25], [0.0, -0.5, 0.25]]], np.float32)
        normal = np.array([[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, -1.0, 0.0]]], np.float32)
        texels = {"position": position, "normal": normal, "used": np.ones((1, 3), bool)}
        colour = np.full((1, 3, 3), 10, np.uint8)
        out, _ = parts.project_head_views(colour, texels, {"centre": [0, 0, 0], "extent": 2.0}, {90: np.full((8, 8, 3), 210, np.uint8)})
        self.assertLess(abs(float(out[0, 0, 0]) - 110), 10)
        self.assertEqual(out[0, 2, 0], 10)
        out, _ = parts.project_head_views(colour, texels, {"centre": [0, 0, 0], "extent": 2.0}, {90: np.full((8, 8, 3), 210, np.uint8)}, face=True)
        self.assertEqual(out[0, 0, 0], 210)  # the face reaches past the middle, so no bare step is left under the fade
        self.assertEqual(out[0, 1, 0], 10)

    def test_a_rear_painting_lands_on_the_rear_and_leaves_the_face(self):
        position = np.array([[[0.0, 0.5, 0.25], [0.0, -0.5, 0.25]]], np.float32)
        normal = np.array([[[0.0, 1.0, 0.0], [0.0, -1.0, 0.0]]], np.float32)
        texels = {"position": position, "normal": normal, "used": np.ones((1, 2), bool)}
        colour = np.full((1, 2, 3), 10, np.uint8)
        painting = np.full((8, 8, 3), 200, np.uint8)
        out, changed = parts.project_head_views(colour, texels, {"centre": [0, 0, 0], "extent": 2.0}, {180: painting})
        self.assertEqual(out[0, 0].tolist(), [200, 200, 200])
        self.assertEqual(out[0, 1].tolist(), [10, 10, 10])
        self.assertEqual(changed.tolist(), [[True, False]])
        out, changed = parts.project_head_views(colour, texels, {"centre": [0, 0, 0], "extent": 2.0}, {0: painting}, face=True)
        self.assertEqual(changed.tolist(), [[False, True]])
        self.assertEqual(out[0, 1].tolist(), [200, 200, 200])

    def test_the_sheet_puts_the_body_bottom_left_and_the_head_top_right(self):
        with mock.patch.object(parts, "SHEET", 96):
            sheet = parts.compose_sheet(Image.new("RGB", (8, 8), (255, 0, 0)), Image.new("RGB", (8, 8), (0, 255, 0)), fill=(0, 0, 255))
        self.assertEqual(sheet.getpixel((10, 90)), (255, 0, 0))
        self.assertEqual(sheet.getpixel((90, 10)), (0, 255, 0))
        self.assertEqual(sheet.getpixel((10, 10)), (0, 0, 255))

    def test_a_brief_fills_both_prompts(self):
        prompts = parts.brief_prompts(BRIEF)
        self.assertIn("a square tired face", prompts["head"])
        self.assertIn("A woodcut look with bold lines.", prompts["head"])
        self.assertIn("woman", prompts["body"])
        self.assertFalse(any("{" in prompt for prompt in prompts.values()))

    def test_the_art_style_comes_from_the_brief_and_a_step_says_what_it_lacks(self):
        for prompt in (parts.HEAD_PROMPT, parts.HAIR_PROMPT, parts.BODY_PAINT_PROMPT, parts.FACE_PROMPT):
            self.assertIn("{style}", prompt)
            self.assertNotIn("oil-painted", prompt)
        with tempfile.TemporaryDirectory() as temporary:
            brief = Path(temporary) / "brief.json"
            brief.write_text(json.dumps({"name": "miner"}))
            run = subprocess.run([sys.executable, str(ROOT / "processing/character_parts.py"), "join", str(brief), "--out", temporary], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertIn("join needs concept, head_base in the brief", run.stderr)

    def test_a_types_default_aspect_skips_an_edit_graph_but_an_asked_one_does_not(self):
        from slopforge.pipelines.model import _aspect_applies
        edit = json.loads((ROOT / "workflows/image_edit_qwen_api.json").read_text())
        text = {"size": {"class_type": "EmptyLatentImage", "inputs": {"width": 1, "height": 1}}}
        self.assertFalse(_aspect_applies(None, "wide", edit))
        self.assertTrue(_aspect_applies(None, "wide", text))
        self.assertTrue(_aspect_applies("wide", "wide", edit))
        self.assertFalse(_aspect_applies(None, None, text))

    def test_gear_scripts_name_their_assets_and_the_hold_clip(self):
        from slopforge.unity_gear import equip_script, library_script
        script = equip_script("Assets/C/a/a.prefab", "Assets/M/p.fbx", "Assets/W/w.fbx", "Assets/L/l.fbx", "Pistol_Idle_Loop", 0.82, 0.66)
        for expected in ('"Assets/C/a/a_equipped.prefab"', '"Assets/M/p.fbx"', '"Assets/W/w.fbx"', '"|Pistol_Idle_Loop"', "0.82f", "0.66f"):
            self.assertIn(expected, script)
        self.assertIn("EndsWith(\"_Loop\")", library_script("Assets/L/l.fbx"))

    def test_the_leg_swing_script_scales_only_the_swing_of_the_legs(self):
        from slopforge.unity_gear import leg_swing_script
        script = leg_swing_script("Assets/C/a.fbx", "Assets/L/l.fbx", "Idle_Loop", 0.5, 0.55)
        for expected in ('"Assets/C/a.fbx"', '"|Idle_Loop"', "? 0.5f", "? 0.55f", 'EndsWith("UpperLeg")', 'Contains("Front-Back")', "SetApplyFootIK(false)"):
            self.assertIn(expected, script)

    def test_body_skin_takes_the_faces_tone_and_keeps_its_shading(self):
        size = 64
        voxel = np.zeros((size, size, 3), float)
        voxel[:] = (40, 36, 30)  # a dark coat
        voxel[:32] = (200, 110, 60)  # the generator's orange skin
        colour = voxel.copy()
        colour[:16] = (210, 180, 160)  # the concept's pale neck, painted over part of it
        colour[8:16] *= 0.6  # a crease in it
        height = np.tile(np.linspace(0.5, -0.5, size)[:, None], (1, size))
        out = parts.match_skin(colour, voxel, height, np.array((130.0, 100.0, 80.0)))
        self.assertTrue(np.allclose(out[60, 30], colour[60, 30], atol=1))  # the coat is untouched
        for row in (2, 24):  # pale and orange skin come out one tone
            self.assertLess(abs(out[row, 30, 0] / out[row, 30, 2] - 130 / 80), 0.05)
        self.assertLess(out[12, 30].sum(), out[2, 30].sum() * 0.8)  # the crease stays darker

    def test_the_stumps_flat_top_counts_as_skin_whatever_its_hue(self):
        # The generator paints the top of a headless neck yellower than its sides, and it showed as a bright band under the chin.
        size = 64
        voxel = np.full((size, size, 3), (40.0, 36.0, 30.0))
        voxel[:32] = (200, 110, 60)
        voxel[0] = (253, 199, 111)
        height = np.tile(np.linspace(0.5, -0.5, size)[:, None], (1, size))
        out = parts.match_skin(voxel.copy(), voxel, height, np.array((130.0, 100.0, 80.0)))
        self.assertLess(abs(out[0, 30, 0] / out[0, 30, 2] - 130 / 80), 0.15)

    def test_tan_trim_is_told_from_skin_by_hue(self):
        # An epaulette's tan sat 0.03 of a turn from the skin's orange on the first coat, and came out pink.
        voxel = np.full((64, 64, 3), (40.0, 36.0, 30.0))
        voxel[:32] = (200, 110, 60)  # hue 0.06
        voxel[20:30] = (153, 111, 61)  # hue 0.09, with the skin's saturation and a darker value
        height = np.tile(np.linspace(0.5, -0.5, 64)[:, None], (1, 64))
        out = parts.match_skin(voxel.copy(), voxel, height, np.array((130.0, 100.0, 80.0)))
        self.assertTrue(np.allclose(out[25, 10], voxel[25, 10], atol=2))

    def test_metal_near_the_skins_colour_keeps_its_own(self):
        # Tan epaulettes sat inside the skin mask and came out pink.
        voxel = np.full((64, 64, 3), (40.0, 36.0, 30.0))
        voxel[:32] = (200, 110, 60)
        height = np.tile(np.linspace(0.5, -0.5, 64)[:, None], (1, 64))
        metal = np.zeros((64, 64), bool)
        metal[20:30, :32] = True
        out = parts.match_skin(voxel.copy(), voxel, height, np.array((130.0, 100.0, 80.0)), keep=metal)
        self.assertTrue(np.allclose(out[25, 10], voxel[25, 10], atol=2))
        self.assertFalse(np.allclose(out[25, 50], voxel[25, 50], atol=2))

    def test_the_inside_of_the_stump_takes_the_tone_too(self):
        # The cut rises to the nape, so the stump's inner wall shows under the chin, yellower than the skin: a bright band there.
        size = 64
        voxel = np.full((size, size, 3), (40.0, 36.0, 30.0))
        voxel[:32] = (200, 110, 60)
        voxel[:6] = (253, 199, 111)
        height = np.tile(np.linspace(0.5, -0.5, size)[:, None], (1, size))
        out = parts.match_skin(voxel.copy(), voxel, height, np.array((130.0, 100.0, 80.0)))
        self.assertLess(abs(out[4, 30, 0] / out[4, 30, 2] - 130 / 80), 0.15)

    def test_level_head_only_retunes_the_nod_when_asked(self):
        from slopforge.unity_gear import leg_swing_script
        self.assertNotIn("Nod Down-Up", leg_swing_script("Assets/C/a.fbx", "Assets/L/l.fbx", "Idle_Loop", 0.6, 0.6, 0.5))
        script = leg_swing_script("Assets/C/a.fbx", "Assets/L/l.fbx", "Idle_Loop", 0.6, 0.6, 0.5, level_head=True)
        for expected in ('"Neck"', '"Head"', "Nod Down-Up", "HumanBodyBones.Head", "HEAD facing"):
            self.assertIn(expected, script)

    def test_arm_drop_scales_how_far_the_arms_lower(self):
        from slopforge.unity_gear import leg_swing_script
        script = leg_swing_script("Assets/C/a.fbx", "Assets/L/l.fbx", "Idle_Loop", 0.6, 0.6, 0.5)
        self.assertIn("0.5f != 1f", script)
        self.assertIn("low[axis] *= 0.5f", script)
        self.assertIn('Contains("Down-Up")', script)

    def test_orange_leather_is_not_brass(self):
        self.assertEqual(parts.brass_mask(np.array([[[200.0, 136.0, 90.0]]])).tolist(), [[False]])

    def test_a_model_folder_must_hold_one_built_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "alch_body.glb").touch()
            (root / "alch_body_prepared.glb").touch()
            self.assertEqual(parts.model_in(root, "body").name, "alch_body.glb")
            with self.assertRaises(SystemExit):
                parts.model_in(root, "head")

    def test_edits_use_a_workflow_whose_outputs_are_cleared(self):
        """Qwen Image 2.1 is research-only, so a character's lineage must not pass through it."""
        from slopforge.providers import combine_rights
        from slopforge.workflow_requirements import workflow_output_rights
        self.assertIn("image_edit_qwen_api.json", (ROOT / "processing/character_parts.py").read_text())
        self.assertEqual(combine_rights(workflow_output_rights(ROOT / "workflows/image_edit_qwen_api.json"))["status"], "cleared")
        self.assertNotIn("qwen_image_2.1", (ROOT / "workflows/image_edit_qwen_api.json").read_text())

    def test_brass_needs_the_generators_metal_as_well_as_the_colour(self):
        # Warm lit skin has brass's colour: a neck and the backs of the hands came out as shiny orange flecks (2026-11-03).
        # The generator's metal map held the buckle, loops and toe caps and none of the skin.
        brassy = np.full((4, 4, 3), (190.0, 150.0, 60.0))
        metal = np.zeros((4, 4))
        metal[:2] = 255
        found = parts.metal_brass(brassy, metal)
        self.assertTrue(found[:2].all())
        self.assertFalse(found[2:].any())

    def test_the_crown_takes_the_colour_of_the_painted_surface_round_it(self):
        # Every repaint view is level, so a texel facing straight up faces none and kept the model's raw colour: a dark disc
        # where a third-person camera looks down on the head (2026-11-03).
        size = 40
        y, x = np.mgrid[:size, :size]
        position = np.stack([x / size - 0.5, y / size - 0.5, np.zeros((size, size))], 2)
        radius = np.hypot(position[..., 0], position[..., 1])
        position[..., 2] = 1 - radius  # a cone, top in the middle
        normal = np.zeros((size, size, 3))
        normal[..., 2] = 1.0
        used = radius < 0.5
        changed = used & (radius > 0.1)  # the painted sides
        colour = np.full((size, size, 3), 200.0)
        colour[~changed] = 20.0  # the crown's dark raw colour
        out, crown = parts.paint_crown(colour, changed, {"position": position, "normal": normal, "used": used})
        self.assertTrue(crown[size // 2, size // 2])
        self.assertAlmostEqual(out[size // 2, size // 2, 0], 200.0, delta=1)
        self.assertEqual(out[2, 2, 0], 20.0)  # outside the head stays as it was
        self.assertEqual(out[size // 2, 3, 0], 200.0)  # painted texels keep their paint

    def test_a_stump_brief_can_ask_for_its_own_neck(self):
        # The edit's fixed "short thick bare neck" gave a concept whose shirt closes at the throat a low neckline and a wide stump, which no later step repaired.
        default = parts.brief_prompts(BRIEF)["body"]
        self.assertIn("short thick bare neck", default)
        asked = parts.brief_prompts(dict(BRIEF, stump_neck="A slim neck rises from the closed collar."))["body"]
        self.assertIn("A slim neck rises from the closed collar.", asked)
        self.assertNotIn("short thick bare neck", asked)
        self.assertIn("take off", asked)

    def test_a_stump_brief_edits_only_the_head_off(self):
        prompt = parts.brief_prompts(BRIEF)["body"]
        self.assertIn("take off this woman's head at the neck", prompt)
        self.assertIn("Everything else stays exactly as it is", prompt)
        self.assertNotIn("oil-painted", prompt)  # the repaint lost the concept's colours and light
        self.assertNotIn("flat and even", prompt)

    def test_a_build_reduces_from_the_detail_mesh_with_hidden_faces_gone(self):
        # Without these a body spent most of its faces and texture on a double skin's hidden wall, and at half the character budget.
        command = parts.build_command(Path("in.png"), "body", Path("out"), 7)
        self.assertIn("--remove-hidden-faces", command)
        self.assertNotIn("--require-manifold", command)
        self.assertEqual(command[command.index("--face-budget") + 1], "60000")
        inputs = json.loads(command[command.index("--workflow-inputs") + 1])
        self.assertEqual(inputs["shape_decimate"]["placement_mode"], "midpoint")
        head = parts.build_command(Path("in.png"), "head", Path("out"), 7)
        self.assertEqual(head[head.index("--face-budget") + 1], "30000")

    @unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
    def test_stump_skin_is_told_from_a_collar_by_colour_in_any_light(self):
        # A stump flares, so an outline measured at its top missed pieces: spikes and a ring round the back of a head, a ring
        # that never closed, and no cap (2026-11-03). Its colour finds it, in shadow too, and leaves grey cloth and dark leather.
        script = f"""import sys
import numpy as np
sys.path.insert(0, {str(ROOT / "blender")!r})
import join_character_parts as j
reference = np.array((0.75, 0.55, 0.42))
colours = np.array((reference, reference * 0.7, (0.3, 0.3, 0.3), (0.2, 0.15, 0.11), (0.6, 0.6, 0.62)))
print("SKIN", "".join("1" if flag else "0" for flag in j.skin_like(colours, reference)))
"""
        run = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-1000:])
        self.assertEqual(next(line for line in run.stdout.splitlines() if line.startswith("SKIN")).split()[1], "11000")

    @unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
    def test_a_skulls_width_ignores_a_scarf_tail_and_loose_hair_below_it(self):
        # The widest point above the neck counted a scarf's tail as skull, and shrank one head by a fifth against its concept (2026-11-04).
        script = f"""import sys
import numpy as np
sys.path.insert(0, {str(ROOT / "blender")!r})
import join_character_parts as j
skull = [(r * np.cos(a), r * np.sin(a), z) for z in np.linspace(1.0, 2.0, 41) for r in (0.4,) for a in np.linspace(0, 6.28, 24)]
tail = [(x, 0.0, 1.15) for x in np.linspace(0.4, 1.2, 12)]
print("WIDTH", j.skull_width(np.array(skull), 1.0), j.skull_width(np.array(skull + tail), 1.0))
"""
        run = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-1000:])
        plain, tailed = map(float, next(line for line in run.stdout.splitlines() if line.startswith("WIDTH")).split()[1:])
        self.assertAlmostEqual(plain, 0.8, delta=0.02)
        self.assertAlmostEqual(tailed, 0.8, delta=0.02)

    @unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
    def test_reducing_a_head_keeps_the_face_when_a_cap_is_busier(self):
        # A plain reduction spends triangles where the surface is busiest. One man's goggles and cap kept 9,400 of 15,000 and his smooth
        # face went from 4,667 to 1,009, a low-poly mannequin (2026-11-04).
        script = f"""import sys
import bmesh, bpy
import numpy as np
sys.path.insert(0, {str(ROOT / "blender")!r})
import join_character_parts as j
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=6, radius=1.0)
head = bpy.context.object
rng = np.random.default_rng(1)
for vertex in head.data.vertices:
    if vertex.co.z > 0.3:  # a busy cap over a smooth face
        vertex.co *= 1 + 0.04 * rng.random()
head.data.update()
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode="OBJECT")
j.HEAD_FACES = 4000
j.trim_head(head, -0.95)
centres = np.array([polygon.center for polygon in head.data.polygons])
face = (centres[:, 1] < 0) & (centres[:, 2] > -0.8) & (centres[:, 2] < 0.2)
print("FACE", int(face.sum()), len(centres))
"""
        run = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-1000:])
        on_face, total = map(int, next(line for line in run.stdout.splitlines() if line.startswith("FACE")).split()[1:])
        self.assertLess(total, 4400)
        self.assertGreater(on_face / total, 0.3)

    @unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
    def test_relaying_a_head_gives_the_face_more_of_the_sheet_and_keeps_its_colours(self):
        # What the head's cut bust and shirt held stayed spent, and shards left a face 5% of its sheet (2026-11-04).
        script = f"""import sys
import bpy
import numpy as np
from pathlib import Path
sys.path.insert(0, {str(ROOT / "blender")!r})
import join_character_parts as j
root = Path(sys.argv[-1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=1.0)
head = bpy.context.object
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode="OBJECT")
size = 256
# Colour says where on the old sheet a texel is, so a wrong transfer shows.
ramp = np.zeros((size, size, 4), np.float32)
ramp[..., 0], ramp[..., 1] = np.meshgrid((np.arange(size) + 0.5) / size, (np.arange(size) + 0.5) / size)
ramp[..., 3] = 1
base = bpy.data.images.new("base", size, size); base.colorspace_settings.name = "Non-Color"; base.pixels.foreach_set(ramp.ravel())
base.filepath_raw, base.file_format = str(root / "base.png"), "PNG"; base.save()
flat = np.full((size, size, 4), (0.5, 0.5, 1.0, 1.0), np.float32)
normal = bpy.data.images.new("normal", size, size); normal.colorspace_settings.name = "Non-Color"; normal.pixels.foreach_set(flat.ravel())
normal.filepath_raw, normal.file_format = str(root / "normal.png"), "PNG"; normal.save()
data = head.data
share = lambda: float(np.sum([j.uv_area(data, p) for p in data.polygons if j.on_face(head, p)]) / max(sum(j.uv_area(data, p) for p in data.polygons), 1e-9))
before = share()
old = {{p.index: np.mean([np.array(data.uv_layers.active.data[i].uv) for i in p.loop_indices], 0) for p in data.polygons}}
baked = j.relay_head(head, str(root / "base.png"), str(root / "normal.png"), 128, colour_space="Non-Color")
after = share()
pixels = np.zeros(128 * 128 * 4, np.float32); baked["base"].pixels.foreach_get(pixels); pixels = pixels.reshape(128, 128, 4)
off = []
for p in data.polygons:
    uv = np.mean([np.array(data.uv_layers.active.data[i].uv) for i in p.loop_indices], 0)
    colour = pixels[min(int(uv[1] * 128), 127), min(int(uv[0] * 128), 127), :2]
    off.append(np.abs(colour - old[p.index]).max())
normals = np.zeros(128 * 128 * 4, np.float32); baked["normal"].pixels.foreach_get(normals); normals = normals.reshape(128, 128, 4)
print("RELAY", before, after, float(np.percentile(off, 90)), float(np.median(normals[..., 2][normals[..., 2] > 0.1])), len(data.uv_layers))
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "probe.py"
            path.write_text(script)
            run = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(path), "--", temporary], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-1000:])
        before, after, off, blue, layers = map(float, next(line for line in run.stdout.splitlines() if line.startswith("RELAY")).split()[1:])
        self.assertGreater(after, before * 1.3)  # on a plain ball, where only islands mostly on the face grow
        self.assertLess(off, 0.08)  # each face still shows the colour it had
        self.assertGreater(blue, 0.9)  # a flat normal stays flat
        self.assertEqual(layers, 1)

    @unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
    def test_a_heads_neck_tucks_smoothly_into_the_stump_and_spares_the_jaw_and_hair(self):
        # Pulling rows in at one height left the row above behind, and the triangles between them showed as teeth at the nape (2026-11-04).
        script = f"""import sys
import bpy
import numpy as np
sys.path.insert(0, {str(ROOT / "blender")!r})
import join_character_parts as j
bpy.ops.wm.read_factory_settings(use_empty=True)
heights = np.linspace(0.95, 1.3, 36)
points = [(0.15 * np.cos(a), 0.15 * np.sin(a), z) for z in heights for a in np.linspace(0, 6.28, 48)]
points += [(0.0, 0.32, 1.05), (0.0, -0.15, 1.1)]  # a lock of hair far behind, and a jaw in front above the plane
mesh = bpy.data.meshes.new("neck")
mesh.from_pydata([tuple(map(float, point)) for point in points], [], [])
head = bpy.data.objects.new("neck", mesh)
bpy.context.scene.collection.objects.link(head)
bpy.context.view_layer.update()
before = j.points(head)
j.tuck_neck(head, 1.0, (0.0, 0.0, 0.1, 0.1), (0.7, -0.1), 1.1, 2.0)
found = j.points(head)
neck = found[:-2]
back = [float(neck[np.abs(neck[:, 2] - z) < 1e-4, 1].max()) for z in heights]
print("TUCK", back[5], back[-1], max(abs(a - b) for a, b in zip(back, back[1:])), float(found[-2, 1]), float(found[-1, 1]), float(before[-1, 1]))
"""
        run = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-1000:])
        low, high, step, lock, jaw, jaw_before = map(float, next(line for line in run.stdout.splitlines() if line.startswith("TUCK")).split()[1:])
        self.assertLess(low, 0.1)  # inside the stump at its cut
        self.assertAlmostEqual(high, 0.15, delta=0.002)  # untouched well above the collar
        self.assertLess(step, 0.015)  # no row jumps from the next
        self.assertAlmostEqual(lock, 0.32, delta=0.001)
        self.assertAlmostEqual(jaw, jaw_before, delta=0.001)

    def test_an_open_skin_figure_shades_and_shadows_both_sides(self):
        # With hidden faces gone a body is one open skin, and Unity's default shadows on it printed jagged black marks on a
        # back that had no marks on it with shadows off (2026-11-03).
        from slopforge.unity_gear import open_skin_script
        script = open_skin_script("Assets/Art/Generated/Characters/a/a.prefab", "Assets/Art/Generated/Characters/a/Materials/a.mat")
        self.assertIn('SetFloat("_Cull", 0f)', script)
        self.assertIn("ShadowCastingMode.TwoSided", script)
        self.assertIn('"Assets/Art/Generated/Characters/a/a.prefab"', script)
        self.assertIn("SavePrefabAsset", script)

    def test_a_rifle_is_held_by_its_wrist_and_forestock_with_its_top_up(self):
        # A hammer's hold carries it across the chest with the head up. A rifle points ahead, and each hand goes on a part of it the weapon route can't name, measured from its origin.
        from slopforge.unity_gear import RIFLE_CARRY, two_hand_script
        script = two_hand_script("Assets/C/a/a.prefab", "Assets/W/r.fbx", "Assets/L/l.fbx", ("Idle_Loop",), RIFLE_CARRY)
        for expected in ("toMuzzle", "Slice(", "SolveSwung(upperR", "SolveSwung(upperL", '"GripR", gripR', "isn't on the weapon", "goes into the body", 'throw new Exception(clip.name + ": a fist ends'):
            self.assertIn(expected, script)
        # Each fist has its own way round: the right closes on the stock's wrist, the left cradles the forestock from under it, and neither follows the other arm's sign.
        hands = RIFLE_CARRY["hands"]
        self.assertGreater(hands["left"]["long"][0], 0)
        self.assertGreater(hands["right"]["thumb"][1], 0)
        self.assertGreater(RIFLE_CARRY["under_forestock"], 0)
        # A jog leans the chest 30 degrees and turns it 15 each way. The rifle keeps most of its line, so each clip carries the weapon's own curves, and the prefab's hold is put back afterwards.
        self.assertLess(RIFLE_CARRY["steady"], 0.5)
        for expected in ("Quaternion.Slerp(Quaternion.identity, carried,", "m_LocalPosition.x", "m_LocalRotation.w", "held.transform.SetPositionAndRotation(restWeaponP, restWeaponQ)"):
            self.assertIn(expected, script)
        self.assertNotIn("headHigh", script)
        self.assertGreater(RIFLE_CARRY["forestock"], RIFLE_CARRY["wrist"])
        # A hammer's hold is what it was.
        hammer = two_hand_script("Assets/C/a/a.prefab", "Assets/W/h.fbx", "Assets/L/l.fbx", ("Idle_Loop",))
        self.assertIn("headHigh", hammer)
        self.assertNotIn("toMuzzle", hammer)
        self.assertNotIn("m_LocalPosition.x", hammer)

    def test_a_launcher_says_which_end_is_its_muzzle(self):
        # Its origin is at its middle, so neither end is the far one, and its bell is at the end a tie would pick only by chance.
        from slopforge.unity_gear import LAUNCHER_CARRY, RIFLE_CARRY, two_hand_script
        self.assertEqual(LAUNCHER_CARRY["to_muzzle"], -1)
        self.assertEqual(RIFLE_CARRY["to_muzzle"], 1)
        script = two_hand_script("Assets/C/a/a.prefab", "Assets/W/l.fbx", "Assets/L/l.fbx", ("Idle_Loop",), LAUNCHER_CARRY)
        self.assertIn("toMuzzle[axis] = -1f;", script)
        # The game fires from the muzzle: the shot leaves from a named point on the weapon, not from the body.
        self.assertIn('new GameObject("Muzzle")', script)
        # A long arm folded on a close grip tucks its elbow into the ribs unless it's sent outwards, and the shot has to keep the hold's elbow or it jumps on the first frame.
        from slopforge.unity_gear import LAUNCHER_SHOT, two_hand_shot_script
        self.assertGreater(LAUNCHER_CARRY["elbow_right"][0], RIFLE_CARRY["elbow_right"][0])
        self.assertEqual(LAUNCHER_SHOT["elbow_right"], LAUNCHER_CARRY["elbow_right"])
        x, y, z = LAUNCHER_CARRY["elbow_right"]
        self.assertIn(f"new Vector3({x}f, {y}f, {z}f)", script)
        self.assertIn(f"new Vector3({x}f, {y}f, {z}f)", two_hand_shot_script("Assets/C/a/a.prefab", "Attack_Shot", LAUNCHER_SHOT))

    def test_a_shot_kicks_the_weapon_back_and_returns_to_the_hold(self):
        # It has to fit the weapon's repeat, and play over a jog: it starts and ends on the hold and carries the weapon's own curves.
        from slopforge.unity_gear import RIFLE_SHOT, two_hand_shot_script
        script = two_hand_shot_script("Assets/C/a/a.prefab", "Attack_Shot", RIFLE_SHOT)
        self.assertLess(RIFLE_SHOT["total"], 0.6)
        self.assertLess(RIFLE_SHOT["rise"], 0.06)
        for expected in ("TwoHand/a_TwoHand_Idle_Loop.anim", "a_twohand.prefab", "Kick(", "SolveSwung(upperR", "SolveSwung(upperL", "m_LocalPosition.x", "m_LocalRotation.w", "settings.loopTime = false"):
            self.assertIn(expected, script)
        for gate in (": a fist ends", ": an arm goes", ": a joint jumps", "doesn't end on the hold"):
            self.assertIn(gate, script)

    def test_a_wrench_is_carried_and_swung_in_one_hand(self):
        # The right hand is solved onto the weapon as on a rifle; the left arm keeps what the clip gives it, and nothing measures it against a grip it doesn't hold.
        from slopforge.unity_gear import WRENCH_CARRY, WRENCH_SWEEP, HAMMER_SWING, two_hand_script, two_hand_strike_script
        hold = two_hand_script("Assets/C/a/a.prefab", "Assets/W/w.fbx", "Assets/L/l.fbx", ("Idle_Loop",), WRENCH_CARRY)
        self.assertIn("SolveSwung(upperR", hold)
        self.assertNotIn("SolveSwung(upperL", hold)
        self.assertNotIn('("left", gripL, reachL)', hold)
        sweep = two_hand_strike_script("Assets/C/a/a.prefab", "Attack_Sweep", WRENCH_SWEEP)
        self.assertIn("SolveSwung(upperR", sweep)
        self.assertNotIn("SolveSwung(upperL", sweep)
        self.assertNotIn("ShoulderFollows(1,", sweep)
        self.assertIn("offL = 0f", sweep)
        # It leaves the hold as the hold left it: its own weapon curve and the fist's roll on the handle, not the prefab's or the forearm's.
        self.assertIn("holdLocalP = weapon.localPosition", sweep)
        self.assertIn("RollOf(handR.rotation * Quaternion.Inverse(bindR) * forearmR)", sweep)
        # A quick weapon: the blow comes well inside the game's half-second repeat, and the swing is over by then.
        self.assertLess(WRENCH_SWEEP["wind"] + WRENCH_SWEEP["strike"], 0.25)
        self.assertLessEqual(WRENCH_SWEEP["total"], 0.5)
        # The hammer's swing is still two-handed.
        hammer = two_hand_strike_script("Assets/C/a/a.prefab", "Attack_Swing", HAMMER_SWING)
        self.assertIn("SolveSwung(upperL", hammer)
        self.assertNotIn("offL = 0f", hammer)
    def test_a_two_handed_swing_runs_from_the_hold_to_the_hold_and_stops_a_bad_bake(self):
        # A clip that starts and ends on the hold, with the weapon animated in it, so any Animator can play it with almost no blend and the fists never slip.
        from slopforge.unity_gear import HAMMER_SWING, two_hand_strike_script
        script = two_hand_strike_script("Assets/C/a/a.prefab", "Attack_Swing", HAMMER_SWING)
        for expected in ('"Assets/C/a/a_twohand.prefab"', '"Assets/C/a/TwoHand/a_TwoHand_Idle_Loop.anim"', '"_TwoHand_" + "Attack_Swing"', '"m_LocalPosition.x"', '"m_LocalRotation.w"',
                         "settings.loopTime = false", "settings.loopBlendPositionY = true", "SetApplyFootIK(false)", "Bake the two-handed hold first",
                         'throw new Exception(clip.name + ": a fist ends', 'throw new Exception(clip.name + ": an arm goes', "bottom < 0.02f", "Leg(thighR, shinR, footR"):
            self.assertIn(expected, script)
        # Each of the body's curves runs from the hold, through the top of the swing, the blow and the settle, back to the hold.
        for key in ("spine_pitch", "spine_yaw", "hip_drop", "hip_forward", "hip_pitch", "hip_yaw"):
            self.assertEqual(len(HAMMER_SWING[key]), 5, key)
            self.assertEqual((HAMMER_SWING[key][0], HAMMER_SWING[key][-1]), (0, 0), key)

    def test_a_side_swing_tips_the_arc_over_and_slides_the_top_hand_down_the_haft(self):
        # The owner wanted a swing from the side. A haft held with the hands apart put the lower hand inside a big man's chest, so the top hand slides down it for the blow, as on an axe.
        from slopforge.unity_gear import HAMMER_SWING, two_hand_strike_script
        self.assertLess(HAMMER_SWING["roll"], -45)
        self.assertLess(HAMMER_SWING["grip_gap"][2], 0.6)
        self.assertLessEqual(HAMMER_SWING["total"], 0.9)  # the game repeats a swing every 0.9 s
        script = two_hand_strike_script("Assets/C/a/a.prefab", "Attack_Swing", HAMMER_SWING)
        self.assertIn("planeUp", script)
        self.assertIn("targetL", script)

    def test_a_swing_carries_through_its_blow_with_the_body_leading(self):
        # The owner: "it doesn't look too natural yet". It sped up to the blow and stopped dead in one frame, with hips, chest and arms all starting and stopping together, and held still.
        from slopforge.unity_gear import HAMMER_SWING, two_hand_strike_script
        theta = HAMMER_SWING["theta"]
        self.assertTrue(theta[1] > theta[2] > theta[3], theta)  # the hands keep going the same way through the blow
        self.assertGreater(HAMMER_SWING["lead"]["hips"], HAMMER_SWING["lead"]["spine"])
        self.assertGreater(HAMMER_SWING["lead"]["spine"], 0)
        self.assertLess(HAMMER_SWING["lead"]["haft"], 0)  # the hammer comes last
        script = two_hand_strike_script("Assets/C/a/a.prefab", "Attack_Swing", HAMMER_SWING)
        for expected in ("Led(t, leadHips)", "Led(t, leadSpine)", "t + leadHaft", "hipSide", "heelTurn", "fastestAt"):
            self.assertIn(expected, script)
        self.assertNotIn("tSettle", script)

    def test_a_swung_fist_rolls_slowly_round_the_haft_to_ease_its_wrist(self):
        # Rolled from the forearm with nothing to limit it, hands flipped 175 degrees in a frame. Held rigid on the weapon, wrists bent to 141 degrees, where a real one stops near 80, and
        # the forearm's twist wrapped round its range. A round haft lets a fist turn on it unseen, so it turns towards the easiest wrist, at a limited speed.
        from slopforge.unity_gear import ARM_SOLVER, HAMMER_SWING, two_hand_strike_script
        solved = ARM_SOLVER[ARM_SOLVER.index("static void SolveSwung"):ARM_SOLVER.index("static void Reach")]
        self.assertNotIn("for (int pass", solved)
        self.assertLessEqual(HAMMER_SWING["roll_rate"], 30)  # degrees a frame
        script = two_hand_strike_script("Assets/C/a/a.prefab", "Attack_Swing", HAMMER_SWING)
        self.assertIn("Mathf.MoveTowards(rhoR", script)
        self.assertIn("Mathf.MoveTowards(rhoL", script)
        # It comes back to where the hold has it by the end of the clip.
        self.assertLess(HAMMER_SWING["twist_most"], 2.0)  # the muscle wraps at 2
        # A fist is checked after the pose has been through the Humanoid muscles, which is what a game plays.
        self.assertLess(script.index("After the Humanoid round trip"), script.index("float offR"))
        # A clip must leave the hold exactly, so a body part's lead fades in from nothing.
        self.assertIn("Led(t, leadHips)", script)
        # Unity's forearm twist wraps at the end of its range, whatever path the hammer takes, so it's unwrapped from frame to frame and capped.
        self.assertIn("Mathf.Clamp(Unwrapped(", script)
        # A flip stops the bake: fists on the haft alone passed every one of them.
        self.assertIn('throw new Exception(clip.name + ": a joint jumps', script)

    def test_a_swings_arms_move_for_themselves(self):
        # The owner: "the arms still look stiff". The shoulder blades never moved, the elbows kept nearly one bend, and the hammer turned with the forearms instead of snapping through.
        from slopforge.unity_gear import HAMMER_SWING, two_hand_strike_script
        reach = HAMMER_SWING["r"]
        self.assertGreater(reach[2] - reach[1], 0.1)  # elbows bent at the top, nearly straight at the blow
        self.assertGreater(reach[1], 0.75)  # brought in further, the fists covered his jaw and the arms crushed across his chest, and the owner said so
        self.assertGreater(max(HAMMER_SWING["elbow_left"]), 0.5)
        self.assertGreater(max(HAMMER_SWING["elbow_right"]), 0.5)
        self.assertLessEqual(HAMMER_SWING["lead"]["haft"], -0.03)  # the wrists hold the hammer back, then let it go
        script = two_hand_strike_script("Assets/C/a/a.prefab", "Attack_Swing", HAMMER_SWING)
        for expected in ("HumanBodyBones.LeftShoulder", "HumanBodyBones.RightShoulder", "ShoulderFollows(", "elbowLeft", "elbowRight"):
            self.assertIn(expected, script)

    def test_two_handed_clips_are_baked_for_the_named_character_and_clips(self):
        # No runtime code: Humanoid clips with both arms solved onto the haft, so any Animator can play them.
        from slopforge.unity_gear import two_hand_script
        script = two_hand_script("Assets/C/a/a.prefab", "Assets/W/h.fbx", "Assets/L/l.fbx", ("Idle_Loop", "Walk_Loop"))
        for expected in ('"Assets/C/a/a.prefab"', '"Assets/W/h.fbx"', '"Assets/L/l.fbx"', '"Idle_Loop"', '"Walk_Loop"', "GetHumanPose", "RootQ.w",
                         '"Assets/C/a/a_twohand.prefab"', "HumanBodyBones.LeftHand", "HumanBodyBones.RightHand", "SetApplyFootIK(false)"):
            self.assertIn(expected, script)
        self.assertNotIn("MonoBehaviour", script)
        self.assertIn('throw new Exception(clip.name + ": a fist ends', script)  # a fist off its grip stops the bake
        self.assertIn("pivot + turn * (butt - pivot)", script)  # a weapon's origin at its grip put a real hammer 32 cm below the fists
        self.assertIn("isn't on the weapon", script)  # and fists on markers said nothing about the hammer: this check does
        self.assertIn("arm goes", script)  # a forearm through a belly passed every check on the fists, and showed in the first film
        self.assertIn('muscle.Contains("Shoulder")', script)  # free arms' shoulder pump rocked a held hammer
        self.assertIn('muscle.StartsWith("Head")', script)  # with the torso's twist damped, the head's counter-turn swung it on every step
        self.assertIn("hipsInClip * Quaternion.Inverse(hips.rotation)", script)  # editing muscles turned the hips 27 degrees on a jog
        self.assertIn("Chest Twist Left-Right", script)  # with the hips' turn back, a chest-mounted hammer swung 38 cm
        self.assertIn("lowestFoot", script)  # narrowed legs on a bouncy clip floated him 22 cm off the floor
        # Unbaked, the hips' rise and fall went out as root motion: his legs ran under a body hanging still in the air (2026-11-04).
        for setting in ("loopBlendPositionY = true", "loopBlendPositionXZ = true", "loopBlendOrientation = true"):
            self.assertIn(setting, script)

    def test_a_concept_gives_the_figures_head_size_and_the_bodys_share_of_it(self):
        concept, body = np.zeros((200, 200), bool), np.zeros((200, 200), bool)
        concept[10:190, 60:140] = True  # the body
        concept[10:40, 80:120] = True
        concept[:10] = False
        concept[10:40, :80] = concept[10:40, 120:] = False  # a head 40 wide on top
        body[30:190, 60:140] = True  # the edit ends 20 rows lower
        collar_share, skull_share = parts.head_measures(concept, body)
        self.assertAlmostEqual(collar_share, 159 / 179, places=3)
        self.assertAlmostEqual(skull_share, 39 / 179, delta=0.01)

    @unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
    def test_a_neck_stump_is_cut_down_inside_its_collar_and_the_head_takes_the_concepts_size(self):
        # An edit that only takes the head off keeps the concept's light and colours and gives the 3D step a solid neck, so
        # there is no hollow collar to patch. Its stump rises far above where the chin was, so sizing the head from the stump
        # sat a tiny head on a funnel (2026-11-03). The concept sets the head's size and crown, and the stump is cut down to
        # the head's neck without cutting the collar round it.
        fixture = """import bpy, sys
for name, parts in (("stump", (((0, 0, 0.6), 0.3, 1.2), ((0, 0, 1.6), 0.1, 0.8), ((0.26, 0, 1.6), 0.03, 0.2), ((-0.26, 0, 1.6), 0.03, 0.2))),
                    ("head", (((0, 0, 0.1), 0.05, 0.2), ((0, 0, 0.45), 0.2, 0.5)))):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for location, radius, depth in parts:
        bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, vertices=48, location=location)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.join()
    item = bpy.context.object
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=8)
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    item.data.materials.append(material)
    bpy.ops.export_scene.gltf(filepath=sys.argv[-1] + "/" + name + ".glb", export_format="GLB")
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture.py").write_text(fixture)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(root / "fixture.py"), "--", str(root)],
                           check=True, capture_output=True, text=True)
            maps = {}
            for key, colour in (("base", (90, 60, 40)), ("normal", (128, 128, 255)), ("rough", (191, 191, 191)), ("metal", (0, 0, 0))):
                maps[key] = str(root / f"{key}.png")
                Image.new("RGB", (16, 16), colour).save(maps[key])
            (root / "request.json").write_text(json.dumps({
                "body": str(root / "stump.glb"), "head": str(root / "head.glb"), "height": 2.0, "name": "stumped", "maps": maps,
                "collar_share": 0.95, "skull_share": 0.2, "output": str(root / "joined.glb"), "report": str(root / "report.json")}))
            run = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(ROOT / "blender/join_character_parts.py"),
                                  "--", str(root / "request.json")], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-1000:])
            report = json.loads((root / "report.json").read_text())
            self.assertAlmostEqual(report["height"], 2.0, delta=0.02)
            self.assertAlmostEqual(report["head_scale"], 1.0, delta=0.05)  # a 0.4 wide skull on a 2 m figure at 0.2
            self.assertLess(report["stump_cut"], 1.9 - 0.2)  # well down from the stump's top
            self.assertGreater(report["cap_faces"], 20)
            self.assertGreater(report["neck_widened"], 1.2)  # the head's 0.05 neck out towards the stump's 0.095
            # Low under the chin and high at the nape: hidden faces are gone from behind the stump, so without its back a gap
            # beside the jaw looked straight through the figure.
            self.assertGreater(report["stump_nape"], report["stump_cut"] + 0.05)
            self.assertGreater(report["collar_top"], report["stump_cut"] + 0.05)  # the collar round it was not cut
            self.assertLess(report["neck_cut"], report["stump_cut"])  # the neck runs on down inside
            (root / "probe.py").write_text(PROBE)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(root / "probe.py"), "--",
                            str(root / "joined.glb"), str(root / "probe.json")], check=True, capture_output=True, text=True)
            probe = json.loads((root / "probe.json").read_text())
            self.assertEqual(probe["materials"], 1)
            self.assertEqual(probe["uv_inside"], 1.0)


if __name__ == "__main__":
    unittest.main()
