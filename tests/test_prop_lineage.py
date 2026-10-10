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

    def _approve(self, generator):
        def commands(command, check):
            if "prepare_3d_input.py" in command[1]:
                Image.new("RGBA", (32, 32), (120, 120, 120, 255)).save(command[command.index("--cutout") + 1])
                Image.new("RGB", (32, 32), "white").save(command[command.index("--output") + 1])
        with patch("slopforge.pipelines.model.generate_model", side_effect=generator), \
                patch("slopforge.pipelines.model._generate_material_candidate", return_value={
                    "number": 1, "status": "candidate", "validation": {"status": "passed", "errors": []},
                    "outputs": {}, "prompt": "surface", "path": "candidate/material.png"}), \
                patch("slopforge.pipelines.model.subprocess.run", side_effect=commands):
            return approve_model(self.root, self.config, self.asset_type, self.style, self.manifest,
                                 "prop:relay", 2, material_count=1)

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


if __name__ == "__main__":
    unittest.main()
