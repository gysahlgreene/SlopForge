import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from slopforge.config import load_project
from slopforge.manifest import load_manifest, new_record, save_manifest
from slopforge.pipelines.model import approve, material_candidate_paths
from slopforge.provenance import file_sha256
from slopforge.style import load_style
from slopforge.taxonomy import load_taxonomy

from slopforge.pipelines.reuse import artifact_integrity, earliest_stale_stage, stage_reuse_decision


class PropReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "mesh.glb").write_bytes(b"mesh")
        self.input = {"id": "mesh:1", "sha256": hashlib.sha256(b"mesh").hexdigest()}
        self.output = {"id": "material:1", "type": "texture", "path": "mesh.glb",
                       "sha256": hashlib.sha256(b"mesh").hexdigest(), "stage": "material_generation",
                       "attempt": 1, "derived_from": [{"artifact_id": self.input["id"],
                                                          "sha256": self.input["sha256"]}]}
        self.stage = {"name": "material_generation", "attempt": 1, "status": "succeeded",
                      "inputs": [self.input], "outputs": [self.output], "settings": {"seed": 1}}

    def test_identical_semantic_inputs_and_intact_artifact_are_reusable(self):
        self.assertTrue(stage_reuse_decision(self.root, self.stage, inputs=[self.input], settings={"seed": 1})["reusable"])

    def test_changed_input_or_settings_is_stale(self):
        decision = stage_reuse_decision(self.root, self.stage,
            inputs=[{"id": "mesh:2", "sha256": "0" * 64}], settings={"seed": 2})
        self.assertFalse(decision["reusable"])
        self.assertTrue(any("semantic mismatch" in reason for reason in decision["reasons"]))
        broken = {**self.stage, "outputs": [{**self.output, "derived_from": []}]}
        self.assertIn("lineage mismatch", " ".join(stage_reuse_decision(self.root, broken,
            inputs=[self.input], settings={"seed": 1})["reasons"]))

    def test_package_stage_outputs_may_record_valid_input_subsets(self):
        concept = {"id": "concept:1", "sha256": "1" * 64}
        conditioning = {"id": "conditioning:1", "sha256": "2" * 64}
        package_shape = {**self.stage, "name": "mesh_workflow_execution",
                         "inputs": [concept, conditioning],
                         "outputs": [{**self.output, "stage": "mesh_workflow_execution",
                             "derived_from": [{"artifact_id": conditioning["id"],
                                               "sha256": conditioning["sha256"]}]}]}
        self.assertTrue(stage_reuse_decision(self.root, package_shape,
            inputs=[concept, conditioning], settings={"seed": 1})["reusable"])
        unrelated = {**package_shape, "outputs": [{**package_shape["outputs"][0],
            "derived_from": [{"artifact_id": "foreign", "sha256": "3" * 64}]}]}
        self.assertIn("lineage mismatch", " ".join(stage_reuse_decision(self.root, unrelated,
            inputs=[concept, conditioning], settings={"seed": 1})["reasons"]))

    def test_output_identity_must_match_stage(self):
        for changed in ({"id": ""}, {"stage": "material_assembly_export"}, {"attempt": 2}):
            with self.subTest(changed=changed):
                decision = stage_reuse_decision(self.root, {**self.stage,
                    "outputs": [{**self.output, **changed}]}, inputs=[self.input], settings={"seed": 1})
                self.assertFalse(decision["reusable"])

    def test_nonpositive_stage_attempt_is_not_reusable(self):
        for attempt in (-1, True):
            with self.subTest(attempt=attempt):
                malformed = {**self.stage, "attempt": attempt,
                             "outputs": [{**self.output, "attempt": attempt}]}
                decision = stage_reuse_decision(self.root, malformed,
                    inputs=[self.input], settings={"seed": 1})
                self.assertFalse(decision["reusable"])

    def test_missing_or_hash_mismatched_output_is_stale(self):
        missing = {**self.output, "path": "missing.glb"}
        self.assertIn("missing", " ".join(stage_reuse_decision(self.root, {**self.stage, "outputs": [missing]},
            inputs=[self.input], settings={"seed": 1})["reasons"]))
        (self.root / "mesh.glb").write_bytes(b"changed")
        self.assertIn("hash mismatch", " ".join(stage_reuse_decision(self.root, self.stage,
            inputs=[self.input], settings={"seed": 1})["reasons"]))

    def test_same_basename_different_content_is_not_substituted(self):
        (self.root / "elsewhere").mkdir()
        (self.root / "elsewhere/mesh.glb").write_bytes(b"different content")
        decision = artifact_integrity(self.root, {**self.output, "path": "absent/mesh.glb"})
        self.assertFalse(decision[0])
        self.assertIn("missing", decision[1])

    def test_nonterminal_stage_is_not_reusable(self):
        decision = stage_reuse_decision(self.root, {**self.stage, "status": "running"},
            inputs=[self.input], settings={"seed": 1})
        self.assertFalse(decision["reusable"])

    def test_earliest_stale_stage_uses_fixed_stage_order(self):
        self.assertEqual(earliest_stale_stage(self.root, [self.stage], {
            "concept_generation": ([], {}), "material_generation": ([self.input], {"seed": 1})
        }), "concept_generation")

    def test_earliest_stale_stage_rejects_unknown_requested_stage(self):
        with self.assertRaisesRegex(ValueError, "unsupported prop stage"):
            earliest_stale_stage(self.root, [], {"mesh_preperation": ([], {})})


    def test_retexture_reuses_processed_mesh_only_for_matching_source_and_settings(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision

        source_path = self.root / "source.glb"
        processed_path = self.root / "processed.blend"
        source_path.write_bytes(b"source mesh")
        processed_path.write_bytes(b"processed mesh")
        source = {"id": "mesh:1", "type": "mesh.glb", "path": "source.glb",
                  "sha256": file_sha256(source_path), "stage": "mesh_workflow_execution", "attempt": 1,
                  "derived_from": []}
        settings = {"face_budget": 1000, "material_scale": 3.0}
        prepared = {"id": "prepared:1", "type": "mesh.prepared", "path": "processed.blend",
                    "sha256": file_sha256(processed_path), "stage": "mesh_preparation", "attempt": 1,
                    "derived_from": [{"artifact_id": source["id"], "sha256": source["sha256"]}]}
        asset = {"source": {"processed_mesh": "processed.blend"}, "executions": [{"stages": [{
            "name": "mesh_preparation", "attempt": 1, "status": "succeeded",
            "inputs": [source], "settings": settings, "outputs": [prepared]}]}]}

        self.assertTrue(processed_mesh_reuse_decision(self.root, asset, source, settings)["reusable"])
        self.assertFalse(processed_mesh_reuse_decision(
            self.root, asset, source, {**settings, "material_scale": 2.0})["reusable"])
        processed_path.write_bytes(b"changed mesh")
        self.assertFalse(processed_mesh_reuse_decision(self.root, asset, source, settings)["reusable"])

    def test_retexture_rebuilds_missing_or_unknown_lineage_mesh(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision

        source_path = self.root / "source.glb"
        source_path.write_bytes(b"source mesh")
        source = {"id": "mesh:legacy", "type": "mesh.glb", "path": "source.glb",
                  "sha256": file_sha256(source_path), "stage": "mesh_workflow_execution", "attempt": 1,
                  "derived_from": []}
        asset = {"source": {"processed_mesh": "missing.blend"}, "executions": []}

        decision = processed_mesh_reuse_decision(self.root, asset, source, {})
        self.assertFalse(decision["reusable"])
        self.assertIn("no matching processed mesh lineage", " ".join(decision["reasons"]))
        self.assertFalse(processed_mesh_reuse_decision(self.root, asset, None, {})["reusable"])

    def test_prop_child_reuse_requires_intact_matching_concept_execution(self):
        from slopforge.pipelines.model import prop_child_reuse_decision

        path = self.root / "candidate.png"
        path.write_bytes(b"concept")
        artifact = {"id": "concept-candidate:1", "type": "image.concept", "path": "candidate.png",
                    "sha256": file_sha256(path), "stage": "concept_generation", "attempt": 1,
                    "derived_from": []}
        stage = {"name": "concept_generation", "attempt": 1, "status": "succeeded", "inputs": [],
                 "settings": {"prompt": "brass relay", "seed": 7}, "outputs": [artifact]}
        execution = {"id": "execution:1", "status": "succeeded",
                     "identity_inputs": {"asset_type": "prop", "brief": "brass relay",
                                          "generation_prompt": "brass relay"}, "stages": [stage]}
        asset = {"type": "prop", "description": "brass relay", "generation_prompt": "brass relay",
                 "candidates": {"items": [{"number": 1, "status": "candidate", "path": "candidate.png",
                                              "execution_id": "execution:1", "artifact": artifact}]},
                 "executions": [execution]}
        child = {"id": "terminal", "type": "prop", "description": "brass relay",
                 "generation_prompt": "brass relay"}

        self.assertTrue(prop_child_reuse_decision(self.root, asset, {"status": "completed"}, child, {})["reusable"])
        child["description"] = "copper terminal"
        self.assertFalse(prop_child_reuse_decision(self.root, asset, {"status": "completed"}, child, {})["reusable"])


    def test_legacy_unknown_provenance_does_not_reuse_unproven_mesh(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision

        source = {"path": "legacy.glb", "type": "mesh.glb", "sha256": "a" * 64,
                  "id": "legacy-mesh", "stage": "legacy", "attempt": 1, "derived_from": []}
        decision = processed_mesh_reuse_decision(
            self.root, {"source": {"processed_mesh": "processed.blend"}, "executions": []}, source, {})
        self.assertFalse(decision["reusable"])

    def test_duplicate_filename_with_different_content_is_not_reused(self):
        duplicate = self.root / "other"
        duplicate.mkdir()
        (self.root / "mesh.glb").write_bytes(b"recorded content")
        (duplicate / "mesh.glb").write_bytes(b"different content")
        reference = {**self.output, "path": "other/mesh.glb",
                     "sha256": hashlib.sha256(b"recorded content").hexdigest()}

        decision = artifact_integrity(self.root, reference)
        self.assertFalse(decision[0])
        self.assertIn("hash mismatch", decision[1])


class PropApprovalReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "Assets").mkdir()
        (self.root / "ai/styles/plain/references/approved").mkdir(parents=True)
        (self.root / "ai/asset_types").mkdir()
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
        self.config["asset_pipeline"]["defaults"].update(model_candidates=1, material_candidates=1)
        self.config["_quality_base_pipeline"]["defaults"].update(model_candidates=1, material_candidates=1)
        self.style = load_style(self.root)
        self.asset_type = load_taxonomy(self.root)["prop"]
        self.asset = new_record("prop", "relay", "Copper relay", self.style, {"strategy": "text_only"})
        self.manifest = {"schema_version": 4, "assets": {"prop:relay": self.asset}}
        concept = self.root / "concept.png"
        Image.new("RGB", (512, 512), "red").save(concept)
        self.asset["candidates"] = {"selected": None, "items": [self._candidate(1, concept)]}
        self.calls = {name: 0 for name in ("prepare", "mesh", "material", "maps", "assembly")}
        self.fail_once = None
        self.fail_times = {}
        self.interrupt_once = None

    def _candidate(self, number, path):
        return {"number": number, "status": "candidate", "path": path.relative_to(self.root).as_posix(),
                "description": "Copper relay", "artifact": {"id": f"concept:{number}", "type": "image.concept",
                "path": path.relative_to(self.root).as_posix(), "sha256": file_sha256(path),
                "stage": "concept_generation", "attempt": number, "derived_from": []}}

    def _maybe_fail(self, name):
        self.calls[name] += 1
        if self.interrupt_once == name:
            self.interrupt_once = None
            raise KeyboardInterrupt(f"interrupted {name}")
        if self.fail_times.get(name, 0):
            self.fail_times[name] -= 1
            raise RuntimeError(f"interrupted {name}")
        if self.fail_once == name:
            self.fail_once = None
            raise RuntimeError(f"interrupted {name}")

    def _commands(self, command, check):
        if "prepare_3d_input.py" in command[1]:
            self._maybe_fail("prepare")
            Image.new("RGBA", (32, 32), "white").save(command[command.index("--cutout") + 1])
            Image.new("RGB", (32, 32), "white").save(command[command.index("--output") + 1])
        elif "make_pbr_maps.py" in command[1]:
            self._maybe_fail("maps")
            for name in ("normal", "roughness", "metallic", "emission"):
                Image.new("RGB", (32, 32), "white").save(command[command.index("--" + name) + 1])

    def _mesh(self, _root, _config, _image, _name, destination, metadata, seed, _budget=None, **_kwargs):
        self._maybe_fail("mesh")
        destination.write_bytes(b"mesh")
        info = {"workflow": "model.json", "seed": seed, "model": "mesh"}
        if _config["asset_pipeline"]["workflows"].get("model"):
            info["textured"] = True
            info["textures"] = {}
            for name in ("basecolor", "normal", "roughness", "metallic"):
                texture = destination.parent / f"{name}.png"
                Image.new("RGB", (32, 32), "white").save(texture)
                info["textures"][name] = texture.name
        metadata.write_text(json.dumps(info))

    def _material(self, _root, _config, _workflow, _prompt, destination, _prefix, seed, metadata, **_kwargs):
        self._maybe_fail("material")
        Image.new("RGB", (32, 32), "blue").save(destination)
        metadata.write_text(json.dumps({"workflow": "image.json", "seed": seed}))

    def _assembly(self, _root, _config, _source, fbx, blend, _textures, _budget, **kwargs):
        self._maybe_fail("assembly")
        for path in (fbx, blend, kwargs["stage_mesh"]):
            path.write_bytes(b"assembled")
        kwargs["preview_dir"].mkdir(parents=True, exist_ok=True)
        for name in ("front", "side", "rear", "three_quarter"):
            (kwargs["preview_dir"] / f"{fbx.stem}_{name}.png").write_bytes(b"preview")

    def _approve(self, *, resume=False, material_prompt=None):
        with ExitStack() as stack:
            stack.enter_context(patch("slopforge.pipelines.model.subprocess.run", side_effect=self._commands))
            stack.enter_context(patch("slopforge.pipelines.model.generate_model", side_effect=self._mesh))
            stack.enter_context(patch("slopforge.pipelines.model.generate_image", side_effect=self._material))
            stack.enter_context(patch("slopforge.pipelines.model.process_model", side_effect=self._assembly))
            stack.enter_context(patch("slopforge.pipelines.model.inspect_model", return_value={}))
            stack.enter_context(patch("slopforge.pipelines.model.validate_model_outputs",
                                      return_value={"status": "passed", "errors": [], "warnings": [], "measured": {}}))
            return approve(self.root, self.config, self.asset_type, self.style, self.manifest,
                           "prop:relay", 1, resume=resume, material_prompt=material_prompt,
                           material_count=1, quality_tier="normal")

    def _mark_interrupted(self):
        self.asset = self.manifest["assets"]["prop:relay"]
        self.asset["executions"][-1]["status"] = "running"
        self.asset["executions"][-1].pop("finished_at", None)
        save_manifest(self.root / self.config["asset_pipeline"]["manifest"], self.manifest)

    def test_identical_execution_reuses_completed_outputs(self):
        self._approve()
        before = dict(self.calls)
        self._mark_interrupted()
        self._approve(resume=True)
        self.assertEqual(self.calls, before)
        self.assertTrue(self.asset["executions"][-1]["reuse_decisions"])

    def test_approve_cli_exposes_explicit_resume_flag(self):
        from slopforge.cli import parse_args

        self.assertTrue(parse_args(["approve", "relay", "1", "--resume"]).resume)

    def test_selected_concept_change_invalidates_mesh_material_and_publication(self):
        self._approve()
        self._mark_interrupted()
        other = self.root / "other.png"
        Image.new("RGB", (512, 512), "green").save(other)
        self.asset["candidates"]["items"][0] = self._candidate(1, other)
        with self.assertRaisesRegex(ValueError, "concept|candidate"):
            self._approve(resume=True)
        self.assertEqual(self.calls["mesh"], 1)

    def test_material_only_change_reuses_mesh_and_rebuilds_descendants(self):
        self._approve()
        self._mark_interrupted()
        self._approve(resume=True, material_prompt="oxidized copper")
        self.assertEqual((self.calls["mesh"], self.calls["material"], self.calls["assembly"]), (1, 2, 2))

    def test_geometry_settings_change_invalidates_geometry_and_descendants(self):
        self._approve()
        self._mark_interrupted()
        self.asset_type["voxel_resolution"] = 128
        self._approve(resume=True)
        self.assertEqual((self.calls["mesh"], self.calls["material"]), (2, 2))

    def test_model_workflow_content_change_invalidates_geometry(self):
        workflows = self.root / "ai/workflows"
        workflows.mkdir()
        workflow = workflows / "model.json"
        workflow.write_text(json.dumps({"1": {"class_type": "Example", "inputs": {"resolution": 128}}}))
        self.config["asset_pipeline"]["workflows"]["model"] = "model.json"
        self._approve()
        self._mark_interrupted()
        workflow.write_text(json.dumps({"1": {"class_type": "Example", "inputs": {"resolution": 256}}}))
        self._approve(resume=True)
        self.assertEqual(self.calls["mesh"], 2)

    def test_processing_settings_change_invalidates_assembly_only(self):
        self._approve()
        self._mark_interrupted()
        self.config["asset_pipeline"]["material_scale"] = 2.0
        self.config["_quality_base_pipeline"]["material_scale"] = 2.0
        self._approve(resume=True)
        self.assertEqual((self.calls["mesh"], self.calls["material"], self.calls["maps"], self.calls["assembly"]),
                         (1, 1, 1, 2))

    def test_missing_preview_rebuilds_assembly_without_inference(self):
        self._approve()
        self._mark_interrupted()
        previous = self.asset["material_candidates"]["items"][-1]
        (self.root / previous["outputs"]["preview_front"]).unlink()
        self._approve(resume=True)
        self.assertEqual((self.calls["mesh"], self.calls["material"], self.calls["assembly"]), (1, 1, 2))

    def test_interruption_resumes_at_earliest_incomplete_stage(self):
        self.fail_once = "prepare"
        with self.assertRaises(RuntimeError):
            self._approve()
        self._approve(resume=True)
        self.assertEqual((self.calls["prepare"], self.calls["mesh"]), (2, 1))

    def test_process_interruption_resumes_from_persisted_running_stage(self):
        self.interrupt_once = "mesh"
        with self.assertRaisesRegex(KeyboardInterrupt, "interrupted mesh"):
            self._approve()
        manifest_path = self.root / self.config["asset_pipeline"]["manifest"]
        self.manifest = load_manifest(manifest_path)
        self.asset = self.manifest["assets"]["prop:relay"]
        execution = self.asset["executions"][-1]
        self.assertEqual(execution["status"], "running")
        self.assertEqual(next(stage for stage in execution["stages"]
                              if stage["name"] == "conditioning_preparation")["status"], "succeeded")
        self.assertEqual(next(stage for stage in execution["stages"]
                              if stage["name"] == "mesh_workflow_execution")["status"], "running")
        self._approve(resume=True)
        self.assertEqual((self.calls["prepare"], self.calls["mesh"]), (1, 2))

    def test_failed_stage_retries_without_regenerating_valid_ancestors(self):
        self.fail_times["mesh"] = 1
        with self.assertRaises(ValueError):
            self._approve()
        self._approve(resume=True)
        self.assertEqual((self.calls["prepare"], self.calls["mesh"]), (1, 2))

    def test_resume_uses_later_successful_mesh_after_an_earlier_attempt_failed(self):
        self.config["asset_pipeline"]["defaults"]["model_candidates"] = 2
        self.config["_quality_base_pipeline"]["defaults"]["model_candidates"] = 2
        self.fail_times["mesh"] = 1
        self.fail_once = "material"
        with self.assertRaises(ValueError):
            self._approve()
        self.assertEqual(self.calls["mesh"], 2)
        self._approve(resume=True)
        self.assertEqual(self.calls["mesh"], 2)

    def test_prior_succeeded_status_does_not_override_fingerprint_mismatch(self):
        self._approve()
        self._mark_interrupted()
        old = self.asset["executions"][-1]
        self.config["asset_pipeline"]["material_scale"] = 2.0
        self.config["_quality_base_pipeline"]["material_scale"] = 2.0
        self._approve(resume=True)
        self.assertEqual(self.calls["assembly"], 2)
        self.assertEqual(next(stage for stage in old["stages"] if stage["name"] == "material_assembly_export")["status"],
                         "succeeded")
        self.assertTrue(any(not item["reusable"] for item in self.asset["executions"][-1]["reuse_decisions"]))

    def test_manifest_reload_preserves_same_reuse_decision(self):
        self._approve()
        execution = self.asset["executions"][-1]
        stage = next(item for item in execution["stages"]
                     if item["name"] == "material_assembly_export")
        before = stage_reuse_decision(self.root, stage, inputs=stage["inputs"], settings=stage["settings"])
        manifest_path = self.root / self.config["asset_pipeline"]["manifest"]
        save_manifest(manifest_path, self.manifest)
        self.manifest = load_manifest(manifest_path)
        self.asset = self.manifest["assets"]["prop:relay"]
        stage = next(item for item in self.asset["executions"][-1]["stages"]
                     if item["name"] == "material_assembly_export")
        after = stage_reuse_decision(self.root, stage, inputs=stage["inputs"], settings=stage["settings"])

        self.assertEqual(before, after)

    def test_missing_artifact_recomputes_at_owning_stage(self):
        self._approve()
        self._mark_interrupted()
        previous = self.asset["material_candidates"]["items"][-1]
        (self.root / previous["outputs"]["surface"]).unlink()
        self._approve(resume=True)

        self.assertEqual((self.calls["mesh"], self.calls["material"], self.calls["assembly"]), (1, 2, 2))

    def test_hash_mismatch_recomputes_at_owning_stage(self):
        self._approve()
        self._mark_interrupted()
        source = self.asset["source"]["glb"]
        (self.root / source).write_bytes(b"replaced mesh content")
        self._approve(resume=True)

        self.assertEqual(self.calls["mesh"], 2)


if __name__ == "__main__":
    unittest.main()
