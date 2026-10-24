import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from slopforge.config import load_project
from slopforge.manifest import load_manifest, new_record, save_manifest
from slopforge.pipelines.image import generate as generate_concepts
from slopforge.pipelines.model import approve as approve_model, generate as generate_prop_concepts
from slopforge.style import load_style
from slopforge.taxonomy import load_taxonomy
from slopforge.validation import validate_model_outputs


def fake_unity_material(_root, _fbx, material, _maps, render=None):
    Path(material).write_bytes(b"mat")
    return {"unity_version": "test", "assets": {}, "material_textures": {}}


class PropLineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        (self.root / "Assets").mkdir(parents=True)
        (self.root / "ai/styles/plain/references/approved").mkdir(parents=True)
        (self.root / "ai/asset_types").mkdir(parents=True)
        (self.root / "ai/project.yaml").write_text("""project: {name: Test}
asset_pipeline:
  active_style: plain
  workflows: {image: image_text2img_api.json}
""")
        (self.root / "ai/styles/plain/style.yaml").write_text("""name: Plain
version: 1
identity: {genre: fantasy, rendering: painted, mood: [warm]}
shape_language: {preferred: [rounded], avoid: [photorealistic]}
palette: {}
materials: {}
surface_language: {preferred: [matte], avoid: []}
lighting: {description: soft, avoid: []}
asset_rules: {}
material_generation: {rules: [surface only]}
""")
        (self.root / "ai/asset_types/prop.yaml").write_text("""name: prop
pipeline: model
output_folder: Models
face_budget: prop_faces
requirements: [isolated object]
avoid: [environment]
""")
        self.config = load_project(self.root)
        self.style = load_style(self.root)
        self.asset_type = load_taxonomy(self.root)["prop"]
        self.config["asset_pipeline"]["defaults"]["model_candidates"] = 2
        self.config["asset_pipeline"]["defaults"]["material_candidates"] = 1
        self.record = new_record("prop", "relay", "Copper relay", self.style, {"strategy": "text_only"})
        self.manifest = {"schema_version": 4, "assets": {"prop:relay": self.record}}

    def tearDown(self):
        self.temp.cleanup()

    def _concept_candidates(self):
        def backend(_root, _config, _workflow, _prompt, destination, _prefix, seed, metadata, **_kwargs):
            Image.new("RGB", (512, 512), (seed % 255, 10, 20)).save(destination)
            metadata.write_text(json.dumps({"workflow": "concept.json", "seed": seed,
                                            "workflow_sha256": "a" * 64}))
        with patch("slopforge.pipelines.image.generate_image", side_effect=backend):
            generate_concepts(self.root, self.config, self.asset_type, self.style, "relay", "Copper relay", 2,
                              self.manifest, "prop:relay", generation_prompt="A copper relay")

    def _approve(self, generator, materializer=None, native_materializer=None, force=False, resume=False, material_count=1):
        def commands(command, check):
            if "prepare_3d_input.py" in command[1]:
                Image.new("RGBA", (32, 32), (120, 120, 120, 255)).save(command[command.index("--cutout") + 1])
                Image.new("RGB", (32, 32), "white").save(command[command.index("--output") + 1])
        with patch("slopforge.pipelines.model.generate_model", side_effect=generator), \
                patch("slopforge.pipelines.model._generate_material_candidate",
                      side_effect=materializer if materializer else None,
                      return_value=None if materializer else {
                          "number": 1, "status": "candidate", "validation": {"status": "passed", "errors": []},
                          "outputs": {}, "prompt": "surface", "path": "candidate/material.png"}), \
                patch("slopforge.pipelines.model._native_material_candidate", side_effect=native_materializer), \
                patch("slopforge.pipelines.model.subprocess.run", side_effect=commands):
            return approve_model(self.root, self.config, self.asset_type, self.style, self.manifest,
                                 "prop:relay", 2, force=force, material_count=material_count, resume=resume)

    def _materializer(self, root, config, asset_type, asset, number, prompt, _stage_mesh, lineage=None, seed=None):
        from slopforge.pipelines.model import material_candidate_paths
        paths = material_candidate_paths(root, config, asset["name"], number, asset_type)
        keys = ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss",
                "emission", "preview_front", "preview_side", "preview_rear", "preview_three_quarter")
        outputs = {}
        for key in keys:
            paths[key].parent.mkdir(parents=True, exist_ok=True)
            paths[key].write_bytes(("bytes:" + key).encode())
            outputs[key] = paths[key].relative_to(root).as_posix()
        paths["validation"].write_text(json.dumps({"status": "passed", "errors": []}))
        return {"number": number, "status": "candidate", "seed": seed,
                "validation": {"status": "passed", "errors": []},
                "outputs": outputs, "prompt": prompt, "path": outputs["surface"], "kind": "surface_swatch"}

    def _topology_rejection(self):
        return validate_model_outputs({}, inspection={
            "status": "passed", "errors": [], "warnings": [],
            "measured": {"mesh_objects": 1, "vertex_count": 24, "face_count": 8,
                         "dimensions": [1, 1, 1], "uv_layers": 1, "material_count": 1,
                         "image_texture_count": 4, "component_count": 60,
                         "nonmanifold_edge_count": 5, "transforms_applied": True,
                         "missing_textures": []}},
            max_components=50, max_nonmanifold_edges=None, max_boundary_edges=None)

    def test_selected_concept_remains_linked_to_correct_mesh_attempt(self):
        self._concept_candidates()
        concept = self.record["candidates"]["items"][1]
        calls = []
        def generator(_root, _config, _image, _name, destination, metadata, seed):
            calls.append(seed)
            destination.write_bytes(f"mesh from selected concept {seed}".encode())
            metadata.write_text(json.dumps({"workflow": "model.json", "seed": seed, "model": "mesh"}))

        topology_rejection = self._topology_rejection()
        material_calls = []

        def materializer(root, config, asset_type, asset, number, prompt, stage_mesh,
                         lineage=None, seed=None):
            item = self._materializer(root, config, asset_type, asset, number,
                                      prompt, stage_mesh, lineage, seed)
            material_calls.append(number)
            if len(material_calls) == 1:
                item.update({"status": "failed", "validation": topology_rejection})
            return item

        self._approve(generator, materializer=materializer)
        reloaded = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])
        record = reloaded["assets"]["prop:relay"]
        execution = record["executions"][-1]
        mesh_stages = [stage for stage in execution["stages"]
                       if stage["name"] == "mesh_workflow_execution"]
        self.assertEqual([stage["attempt"] for stage in mesh_stages], [1, 2])
        self.assertTrue(all(stage["inputs"][0]["sha256"] == concept["artifact"]["sha256"]
                            for stage in mesh_stages))
        success = mesh_stages[-1]
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0], calls[1])
        self.assertEqual(success["status"], "succeeded")
        self.assertEqual(success["attempt"], 2)
        self.assertEqual(record["model_attempts"][-1]["execution_id"], execution["id"])
        self.assertEqual(execution["retry_decisions"][-1]["action"], "next_candidate")

    def test_approved_concept_candidate_is_saved_as_approved(self):
        self._concept_candidates()
        self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
            dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))),
            self._materializer)
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        self.assertEqual(record["candidates"]["selected"], 2)
        self.assertEqual([item.get("approval") for item in record["candidates"]["items"]], [None, "approved"])

    def test_topology_rejections_exhaust_configured_mesh_budget(self):
        self._concept_candidates()
        self.config["asset_pipeline"]["defaults"]["model_candidates"] = 3
        mesh_calls = []
        material_calls = []

        def generator(_root, _config, _image, _name, destination, metadata, seed):
            mesh_calls.append(seed)
            destination.write_bytes(f"mesh {seed}".encode())
            metadata.write_text(json.dumps({"workflow": "model.json", "seed": seed}))

        def materializer(root, config, asset_type, asset, number, prompt, stage_mesh,
                         lineage=None, seed=None):
            item = self._materializer(root, config, asset_type, asset, number,
                                      prompt, stage_mesh, lineage, seed)
            item.update({"status": "failed", "validation": self._topology_rejection()})
            material_calls.append(number)
            return item

        with self.assertRaisesRegex(ValueError, "No qualified model after 3 attempts"):
            self._approve(generator, materializer=materializer)

        self.assertEqual(len(mesh_calls), 3)
        self.assertEqual(len(set(mesh_calls)), 3)
        self.assertEqual(len(material_calls), 3)
        execution = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])[
            "assets"]["prop:relay"]["executions"][-1]
        self.assertEqual([item["action"] for item in execution["retry_decisions"]],
                         ["next_candidate", "next_candidate", "exhausted"])
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        self.assertEqual([(item["number"], item["status"]) for item in record["material_candidates"]["items"]],
                         [(1, "failed"), (2, "failed"), (3, "failed")])

    def test_conditioning_artifacts_link_to_approved_concept_content(self):
        self._concept_candidates()
        concept = self.record["candidates"]["items"][1]
        self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
            dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))))
        execution = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]["executions"][-1]
        conditioning = next(stage for stage in execution["stages"] if stage["name"] == "conditioning_preparation")
        self.assertEqual(conditioning["inputs"][0]["sha256"], concept["artifact"]["sha256"])
        self.assertEqual({item["type"] for item in conditioning["outputs"]}, {"image.cutout", "image.3d_input"})

    def test_failed_mesh_stage_survives_reload_with_prior_success(self):
        self._concept_candidates()
        calls = []
        def generator(*_args, **_kwargs):
            calls.append(1)
            raise RuntimeError("mesh boundary failed")
        with self.assertRaisesRegex(ValueError, "No qualified model"):
            self._approve(generator)
        self.assertEqual(len(calls), 1)
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        execution = record["executions"][-1]
        self.assertEqual(next(stage for stage in execution["stages"] if stage["name"] == "conditioning_preparation")["status"], "succeeded")
        failed = next(stage for stage in execution["stages"] if stage["name"] == "mesh_workflow_execution")
        self.assertEqual(failed["status"], "failed")
        self.assertIn("mesh boundary failed", failed["error"])
        self.assertEqual(execution["status"], "failed")

    def test_source_copy_failure_after_execution_start_is_persisted(self):
        self._concept_candidates()
        original_status = self.record["status"]
        with patch("slopforge.pipelines.model.shutil.copy2", side_effect=OSError("copy boundary failed")):
            with self.assertRaisesRegex(OSError, "copy boundary failed"):
                self._approve(lambda *_args, **_kwargs: self.fail("mesh generation must not start"))

        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        execution = record["executions"][-1]
        self.assertEqual(execution["status"], "failed")
        self.assertEqual(execution["failure"]["category"], "unknown")
        self.assertEqual(execution["failure"]["stage"], "model_approval")
        self.assertEqual(record["status"], original_status)
        self.assertEqual(record["last_failure"], execution["failure"])
        self.assertTrue(all(item["outcome"] == "not_run" for item in execution["blocked_stages"]))
        self.assertTrue(all(stage["status"] != "running" for stage in execution["stages"]))

    def test_worker_journal_updates_survive_parent_manifest_save(self):
        self._concept_candidates()
        def worker(_root, config, _image, _name, _dest, _metadata, _seed, **_kwargs):
            context = config["_journal_context"]
            manifest = load_manifest(context["manifest_path"])
            asset = manifest["assets"][context["asset_selector"]]
            execution = next(item for item in asset["executions"] if item["id"] == context["execution_id"])
            execution["stages"].append({"name": "worker_marker", "attempt": 1, "status": "succeeded"})
            from slopforge.manifest import save_manifest
            save_manifest(context["manifest_path"], manifest)
            raise RuntimeError("parent must retain worker write")
        with self.assertRaisesRegex(ValueError, "No qualified model"):
            self._approve(worker)
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        self.assertEqual(record["executions"][-1]["stages"][-1]["name"], "worker_marker")

    def test_maps_and_material_outputs_link_to_exact_mesh_and_concept(self):
        self._concept_candidates()
        self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
            dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))),
            self._materializer)
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        candidate = record["material_candidates"]["items"][0]
        self.assertEqual(candidate["upstream_artifacts"][0]["sha256"], record["source"]["concept_artifact"]["sha256"])
        mesh = record["executions"][-1]["stages"]
        mesh_ref = next(item for stage in mesh for item in stage["outputs"] if item["type"] == "mesh.glb")
        for artifact in candidate["artifacts"]:
            parents = {item["artifact_id"] for item in artifact["derived_from"]}
            self.assertIn(mesh_ref["id"], parents)
            self.assertIn("concept-candidate:2", parents)

    def test_native_mesh_pbr_maps_link_to_exact_mesh_and_concept(self):
        self._concept_candidates()
        def generator(_root, _config, _image, _name, dest, metadata, seed):
            dest.write_bytes(b"textured mesh")
            metadata.write_text(json.dumps({"workflow": "trellis", "seed": seed, "textured": True,
                "textures": {name: f"native_material/{name}.png" for name in
                             ("basecolor", "normal", "roughness", "metallic")}}))
        def native(root, config, _context, asset_type, asset, number, mesh_info, lineage=None):
            result = self._materializer(root, config, asset_type, asset, number, "mesh PBR", Path("unused"), lineage)
            result["kind"] = "mesh_pbr"
            return result
        self._approve(generator, native_materializer=native)
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        candidate = record["material_candidates"]["items"][0]
        self.assertEqual(candidate["kind"], "mesh_pbr")
        self.assertTrue({"texture.basecolor", "texture.normal", "texture.roughness", "texture.metallic"}
                        .issubset({item["type"] for item in candidate["artifacts"]}))
        for artifact in candidate["artifacts"]:
            parents = {item["artifact_id"] for item in artifact["derived_from"]}
            self.assertIn("concept-candidate:2", parents)
            self.assertTrue(any(parent.startswith("mesh:") for parent in parents))

    def test_native_candidate_without_its_declared_emitter_tries_the_next_mesh_seed(self):
        from slopforge.validation import apply_declared_emitter
        self._concept_candidates()
        seeds = []
        def generator(_root, _config, _image, _name, dest, metadata, seed):
            seeds.append(seed)
            dest.write_bytes(f"textured mesh {seed}".encode())
            metadata.write_text(json.dumps({"workflow": "trellis", "seed": seed, "textured": True,
                "textures": {name: f"native_material/{name}.png" for name in
                             ("basecolor", "normal", "roughness", "metallic")}}))
        def native(root, config, _context, asset_type, asset, number, mesh_info, lineage=None):
            result = self._materializer(root, config, asset_type, asset, number, "mesh PBR", Path("unused"), lineage)
            validation = apply_declared_emitter(self._topology_rejection() | {
                "status": "passed", "errors": [], "failure_codes": []}, 0.0 if number == 1 else 0.0065)
            failed = validation["status"] == "failed"
            result.update(kind="mesh_pbr", status="failed" if failed else "candidate", validation=validation)
            return result
        self._approve(generator, native_materializer=native)
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        self.assertEqual(len(set(seeds)), 2)
        self.assertEqual([(item["number"], item["status"]) for item in record["material_candidates"]["items"]],
                         [(1, "failed"), (2, "candidate")])
        decision = record["executions"][-1]["retry_decisions"][0]
        self.assertEqual((decision["category"], decision["action"]), ("candidate_quality", "next_candidate"))

    def test_native_assembly_failure_is_recorded_on_the_assembly_stage(self):
        from slopforge.pipelines.model import _lineage_start
        self._concept_candidates()
        def generator(_root, _config, _image, _name, dest, metadata, seed):
            dest.write_bytes(b"textured mesh")
            metadata.write_text(json.dumps({"workflow": "trellis", "seed": seed, "textured": True,
                "textures": {name: f"native_material/{name}.png" for name in
                             ("basecolor", "normal", "roughness", "metallic")}}))
        def native(_root, _config, _context, _asset_type, _asset, number, _mesh_info, lineage=None):
            _lineage_start(lineage, "material_assembly_export", number, (), {"preserve_uvs": True})
            raise RuntimeError("blender assembly failed")
        with self.assertRaisesRegex(ValueError, "No qualified model"):
            self._approve(generator, native_materializer=native)
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        assembly = next(stage for stage in record["executions"][-1]["stages"]
                        if stage["name"] == "material_assembly_export")
        self.assertEqual(assembly["status"], "failed")
        self.assertEqual(assembly["failure"]["stage_id"], assembly["id"])
        self.assertEqual(record["model_attempts"][-1]["failure"]["stage"], "material_assembly_export")

    def test_final_exports_and_previews_link_to_selected_material_candidate(self):
        self._concept_candidates()
        self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
            dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))),
            self._materializer)
        from slopforge.pipelines.model import approve_texture, model_paths
        with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                patch("slopforge.pipelines.model.build_unity_material", side_effect=fake_unity_material):
            approve_texture(self.root, self.config, self.manifest, "prop:relay", 1)
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        publication = record["executions"][-1]
        stage = next(item for item in publication["stages"] if item["name"] == "final_publication")
        self.assertEqual(stage["status"], "succeeded")
        types = {item["type"] for item in stage["outputs"]}
        self.assertTrue({"texture.basecolor", "texture.normal", "texture.roughness", "texture.metallic",
                         "mesh.fbx", "project.blend", "preview.front", "preview.side", "preview.rear",
                         "preview.three_quarter", "material.unity", "validation.json"}.issubset(types))
        selected = record["material_candidates"]["items"][0]
        candidate_hashes = {item["sha256"] for item in selected["artifacts"]}
        candidate_ids = {item["id"] for item in selected["artifacts"]}
        self.assertTrue(all(parent["artifact_id"] in candidate_ids
                            for output in stage["outputs"] if output["type"] != "mesh.glb"
                            for parent in output["derived_from"]))
        self.assertTrue(candidate_hashes)

    def test_same_bytes_at_different_candidate_and_final_paths_keep_same_hash(self):
        self._concept_candidates()
        self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
            dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))),
            self._materializer)
        from slopforge.pipelines.model import approve_texture
        with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                patch("slopforge.pipelines.model.build_unity_material", side_effect=fake_unity_material):
            approve_texture(self.root, self.config, self.manifest, "prop:relay", 1)
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        candidate = record["material_candidates"]["items"][0]
        publication = record["executions"][-1]["stages"][-1]
        candidate_surface = next(item for item in candidate["artifacts"] if item["type"] == "surface.swatch")
        final_surface = next(item for item in publication["outputs"] if item["type"] == "surface.swatch")
        self.assertNotEqual(candidate_surface["path"], final_surface["path"])
        self.assertEqual(candidate_surface["sha256"], final_surface["sha256"])

    def test_reused_candidate_publication_uses_recorded_prior_candidate_paths(self):
        self._concept_candidates()
        self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
            dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))),
            self._materializer)
        candidate = self.record["material_candidates"]["items"][0]
        prior = self.root / "ai/assets/candidates/prop/relay/material_00"
        prior.mkdir(parents=True)
        for key, relative in list(candidate["outputs"].items()):
            old_path = self.root / relative
            new_path = prior / old_path.name
            new_path.write_bytes(old_path.read_bytes())
            old_path.unlink()
            candidate["outputs"][key] = new_path.relative_to(self.root).as_posix()
            for artifact in candidate.get("artifacts", []):
                if artifact.get("path") == relative:
                    artifact["path"] = candidate["outputs"][key]
        from slopforge.pipelines.model import approve_texture, model_paths
        with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                patch("slopforge.pipelines.model.build_unity_material",
                      side_effect=fake_unity_material):
            approve_texture(self.root, self.config, self.manifest, "prop:relay", candidate["number"])
        final = model_paths(self.root, self.config, "relay", "prop")
        self.assertEqual(final["basecolor"].read_bytes(), b"bytes:basecolor")

    def test_retexture_records_child_execution_for_existing_mesh(self):
        self._concept_candidates()
        self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
            dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))),
            self._materializer)
        from slopforge.pipelines.model import approve_texture, retexture
        with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                patch("slopforge.pipelines.model.build_unity_material", side_effect=fake_unity_material):
            approve_texture(self.root, self.config, self.manifest, "prop:relay", 1)
        generation = self.record["executions"][-2]
        with patch("slopforge.pipelines.model._generate_material_candidate", side_effect=self._materializer):
            retexture(self.root, self.config, self.asset_type, self.style, self.manifest,
                      "prop:relay", count=1)
        child = self.record["executions"][-1]
        self.assertEqual(child["parent_execution_id"], generation["id"])
        self.assertEqual(child["identity_inputs"]["mesh_sha256"], generation["stages"][1]["outputs"][0]["sha256"])

    def test_unknown_backend_facts_remain_unknown_after_full_prop_reload(self):
        self._concept_candidates()
        self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
            dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))),
            self._materializer)
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        execution = next(item for item in record["executions"] if item["id"] == record["model_attempts"][-1]["execution_id"])
        mesh = next(stage for stage in execution["stages"] if stage["name"] == "mesh_workflow_execution")
        provenance = mesh["provenance"]
        self.assertIn(provenance["backend"]["version"]["status"], {"unavailable", "not_recorded"})
        self.assertIn(provenance["model_weights"]["status"], {"unavailable", "not_recorded"})
        self.assertIn(provenance["custom_node_revisions"]["status"], {"unavailable", "not_recorded"})

    def test_normal_prop_generation_identity_uses_brief_and_prompt(self):
        def backend(_root, _config, _workflow, _prompt, destination, _prefix, _seed, metadata, **_kwargs):
            Image.new("RGB", (512, 512), "teal").save(destination)
            metadata.write_text(json.dumps({"workflow": "image.json"}))
        with patch("slopforge.candidates.secrets.randbits", return_value=17), \
                patch("slopforge.pipelines.model.generate_image", side_effect=backend):
            generate_prop_concepts(self.root, self.config, self.asset_type, self.style, "relay", "Copper relay", 1,
                                   self.manifest, "prop:relay", generation_prompt="A copper relay")
            first = self.record["executions"][-1]["identity_sha256"]
            generate_prop_concepts(self.root, self.config, self.asset_type, self.style, "relay", "Silver relay", 1,
                                   self.manifest, "prop:relay", generation_prompt="A silver relay")
        self.assertNotEqual(first, self.record["executions"][-1]["identity_sha256"])

    def test_concept_aspect_sets_the_canvas_and_is_part_of_the_concept_identity(self):
        from slopforge.config import workflow_node_inputs
        used = []
        def backend(_root, config, _workflow, _prompt, destination, _prefix, _seed, metadata, **_kwargs):
            used.append(workflow_node_inputs(config, "image", "image_text2img_api.json"))
            Image.new("RGB", (512, 512), "teal").save(destination)
            metadata.write_text(json.dumps({"workflow": "image.json"}))
        with patch("slopforge.candidates.secrets.randbits", return_value=17), \
                patch("slopforge.pipelines.model.generate_image", side_effect=backend):
            generate_prop_concepts(self.root, self.config, self.asset_type, self.style, "relay", "Copper relay", 1,
                                   self.manifest, "prop:relay", generation_prompt="A copper relay")
            square = self.record["executions"][-1]
            generate_prop_concepts(self.root, self.config, self.asset_type, self.style, "relay", "Copper relay", 1,
                                   self.manifest, "prop:relay", generation_prompt="A copper relay", aspect="portrait")
            portrait = self.record["executions"][-1]
        self.assertEqual(used, [{}, {"57:13": {"width": 896, "height": 1152}}])
        self.assertNotIn("57:13", square["identity_inputs"]["workflow"]["configured_inputs"])
        self.assertEqual(portrait["identity_inputs"]["workflow"]["configured_inputs"]["57:13"],
                         {"width": 896, "height": 1152})
        self.assertNotEqual(square["identity_sha256"], portrait["identity_sha256"])
        self.assertEqual(workflow_node_inputs(self.config, "image", "image_text2img_api.json"), {})

    def test_an_asset_type_can_set_its_concept_canvas(self):
        # Weapons are drawn side-on on the wide canvas without passing --aspect each time.
        from slopforge.config import workflow_node_inputs
        used = []
        def backend(_root, config, _workflow, _prompt, destination, _prefix, _seed, metadata, **_kwargs):
            used.append(workflow_node_inputs(config, "image", "image_text2img_api.json"))
            Image.new("RGB", (512, 512), "teal").save(destination)
            metadata.write_text(json.dumps({"workflow": "image.json"}))
        self.asset_type["aspect"] = "wide"
        with patch("slopforge.candidates.secrets.randbits", return_value=17), \
                patch("slopforge.pipelines.model.generate_image", side_effect=backend):
            generate_prop_concepts(self.root, self.config, self.asset_type, self.style, "relay", "Copper relay", 1,
                                   self.manifest, "prop:relay", generation_prompt="A copper relay")
            generate_prop_concepts(self.root, self.config, self.asset_type, self.style, "relay", "Copper relay", 1,
                                   self.manifest, "prop:relay", generation_prompt="A copper relay", aspect="square")
        self.assertEqual(used, [{"57:13": {"width": 1536, "height": 640}}, {"57:13": {"width": 1024, "height": 1024}}])

    def test_unapproved_kit_material_stops_before_mesh_inference(self):
        from slopforge.failures import StageFailure
        self._concept_candidates()
        for pipeline in (self.config["asset_pipeline"], self.config["_quality_base_pipeline"]):
            pipeline["workflows"]["model"] = "trellis2_image_to_model_api.json"
        self.record["kit_material"] = {"asset_key": "texture:ruin_stone"}
        calls = []
        with patch("slopforge.pipelines.model.blender_executable", return_value="blender"), \
                self.assertRaisesRegex(StageFailure, "ruin_stone"):
            self._approve(lambda *_args, **_kwargs: calls.append(1))
        self.assertEqual(calls, [])
        failure = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])[
            "assets"]["prop:relay"]["executions"][-1]["failure"]
        self.assertEqual((failure["category"], failure["operation"]), ("configuration", "kit_material_preflight"))

    def _guided_concepts(self, guide, rendered, calls, **options):
        def backend(_root, _config, workflow, _prompt, destination, _prefix, _seed, metadata, **kwargs):
            calls.append((Path(workflow).name, kwargs.get("conditioning")))
            Image.new("RGB", (512, 512), "teal").save(destination)
            metadata.write_text(json.dumps({"workflow": "image.json"}))

        def render(_root, _config, destination, shape, ratio, width, height):
            rendered.append((shape, ratio, width, height))
            Image.new("L", (width, height), int(ratio * 100)).save(destination)
        with patch("slopforge.candidates.secrets.randbits", return_value=17), \
                patch("slopforge.pipelines.model.generate_image", side_effect=backend), \
                patch("slopforge.pipelines.model._render_shape_guide", side_effect=render):
            generate_prop_concepts(self.root, self.config, self.asset_type, self.style, "stump", "Short stump", 1,
                                   self.manifest, "prop:relay", generation_prompt="A short stump", shape_guide=guide,
                                   **options)
        return self.record["executions"][-1]

    def _configure_guided_workflow(self):
        for pipeline in (self.config["asset_pipeline"], self.config["_quality_base_pipeline"]):
            pipeline["workflows"]["guided_image"] = "image_character_pose_api.json"

    def test_shape_guide_routes_the_concept_through_the_guided_graph_and_joins_its_identity(self):
        self._configure_guided_workflow()
        rendered, calls = [], []
        half = self._guided_concepts(("cylinder", 0.5), rendered, calls, aspect="landscape")
        three_quarters = self._guided_concepts(("cylinder", 0.75), rendered, calls, aspect="landscape")
        # The guide is rendered for the concept canvas the aspect selects.
        self.assertEqual(rendered, [("cylinder", 0.5, 1152, 896), ("cylinder", 0.75, 1152, 896)])
        workflow, conditioning = calls[0]
        self.assertEqual(workflow, "image_character_pose_api.json")
        guide = conditioning["references"][0]
        self.assertEqual((guide["category"], guide["strength"]), ("shape_guide", 0.65))
        self.assertEqual(conditioning["workflow_inputs"][0],
                         {"image": {"node": "pose_image", "input": "image"},
                          "strength": {"node": "pose_control", "input": "strength"}})
        self.assertEqual(half["identity_inputs"]["workflow"]["identifier"], "image_character_pose_api.json")
        self.assertNotEqual(half["identity_sha256"], three_quarters["identity_sha256"])

    def test_shape_guide_needs_the_guided_workflow_and_refuses_character_concepts(self):
        with self.assertRaisesRegex(ValueError, "guided_image"):
            self._guided_concepts(("box", 1.25), [], [])
        self._configure_guided_workflow()
        self.asset_type = {**self.asset_type, "prompt_mode": "character"}
        with self.assertRaisesRegex(ValueError, "shape guide"):
            self._guided_concepts(("box", 1.25), [], [])

    def test_concept_aspect_is_refused_for_character_concepts(self):
        with self.assertRaisesRegex(ValueError, "aspect"):
            generate_prop_concepts(self.root, self.config, {**self.asset_type, "prompt_mode": "character"}, self.style,
                                   "pilot", "Pilot", 1, self.manifest, "prop:relay", generation_prompt="A pilot",
                                   aspect="portrait")

    def test_declared_emitter_absent_from_concept_stops_before_mesh_inference(self):
        from slopforge.failures import StageFailure
        self._concept_candidates()
        for pipeline in (self.config["asset_pipeline"], self.config["_quality_base_pipeline"]):
            pipeline["workflows"]["model"] = "trellis2_image_to_model_api.json"
        self.record["materials"] = [{"region": "lens", "class": "emissive", "color": "#e0a030",
                                     "description": "amber glass"}]
        calls = []
        # A mesh-aware workflow checks for Blender first; CI has none, and this test is about the emitter check.
        with patch("slopforge.pipelines.model.blender_executable", return_value="blender"), \
                self.assertRaisesRegex(StageFailure, "lens"):
            self._approve(lambda *_args, **_kwargs: calls.append(1))  # the harness cutout is plain grey
        self.assertEqual(calls, [])
        execution = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])[
            "assets"]["prop:relay"]["executions"][-1]
        self.assertEqual((execution["failure"]["category"], execution["failure"]["operation"]),
                         ("configuration", "emitter_preflight"))

    def test_emitter_preflight_reads_only_the_object_not_the_removed_background(self):
        from slopforge.failures import StageFailure
        from slopforge.pipelines.model import check_emitters_in_concept
        with tempfile.TemporaryDirectory() as temporary:
            cutout = Path(temporary) / "cutout.png"
            # rembg keeps the light-grey backdrop colour under transparent pixels.
            image = Image.new("RGBA", (256, 256), (215, 215, 215, 0))
            image.paste((70, 70, 80, 255), (60, 60, 196, 196))
            image.save(cutout)
            paper = [{"region": "panels", "class": "emissive", "description": "paper"}]
            with self.assertRaisesRegex(StageFailure, "panels"):
                check_emitters_in_concept(paper, cutout)
            image.paste((224, 160, 48, 255), (100, 100, 140, 140))
            image.paste((232, 230, 226, 255), (150, 70, 190, 110))
            image.save(cutout)
            check_emitters_in_concept(paper + [{"region": "lens", "class": "emissive", "color": "#e0a030",
                                                "description": ""}], cutout)
            check_emitters_in_concept([{"region": "body", "class": "nonmetal", "description": ""}], cutout)

    def test_concept_attempt_state_is_persisted_before_boundary_and_failure(self):
        save_manifest(self.root / self.config["asset_pipeline"]["manifest"], self.manifest)
        def backend(*_args, **_kwargs):
            saved = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])
            execution = saved["assets"]["prop:relay"]["executions"][-1]
            self.assertEqual(execution["stages"][-1]["status"], "running")
            raise RuntimeError("concept boundary failed")
        with patch("slopforge.candidates.secrets.randbits", return_value=17), \
                patch("slopforge.pipelines.model.generate_image", side_effect=backend):
            with self.assertRaisesRegex(RuntimeError, "No valid candidates"):
                generate_prop_concepts(self.root, self.config, self.asset_type, self.style, "relay", "Copper relay", 1,
                                       self.manifest, "prop:relay", generation_prompt="A copper relay")
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        stage = record["executions"][-1]["stages"][-1]
        self.assertEqual(stage["status"], "failed")
        self.assertIn("concept boundary failed", stage["error"])

    def test_concept_stage_persists_pending_before_running(self):
        from slopforge import candidates as candidates_module
        real_begin = candidates_module.begin_stage
        save_manifest(self.root / self.config["asset_pipeline"]["manifest"], self.manifest)
        def begin(stage):
            saved = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])
            persisted = saved["assets"]["prop:relay"]["executions"][-1]["stages"][-1]
            self.assertEqual(persisted["status"], "pending")
            real_begin(stage)
        def backend(_root, _config, _workflow, _prompt, destination, _prefix, _seed, metadata, **_kwargs):
            Image.new("RGB", (512, 512), "teal").save(destination)
            metadata.write_text(json.dumps({"workflow": "image.json"}))
        with patch("slopforge.candidates.begin_stage", side_effect=begin), \
                patch("slopforge.candidates.secrets.randbits", return_value=17), \
                patch("slopforge.pipelines.model.generate_image", side_effect=backend):
            generate_prop_concepts(self.root, self.config, self.asset_type, self.style, "relay", "Copper relay", 1,
                                   self.manifest, "prop:relay", generation_prompt="A copper relay")

    def test_model_identity_changes_with_checkpoint_and_material_settings(self):
        self._concept_candidates()
        pipeline = self.config["asset_pipeline"]
        pipeline["overwrite_existing"] = True
        pipeline["tools"]["hunyuan_checkpoint"] = "weights-a.safetensors"
        pipeline["material_scale"] = 3
        with patch("slopforge.pipelines.model.secrets.randbits", return_value=17):
            self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
                dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))))
            first = self.record["executions"][-1]["identity_sha256"]
            pipeline["tools"]["hunyuan_checkpoint"] = "weights-b.safetensors"
            pipeline["material_scale"] = 9
            self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
                dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))),
                force=True)
        self.assertNotEqual(first, self.record["executions"][-1]["identity_sha256"])

    def test_retexture_with_real_helper_persists_candidate_and_terminal_execution(self):
        self._concept_candidates()
        self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
            dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))),
            self._materializer)
        from slopforge.pipelines.model import approve_texture, retexture
        with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                patch("slopforge.pipelines.model.build_unity_material",
                      side_effect=fake_unity_material):
            approve_texture(self.root, self.config, self.manifest, "prop:relay", 1)

        def generate_image(_root, _config, _workflow, _prompt, destination, _prefix, _seed, metadata):
            Image.new("RGB", (32, 32), "orange").save(destination)
            metadata.write_text("{}")
        def command(args, check):
            if "make_pbr_maps.py" in args[1]:
                for key in ("basecolor", "normal", "roughness", "metallic", "emission"):
                    Image.new("RGB", (32, 32), "gray").save(args[args.index("--" + key) + 1])
        def process(_root, _config, _mesh, fbx, blend, _maps, _budget, **options):
            fbx.write_bytes(b"fbx")
            blend.write_bytes(b"blend")
            options["preview_dir"].mkdir(parents=True)
            for view in ("front", "side", "rear", "three_quarter"):
                Image.new("RGB", (8, 8), "gray").save(options["preview_dir"] / f"relay_{view}.png")
        with patch("slopforge.pipelines.model.generate_image", side_effect=generate_image), \
                patch("slopforge.pipelines.model.subprocess.run", side_effect=command), \
                patch("slopforge.pipelines.model.process_model", side_effect=process), \
                patch("slopforge.pipelines.model.inspect_model", return_value={}), \
                patch("slopforge.pipelines.model.validate_model_outputs", return_value={"status": "passed", "errors": []}):
            retexture(self.root, self.config, self.asset_type, self.style, self.manifest, "prop:relay")
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        self.assertEqual(len(record["material_candidates"]["items"]), 2)
        execution = record["executions"][-1]
        self.assertEqual(execution["status"], "succeeded")
        material_generation = next(stage for stage in execution["stages"]
                                  if stage["name"] == "material_generation")
        unknown_workflow = material_generation["provenance"]["workflow_effective_sha256"]
        self.assertEqual(unknown_workflow["status"], "not_recorded")
        self.assertTrue(unknown_workflow["reason"])
        swatch = next(item for stage in execution["stages"] for item in stage["outputs"]
                      if item["type"] == "surface.swatch")
        maps = next(stage for stage in execution["stages"] if stage["name"] == "material_map_acquisition")
        self.assertIn(swatch["id"], {item["id"] for item in maps["inputs"]})
        self.assertTrue(all({parent["artifact_id"] for parent in item["derived_from"]} == {swatch["id"]}
                            for item in maps["outputs"]))
        assembly = next(stage for stage in execution["stages"] if stage["name"] == "material_assembly_export")
        self.assertTrue(assembly["inputs"])
        assembly_input_ids = {item["id"] for item in assembly["inputs"]}
        self.assertTrue(all({parent["artifact_id"] for parent in item["derived_from"]} == assembly_input_ids
                            for item in assembly["outputs"]))


    def test_resume_on_running_prior_rejects_unresolved_mesh_and_preserves_successes(self):
        """Recovery must validate unresolved stages, mark interruptions, and block resume
        when a mesh stage may have accepted a remote prompt.

        Regression: on ``approve(..., resume=True)`` a prior whose work was killed mid-
        inference could survive with ``status == 'running'``.  Without recovery the
        resume logic blindly reused that execution as a parent.  This test verifies
        that:

        1. The running mesh stage is terminated with ``category=interruption`` and its
           exact ``stage_id``.
        2. Evidence shows ``completion_not_persisted``, ``recovery_detected_at``, and
           unknown original termination time/cause.
        3. Resume is stopped with an actionable service-inspection message before any
           new inference submission.
        4. Re-loaded manifest reflects the recovered interruption evidence and
           preserved successes.
        """
        # -- Phase 1: create a normal prior execution with one succeeded stage --
        self._concept_candidates()

        calls = []
        def generator(*_args, **_kwargs):
            calls.append(1)
            raise StageFailure("configuration", "preflight broken", operation="preflight",
                               remedy="fix config")

        with self.assertRaises(ValueError):
            self._approve(generator)

        manifest_path = self.root / self.config["asset_pipeline"]["manifest"]
        record = load_manifest(manifest_path)["assets"]["prop:relay"]
        prior = record["executions"][-1]

        # Add a succeeded conditioning_preparation stage to prove it survives recovery.
        conditioning_stage = next(
            s for s in prior["stages"] if s["name"] == "conditioning_preparation")
        self.assertEqual(conditioning_stage["status"], "succeeded")
        succeeded_output_count = len(conditioning_stage.get("outputs", []))

        # -- Phase 2: corrupt the prior -- mark it running with a running mesh stage
        prior["status"] = "running"
        mesh_stage = {"id": "running-mesh-id-001",
                      "name": "mesh_workflow_execution",
                      "attempt": 1,
                      "status": "running",
                      "started_at": "2025-01-01T00:00:00+00:00",
                      "failed_at": None,
                      "inputs": [], "outputs": [],
                      "settings": {"seed": 42},
                      "provenance": {}}
        prior["stages"].append(mesh_stage)
        record["schema_version"] = 4
        full = load_manifest(manifest_path)  # get full wrapper
        full["assets"]["prop:relay"] = record  # update the asset in place
        save_manifest(manifest_path, full)
        self.manifest = load_manifest(manifest_path)
        self.record = self.manifest["assets"]["prop:relay"]

        # -- Phase 3: resume -- must reject before any new inference --
        execution_count_before = len(self.record["executions"])
        with self.assertRaisesRegex(ValueError,
                                     r"Cannot resume: unresolved mesh_workflow_execution.*inspect"):
            self._approve(generator, resume=True)

        # The persisted interruption must keep later resume attempts blocked too.
        with self.assertRaises(ValueError):
            self._approve(generator, resume=True)

        # No new execution was created by the resume call.
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.record["executions"]), execution_count_before)

        # -- Phase 4: verify recovered interruption evidence after reload --
        reloaded = load_manifest(manifest_path)
        reloaded_prior = reloaded["assets"]["prop:relay"]["executions"][-1]

        # Prior execution is now marked failed with interruption category.
        self.assertEqual(reloaded_prior["status"], "failed")
        self.assertEqual(reloaded_prior["failure"]["category"], "interruption")
        self.assertTrue(
            reloaded_prior["failure"]["evidence"].get("completion_not_persisted"))
        self.assertIsNotNone(
            reloaded_prior["failure"]["evidence"].get("recovery_detected_at"))
        self.assertTrue(
            reloaded_prior["failure"]["evidence"].get(
                "unknown_original_termination_time"))
        self.assertTrue(
            reloaded_prior["failure"]["evidence"].get(
                "unknown_original_termination_cause"))

        # The running mesh stage is terminated with interruption evidence.
        recovered_stage = reloaded_prior["stages"][-1]
        self.assertEqual(recovered_stage["id"], mesh_stage["id"])
        self.assertEqual(recovered_stage["status"], "failed")
        self.assertEqual(recovered_stage["failure"]["category"], "interruption")
        self.assertEqual(recovered_stage["failure"]["stage"], "mesh_workflow_execution")
        self.assertEqual(recovered_stage["failure"]["stage_id"], "running-mesh-id-001")
        self.assertTrue(recovered_stage["failure"]["evidence"]["outcome_unknown"])
        self.assertIsNotNone(
            recovered_stage["failure"]["evidence"].get("recovery_detected_at"))
        self.assertTrue(
            recovered_stage["failure"]["evidence"].get("completion_not_persisted"))

        # Succeeded stages are preserved intact.
        preserved_conditioning = next(
            s for s in reloaded_prior["stages"]
            if s["name"] == "conditioning_preparation")
        self.assertEqual(preserved_conditioning["status"], "succeeded")
        self.assertEqual(len(preserved_conditioning["outputs"]), succeeded_output_count)

    def test_resume_finishes_running_prior_without_running_stages_as_interruption(self):
        # The process died between stages: the execution is running but no stage is.
        from slopforge.failures import StageFailure
        self._concept_candidates()

        def generator(*_args, **_kwargs):
            raise StageFailure("configuration", "preflight broken", operation="preflight", remedy="fix config")

        with self.assertRaises(ValueError):
            self._approve(generator)
        manifest_path = self.root / self.config["asset_pipeline"]["manifest"]
        full = load_manifest(manifest_path)
        prior = full["assets"]["prop:relay"]["executions"][-1]
        prior_id = prior["id"]
        prior["status"] = "running"
        prior.pop("failure", None)
        prior.pop("finished_at", None)
        self.assertFalse(any(stage["status"] == "running" for stage in prior["stages"]))
        save_manifest(manifest_path, full)
        self.manifest = load_manifest(manifest_path)
        self.record = self.manifest["assets"]["prop:relay"]

        with self.assertRaises(ValueError):
            self._approve(generator, resume=True)

        reloaded = load_manifest(manifest_path)["assets"]["prop:relay"]["executions"]
        recovered = next(item for item in reloaded if item["id"] == prior_id)
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(recovered["failure"]["category"], "interruption")
        self.assertTrue(recovered["failure"]["evidence"]["completion_not_persisted"])
        self.assertFalse(any(item["status"] == "running" for item in reloaded))

    def _mesh_history(self, decision):
        from slopforge.pipelines.model import _mesh_slot_history

        slot = {"scope_sha256": "a" * 64,
                "seed_index": decision.get("used", 1) - 1,
                "origin_execution_id": "execution-1"}
        stage = {"id": "stage-1", "name": "mesh_workflow_execution",
                 "attempt": 1, "status": "failed", "attempt_slot": slot}
        execution = {"id": "execution-1", "parent_execution_id": None,
                     "stages": [stage], "retry_decisions": [decision]}
        return _mesh_slot_history({"executions": [execution]}, "execution-1", "a" * 64, 2)

    def test_complete_candidate_quality_retry_decisions_consume_seed(self):
        for action, used, next_seed in (("next_candidate", 1, 1), ("exhausted", 2, None)):
            with self.subTest(action=action):
                decision = {"scope": "mesh", "scope_sha256": "a" * 64,
                            "stage": "mesh_workflow_execution", "stage_id": "stage-1",
                            "attempt": 1, "category": "candidate_quality", "used": used,
                            "limit": 2, "action": action, "next_seed_index": next_seed}
                slots, rejected = self._mesh_history(decision)
                seed_index = used - 1
                self.assertEqual(set(slots), {seed_index})
                self.assertEqual(rejected, {seed_index})

    def test_incomplete_candidate_quality_stop_decision_blocks_resume(self):
        decision = {"scope": "mesh", "scope_sha256": "a" * 64,
                    "stage": "mesh_workflow_execution", "stage_id": "stage-1",
                    "attempt": 1, "category": "candidate_quality", "action": "stop"}
        with self.assertRaisesRegex(ValueError, "Retry decision"):
            self._mesh_history(decision)

        decision.update({"used": 1, "limit": 2, "next_seed_index": None})
        with self.assertRaisesRegex(ValueError, "action contradicts"):
            self._mesh_history(decision)

    def test_retry_decision_with_non_canonical_scope_hash_blocks_resume(self):
        decision = {"scope": "mesh", "scope_sha256": "A" * 64,
                    "stage": "mesh_workflow_execution", "stage_id": "stage-1",
                    "attempt": 1, "category": "candidate_quality", "used": 1,
                    "limit": 2, "action": "next_candidate", "next_seed_index": 1}
        with self.assertRaisesRegex(ValueError, "Retry decision is malformed"):
            self._mesh_history(decision)

    def test_incomplete_non_quality_stop_decision_blocks_resume(self):
        decision = {"scope": "mesh", "scope_sha256": "a" * 64,
                    "stage": "mesh_workflow_execution", "stage_id": "stage-1",
                    "attempt": 1, "category": "unknown", "action": "stop"}
        with self.assertRaisesRegex(ValueError, "Retry decision"):
            self._mesh_history(decision)

        decision.update({"used": 1, "limit": 2, "next_seed_index": None})
        slots, rejected = self._mesh_history(decision)
        self.assertEqual(set(slots), {0})
        self.assertEqual(rejected, set())


if __name__ == "__main__":
    unittest.main()
