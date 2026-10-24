import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from processing.comfy_generate_3d import copy_generated_maps, copy_conditioning_image
from processing import comfy_generate_3d
from slopforge.pipelines.model import _generate_material_candidate, _native_material_candidate, retexture
from slopforge.manifest import begin_stage, save_manifest, start_execution, start_stage
from slopforge.unity_material import make_metallic_gloss


class MeshPBRTests(unittest.TestCase):
    def test_retexture_passes_processed_mesh_to_blender_only_with_reuse_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "image.json").write_text("{}")
            (root / "source.glb").write_bytes(b"source")
            (root / "processed.blend").write_bytes(b"processed")
            asset = {"name": "relay", "description": "Brass relay",
                     "source": {"glb": "source.glb", "processed_mesh": "processed.blend"}}
            config = {"asset_pipeline": {"candidate_root": "candidates", "workflows": {"image": "image.json"},
                                         "model_budgets": {"prop_faces": 1000}, "material_scale": 3.0,
                                         "tools": {}}}
            asset_type = {"name": "prop", "face_budget": "prop_faces"}

            for proven in (False, True):
                with self.subTest(proven=proven):
                    reuse = []

                    def process(_root, _config, _source, fbx, blend, _textures, _budget, **kwargs):
                        reuse.append(kwargs["reuse_stage_mesh"])
                        for path in (fbx, blend, kwargs["stage_mesh"]):
                            path.write_bytes(b"result")
                        kwargs["preview_dir"].mkdir(parents=True, exist_ok=True)
                        for view in ("front", "side", "rear", "three_quarter"):
                            Image.new("RGB", (8, 8), "gray").save(kwargs["preview_dir"] / f"relay_{view}.png")

                    def generate_image(_root, _config, _workflow, _prompt, destination, _prefix, seed, metadata):
                        Image.new("RGB", (8, 8), "blue").save(destination)
                        metadata.write_text(json.dumps({"workflow": "image.json", "seed": seed}))

                    def commands(command, check):
                        for key in ("normal", "roughness", "metallic", "emission"):
                            Image.new("RGB", (8, 8), "white").save(command[command.index("--" + key) + 1])

                    with patch("slopforge.pipelines.model.resolve_workflow", return_value=root / "image.json"), \
                            patch("slopforge.pipelines.model.generate_image", side_effect=generate_image), \
                            patch("slopforge.pipelines.model.subprocess.run", side_effect=commands), \
                            patch("slopforge.pipelines.model.make_metallic_gloss",
                                  side_effect=lambda _metal, _rough, output: Path(output).write_bytes(b"packed")), \
                            patch("slopforge.pipelines.model.process_model", side_effect=process), \
                            patch("slopforge.pipelines.model.inspect_model", return_value={}), \
                            patch("slopforge.pipelines.model.validate_model_outputs",
                                  return_value={"status": "passed", "errors": [], "warnings": [], "measured": {}}), \
                            patch("slopforge.pipelines.model._lineage_start"), \
                            patch("slopforge.pipelines.model._lineage_finish", return_value=[]), \
                            patch("slopforge.pipelines.model._lineage_provenance"):
                        candidate = _generate_material_candidate(root, config, asset_type, asset, int(proven) + 1,
                            "matte brass", root / "processed.blend",
                            lineage={"processed_mesh_reusable": proven}, seed=int(proven) + 1)
                        self.assertNotIn("error", candidate, candidate.get("error"))

                    self.assertEqual(reuse, [proven])

    def test_material_identity_binds_prepared_mesh_content_of_bundled_graph(self):
        graph = json.loads((Path(__file__).resolve().parents[1] / "workflows" /
                            "trellis2_image_to_model_h100_api.json").read_text())
        graph["prepared_mesh"]["inputs"]["model_file"] = "3d/prepared.glb"
        identities = [comfy_generate_3d._workflow_identity(graph, graph, {"ai3d/concept.png": "a" * 64},
                                                           "3d/prepared.glb", digest)
                      for digest in ("b" * 64, "c" * 64)]
        self.assertEqual(identities[0][1]["prepared_mesh.model_file"], "b" * 64)
        self.assertNotEqual(identities[0][0]["effective_sha256"], identities[1][0]["effective_sha256"])

    def test_3d_sidecar_records_separate_shape_texture_calls_and_unknown_weights(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "concept.png"
            image.write_bytes(b"concept")
            workflow_path = root / "trellis.json"
            workflow_path.write_text(json.dumps({
                "prepared_mesh": {"class_type": "Load3DAdvanced", "inputs": {"model_file": "none", "viewport_state": {},
                                                                             "width": 1024, "height": 1024}},
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
                def health(self, retry_window=0): return {"system": {"comfyui_version": "0.3.1"}, "devices": []}
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
                       "attempt": 1, "stage_id": stage["id"], "upstream_artifacts": [concept]}
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
            prepared_digest = __import__("hashlib").sha256(b"prepared").hexdigest()
            self.assertEqual(saved["effective_bindings"]["uploaded_inputs"]["prepared_mesh.model_file"], prepared_digest)
            self.assertTrue(all(fact and fact["status"] == "known" and len(fact["value"]) == 64
                                for fact in client.queued_facts))
            output_digests = {item["path"]: item["sha256"] for item in saved["outputs"]}
            self.assertEqual(output_digests[mesh.name], __import__("hashlib").sha256(b"final.glb").hexdigest())
            self.assertEqual(output_digests["mesh_untextured.glb"],
                             __import__("hashlib").sha256(b"raw.glb").hexdigest())
            self.assertEqual(output_digests["native_material/basecolor.png"],
                             __import__("hashlib").sha256(b"basecolor.png").hexdigest())
            record = json.loads(manifest_path.read_text())["assets"]["prop:relay"]
            # The worker has not yet returned control to the model orchestrator;
            # the parent mesh_workflow_execution stage must remain running with no outputs.
            parent_stage = next(stage for stage in record["executions"][-1]["stages"]
                                if stage["name"] == "mesh_workflow_execution")
            self.assertEqual(parent_stage["status"], "running")
            self.assertEqual(parent_stage["outputs"], [])
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
            stage = start_stage(execution, "mesh_workflow_execution", 2, [concept], {}, {})
            begin_stage(stage)
            save_manifest(manifest_path, {"schema_version": 4, "assets": {"prop:relay": asset}})
            context["attempt"] = 2
            context["stage_id"] = stage["id"]
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
            stage = start_stage(execution, "mesh_workflow_execution", 3, [concept], {}, {})
            begin_stage(stage)
            save_manifest(manifest_path, {"schema_version": 4, "assets": {"prop:relay": asset}})
            context["stage_id"] = stage["id"]
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

    def test_missing_workflow_normal_yields_detectable_placeholder(self):
        from slopforge.validation import is_placeholder_normal
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = {"save_" + key: {"images": [{"filename": key + ".png"}]}
                       for key in ("basecolor", "roughness", "metallic")}
            class Client:
                def download_output(self, item, target):
                    Image.new("RGB", (128, 128), "gray").save(target)
            textures = copy_generated_maps(outputs, root, Client())
            self.assertTrue(is_placeholder_normal(root / textures["normal"]))
            self.assertFalse(is_placeholder_normal(root / textures["basecolor"]))

    def test_material_map_measurement_flags_near_black_atlas_and_size_mismatch(self):
        from slopforge.validation import measure_material_maps
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            black = Image.new("RGB", (64, 64), (0, 0, 0)); black.putpixel((0, 0), (200, 90, 40))
            black.save(root / "basecolor.png")
            Image.new("L", (32, 32), 128).save(root / "roughness.png")
            result = measure_material_maps({"basecolor": root / "basecolor.png", "roughness": root / "roughness.png"})
            self.assertGreater(result["maps"]["basecolor"]["near_black_fraction"], 0.99)
            joined = " | ".join(result["warnings"])
            self.assertIn("basecolor map is", joined)
            self.assertIn("single constant color", joined)
            self.assertIn("dimensions differ", joined)

    def test_material_map_measurement_flags_near_fully_metallic_map(self):
        from slopforge.validation import measure_material_maps
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "metallic.png"
            metal = Image.new("L", (64, 64), 255); metal.putpixel((0, 0), 0); metal.save(path)
            result = measure_material_maps({"metallic": path})
            self.assertGreater(result["maps"]["metallic"]["near_full_metal_fraction"], 0.99)
            self.assertIn("fully metallic", " | ".join(result["warnings"]))
            Image.new("L", (64, 64), 0).save(path)
            self.assertFalse([item for item in measure_material_maps({"metallic": path})["warnings"]
                              if "near-black" in item])

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
            worker_stage = start_stage(execution, "material_generation", 1, map_inputs, {}, {})
            worker_stage.update(status="succeeded", outputs=[])
            manifest = {"schema_version": 4, "assets": {"prop:relay": asset}}
            save_manifest(root / "manifest.json", manifest)
            lineage = {"root": root, "pipeline": config["asset_pipeline"], "manifest": manifest,
                       "key": "prop:relay", "execution_id": execution["id"],
                       "upstream": [concept, mesh], "material_inputs": map_inputs,
                       "assembly_inputs": [prepared]}
            context = {**lineage, "_stage_handles": {}}
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
                candidate = _native_material_candidate(root, config, context, {"face_budget": "prop_faces"}, asset, 1,
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
                                  if stage["name"] == "material_generation" and stage["outputs"])
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


class DeclaredMaterialTests(unittest.TestCase):
    def _candidate(self, root, materials, metallic_value, basecolor, cutout=None, limits=None):
        source = root / "source"
        source.mkdir()
        (source / "relay.glb").write_bytes(b"mesh")
        basecolor.save(source / "basecolor.png")
        for key, value in (("normal", (128, 128, 255)), ("roughness", (200,) * 3), ("metallic", (metallic_value,) * 3)):
            Image.new("RGB", basecolor.size, value).save(source / f"{key}.png")
        textures = {key: f"{key}.png" for key in ("basecolor", "normal", "roughness", "metallic")}
        config = {"asset_pipeline": {"candidate_root": "candidates", "manifest": "manifest.json",
                                     "model_budgets": {"prop_faces": 1000}}}
        asset = {"name": "lantern", "description": "Stone lantern", "materials": materials, "executions": [],
                 "source": {"glb": "source/relay.glb", "processed_mesh": "source/processed.blend"}}
        execution = start_execution(asset, {"brief": "lantern"})
        manifest = {"schema_version": 4, "assets": {"prop:lantern": asset}}
        save_manifest(root / "manifest.json", manifest)
        lineage = {"root": root, "pipeline": config["asset_pipeline"], "manifest": manifest,
                   "key": "prop:lantern", "execution_id": execution["id"], "upstream": [],
                   "material_inputs": [], "assembly_inputs": [], "concept_cutout": cutout}

        def process(_root, _config, _mesh, fbx, blend, maps, budget, **options):
            fbx.write_bytes(b"fbx"); blend.write_bytes(b"blend"); options["preview_dir"].mkdir()
            for view in ("front", "side", "rear", "three_quarter"):
                Image.new("RGB", (64, 64), "gray").save(options["preview_dir"] / f"lantern_{view}.png")

        inspection = {"status": "passed", "errors": [], "warnings": [],
                      "measured": {"mesh_objects": 1, "vertex_count": 1000, "face_count": 500,
                                   "dimensions": [1, 1, 1], "uv_layers": 1, "material_count": 1,
                                   "image_texture_count": 4, "component_count": 1, "nonmanifold_edge_count": 0,
                                   "transforms_applied": True, "missing_textures": []}}
        with patch("slopforge.pipelines.model.process_model", side_effect=process), \
                patch("slopforge.pipelines.model.inspect_model", return_value=inspection):
            return _native_material_candidate(root, config, {**lineage, "_stage_handles": {}},
                                              {"face_budget": "prop_faces", **(limits or {})},
                                              asset, 1, {"workflow": "w.json", "seed": 1, "textures": textures},
                                              lineage=lineage)

    def test_base_colour_that_drifts_from_the_concept_retries_the_next_seed(self):
        # 2026-10-21 protocol jug B2: a cobalt concept baked a teal glaze (hue difference 9.9), and the
        # v2 jug a washed-out navy (saturation 0.62 from the concept's side); other seeds stayed faithful.
        from slopforge.failures import candidate_quality_rejection
        limits = {"max_concept_hue_difference": 4, "min_concept_chroma_ratio": 0.6}
        jug = [{"region": "jug", "class": "nonmetal", "description": "glaze"}]
        for concept_rgb, view_rgb, code in (((40, 60, 150), (40, 62, 148), None),
                                            ((40, 60, 150), (30, 110, 140), "colour_hue_shift"),
                                            ((40, 60, 150), (48, 48, 81), "colour_desaturated"),  # same hue
                                            ((128, 128, 130), (30, 110, 140), None)):  # grey concept: no hue to keep
            with self.subTest(view=view_rgb), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                candidate = self._colour_candidate(root, jug, concept_rgb, (20, 20, 30), view_rgb, limits)
                validation = candidate["validation"]
                self.assertEqual(validation["measured"]["colour_source"], "concept_view")
                if code is None:
                    self.assertEqual(candidate["status"], "candidate")
                    self.assertFalse({"colour_hue_shift", "colour_desaturated"} & set(validation.get("failure_codes", [])))
                else:
                    self.assertEqual(candidate["status"], "failed")
                    self.assertIn(code, validation["failure_codes"])
                    self.assertTrue(candidate_quality_rejection(validation))
                    self.assertIn(code, candidate["failure"]["message"])

    def test_base_colour_that_turns_dark_where_the_concept_is_light_retries_the_next_seed(self):
        # 2026-10-23 moorland cliff: TRELLIS textured light granite mostly black (darkened share 0.45), and the
        # hue and saturation checks skip near-grey stone. Dark beams that are dark in the concept too stay accepted.
        from slopforge.failures import candidate_quality_rejection
        limits = {"max_concept_hue_difference": 4, "min_concept_chroma_ratio": 0.6, "max_concept_darkened_share": 0.4}
        stone = [{"region": "rock", "class": "nonmetal", "description": "granite"}]
        grey, black, beam = (150, 150, 146), (22, 22, 21), (45, 30, 22)

        def picture(blackened, beams):
            image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            image.paste((*grey, 255), (16, 8, 48, 56))
            for x in beams:  # dark vertical beams, as on a timber wall
                image.paste((*beam, 255), (x, 8, x + 4, 56))
            if blackened:  # the left 60% of the object turned near-black
                image.paste((*black, 255), (16, 8, 35, 56))
            return image
        for blackened, beams, status in ((False, (), "candidate"), (True, (), "failed"),
                                         (False, (20, 30, 40), "candidate")):
            with self.subTest(blackened=blackened, beams=beams), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                picture(False, beams).save(root / "concept_cutout.png")

                def view(_root, _config, _cutout, _mesh, paths, name, **_options):
                    picture(blackened, beams).save(paths["directory"] / f"{name}_base.png")
                    return {"status": "rendered", "silhouette_iou": 0.95}
                with patch("slopforge.pipelines.model._concept_view", side_effect=view):
                    candidate = self._candidate(root, stone, 0, Image.new("RGB", (64, 64), grey),
                                                cutout=root / "concept_cutout.png", limits=limits)
                validation = candidate["validation"]
                self.assertEqual(candidate["status"], status)
                if status == "failed":
                    self.assertEqual(validation["failure_codes"], ["colour_darkened"])
                    self.assertGreater(validation["measured"]["concept_darkened_share"], 0.4)
                    self.assertTrue(candidate_quality_rejection(validation))  # the next seed is tried
                else:
                    self.assertLess(validation["measured"]["concept_darkened_share"], 0.1)

    def test_a_mesh_that_drops_the_concepts_thin_parts_retries_when_a_minimum_is_declared(self):
        # A bow's string is a few pixels wide: the row-filled concept fit cannot see it go missing.
        from slopforge.failures import candidate_quality_rejection
        bow = [{"region": "bow", "class": "nonmetal", "description": "yew"}]

        def picture(string):
            image = Image.new("RGBA", (256, 128), (0, 0, 0, 0))
            image.paste((120, 80, 40, 255), (20, 20, 60, 108))  # the bow's thick riser
            if string:
                image.paste((230, 230, 220, 255), (200, 20, 202, 108))  # a 2-pixel string
            return image
        for limit, string, status in ((None, False, "candidate"), (0.6, True, "candidate"), (0.6, False, "failed")):
            with self.subTest(limit=limit, string=string), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                picture(True).save(root / "concept_cutout.png")

                def view(_root, _config, _cutout, _mesh, paths, name, **_options):
                    picture(string).save(paths["directory"] / f"{name}_base.png")
                    return {"status": "rendered", "silhouette_iou": 0.95}
                limits = {"max_concept_hue_difference": 4, **({"min_concept_thin_recall": limit} if limit else {})}
                with patch("slopforge.pipelines.model._concept_view", side_effect=view):
                    candidate = self._candidate(root, bow, 0, Image.new("RGB", (64, 64), (120, 80, 40)),
                                                cutout=root / "concept_cutout.png", limits=limits)
                measured = candidate["validation"]["measured"]
                self.assertEqual(candidate["status"], status)
                self.assertGreater(measured["concept_thin_share"], 0.01)
                self.assertEqual(measured["concept_thin_recall"], 1.0 if string else 0.0)  # recorded either way
                if status == "failed":
                    self.assertEqual(candidate["validation"]["failure_codes"], ["thin_feature_missing"])
                    self.assertTrue(candidate_quality_rejection(candidate["validation"]))

    def test_without_a_concept_view_only_hue_is_checked_on_the_whole_map(self):
        # Hidden insides and bases lower the whole map's saturation (2026-10-21 jug: 0.42 of the concept's,
        # 0.83 from the concept's side), so a washed-out atlas alone must not fail the candidate.
        limits = {"max_concept_hue_difference": 4, "min_concept_chroma_ratio": 0.6}
        jug = [{"region": "jug", "class": "nonmetal", "description": "glaze"}]
        for atlas_rgb, status in (((48, 48, 81), "candidate"), ((30, 110, 140), "failed")):  # same hue, 0.39 saturation
            with self.subTest(atlas=atlas_rgb), tempfile.TemporaryDirectory() as temporary:
                candidate = self._colour_candidate(Path(temporary), jug, (40, 60, 150), atlas_rgb, None, limits)
                validation = candidate["validation"]
                self.assertEqual(validation["measured"]["colour_source"], "atlas")
                self.assertEqual(candidate["status"], status)
                self.assertNotIn("colour_desaturated", validation.get("failure_codes", []))
                self.assertTrue(any("saturation against the concept was not checked" in item
                                    for item in validation["warnings"]))

    def test_candidate_that_no_longer_fits_the_concept_outline_retries(self):
        # 2026-10-22 shattered glass bottles fitted 0.71-0.75; whole props 0.86-0.99.
        jug = [{"region": "jug", "class": "nonmetal", "description": "glaze"}]
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._colour_candidate(Path(temporary), jug, (40, 60, 150), (40, 62, 148), None,
                                               {"min_concept_fit": 0.8})
        self.assertEqual(candidate["status"], "failed")
        self.assertIn("concept_fit", candidate["validation"]["failure_codes"])
        self.assertEqual(candidate["validation"]["measured"]["concept_fit"], 0.7)

    def _colour_candidate(self, root, materials, concept_rgb, atlas_rgb, view_rgb, limits):
        cutout = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        cutout.paste((*concept_rgb, 255), (16, 8, 48, 56))
        cutout.save(root / "concept_cutout.png")

        def view(_root, _config, _cutout, _mesh, paths, name, **options):
            self.assertEqual((options["min_iou"], options["uv"]), (0.8, False))
            if view_rgb is None:
                return {"status": "skipped", "silhouette_iou": 0.7, "reason": "best silhouette fit 0.700 is below 0.8"}
            render = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            render.paste((*view_rgb, 255), (16, 8, 48, 56))
            render.save(paths["directory"] / f"{name}_base.png")
            return {"status": "rendered", "silhouette_iou": 0.95}

        with patch("slopforge.pipelines.model._concept_view", side_effect=view):
            return self._candidate(root, materials, 0, Image.new("RGB", (64, 64), atlas_rgb),
                                   cutout=root / "concept_cutout.png", limits=limits)

    def test_partial_metal_map_is_zeroed_when_brief_declares_no_metal(self):
        # 2026-10-20 glazed jug: TRELLIS.2 decoded the declared non-metal glaze at metallic ~0.38-0.60.
        for value in (100, 255):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                candidate = self._candidate(root, [{"region": "jug", "class": "nonmetal", "description": "glaze"}],
                                            value, Image.new("RGB", (64, 64), (29, 46, 75)))
                self.assertEqual(candidate["status"], "candidate")
                self.assertEqual(candidate["metallic_source"], "declared_nonmetal")
                self.assertFalse([item for item in candidate["validation"]["warnings"] if "metallic" in item])
                with Image.open(root / candidate["outputs"]["metallic"]) as metallic:
                    self.assertEqual(metallic.convert("L").getextrema(), (0, 0))
                with Image.open(root / candidate["outputs"]["metallic_gloss"]) as packed:
                    self.assertEqual(packed.getchannel("R").getextrema(), (0, 0))
                with Image.open(root / "source/metallic.png") as raw:  # generator output is kept
                    self.assertEqual(raw.getpixel((0, 0)), (value,) * 3)
                metallic = candidate["validation"]["measured"]["material_maps"]["metallic"]
                self.assertEqual(metallic["mean"], 0)
                self.assertAlmostEqual(metallic["generator_mean"], value / 255, places=3)

    def test_mixed_and_undeclared_briefs_keep_the_generated_metallic_map(self):
        for materials in ([{"region": "planks", "class": "nonmetal", "description": "oak"},
                           {"region": "brackets", "class": "metal", "description": "iron"}], []):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                candidate = self._candidate(root, materials, 128, Image.new("RGB", (64, 64), (90, 70, 50)))
                self.assertEqual(candidate["status"], "candidate")
                self.assertEqual(candidate["metallic_source"], "generator")
                self.assertAlmostEqual(candidate["validation"]["measured"]["material_maps"]["metallic"]["mean"],
                                       128 / 255, places=3)

    def test_declared_metal_brief_accepts_full_metal_map_without_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate(Path(temporary), [{"region": "key", "class": "metal", "description": "brass"}],
                                        255, Image.new("RGB", (64, 64), (180, 140, 60)))
            self.assertEqual(candidate["status"], "candidate")
            self.assertFalse([item for item in candidate["validation"]["warnings"] if "metallic" in item])

    def test_declared_emissive_region_derives_emission_from_white_panels_not_flecks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = Image.new("RGB", (256, 256), (90, 90, 90))
            base.paste((250, 250, 250), (40, 40, 120, 140))  # glowing panel
            for x in range(150, 250, 12):
                base.putpixel((x, 200), (255, 255, 255))  # stone flecks
            candidate = self._candidate(root, [{"region": "body", "class": "nonmetal", "description": ""},
                                               {"region": "windows", "class": "emissive", "description": ""}], 0, base)
            self.assertEqual(candidate["status"], "candidate")
            self.assertEqual(candidate["emission_source"], "declared_emissive_mask")
            with Image.open(root / candidate["outputs"]["emission"]) as emission:
                self.assertGreater(max(emission.getpixel((80, 90))), 150)
                self.assertEqual(emission.getpixel((210, 200)), (0, 0, 0))

    def test_pale_emitter_found_at_trellis_paper_albedo_but_pale_body_does_not_glow(self):
        from slopforge.unity_material import derive_emission
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Paper panels as TRELLIS.2 baked them in the 2026-10-20 lantern runs (201 flat, 157-173 mottled)
            # on granite with a median near 105.
            base = Image.new("RGB", (256, 256), (105, 105, 102))
            base.paste((201, 202, 202), (20, 20, 80, 80))
            base.paste((166, 165, 164), (120, 20, 180, 80))
            base.save(root / "basecolor.png")
            fraction = derive_emission(root / "basecolor.png", root / "emission.png")
            with Image.open(root / "emission.png") as emission:
                self.assertGreater(max(emission.getpixel((50, 50))), 150)
                self.assertGreater(max(emission.getpixel((150, 50))), 150)
                self.assertEqual(emission.getpixel((128, 200)), (0, 0, 0))
            self.assertAlmostEqual(fraction, 2 * 60 * 60 / 256 ** 2, delta=0.01)
            # A body as pale as the paper cannot be told apart from it; it must not glow as a whole.
            Image.new("RGB", (256, 256), (186, 184, 180)).save(root / "pale.png")
            self.assertEqual(derive_emission(root / "pale.png", root / "pale_emission.png"), 0)

    def test_pale_emitter_covering_most_of_the_map_is_still_found(self):
        from slopforge.unity_material import derive_emission
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # A paper lampshade: the emitter is most of the map, so the map's median is the paper itself.
            base = Image.new("RGB", (256, 256), (40, 32, 28))
            base.paste((230, 230, 228), (20, 20, 236, 236))
            base.save(root / "basecolor.png")
            self.assertGreater(derive_emission(root / "basecolor.png", root / "emission.png"), 0.5)

    def test_one_found_emitter_does_not_hide_another_missing_one(self):
        from slopforge.unity_material import derive_emission
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # An amber lens is present; the declared pale window panels are not.
            base = Image.new("RGB", (256, 256), (90, 80, 70))
            base.paste((224, 160, 48), (40, 40, 130, 130))
            base.save(root / "basecolor.png")
            targets = [(None, (255, 178, 102)), ((224, 160, 48), (224, 160, 48))]
            self.assertEqual(derive_emission(root / "basecolor.png", root / "emission.png", targets), 0)
            with Image.open(root / "emission.png") as emission:
                self.assertGreater(max(emission.getpixel((85, 85))), 150)  # the found lens still glows

    def test_declared_emitter_missing_from_base_color_is_a_retryable_candidate_failure(self):
        from slopforge.failures import should_retry
        materials = [{"region": "body", "class": "nonmetal", "description": ""},
                     {"region": "panels", "class": "emissive", "description": ""}]
        with tempfile.TemporaryDirectory() as temporary:
            # 2026-10-20 C3: windows rebuilt as slats with warm slivers of paper, so no pale panel was baked.
            base = Image.new("RGB", (256, 256), (120, 120, 118))
            base.paste((185, 164, 151), (40, 40, 120, 140))
            candidate = self._candidate(Path(temporary), materials, 0, base)
        self.assertEqual(candidate["status"], "failed")
        self.assertEqual(candidate["validation"]["failure_codes"], ["emitter_missing"])
        self.assertEqual(candidate["validation"]["measured"]["emissive_fraction"], 0)
        self.assertEqual(candidate["failure"]["category"], "candidate_quality")
        self.assertTrue(should_retry(candidate["failure"], used=1, limit=3))
        self.assertFalse(should_retry(candidate["failure"], used=3, limit=3))
        with tempfile.TemporaryDirectory() as temporary:
            base.paste((230, 230, 228), (40, 40, 120, 140))
            found = self._candidate(Path(temporary), materials, 0, base)
        self.assertEqual(found["status"], "candidate")
        self.assertNotIn("emitter_missing", found["validation"].get("failure_codes", []))

    def test_unity_material_marks_itself_emissive_so_urp_keeps_the_emission_keyword(self):
        from slopforge.unity_material import build_unity_material
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            from test_unity_import import fake_unity
            maps = {name: root / f"Assets/{name}.png" for name in ("basecolor", "normal", "metallic_gloss", "emission")}
            for path in maps.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (4, 4), "gray").save(path)
            (root / "Assets/lantern.fbx").write_bytes(b"x")
            scripts = []
            unity = fake_unity(root, {role: "a" * 32 for role in ("fbx", "material", *maps)})

            def run(*args, **kwargs):
                scripts.extend(path.read_text() for path in (root / "Assets/Editor").glob("*.cs"))
                unity(*args, **kwargs)

            with patch("slopforge.unity_material.unity_cli", return_value="unity"), \
                    patch("slopforge.unity_material.subprocess.run", side_effect=run):
                build_unity_material(root, root / "Assets/lantern.fbx", root / "Assets/lantern.mat", maps)
        # URP's validation sets _EMISSION from the GI flags, which default to EmissiveIsBlack.
        self.assertLess(scripts[0].index("MaterialGlobalIlluminationFlags.BakedEmissive"),
                        scripts[0].index("AssetDatabase.SaveAssets()"))
        self.assertIn('!assigned.IsKeywordEnabled("_EMISSION")', scripts[0])

    def test_declared_emissive_colour_matches_coloured_lens_and_glows_in_that_colour(self):
        from slopforge.style import parse_material_spec
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = Image.new("RGB", (256, 256), (40, 40, 45))
            base.paste((230, 160, 40), (100, 100, 160, 160))  # amber lens
            lens = parse_material_spec("lens=emissive#e6a028: amber glass")
            self.assertEqual(lens["color"], "#e6a028")
            candidate = self._candidate(root, [{"region": "housing", "class": "nonmetal", "description": ""}, lens], 0, base)
            self.assertGreater(candidate["validation"]["measured"]["emissive_fraction"], 0.04)
            with Image.open(root / candidate["outputs"]["emission"]) as emission:
                self.assertEqual(emission.getpixel((130, 130)), (230, 160, 40))
                self.assertEqual(emission.getpixel((20, 20)), (0, 0, 0))
        with self.assertRaisesRegex(ValueError, "--material must be"):
            parse_material_spec("housing=metal#ffffff")  # metal has no colour rule
        self.assertEqual(parse_material_spec("grip=nonmetal#5a3a22: leather")["color"], "#5a3a22")

    def test_a_coloured_nonmetal_beside_declared_metal_loses_its_false_metal(self):
        # A sword declares a steel blade, so the generator's metallic map is kept; its leather grip must not shine.
        from slopforge.failures import candidate_quality_rejection
        from slopforge.style import parse_material_spec
        sword = [parse_material_spec("blade=metal: steel"), parse_material_spec("grip=nonmetal#5a3a22: leather")]
        for grip_in_map, status in ((True, "candidate"), (False, "failed")):
            with self.subTest(grip_in_map=grip_in_map), tempfile.TemporaryDirectory() as temporary:
                base = Image.new("RGB", (256, 256), (170, 175, 180))  # steel
                if grip_in_map:
                    base.paste((90, 58, 34), (0, 0, 80, 256))  # the grip's leather colour
                candidate = self._candidate(Path(temporary), sword, 200, base)
                validation = candidate["validation"]
                self.assertEqual(candidate["status"], status)
                self.assertEqual(candidate["metallic_source"], "generator_with_declared_nonmetals")
                with Image.open(Path(temporary) / candidate["outputs"]["metallic"]) as metallic:
                    grey = metallic.convert("L")
                    self.assertEqual(grey.getpixel((200, 128)), 200)  # the steel keeps its metal
                    if grip_in_map:
                        self.assertEqual(grey.getpixel((40, 128)), 0)  # the leather is a dielectric
                if grip_in_map:
                    self.assertGreater(validation["measured"]["nonmetal_fraction"], 0.2)
                else:
                    self.assertEqual(validation["failure_codes"], ["nonmetal_missing"])
                    self.assertTrue(candidate_quality_rejection(validation))

    def test_reconstruction_rules_are_appended_to_agent_prompts_with_materials(self):
        from slopforge.style import parse_material_spec, reconstruction_rules
        materials = [parse_material_spec("body=nonmetal: weathered granite"), parse_material_spec("windows=emissive")]
        rules = reconstruction_rules({"pipeline": "model"}, materials)
        self.assertIn("no dramatic shadows or baked highlights", rules)
        self.assertIn("- body: weathered granite; matte non-metallic surface", rules)
        self.assertIn("- windows: a solid opaque surface with a dull matte finish", rules)
        self.assertNotRegex(rules.lower(), r"glow|lit\b|switched|light source")  # glow words drew it lit
        self.assertEqual(reconstruction_rules({"pipeline": "image"}, materials), "")
        self.assertIn("clear gap between each hand and the hips",
                      reconstruction_rules({"pipeline": "model", "prompt_mode": "character"}))
        self.assertNotIn("clear gap", reconstruction_rules({"pipeline": "model"}))
        # A weapon's blade or bowstring cannot follow the props' "no thin parts" rule, so its type replaces it.
        weapon = reconstruction_rules({"pipeline": "model", "reconstruction_rule": "Blades drawn with real thickness"})
        self.assertIn("- Blades drawn with real thickness", weapon)
        self.assertNotIn("no thin hollow tubes", weapon)
        self.assertIn("no thin hollow tubes", reconstruction_rules({"pipeline": "model"}))
        from slopforge.config import load_project
        from slopforge.initializer import init_project
        from slopforge.style import build_prompt, load_style
        from slopforge.taxonomy import load_taxonomy
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            init_project(root)
            style = load_style(root, load_project(root))
            style["materials"] = {"stone": {"description": "weathered"}}  # non-empty style materials
            prompt = build_prompt(style, load_taxonomy(root)["prop"], "lantern", "asset", materials)
            self.assertIn("- body: weathered granite; matte non-metallic surface", prompt)
            self.assertIn("- stone: weathered", prompt)
        with self.assertRaisesRegex(ValueError, "--material must be"):
            parse_material_spec("body=plastic")
