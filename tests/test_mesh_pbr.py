import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from processing.comfy_generate_3d import copy_generated_maps, copy_conditioning_image
from processing import comfy_generate_3d
from slopforge.pipelines.model import _native_material_candidate, retexture
from slopforge.manifest import begin_stage, save_manifest, start_execution, start_stage
from slopforge.unity_material import make_metallic_gloss


class MeshPBRTests(unittest.TestCase):
    def test_3d_sidecar_records_separate_shape_texture_calls_and_unknown_weights(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "concept.png"
            image.write_bytes(b"concept")
            workflow_path = root / "trellis.json"
            workflow_path.write_text(json.dumps({
                "prepared_mesh": {"class_type": "LoadMesh", "inputs": {"model_file": "old.glb"}},
                "save_raw": {"class_type": "SaveGLB", "inputs": {"filename_prefix": "raw"}},
                "save": {"class_type": "SaveGLB", "inputs": {"filename_prefix": "final"}},
                "save_basecolor": {"class_type": "SaveImage", "inputs": {"filename_prefix": "base"}},
                "save_roughness": {"class_type": "SaveImage", "inputs": {"filename_prefix": "rough"}},
                "save_metallic": {"class_type": "SaveImage", "inputs": {"filename_prefix": "metal"}},
                "save_normal": {"class_type": "SaveImage", "inputs": {"filename_prefix": "normal"}},
                "texture": {"class_type": "ApplyTextureToMesh", "inputs": {}},
                "1": {"class_type": "Checkpoint", "inputs": {"ckpt_name": "configured.safetensors"}},
            }))
            mesh, metadata = root / "mesh.glb", root / "generation.json"

            class Client:
                def __init__(self, _url): self.calls = 0; self.missing_shape_output = False; self.queued_facts = []
                def health(self): return {"system": {"comfyui_version": "0.3.1"}, "devices": []}
                def upload_input(self, _path, folder): return {"name": f"upload{folder}.png", "subfolder": folder}
                def queue_workflow(self, _workflow):
                    self.calls += 1
                    saved = json.loads(manifest_path.read_text())["assets"]["prop:relay"]
                    current = next(stage for stage in reversed(saved["executions"][-1]["stages"])
                                   if stage["status"] == "running")
                    self.queued_facts.append(current["provenance"].get("workflow_effective_sha256"))
                    return f"prompt-{self.calls}"
                def wait_for_completion(self, prompt, timeout=3600):
                    if int(prompt.split("-")[-1]) % 2:
                        if self.missing_shape_output:
                            return {"outputs": {}}
                        return {"outputs": {"save_raw": {"glb": {"filename": "raw.glb"}}}}
                    return {"outputs": {
                        "save": {"glb": {"filename": "final.glb"}},
                        **{f"save_{key}": {"images": [{"filename": f"{key}.png"}]}
                           for key in ("basecolor", "roughness", "metallic", "normal")},
                    }}
                def download_output(self, item, path): Path(path).write_bytes(item["filename"].encode())

            client = Client("http://comfy")
            def blender(*args, **_kwargs): Path(args[0][8]).write_bytes(b"prepared")
            concept = {"id": "concept:1", "type": "image.concept", "path": "concept.png",
                       "sha256": "a" * 64, "stage": "concept_generation", "attempt": 1, "derived_from": []}
            asset = {"id": "relay", "name": "relay", "type": "prop", "description": "relay"}
            execution = start_execution(asset, {"brief": "relay"})
            stage = start_stage(execution, "mesh_workflow_execution", 1, [concept], {}, {})
            begin_stage(stage)
            manifest_path = root / "manifest.json"
            save_manifest(manifest_path, {"schema_version": 4, "assets": {"prop:relay": asset}})
            client.manifest_path = manifest_path
            context = {"project_root": str(root), "manifest_path": str(manifest_path),
                       "asset_selector": "prop:relay", "execution_id": execution["id"],
                       "attempt": 1, "upstream_artifacts": [concept]}
            with patch.object(comfy_generate_3d, "ComfyUIClient", return_value=client), \
                    patch.object(comfy_generate_3d.subprocess, "run", side_effect=blender), \
                    patch.object(sys, "argv", ["comfy_generate_3d.py", "--image", str(image),
                        "--name", "relay", "--dest", str(mesh), "--workflow", str(workflow_path),
                        "--blender", "blender", "--seed", "17", "--metadata", str(metadata),
                        "--journal-context", json.dumps(context)]):
                comfy_generate_3d.main()

            saved = json.loads(metadata.read_text())
            self.assertEqual(saved["shape_prompt_id"], "prompt-1")
            self.assertEqual(saved["prompt_id"], "prompt-2")
            self.assertNotEqual(saved["shape_prompt_id"], saved["prompt_id"])
            self.assertEqual(saved["model_filenames"][0]["value"], "configured.safetensors")
            self.assertEqual(saved["provenance"]["model_weights"]["status"], "unavailable")
            self.assertEqual(saved["provenance"]["custom_node_revisions"]["status"], "unavailable")
            self.assertEqual(len(client.queued_facts), 2)
            self.assertTrue(all(fact and fact["status"] == "known" and len(fact["value"]) == 64
                                for fact in client.queued_facts))
            output_digests = {item["path"]: item["sha256"] for item in saved["outputs"]}
            self.assertEqual(output_digests[mesh.name], __import__("hashlib").sha256(b"final.glb").hexdigest())
            self.assertEqual(output_digests["mesh_untextured.glb"],
                             __import__("hashlib").sha256(b"raw.glb").hexdigest())
            self.assertEqual(output_digests["native_material/basecolor.png"],
                             __import__("hashlib").sha256(b"basecolor.png").hexdigest())
            record = json.loads(manifest_path.read_text())["assets"]["prop:relay"]
            raw = next(item for stage in record["executions"][-1]["stages"] for item in stage["outputs"]
                       if item["type"] == "mesh.raw")
            prepared_stage = next(stage for stage in record["executions"][-1]["stages"]
                                  if stage["name"] == "mesh_preparation")
            self.assertIn(raw["id"], {item["id"] for item in prepared_stage["inputs"]})
            prepared = next(item for item in prepared_stage["outputs"] if item["type"] == "mesh.prepared")
            self.assertIn(raw["id"], {item["artifact_id"] for item in prepared["derived_from"]})
            material_stage = next(stage for stage in record["executions"][-1]["stages"]
                                  if stage["name"] == "material_generation")
            self.assertIn(prepared["id"], {item["id"] for item in material_stage["inputs"]})
            final_acquisition = next(stage for stage in reversed(record["executions"][-1]["stages"])
                                     if stage["name"] == "mesh_output_acquisition")
            self.assertTrue(all(prepared["id"] in {parent["artifact_id"] for parent in artifact["derived_from"]}
                                for artifact in final_acquisition["outputs"]))

            second_mesh, second_metadata = root / "mesh-2.glb", root / "generation-2.json"
            context["attempt"] = 2
            with patch.object(comfy_generate_3d, "ComfyUIClient", return_value=client), \
                    patch.object(comfy_generate_3d.subprocess, "run", side_effect=blender), \
                    patch.object(sys, "argv", ["comfy_generate_3d.py", "--image", str(image),
                        "--name", "relay", "--dest", str(second_mesh), "--workflow", str(workflow_path),
                        "--blender", "blender", "--seed", "18", "--metadata", str(second_metadata),
                        "--journal-context", json.dumps(context)]):
                comfy_generate_3d.main()
            record = json.loads(manifest_path.read_text())["assets"]["prop:relay"]
            artifact_ids = [item["id"] for run in record["executions"] for stage in run["stages"]
                            for item in stage["outputs"]]
            self.assertEqual(len(artifact_ids), len(set(artifact_ids)))

            client.missing_shape_output = True
            context["attempt"] = 3
            missing_mesh, missing_metadata = root / "missing.glb", root / "missing.json"
            with patch.object(comfy_generate_3d, "ComfyUIClient", return_value=client), \
                    patch.object(comfy_generate_3d.subprocess, "run", side_effect=blender), \
                    patch.object(sys, "argv", ["comfy_generate_3d.py", "--image", str(image),
                        "--name", "relay", "--dest", str(missing_mesh), "--workflow", str(workflow_path),
                        "--blender", "blender", "--seed", "19", "--metadata", str(missing_metadata),
                        "--journal-context", json.dumps(context)]):
                with self.assertRaisesRegex(ValueError, "raw mesh"):
                    comfy_generate_3d.main()
            record = json.loads(manifest_path.read_text())["assets"]["prop:relay"]
            raw_shape = next(stage for stage in record["executions"][-1]["stages"]
                             if stage["name"] == "mesh_workflow_execution" and stage["attempt"] == 3)
            self.assertEqual(raw_shape["status"], "failed")

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
            config = {"asset_pipeline": {"candidate_root": "candidates", "manifest": "manifest.json",
                                         "model_budgets": {"prop_faces": 1000}}}
            asset = {"name": "relay", "description": "Ceramic and copper relay",
                     "generation_prompt": "Turquoise front plate, copper couplings",
                     "source": {"glb": "source/relay.glb", "processed_mesh": "source/processed.blend"},
                     "executions": []}
            concept = {"id": "concept:1", "type": "image.concept", "path": "concept.png",
                       "sha256": "a" * 64, "stage": "concept_generation", "attempt": 1, "derived_from": []}
            mesh = {"id": "mesh:1", "type": "mesh.final", "path": "source/relay.glb",
                    "sha256": "b" * 64, "stage": "mesh_output_acquisition", "attempt": 1, "derived_from": []}
            prepared = {"id": "prepared:1", "type": "mesh.prepared", "path": "source/processed.blend",
                        "sha256": "c" * 64, "stage": "mesh_preparation", "attempt": 1, "derived_from": []}
            map_inputs = [{"id": f"worker-map:{key}", "type": f"texture.{key}",
                           "path": f"source/{key}.png", "sha256": __import__("hashlib").sha256(originals[key]).hexdigest(),
                           "stage": "mesh_output_acquisition", "attempt": 1, "derived_from": []}
                          for key in originals]
            execution = start_execution(asset, {"brief": "relay"})
            manifest = {"schema_version": 4, "assets": {"prop:relay": asset}}
            save_manifest(root / "manifest.json", manifest)
            lineage = {"root": root, "pipeline": config["asset_pipeline"], "manifest": manifest,
                       "key": "prop:relay", "execution_id": execution["id"],
                       "upstream": [concept, mesh], "material_inputs": map_inputs,
                       "assembly_inputs": [prepared]}
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
                candidate = _native_material_candidate(root, config, {"face_budget": "prop_faces"}, asset, 1,
                                                       metadata, lineage=lineage)
            self.assertEqual(candidate["kind"], "mesh_pbr")
            self.assertEqual(candidate["status"], "candidate")
            material_directory = (root / candidate["outputs"]["surface"]).parent
            retained_metadata = json.loads((material_directory / "generation.json").read_text())
            self.assertEqual((material_directory / retained_metadata["conditioning_image"]).read_bytes(),
                             (source / "conditioning.png").read_bytes())
            for key, data in originals.items():
                self.assertEqual((root / candidate["outputs"][key]).read_bytes(), data)
            saved = json.loads((root / "manifest.json").read_text())["assets"]["prop:relay"]
            material_stage = next(stage for stage in saved["executions"][0]["stages"]
                                  if stage["name"] == "material_generation")
            material_refs = material_stage["outputs"]
            self.assertEqual({item["id"] for item in material_stage["inputs"]},
                             {item["id"] for item in map_inputs})
            self.assertTrue(all({parent["artifact_id"] for parent in item["derived_from"]}
                                == {value["id"] for value in map_inputs}
                                for item in material_refs if item["type"].startswith("texture.")))
            assembly = next(stage for stage in saved["executions"][0]["stages"]
                            if stage["name"] == "material_assembly_export")
            self.assertIn(prepared["id"], {item["id"] for item in assembly["inputs"]})
            asset["material_candidates"] = {"items": [candidate]}
            with self.assertRaisesRegex(ValueError, "mesh-generated PBR"):
                retexture(root, config, {}, {}, {"assets": {"prop:relay": asset}}, "prop:relay")

    def test_missing_generated_map_stops_the_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "basecolor map"):
                copy_generated_maps({}, Path(temporary))


if __name__ == "__main__":
    unittest.main()
