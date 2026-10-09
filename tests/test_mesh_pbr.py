import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from processing.comfy_generate_3d import copy_generated_maps, copy_conditioning_image
from slopforge.pipelines.model import _native_material_candidate, retexture
from slopforge.unity_material import make_metallic_gloss


class MeshPBRTests(unittest.TestCase):
    def test_actual_conditioning_image_is_downloaded_for_inspection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = {"filename": "crop.png", "subfolder": "generated", "type": "output"}

            class Client:
                def download_output(self, item, target):
                    assert item == source
                    Image.new("RGB", (32, 32), (200, 160, 100)).save(target)

            result = copy_conditioning_image({"save_conditioning": {"images": [source]}}, root, Client())
            self.assertEqual(result, "conditioning.png")
            with Image.open(root / result) as image:
                self.assertEqual(image.getpixel((0, 0)), (200, 160, 100))

    def test_missing_conditioning_output_is_an_actionable_failure(self):
        with self.assertRaisesRegex(ValueError, "conditioning image"):
            copy_conditioning_image({}, Path("unused"), object())

    def test_corrupt_conditioning_image_fails_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            class Client:
                def download_output(self, item, target):
                    target.write_bytes(b"not an image")

            with self.assertRaisesRegex(ValueError, "conditioning image.*invalid image"):
                copy_conditioning_image({"save_conditioning": {"images": [{}]}},
                                        Path(temporary), Client())

    def test_native_material_maps_keep_the_high_poly_normal_bake(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baked = root / "baked.png"
            Image.new("RGB", (128, 128), (80, 160, 240)).save(baked)
            outputs = {"save_" + key: {"images": [{"filename": key + ".png"}]}
                       for key in ("basecolor", "roughness", "metallic")}
            class Client:
                def download_output(self, item, target):
                    Image.new("RGB", (128, 128), "gray").save(target)
            textures = copy_generated_maps(outputs, root, Client(), baked_normal=baked)
            self.assertEqual((root / textures["normal"]).read_bytes(), baked.read_bytes())

    def test_native_material_maps_keep_a_workflow_generated_normal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = {"save_" + key: {"images": [{"filename": key + ".png"}]}
                       for key in ("basecolor", "roughness", "metallic", "normal")}
            class Client:
                def download_output(self, item, target):
                    Image.new("RGB", (128, 128), (80, 160, 240)).save(target)
            textures = copy_generated_maps(outputs, root, Client())
            with Image.open(root / textures["normal"]) as image:
                self.assertEqual(image.size, (128, 128))
                self.assertEqual(image.getpixel((0, 0)), (80, 160, 240))

    def test_unity_metallic_gloss_map_packs_inverse_roughness_in_alpha(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metallic, roughness, packed = root / "metallic.png", root / "roughness.png", root / "packed.png"
            metal = Image.new("L", (2, 1)); metal.putdata([0, 200]); metal.save(metallic)
            rough = Image.new("L", (2, 1)); rough.putdata([255, 0]); rough.save(roughness)
            make_metallic_gloss(metallic, roughness, packed)
            with Image.open(packed) as image:
                self.assertEqual((image.getpixel((0, 0)), image.getpixel((1, 0))),
                                 ((0, 0, 0, 0), (200, 200, 200, 255)))

    def test_native_material_preserves_generated_maps_and_uvs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "relay.glb").write_bytes(b"mesh")
            Image.new("RGB", (32, 32), "teal").save(source / "conditioning.png")
            textures = {}
            originals = {}
            for index, key in enumerate(("basecolor", "normal", "roughness", "metallic")):
                path = source / f"{key}.png"
                Image.new("RGB", (64, 64), (40 + index * 30, 80, 120)).save(path)
                textures[key] = path.name
                originals[key] = path.read_bytes()
            config = {"asset_pipeline": {"candidate_root": "candidates", "model_budgets": {"prop_faces": 1000}}}
            asset = {"name": "relay", "description": "Ceramic and copper relay",
                     "generation_prompt": "Turquoise front plate, copper couplings",
                     "source": {"glb": "source/relay.glb", "processed_mesh": "source/processed.blend"}}
            metadata = {"workflow": "trellis.json", "seed": 42, "textures": textures,
                        "conditioning_image": "conditioning.png"}

            def process(_root, _config, _mesh, fbx, blend, maps, budget, **options):
                self.assertTrue(options["preserve_uvs"])
                self.assertNotIn("surface_source", options)
                fbx.write_bytes(b"fbx")
                blend.write_bytes(b"blend")
                options["preview_dir"].mkdir()
                for view in ("front", "side", "rear", "three_quarter"):
                    Image.new("RGB", (64, 64), "gray").save(options["preview_dir"] / f"relay_{view}.png")

            inspection = {"status": "passed", "errors": [], "warnings": [],
                          "measured": {"mesh_objects": 1, "vertex_count": 1000, "face_count": 500,
                                       "dimensions": [1, 1, 1], "uv_layers": 1, "material_count": 1,
                                       "image_texture_count": 4,
                                       "component_count": 1, "nonmanifold_edge_count": 0,
                                       "transforms_applied": True, "missing_textures": []}}
            with patch("slopforge.pipelines.model.process_model", side_effect=process), \
                    patch("slopforge.pipelines.model.inspect_model", return_value=inspection):
                candidate = _native_material_candidate(root, config, {"face_budget": "prop_faces"}, asset, 1, metadata)
            self.assertEqual(candidate["kind"], "mesh_pbr")
            self.assertEqual(candidate["status"], "candidate")
            material_directory = (root / candidate["outputs"]["surface"]).parent
            retained_metadata = json.loads((material_directory / "generation.json").read_text())
            self.assertEqual((material_directory / retained_metadata["conditioning_image"]).read_bytes(),
                             (source / "conditioning.png").read_bytes())
            for key, data in originals.items():
                self.assertEqual((root / candidate["outputs"][key]).read_bytes(), data)
            asset["material_candidates"] = {"items": [candidate]}
            with self.assertRaisesRegex(ValueError, "mesh-generated PBR"):
                retexture(root, config, {}, {}, {"assets": {"prop:relay": asset}}, "prop:relay")

    def test_missing_generated_map_stops_the_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "basecolor map"):
                copy_generated_maps({}, Path(temporary))


if __name__ == "__main__":
    unittest.main()
