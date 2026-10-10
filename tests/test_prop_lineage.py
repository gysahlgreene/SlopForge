import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from slopforge.config import load_project
from slopforge.manifest import load_manifest, new_record
from slopforge.pipelines.image import generate as generate_concepts
from slopforge.pipelines.model import approve as approve_model
from slopforge.style import load_style
from slopforge.taxonomy import load_taxonomy


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

    def _approve(self, generator, materializer=None, native_materializer=None):
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
                                 "prop:relay", 2, material_count=1)

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

    def test_selected_concept_remains_linked_to_correct_mesh_attempt(self):
        self._concept_candidates()
        concept = self.record["candidates"]["items"][1]
        calls = []
        def generator(_root, _config, _image, _name, destination, metadata, seed):
            calls.append(seed)
            if len(calls) == 1:
                raise RuntimeError("first mesh failed")
            destination.write_bytes(b"mesh from selected concept")
            metadata.write_text(json.dumps({"workflow": "model.json", "seed": seed, "model": "mesh"}))
        self._approve(generator)
        reloaded = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])
        record = reloaded["assets"]["prop:relay"]
        execution = record["executions"][-1]
        success = next(stage for stage in execution["stages"] if stage["name"] == "mesh_workflow_execution"
                       and stage["status"] == "succeeded")
        self.assertEqual(success["inputs"][0]["sha256"], concept["artifact"]["sha256"])
        self.assertEqual(success["attempt"], 2)
        self.assertEqual(record["model_attempts"][-1]["execution_id"], execution["id"])

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
        with self.assertRaisesRegex(ValueError, "No qualified model"):
            self._approve(lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("mesh boundary failed")))
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        execution = record["executions"][-1]
        self.assertEqual(next(stage for stage in execution["stages"] if stage["name"] == "conditioning_preparation")["status"], "succeeded")
        failed = next(stage for stage in execution["stages"] if stage["name"] == "mesh_workflow_execution")
        self.assertEqual(failed["status"], "failed")
        self.assertIn("mesh boundary failed", failed["error"])
        self.assertEqual(execution["status"], "failed")

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
        def native(root, config, asset_type, asset, number, mesh_info, lineage=None):
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

    def test_final_exports_and_previews_link_to_selected_material_candidate(self):
        self._concept_candidates()
        self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
            dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))),
            self._materializer)
        from slopforge.pipelines.model import approve_texture, model_paths
        def unity(_root, _fbx, output, _maps): Path(output).write_bytes(b"unity material")
        with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                patch("slopforge.pipelines.model.build_unity_material", side_effect=unity):
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
                patch("slopforge.pipelines.model.build_unity_material", side_effect=lambda _r, _f, out, _m: Path(out).write_bytes(b"mat")):
            approve_texture(self.root, self.config, self.manifest, "prop:relay", 1)
        record = load_manifest(self.root / self.config["asset_pipeline"]["manifest"])["assets"]["prop:relay"]
        candidate = record["material_candidates"]["items"][0]
        publication = record["executions"][-1]["stages"][-1]
        candidate_surface = next(item for item in candidate["artifacts"] if item["type"] == "surface.swatch")
        final_surface = next(item for item in publication["outputs"] if item["type"] == "surface.swatch")
        self.assertNotEqual(candidate_surface["path"], final_surface["path"])
        self.assertEqual(candidate_surface["sha256"], final_surface["sha256"])

    def test_retexture_records_child_execution_for_existing_mesh(self):
        self._concept_candidates()
        self._approve(lambda _root, _config, _image, _name, dest, metadata, seed: (
            dest.write_bytes(b"mesh"), metadata.write_text(json.dumps({"workflow": "model", "seed": seed}))),
            self._materializer)
        from slopforge.pipelines.model import approve_texture, retexture
        with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                patch("slopforge.pipelines.model.build_unity_material", side_effect=lambda _r, _f, out, _m: Path(out).write_bytes(b"mat")):
            approve_texture(self.root, self.config, self.manifest, "prop:relay", 1)
        generation = self.record["executions"][-2]
        with patch("slopforge.pipelines.model._generate_material_candidate", side_effect=self._materializer):
            retexture(self.root, self.config, self.asset_type, self.style, self.manifest,
                      "prop:relay", count=1)
        child = self.record["executions"][-1]
        self.assertEqual(child["parent_execution_id"], generation["id"])
        self.assertEqual(child["identity_inputs"]["mesh_sha256"], generation["stages"][1]["outputs"][0]["sha256"])


if __name__ == "__main__":
    unittest.main()
