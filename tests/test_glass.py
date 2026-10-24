import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from slopforge.style import parse_material_spec, reconstruction_rules
from slopforge.unity_material import GLASS_ALPHA, apply_glass, build_unity_material

GREEN, CORK, BRASS, GLOBE = (60, 150, 90), (170, 130, 90), (110, 90, 40), (205, 205, 200)


def maps(root, basecolor):
    paths = {key: root / f"{key}.png" for key in ("basecolor", "roughness", "metallic")}
    basecolor.save(paths["basecolor"])
    Image.new("RGB", basecolor.size, (200, 200, 200)).save(paths["roughness"])
    Image.new("RGB", basecolor.size, (180, 180, 180)).save(paths["metallic"])
    return paths


def two_regions(body, part, size=128):
    image = Image.new("RGB", (size, size), body)
    image.paste(part, (0, 0, size, size // 4))
    return image


class GlassDeclarationTests(unittest.TestCase):
    def test_glass_takes_an_optional_tint_and_a_solid_surface_concept_rule(self):
        bottle = parse_material_spec("bottle=glass#3c965a: green glass")
        self.assertEqual((bottle["class"], bottle["color"]), ("glass", "#3c965a"))
        self.assertNotIn("color", parse_material_spec("panes=glass: clear glass"))
        # 2026-10-22: a bottle drawn see-through reconstructed as shards; drawn solid it came out whole.
        rules = reconstruction_rules({"pipeline": "model"}, [bottle])
        self.assertIn("nothing visible through it", rules)
        with self.assertRaisesRegex(ValueError, "glass"):
            parse_material_spec("bottle=metal#3c965a")  # only metal takes no colour


class ApplyGlassTests(unittest.TestCase):
    def test_tinted_glass_becomes_see_through_smooth_and_non_metallic(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = maps(Path(temporary), two_regions(GREEN, CORK))
            fraction = apply_glass(paths["basecolor"], paths["roughness"], paths["metallic"], [GREEN])
            with Image.open(paths["basecolor"]) as base, Image.open(paths["roughness"]) as rough, \
                    Image.open(paths["metallic"]) as metal:
                self.assertEqual(base.mode, "RGBA")
                self.assertEqual(base.getpixel((64, 100))[3], 255 - round(255 * (1 - GLASS_ALPHA)))  # glass
                self.assertEqual(base.getpixel((64, 10))[3], 255)  # cork stays opaque
                self.assertLess(rough.convert("L").getpixel((64, 100)), 20)
                self.assertEqual(rough.convert("L").getpixel((64, 10)), 200)
                self.assertEqual(metal.convert("L").getpixel((64, 100)), 0)
        self.assertAlmostEqual(fraction, 0.75, delta=0.05)

    def test_shaded_tinted_glass_is_found_by_hue(self):
        # 2026-10-22 bottle: colour distance found 44% of the glass and left it blotchy; the tint's hue found 84%.
        dark_green = (25, 70, 40)
        with tempfile.TemporaryDirectory() as temporary:
            paths = maps(Path(temporary), two_regions(dark_green, CORK))
            apply_glass(paths["basecolor"], paths["roughness"], paths["metallic"], [GREEN])
            with Image.open(paths["basecolor"]) as base:
                self.assertLess(base.getpixel((64, 100))[3], 255)
                self.assertEqual(base.getpixel((64, 10))[3], 255)

    def test_clear_glass_is_found_as_the_pale_region(self):
        # 2026-10-22 lantern: the clear globe baked pale grey-white inside a dark brass frame.
        with tempfile.TemporaryDirectory() as temporary:
            paths = maps(Path(temporary), two_regions(BRASS, GLOBE))
            fraction = apply_glass(paths["basecolor"], paths["roughness"], paths["metallic"], [None])
            with Image.open(paths["basecolor"]) as base:
                self.assertLess(base.getpixel((64, 10))[3], 255)
                self.assertEqual(base.getpixel((64, 100))[3], 255)
        self.assertAlmostEqual(fraction, 0.25, delta=0.05)


class GlassCandidateTests(unittest.TestCase):
    def test_declared_glass_is_found_or_the_next_seed_is_tried(self):
        from slopforge.failures import candidate_quality_rejection
        from test_mesh_pbr import DeclaredMaterialTests
        helper = DeclaredMaterialTests()
        materials = [parse_material_spec("bottle=glass#3c965a: green glass"),
                     parse_material_spec("cork=nonmetal: natural cork")]
        for base, status in ((two_regions(GREEN, CORK), "candidate"), (Image.new("RGB", (128, 128), CORK), "failed")):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                candidate = helper._candidate(Path(temporary), materials, 0, base)
                validation = candidate["validation"]
                self.assertEqual(candidate["status"], status)
                self.assertEqual(candidate["glass_source"], "declared_glass_mask")
                if status == "failed":
                    self.assertIn("glass_missing", validation["failure_codes"])
                    self.assertTrue(candidate_quality_rejection(validation))
                else:
                    self.assertGreater(validation["measured"]["glass_fraction"], 0.5)
                    with Image.open(Path(temporary) / candidate["outputs"]["basecolor"]) as image:
                        self.assertEqual(image.mode, "RGBA")


class UnityGlassTests(unittest.TestCase):
    def test_glass_faces_get_a_transparent_material_only_when_the_base_colour_has_alpha(self):
        from test_unity_import import fake_unity
        for alpha, transparent in ((255, False), (89, True)):
            with self.subTest(alpha=alpha), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                paths = {name: root / f"Assets/{name}.png" for name in ("basecolor", "normal", "metallic_gloss", "emission")}
                for path in paths.values():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGBA", (4, 4), (60, 150, 90, alpha)).save(path)
                (root / "Assets/bottle.fbx").write_bytes(b"fbx")
                scripts = []
                unity = fake_unity(root, {role: "a" * 32 for role in ("fbx", "material", *paths)})

                def run(*args, **kwargs):
                    scripts.extend(path.read_text() for path in (root / "Assets/Editor").glob("*.cs"))
                    unity(*args, **kwargs)

                with patch("slopforge.unity_material.unity_cli", return_value="unity"), \
                        patch("slopforge.unity_material.subprocess.run", side_effect=run):
                    build_unity_material(root, root / "Assets/bottle.fbx", root / "Assets/bottle.mat", paths)
                # Glass faces get their own transparent material; the main material stays opaque.
                self.assertEqual("if (true)" in scripts[0] and "SetTransparent(glass);" in scripts[0], transparent)
                self.assertIn('glassPath = "Assets/bottle_Glass.mat"', scripts[0])
