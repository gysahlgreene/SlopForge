import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from processing.comfy_generate_3d import copy_generated_maps
from slopforge.pipelines.model import _native_material_candidate, retexture
from slopforge.unity_material import make_metallic_gloss


class MeshPBRTests(unittest.TestCase):
    def test_unity_metallic_gloss_map_packs_inverse_roughness_in_alpha(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metallic, roughness, packed = (
                root / "metallic.png",
                root / "roughness.png",
                root / "packed.png",
            )
            metal = Image.new("L", (2, 1))
            metal.putdata([0, 200])
            metal.save(metallic)
            rough = Image.new("L", (2, 1))
            rough.putdata([255, 0])
            rough.save(roughness)
            make_metallic_gloss(metallic, roughness, packed)
            with Image.open(packed) as image:
                self.assertEqual(
                    (image.getpixel((0, 0)), image.getpixel((1, 0))),
                    ((0, 0, 0, 0), (200, 200, 200, 255)),
                )

    def test_native_material_preserves_generated_maps_and_uvs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "relay.glb").write_bytes(b"mesh")
            textures = {}
            originals = {}
            for index, key in enumerate(
                ("basecolor", "normal", "roughness", "metallic")
            ):
                path = source / f"{key}.png"
                Image.new("RGB", (64, 64), (40 + index * 30, 80, 120)).save(path)
                textures[key] = path.name
                originals[key] = path.read_bytes()
            config = {
                "asset_pipeline": {
                    "candidate_root": "candidates",
                    "model_budgets": {"prop_faces": 1000},
                }
            }
            asset = {
                "name": "relay",
                "description": "Ceramic and copper relay",
                "generation_prompt": "Turquoise front plate, copper couplings",
                "source": {
                    "glb": "source/relay.glb",
                    "processed_mesh": "source/processed.blend",
                },
            }
            metadata = {"workflow": "trellis.json", "seed": 42, "textures": textures}

            def process(_root, _config, _mesh, fbx, blend, maps, budget, **options):
                self.assertTrue(options["preserve_uvs"])
                self.assertNotIn("surface_source", options)
                fbx.write_bytes(b"fbx")
                blend.write_bytes(b"blend")
                options["preview_dir"].mkdir()
                for view in ("front", "side", "rear"):
                    Image.new("RGB", (64, 64), "gray").save(
                        options["preview_dir"] / f"relay_{view}.png"
                    )

            inspection = {
                "status": "passed",
                "errors": [],
                "warnings": [],
                "measured": {"face_count": 500, "uv_layers": 1},
            }
            with (
                patch("slopforge.pipelines.model.process_model", side_effect=process),
                patch(
                    "slopforge.pipelines.model.inspect_model", return_value=inspection
                ),
            ):
                candidate = _native_material_candidate(
                    root, config, {"face_budget": "prop_faces"}, asset, 1, metadata
                )
            self.assertEqual(candidate["kind"], "mesh_pbr")
            self.assertEqual(candidate["status"], "candidate")
            for key, data in originals.items():
                self.assertEqual((root / candidate["outputs"][key]).read_bytes(), data)
            asset["material_candidates"] = {"items": [candidate]}
            with self.assertRaisesRegex(ValueError, "mesh-generated PBR"):
                retexture(
                    root,
                    config,
                    {},
                    {},
                    {"assets": {"prop:relay": asset}},
                    "prop:relay",
                )

    def test_missing_generated_map_stops_the_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "basecolor map"):
                copy_generated_maps({}, Path(temporary))


if __name__ == "__main__":
    unittest.main()
