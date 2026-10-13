import copy
import tempfile
import unittest
import hashlib
from pathlib import Path
from unittest.mock import patch

import yaml

from slopforge import recipes
from slopforge.manifest import load_manifest, new_record, save_manifest
from slopforge.provenance import file_sha256


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "ai/recipes").mkdir(parents=True)
        self.definition = {
            "id": "sample_pack", "version": 1, "description": "Small concept pack",
            "children": [
                {"id": "dependent", "type": "concept", "description": "Dependent concept",
                 "depends_on": ["source"]},
                {"id": "source", "type": "concept", "description": "Source concept"},
                {"id": "independent", "type": "concept", "description": "Independent concept"},
            ],
        }
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        self.types = {"concept": {"name": "concept", "pipeline": "image"}}
        self.style = {"name": "default", "version": 1}
        self.style["_directory"] = str(self.root / "styles")
        (self.root / "styles/references/approved").mkdir(parents=True, exist_ok=True)
        self.config = {"asset_pipeline": {"defaults": {"image_candidates": 1},
                                          "workflows": {"image": "image.json"}}}
        self.manifest = {"schema_version": 3, "assets": {}}
        self.events = []

    def tearDown(self):
        self.temp.cleanup()

    def fake_pipeline(self, root, config, style, asset_type, child, manifest, key):
        self.events.append(child["id"])
        asset = manifest["assets"][key]
        number = len(asset["candidates"]["items"]) + 1
        candidate = {"number": number, "path": f"ai/assets/candidates/concept/{asset['name']}/candidate_{number:02d}.png",
                     "status": "candidate", "seed": number,
                     "generator": {"workflow": "image.json", "seed": number},
                     "validation": {"status": "passed", "errors": [], "warnings": []}}
        asset["candidates"]["items"].append(candidate)
        asset["status"] = "candidate"
        return [candidate]

    def ready_prop_recipe(self, *, with_dependency=False):
        children = []
        if with_dependency:
            children.append({"id": "source", "type": "concept", "description": "Source"})
        children.append({"id": "terminal", "type": "prop", "description": "Brass relay",
                         "depends_on": ["source"] if with_dependency else []})
        self.definition["children"] = children
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"concept": {"name": "concept", "pipeline": "image"},
                       "prop": {"name": "prop", "pipeline": "model"}}
        with patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipe = recipes.run_recipe(self.root, self.config, self.style, asset_types, self.manifest,
                                        "sample_pack", instance_name="integrity")
        stage = recipe["recipe_instance"]["stages"]["terminal"]
        asset = self.manifest["assets"][stage["asset_key"]]
        path = "Assets/Published/terminal.fbx"
        published = self.root / path
        published.parent.mkdir(parents=True, exist_ok=True)
        published.write_bytes(b"approved output")
        asset["status"] = "ready"
        asset["generator"] = {"workflow": "old.json", "seed": 1}
        asset["candidates"]["selected"] = 1
        asset["outputs"] = {"model": path}
        asset["artifacts"] = {"output.model": {
            "id": "output.model", "type": "model.fbx", "status": "ready", "path": path,
            "sha256": file_sha256(published),
            "approval": {"status": "approved", "approved_at": "historical"},
        }}
        candidate_input = {
            "id": "candidate:1", "type": "surface.swatch",
            "path": "Assets/src.png", "sha256": "b" * 64,
            "stage": "material_assembly_export", "attempt": 1,
            "derived_from": []}
        parent_exe = {"id": "parent-exec-1", "status": "succeeded",
                      "parent_execution_id": None, "identity_inputs": {},
                      "stages": [{"name": "material_assembly_export", "attempt": 1,
                                   "status": "succeeded", "inputs": [], "settings": {},
                                   "outputs": [candidate_input]}]}
        # candidate_ref for derived_from uses artifact_id format
        candidate_ref = {"artifact_id": candidate_input["id"],
                         "sha256": candidate_input["sha256"]}
        # candidate_input_for_stage uses id format (for stage inputs)
        candidate_input_for_stage = {"id": candidate_input["id"],
                                      "sha256": candidate_input["sha256"]}
        asset["published_artifacts"] = [{
            "id": "execution:published:model", "type": "model.fbx", "path": path,
            "sha256": file_sha256(published), "stage": "final_publication",
            "attempt": 1, "derived_from": [candidate_ref],
        }]
        asset["executions"] = [{"id": "execution", "status": "succeeded",
                                  "parent_execution_id": "parent-exec-1",
                                  "identity_inputs": {},
            "stages": [{"name": "final_publication", "attempt": 1,
                        "status": "succeeded",
                        "outputs": [{"id": "execution:published:model",
                                     "type": "model.fbx",
                                     "path": path,
                                     "sha256": file_sha256(published),
                                     "stage": "final_publication",
                                     "attempt": 1,
                                     "derived_from": [candidate_ref]}],
                        "inputs": [candidate_input_for_stage],
                        "settings": {}}]},
            parent_exe]
        stage["status"] = "approved"
        return recipe, stage, asset, published, asset_types

    def test_ready_recipe_output_deleted_invalidates_current_approval(self):
        recipe, stage, asset, published, asset_types = self.ready_prop_recipe()
        published.unlink()
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types, self.manifest, "integrity")

        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")
        self.assertEqual(recipe["artifacts"]["terminal.output.model"]["status"], "superseded")

    def test_malformed_asset_artifact_and_missing_output_invalidate_before_sync(self):
        _, stage, asset, published, asset_types = self.ready_prop_recipe()
        self.events.clear()
        published.unlink()
        asset["artifacts"]["corrupt"] = {}
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertEqual(self.events, ["terminal"])
        self.assertEqual(stage["status"], "completed")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")
        self.assertNotIn("corrupt", asset["artifacts"])

    def test_recipe_artifact_sync_marks_malformed_record_stale_without_raising(self):
        recipe_asset = {"name": "test", "artifacts": {}}
        child = {"id": "child", "artifacts": {"corrupt": {}}}
        stages = {"child": {"asset_key": "child", "status": "approved"}}
        recipes._sync_recipe_artifacts(recipe_asset, stages,
                                      {"assets": {"child": child, "recipe:test": recipe_asset}})
        self.assertEqual(stages["child"]["status"], "stale")

    def test_child_artifact_sync_rejects_unhashable_candidate_status_without_raising(self):
        asset = {"status": "candidate", "candidates": {"items": [
            {"number": 1, "path": "candidate.png", "status": []}]}, "artifacts": {}}
        self.assertFalse(recipes._sync_child_artifacts(self.root, asset, "child"))

    def test_recipe_artifact_sync_rejects_unhashable_approval_status_without_raising(self):
        recipe_asset = {"name": "test", "artifacts": {}}
        child = {"id": "child", "artifacts": {"output": {
            "id": "output", "type": "model.fbx", "path": "output.fbx",
            "status": "ready", "approval": {"status": []}}}}
        stages = {"child": {"asset_key": "child", "status": "approved"}}
        recipes._sync_recipe_artifacts(recipe_asset, stages, {"assets": {"child": child}})
        self.assertEqual(stages["child"]["status"], "stale")

    def test_recipe_artifact_sync_rejects_approval_without_status(self):
        recipe_asset = {"name": "test", "artifacts": {}}
        child = {"id": "child", "artifacts": {"output": {
            "id": "output", "type": "model.fbx", "path": "output.fbx",
            "status": "ready", "approval": {}}}}
        stages = {"child": {"asset_key": "child", "status": "approved"}}
        recipes._sync_recipe_artifacts(recipe_asset, stages,
                                      {"assets": {"child": child, "recipe:test": recipe_asset}})
        self.assertEqual(stages["child"]["status"], "stale")

    def test_recipe_artifact_sync_rejects_invalid_artifact_id_without_raising(self):
        recipe_asset = {"name": "test", "artifacts": {}}
        child = {"id": "child", "artifacts": {"output ": {
            "id": "output ", "type": "model.fbx", "path": "output.fbx", "status": "ready"}}}
        stages = {"child": {"asset_key": "child", "status": "approved"}}
        recipes._sync_recipe_artifacts(recipe_asset, stages, {"assets": {"child": child}})
        self.assertEqual(stages["child"]["status"], "stale")

    def test_ready_recipe_output_hash_mismatch_invalidates_current_approval(self):
        recipe, stage, asset, published, asset_types = self.ready_prop_recipe()
        published.write_bytes(b"changed output")
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types, self.manifest, "integrity")

        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")
        self.assertEqual(recipe["artifacts"]["terminal.output.model"]["status"], "superseded")

    def test_invalid_ready_output_is_invalidated_before_dependency_block(self):
        _, stage, asset, published, asset_types = self.ready_prop_recipe(with_dependency=True)
        published.unlink()
        source_stage = self.manifest["assets"]["recipe:integrity"]["recipe_instance"]["stages"]["source"]
        source_stage["status"] = "failed"

        def fail_source(*_args):
            raise RuntimeError("source remains unavailable")

        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"image": fail_source}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types, self.manifest, "integrity")

        self.assertEqual(stage["status"], "blocked")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_missing_ready_output_hash_invalidates_approval(self):
        _, stage, asset, _, asset_types = self.ready_prop_recipe()
        asset["artifacts"]["output.model"].pop("sha256")
        asset["published_artifacts"][0].pop("sha256")
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_malformed_published_reference_sibling_invalidates_approval(self):
        _, stage, asset, _, asset_types = self.ready_prop_recipe()
        asset["published_artifacts"].append(None)
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_incomplete_published_reference_sibling_invalidates_approval(self):
        _, stage, asset, _, asset_types = self.ready_prop_recipe()
        asset["published_artifacts"].append({"id": None})
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_wrong_current_output_artifact_type_invalidates_approval(self):
        _, stage, asset, _, asset_types = self.ready_prop_recipe()
        asset["artifacts"]["output.model"]["type"] = "image.prop"
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_malformed_candidate_sibling_invalidates_and_regenerates(self):
        _, stage, asset, _, asset_types = self.ready_prop_recipe()
        self.events.clear()
        asset["candidates"]["items"].append(None)
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertEqual(self.events, ["terminal"])
        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_incomplete_candidate_member_invalidates_and_regenerates(self):
        _, stage, asset, _, asset_types = self.ready_prop_recipe()
        self.events.clear()
        asset["candidates"]["items"].append({"number": 2, "status": "candidate"})
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertEqual(self.events, ["terminal"])
        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_malformed_candidate_collection_invalidates_and_regenerates(self):
        _, stage, asset, _, asset_types = self.ready_prop_recipe()
        self.events.clear()
        asset["candidates"]["items"] = {"malformed": "collection"}
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertEqual(self.events, ["terminal"])
        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_malformed_candidate_container_does_not_raise_and_invalidates(self):
        _, stage, asset, _, asset_types = self.ready_prop_recipe()
        self.events.clear()
        asset["candidates"] = None
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertEqual(self.events, ["terminal"])
        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_malformed_candidate_artifact_approval_does_not_raise(self):
        _, stage, asset, _, asset_types = self.ready_prop_recipe()
        asset["artifacts"]["candidate.1"] = {
            "id": "candidate.1", "type": "prop.candidate", "status": "candidate",
            "path": asset["candidates"]["items"][0]["path"], "approval": None}
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_malformed_artifact_collection_does_not_raise_and_invalidates(self):
        _, stage, asset, _, asset_types = self.ready_prop_recipe()
        asset["artifacts"] = None
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["status"], "stale")

    def test_invalid_ready_output_path_invalidates_approval(self):
        _, stage, asset, _, asset_types = self.ready_prop_recipe()
        asset["outputs"]["model"] = None
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types,
                                  self.manifest, "integrity")

        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_dependency_order_and_aggregate_outputs(self):
        snapshots = []
        with patch.dict(recipes.PIPELINE_HANDLERS, {"image": self.fake_pipeline}):
            result = recipes.run_recipe(self.root, self.config, self.style, self.types, self.manifest,
                                        "sample_pack", instance_name="demo",
                                        save=lambda data: snapshots.append(data["assets"]["recipe:demo"]["status"]))

        self.assertEqual(self.events, ["source", "dependent", "independent"])
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertEqual(result["recipe_instance"]["stages"]["source"]["status"], "completed")
        self.assertEqual(result["recipe_instance"]["stages"]["dependent"]["status"], "completed")
        stages = result["recipe_instance"]["stages"]
        dependent = self.manifest["assets"][stages["dependent"]["asset_key"]]
        self.assertEqual(dependent["dependencies"], [{"asset_id": stages["source"]["asset_id"]}])
        self.assertEqual(len(result["artifacts"]), 3)
        aggregate = result["artifacts"]["source.candidate.1"]
        self.assertEqual(aggregate["path"], "ai/assets/candidates/concept/demo_source/candidate_01.png")
        self.assertEqual(aggregate["derived_from"], [{"asset_id": stages["source"]["asset_id"], "output_id": "candidate.1"}])
        self.assertEqual(aggregate["provenance"]["seed"], 1)
        self.assertIn("running", snapshots)
        self.assertIn("awaiting_approval", snapshots)

    def test_malformed_pipeline_candidate_member_fails_child_stage(self):
        self.definition["children"] = [{"id": "source", "type": "concept",
                                        "description": "Source concept"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))

        def malformed_pipeline(*args):
            return [*self.fake_pipeline(*args), None]

        with patch.dict(recipes.PIPELINE_HANDLERS, {"image": malformed_pipeline}):
            result = recipes.run_recipe(self.root, self.config, self.style, self.types,
                                        self.manifest, "sample_pack", instance_name="malformed")

        self.assertEqual(result["recipe_instance"]["stages"]["source"]["status"], "failed")

    def test_child_content_overrides_are_used_and_snapshotted_for_resume(self):
        captured = []

        def inspect_child(root, config, style, asset_type, child, manifest, key):
            captured.append((child["description"], child["generation_prompt"]))
            return self.fake_pipeline(root, config, style, asset_type, child, manifest, key)

        overrides = {"source": {"description": "A lunar rescue beacon",
                                 "generation_prompt": "Cracked ceramic beacon with lunar rescue marks"}}
        with patch.dict(recipes.PIPELINE_HANDLERS, {"image": inspect_child}):
            result = recipes.run_recipe(self.root, self.config, self.style, self.types, self.manifest,
                                        "sample_pack", instance_name="tailored", child_overrides=overrides)
        recipe_definition = result["recipe_instance"]["definition"]
        source = next(child for child in recipe_definition["children"] if child["id"] == "source")
        self.assertEqual(captured[0], ("A lunar rescue beacon", "Cracked ceramic beacon with lunar rescue marks"))
        self.assertEqual(source["generation_prompt"], "Cracked ceramic beacon with lunar rescue marks")

    def test_partial_failure_blocks_dependents_and_resume_retries_only_incomplete_stages(self):
        failed_once = set()

        def flaky(*args):
            child = args[4]
            if child["id"] == "source" and child["id"] not in failed_once:
                failed_once.add(child["id"])
                self.events.append(child["id"])
                raise RuntimeError("temporary failure")
            return self.fake_pipeline(*args)

        with patch.dict(recipes.PIPELINE_HANDLERS, {"image": flaky}):
            partial = recipes.run_recipe(self.root, self.config, self.style, self.types, self.manifest,
                                         "sample_pack", instance_name="demo")
            self.assertEqual(partial["status"], "partial")
            self.assertEqual(partial["recipe_instance"]["stages"]["dependent"]["status"], "blocked")
            completed = recipes.resume_recipe(self.root, self.config, self.style, self.types, self.manifest, "demo")

        self.assertEqual(self.events, ["source", "independent", "source", "dependent"])
        self.assertEqual(completed["status"], "awaiting_approval")

    def test_interrupted_running_stage_resumes_and_persists_transitions(self):
        interrupted = False

        def interrupt_once(*args):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            return self.fake_pipeline(*args)

        manifest_path = self.root / "ai/assets/manifest.json"
        persist = lambda data: save_manifest(manifest_path, data)
        with patch.dict(recipes.PIPELINE_HANDLERS, {"image": interrupt_once}):
            with self.assertRaises(KeyboardInterrupt):
                recipes.run_recipe(self.root, self.config, self.style, self.types, self.manifest,
                                   "sample_pack", instance_name="demo",
                                   save=persist)
            self.manifest = load_manifest(manifest_path)
            running = self.manifest["assets"]["recipe:demo"]["recipe_instance"]["stages"]["source"]
            self.assertEqual(running["status"], "running")
            result = recipes.resume_recipe(self.root, self.config, self.style, self.types, self.manifest,
                                           "demo", save=persist)

        self.assertEqual(result["recipe_instance"]["stages"]["source"]["status"], "completed")
        self.assertEqual(load_manifest(manifest_path)["assets"]["recipe:demo"]["status"], "awaiting_approval")

    def test_resume_preserves_approved_children_and_regenerate_targets_only_one_child(self):
        with patch.dict(recipes.PIPELINE_HANDLERS, {"image": self.fake_pipeline}):
            recipes.run_recipe(self.root, self.config, self.style, self.types, self.manifest,
                               "sample_pack", instance_name="demo")
            record = self.manifest["assets"]["recipe:demo"]
            stages = record["recipe_instance"]["stages"]
            approved = self.manifest["assets"][stages["source"]["asset_key"]]
            approved["status"] = "ready"
            approved["candidates"]["selected"] = 1
            approved["outputs"]["image"] = "Assets/approved.png"
            before = (approved["candidates"]["selected"], approved["outputs"]["image"])
            self.events.clear()
            recipes.resume_recipe(self.root, self.config, self.style, self.types, self.manifest, "demo")
            self.assertEqual(self.events, [])

            self.events.clear()
            regenerated = recipes.regenerate_child(self.root, self.config, self.style, self.types, self.manifest,
                                                   "demo", "source")

        self.assertEqual(self.events, ["source"])
        self.assertEqual(regenerated["recipe_instance"]["stages"]["source"]["status"], "approved")
        self.assertEqual((approved["candidates"]["selected"], approved["outputs"]["image"]), before)
        self.assertEqual(len(approved["candidates"]["items"]), 2)

    def test_definition_rejects_dependency_cycles_before_creating_assets(self):
        self.definition["children"][0]["depends_on"] = ["source"]
        self.definition["children"][1]["depends_on"] = ["dependent"]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))

        with self.assertRaisesRegex(ValueError, "cycle"):
            recipes.run_recipe(self.root, self.config, self.style, self.types, self.manifest,
                               "sample_pack", instance_name="demo")
        self.assertEqual(self.manifest["assets"], {})

    def test_model_children_use_the_existing_model_pipeline(self):
        child = {"id": "terminal", "type": "prop", "description": "Wall terminal",
                 "generation_prompt": "A blue wall terminal"}
        self.definition["children"] = [child]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"prop": {"name": "prop", "pipeline": "model"}}
        result = [{"number": 1, "status": "candidate"}]
        self.config["asset_pipeline"]["defaults"]["model_candidates"] = 3
        self.config["asset_pipeline"]["defaults"]["image_candidates"] = 4

        with patch("slopforge.recipes.model.generate", return_value=result) as generate:
            recipes.run_recipe(self.root, self.config, self.style, asset_types, self.manifest,
                               "sample_pack", instance_name="demo")

        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[6], 4)
        self.assertEqual(generate.call_args.kwargs["generation_prompt"], "A blue wall terminal")
        self.assertEqual(self.manifest["assets"]["recipe:demo"]["status"], "awaiting_approval")

    def test_image_children_use_configured_candidate_default(self):
        child = {"id": "coin", "type": "concept", "description": "Gold coin"}
        self.definition["children"] = [child]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        self.config["asset_pipeline"]["defaults"]["image_candidates"] = 5

        with patch("slopforge.recipes.image.generate", return_value=[{"number": 1, "status": "candidate"}]) as generate:
            recipes.run_recipe(self.root, self.config, self.style, self.types, self.manifest,
                               "sample_pack", instance_name="demo")

        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[6], 5)

    def test_recipe_child_passes_resolved_reference_library_to_existing_pipeline(self):
        library_dir = self.root / "ai/libraries/character"
        library_dir.mkdir(parents=True)
        reference = self.root / "alice.png"
        reference.write_bytes(b"portrait")
        (library_dir / "alice.yaml").write_text(yaml.safe_dump({
            "name": "Alice", "kind": "character", "version": 1,
            "entries": [{"id": "portrait", "path": "alice.png", "category": "identity", "strength": 0.9}],
        }))
        self.definition["children"] = [{"id": "portrait", "type": "concept", "description": "Portrait",
                                         "reference_library": "character/alice"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        with patch("slopforge.recipes.image.generate", return_value=[{"number": 1, "status": "candidate"}]) as generate:
            recipes.run_recipe(self.root, self.config, self.style, self.types, self.manifest,
                               "sample_pack", instance_name="demo")
        self.assertEqual(generate.call_args.kwargs["reference_entries"][0]["id"], "portrait")
        self.assertEqual(generate.call_args.kwargs["reference_entries"][0]["path"], str(reference.resolve()))

    def test_recipe_blocks_missing_library_entries_before_creating_a_run(self):
        library_dir = self.root / "ai/libraries/character"
        library_dir.mkdir(parents=True)
        (library_dir / "alice.yaml").write_text(yaml.safe_dump({
            "name": "Alice", "kind": "character", "version": 1,
            "entries": [{"id": "portrait", "path": "missing.png"}],
        }))
        self.definition["children"] = [{"id": "portrait", "type": "concept", "description": "Portrait",
                                         "reference_library": "character/alice"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            recipes.run_recipe(self.root, self.config, self.style, self.types, self.manifest,
                               "sample_pack", instance_name="demo")
        self.assertEqual(self.manifest["assets"], {})

    def test_recipe_and_child_quality_tiers_propagate_and_are_snapshotted(self):
        self.definition["quality_tier"] = "final"
        self.definition["children"] = [{"id": "coin", "type": "concept", "description": "Coin",
                                         "quality_tier": "draft"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        self.config["asset_pipeline"]["defaults"]["image_candidates"] = 5
        with patch("slopforge.recipes.image.generate", return_value=[{"number": 1, "status": "candidate"}]) as generate:
            recipe_asset = recipes.run_recipe(self.root, self.config, self.style, self.types, self.manifest,
                                              "sample_pack", instance_name="demo")
        self.assertEqual(recipe_asset["recipe_instance"]["quality_tier"], "final")
        stage = recipe_asset["recipe_instance"]["stages"]["coin"]
        self.assertEqual(stage["quality_tier"], "draft")
        self.assertEqual(generate.call_args.args[1]["asset_pipeline"]["selected_quality_tier"], "draft")
        self.assertEqual(generate.call_args.args[1]["asset_pipeline"]["defaults"]["image_candidates"], 1)

    def test_recipe_run_applies_character_reference_library_to_children(self):
        reference = self.root / "References/alice.png"
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b"reference")
        library = self.root / "ai/libraries/character/alice.yaml"
        library.parent.mkdir(parents=True)
        library.write_text(yaml.safe_dump({"kind": "character", "entries": [{"id": "identity", "path": "References/alice.png"}]}))
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        with patch.dict(recipes.PIPELINE_HANDLERS, {"image": self.fake_pipeline}):
            result = recipes.run_recipe(self.root, self.config, self.style, self.types, self.manifest,
                                        "sample_pack", instance_name="alice_sprites",
                                        reference_library="character/alice")
        snapshot = result["recipe_instance"]["definition"]
        self.assertTrue(all(child["reference_library"] == "character/alice" for child in snapshot["children"]))

    def test_invalid_dependency_shape_returns_recipe_validation_error(self):
        self.definition["children"][0]["depends_on"] = [{}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))

        with self.assertRaisesRegex(ValueError, "Invalid dependencies"):
            recipes.load_recipe(self.root, "sample_pack", self.types)

    def test_completed_prop_recipe_child_with_changed_inputs_is_regenerated(self):
        self.definition["children"] = [{"id": "terminal", "type": "prop", "description": "Brass relay"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"prop": {"name": "prop", "pipeline": "model"}}
        generated = []

        def generate(*_args, **_kwargs):
            generated.append(True)
            return [{"number": len(generated), "status": "candidate"}]

        persist = lambda data: save_manifest(self.root / "manifest.json", data)
        with patch("slopforge.recipes.model.generate", side_effect=generate), \
                patch("slopforge.recipes.model.prop_child_reuse_decision",
                      return_value={"reusable": False, "reasons": ["prop child brief changed"]}):
            recipes.run_recipe(self.root, self.config, self.style, asset_types, self.manifest,
                               "sample_pack", instance_name="demo", save=persist)
            self.manifest = load_manifest(self.root / "manifest.json")
            recipes.resume_recipe(self.root, self.config, self.style, asset_types, self.manifest,
                                  "demo", save=persist)

        self.assertEqual(len(generated), 2)
        stage = self.manifest["assets"]["recipe:demo"]["recipe_instance"]["stages"]["terminal"]
        self.assertEqual(stage["status"], "completed")
        self.assertEqual(stage["reuse_decisions"][-1]["reasons"], ["prop child brief changed"])

    def test_recipe_resume_reuses_intact_child_after_manifest_reload(self):
        self.definition["children"] = [{"id": "terminal", "type": "prop", "description": "Brass relay"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"prop": {"name": "prop", "pipeline": "model"}}
        generated = []

        def generate(*_args, **_kwargs):
            generated.append(True)
            return [{"number": 1, "status": "candidate"}]

        persist = lambda data: save_manifest(self.root / "manifest.json", data)
        with patch("slopforge.recipes.model.generate", side_effect=generate), \
                patch("slopforge.recipes.model.prop_child_reuse_decision",
                      return_value={"reusable": True, "reasons": []}):
            recipes.run_recipe(self.root, self.config, self.style, asset_types, self.manifest,
                               "sample_pack", instance_name="demo", save=persist)
            self.manifest = load_manifest(self.root / "manifest.json")
            recipes.resume_recipe(self.root, self.config, self.style, asset_types, self.manifest,
                                  "demo", save=persist)

        self.assertEqual(len(generated), 1)
        stage = self.manifest["assets"]["recipe:demo"]["recipe_instance"]["stages"]["terminal"]
        self.assertEqual(stage["reuse_decisions"][-1]["reusable"], True)

    def test_failed_replacement_does_not_restore_stale_recipe_child_as_approved(self):
        self.style["_directory"] = str(self.root / "styles")
        (self.root / "styles/references/approved").mkdir(parents=True, exist_ok=True)
        self.config["asset_pipeline"]["workflows"] = {"image": "image.json"}
        self.definition["children"] = [{"id": "terminal", "type": "prop", "description": "Brass relay"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"prop": {"name": "prop", "pipeline": "model"}}
        with patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipe = recipes.run_recipe(self.root, self.config, self.style, asset_types, self.manifest,
                                        "sample_pack", instance_name="demo")
        stage = recipe["recipe_instance"]["stages"]["terminal"]
        asset = self.manifest["assets"][stage["asset_key"]]
        asset["status"] = "ready"
        asset["generator"] = {"workflow": "old.json", "seed": 1}
        asset["candidates"]["selected"] = 1
        asset["candidates"]["items"][0]["approval"] = "approved"
        self.root.joinpath("old.fbx").write_bytes(b"old output")
        self.root.joinpath("archive.fbx").write_bytes(b"unrelated output")
        asset["outputs"] = {"model": "old.fbx"}
        asset["artifacts"] = {
            "output.model": {"id": "output.model", "type": "mesh.fbx", "status": "ready",
                             "path": "old.fbx", "provenance": {"seed": 1},
                             "derived_from": [{"asset_id": "source-id", "output_id": "concept"}],
                             "approval": {"status": "approved", "approved_at": "historical-approval"}},
            "candidate.1": {"id": "candidate.1", "type": "prop.candidate", "status": "candidate",
                            "path": asset["candidates"]["items"][0]["path"],
                            "provenance": {"historical": True},
                            "approval": {"status": "approved", "approved_at": "historical-candidate-approval"}},
            "archive": {"id": "archive", "type": "mesh.fbx", "status": "ready",
                        "path": "archive.fbx", "approval": {"status": "approved"}},
        }
        old_outputs = copy.deepcopy(asset["outputs"])
        old_approval = copy.deepcopy(asset["artifacts"]["output.model"]["approval"])
        old_provenance = copy.deepcopy(asset["artifacts"]["output.model"]["provenance"])
        old_lineage = copy.deepcopy(asset["artifacts"]["output.model"]["derived_from"])
        old_candidate_artifact = copy.deepcopy(asset["artifacts"]["candidate.1"])
        old_aggregate_approval = {"status": "approved", "approved_at": "historical-aggregate-approval"}
        self.manifest["assets"]["recipe:demo"]["artifacts"] = {
            "terminal.output.model": {"id": "terminal.output.model", "type": "mesh.fbx",
                                      "status": "ready", "path": "old.fbx",
                                      "derived_from": [{"asset_id": asset["id"], "output_id": "output.model"}],
                                      "provenance": {"seed": 1}, "approval": copy.deepcopy(old_aggregate_approval)}
        }
        stage["status"] = "approved"
        handler_state = []

        def fail_at_handler_boundary(*_args):
            handler_state.append((asset["status"], asset["candidates"]["selected"],
                                  asset.get("generator"), stage["status"],
                                  copy.deepcopy(asset["artifacts"]),
                                  copy.deepcopy(self.manifest["assets"]["recipe:demo"].get("artifacts", {})),
                                  copy.deepcopy(asset["outputs"])))
            raise RuntimeError("replacement failed")

        running_snapshots = []

        def persist(data):
            saved_stage = data["assets"]["recipe:demo"]["recipe_instance"]["stages"]["terminal"]
            if saved_stage["status"] == "running":
                data = copy.deepcopy(data)
                running_snapshots.append(data)
                saved_asset = data["assets"][saved_stage["asset_key"]]
                self.assertNotEqual(saved_asset["status"], "ready")
                self.assertIsNone(saved_asset["candidates"]["selected"])
                self.assertNotIn("generator", saved_asset)
                self.assertEqual(saved_asset["artifacts"]["output.model"]["status"], "superseded")
                self.assertEqual(saved_asset["artifacts"]["output.model"]["approval"], old_approval)
                self.assertEqual(saved_asset["artifacts"]["output.model"]["provenance"], old_provenance)
                self.assertEqual(saved_asset["artifacts"]["output.model"]["derived_from"], old_lineage)
                self.assertEqual(saved_asset["artifacts"]["candidate.1"], old_candidate_artifact)
                self.assertEqual(saved_asset["artifacts"]["archive"]["status"], "ready")
                self.assertEqual(saved_asset["outputs"], old_outputs)
                aggregate = data["assets"]["recipe:demo"]["artifacts"]["terminal.output.model"]
                self.assertEqual(aggregate["status"], "superseded")
                self.assertEqual(aggregate["approval"], old_aggregate_approval)

        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": False, "reasons": ["brief changed"]}), \
                patch.dict(recipes.PIPELINE_HANDLERS,
                           {"model": fail_at_handler_boundary}):
            result = recipes.resume_recipe(self.root, self.config, self.style, asset_types, self.manifest,
                                           "demo", save=persist)

        self.assertEqual(stage["status"], "stale")
        self.assertEqual(asset["status"], "stale")
        self.assertEqual(len(handler_state), 1)
        self.assertEqual(handler_state[0][:4], ("stale", None, None, "running"))
        self.assertEqual(handler_state[0][4]["output.model"]["status"], "superseded")
        self.assertEqual(handler_state[0][4]["output.model"]["approval"], old_approval)
        self.assertEqual(handler_state[0][5]["terminal.output.model"]["status"], "superseded")
        self.assertEqual(handler_state[0][5]["terminal.output.model"]["approval"], old_aggregate_approval)
        self.assertEqual(handler_state[0][4]["candidate.1"], old_candidate_artifact)
        self.assertEqual(handler_state[0][6], old_outputs)
        self.assertEqual(len(running_snapshots), 1)
        self.assertIsNone(asset["candidates"]["selected"])
        self.assertNotIn("generator", asset)
        self.assertEqual(asset["candidates"]["items"][0]["approval"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["approval"], old_approval)
        self.assertEqual(result["status"], "partial")

    def test_successful_stale_recipe_replacement_does_not_keep_old_approval(self):
        self.definition["children"] = [{"id": "terminal", "type": "prop", "description": "Brass relay"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"prop": {"name": "prop", "pipeline": "model"}}
        with patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipe = recipes.run_recipe(self.root, self.config, self.style, asset_types, self.manifest,
                                        "sample_pack", instance_name="demo")
        stage = recipe["recipe_instance"]["stages"]["terminal"]
        asset = self.manifest["assets"][stage["asset_key"]]
        asset["status"] = "ready"
        asset["generator"] = {"workflow": "old.json", "seed": 1}
        asset["candidates"]["selected"] = 1
        asset["candidates"]["items"][0]["approval"] = "approved"
        asset["outputs"] = {"model": "old.fbx"}
        stage["status"] = "approved"
        handler_state = []

        def replace_at_handler_boundary(*_args):
            handler_state.append((asset["status"], asset["candidates"]["selected"],
                                  asset.get("generator"), stage["status"]))
            candidate = {"number": 2, "status": "candidate", "path": "fresh.glb",
                         "execution_id": "fresh-execution"}
            asset["candidates"]["items"].append(candidate)
            asset["generator"] = {"workflow": "fresh.json", "seed": 2}
            return [candidate]

        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": False, "reasons": ["brief changed"]}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": replace_at_handler_boundary}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types, self.manifest, "demo")

        self.assertEqual(stage["status"], "completed")
        self.assertEqual(handler_state, [("stale", None, None, "running")])
        self.assertEqual(asset["status"], "stale")
        self.assertNotIn("generator", asset)
        self.assertEqual(stage["provenance"], {"workflow": "fresh.json", "seed": 2})
        self.assertEqual(asset["candidates"]["items"][0]["approval"], "approved")
        self.assertEqual(asset["candidates"]["items"][1]["status"], "candidate")
        self.assertEqual(asset["artifacts"]["candidate.2"]["status"], "candidate")
        self.assertEqual(asset["outputs"]["model"], "old.fbx")

    def test_stale_recipe_child_replacement_clears_readiness_before_regeneration(self):
        """A stale prop child must lose ready status and require approval of the new result."""
        self.definition["children"] = [{"id": "terminal", "type": "prop", "description": "Brass relay"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"prop": {"name": "prop", "pipeline": "model"}}

        # First run to create a ready asset
        with patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipe = recipes.run_recipe(self.root, self.config, self.style, asset_types, self.manifest,
                                        "sample_pack", instance_name="demo")

        stage = recipe["recipe_instance"]["stages"]["terminal"]
        asset = self.manifest["assets"][stage["asset_key"]]

        # Mark as ready with outputs and selected candidate
        asset["status"] = "ready"
        asset["outputs"] = {"mesh": "Assets/mesh.fbx"}
        asset["generator"] = {"workflow": "test.json", "seed": 1}
        asset["candidates"]["selected"] = 1
        stage["status"] = "approved"

        # Simulate a changed brief that makes the child stale
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": False, "reasons": ["prop child brief changed"]}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            result = recipes.resume_recipe(self.root, self.config, self.style, asset_types, self.manifest, "demo")

        # The stage should be completed (not approved) since it's a fresh generation
        self.assertEqual(stage["status"], "completed")
        # The asset should NOT be ready - it needs approval of the new result
        self.assertNotEqual(asset.get("status"), "ready")
        # The new generation should have produced candidates
        self.assertGreater(len(asset.get("candidates", {}).get("items", [])), 0)
        # The recipe should not be ready since the child needs approval
        self.assertNotEqual(result["status"], "ready")
        # Fresh candidate paths in asset.outputs are valid before approval
        self.assertIsNotNone(asset.get("outputs"))
        # The old selected candidate pointer must be cleared
        self.assertIsNone(asset.get("candidates", {}).get("selected"))
        # Historical candidate evidence must be preserved
        self.assertGreaterEqual(len(asset.get("candidates", {}).get("items", [])), 1)
        # Current generator provenance must not identify the old ready result
        self.assertIsNone(asset.get("generator"))

    # ---------------------------------------------------------------
    # Finding 1  — publication provenance must match recorded stage output
    # All tests below MUST be RED before the production fix is applied.
    # ---------------------------------------------------------------

    def test_fabricated_publication_reference_without_recorded_execution_is_rejected(self):
        """A reference with plausible ID/path/hash but no matching
        final_publication execution must reject readiness."""
        self.definition["children"] = [{"id": "terminal", "type": "prop", "description": "Brass relay"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"concept": {"name": "concept", "pipeline": "image"},
                       "prop": {"name": "prop", "pipeline": "model"}}
        path = "Assets/Published/fake.fbx"
        published = self.root / path
        published.parent.mkdir(parents=True, exist_ok=True)
        published.write_bytes(b"approved output")

        with patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipe = recipes.run_recipe(self.root, self.config, self.style,
                                        asset_types, self.manifest,
                                        "sample_pack", instance_name="intl1")
        stage = recipe["recipe_instance"]["stages"]["terminal"]
        asset = self.manifest["assets"][stage["asset_key"]]

        asset["status"] = "ready"
        asset["generator"] = {"workflow": "old.json", "seed": 1}
        asset["candidates"]["selected"] = 1
        asset["outputs"] = {"model": path}
        asset["artifacts"] = {"output.model": {
            "id": "output.model", "type": "model.fbx", "status": "ready",
            "path": path, "sha256": file_sha256(published),
            "approval": {"status": "approved", "approved_at": "historical"},
        }}
        # Fabricated reference pointing at a non-existent execution
        asset["published_artifacts"] = [{"id": "nonexistent-run:published:model",
            "type": "model.fbx", "path": path, "sha256": file_sha256(published),
            "stage": "final_publication", "attempt": 1, "derived_from": []}]
        stage["status"] = "approved"

        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style,
                                  asset_types, self.manifest, "intl1")

        self.assertNotEqual(stage["status"], "approved")
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_reference_to_real_execution_but_wrong_output_id_is_rejected(self):
        """A reference pointing at a real execution that does not match the
        recorded output identity must reject readiness."""
        self.definition["children"] = [{"id": "terminal", "type": "prop", "description": "Brass relay"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"concept": {"name": "concept", "pipeline": "image"},
                       "prop": {"name": "prop", "pipeline": "model"}}
        path = "Assets/Published/match.fbx"
        published = self.root / path
        published.parent.mkdir(parents=True, exist_ok=True)
        published.write_bytes(b"approved output")

        with patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipe = recipes.run_recipe(self.root, self.config, self.style,
                                        asset_types, self.manifest,
                                        "sample_pack", instance_name="intl2")
        stage = recipe["recipe_instance"]["stages"]["terminal"]
        asset = self.manifest["assets"][stage["asset_key"]]

        asset["status"] = "ready"
        asset["generator"] = {"workflow": "old.json", "seed": 1}
        asset["candidates"]["selected"] = 1
        asset["outputs"] = {"model": path}
        asset["artifacts"] = {"output.model": {
            "id": "output.model", "type": "model.fbx", "status": "ready",
            "path": path, "sha256": file_sha256(published),
            "approval": {"status": "approved", "approved_at": "historical"},
        }}
        # Reference with WRONG output_id (mesh instead of model)
        asset["published_artifacts"] = [{"id": "execution:published:mesh",
            "type": "model.fbx", "path": path, "sha256": file_sha256(published),
            "stage": "final_publication", "attempt": 1, "derived_from": []}]
        stage["status"] = "approved"

        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style,
                                  asset_types, self.manifest, "intl2")

        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_duplicate_ambiguous_output_references_is_rejected(self):
        """Duplicate or ambiguous matching publication provenance must reject readiness."""
        self.definition["children"] = [{"id": "terminal", "type": "prop", "description": "Brass relay"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"concept": {"name": "concept", "pipeline": "image"},
                       "prop": {"name": "prop", "pipeline": "model"}}
        path = "Assets/Published/ambig.fbx"
        published = self.root / path
        published.parent.mkdir(parents=True, exist_ok=True)
        published.write_bytes(b"approved output")

        with patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipe = recipes.run_recipe(self.root, self.config, self.style,
                                        asset_types, self.manifest,
                                        "sample_pack", instance_name="intl3")
        stage = recipe["recipe_instance"]["stages"]["terminal"]
        asset = self.manifest["assets"][stage["asset_key"]]

        asset["status"] = "ready"
        asset["generator"] = {"workflow": "old.json", "seed": 1}
        asset["candidates"]["selected"] = 1
        asset["outputs"] = {"model": path}
        asset["artifacts"] = {"output.model": {
            "id": "output.model", "type": "model.fbx", "status": "ready",
            "path": path, "sha256": file_sha256(published),
            "approval": {"status": "approved", "approved_at": "historical"},
        }}
        # Two references with same suffix and path — ambiguous
        asset["published_artifacts"] = [
            {"id": "execution-a:published:model", "type": "model.fbx",
             "path": path, "sha256": file_sha256(published),
             "stage": "final_publication", "attempt": 1, "derived_from": []},
            {"id": "execution-b:published:model", "type": "model.fbx",
             "path": path, "sha256": file_sha256(published),
             "stage": "final_publication", "attempt": 1, "derived_from": []}]
        stage["status"] = "approved"

        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style,
                                  asset_types, self.manifest, "intl3")

        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_one_exact_unambiguous_recorded_publication_output_remains_valid(self):
        """A single exact matching published artifact must leave readiness intact."""
        recipe, stage, asset, published, asset_types = self.ready_prop_recipe()
        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types, self.manifest, "integrity")

        self.assertEqual(asset["status"], "ready")
        self.assertEqual(stage["status"], "approved")



    def test_duplicate_succeeded_and_failed_publication_stage_is_rejected(self):
        """When final_publication attempt 1 exists as both succeeded and failed,
        the duplicate must be rejected regardless of which record matches."""
        children = [{"id": "terminal", "type": "prop", "description": "Brass relay"}]
        self.definition["children"] = children
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"concept": {"name": "concept", "pipeline": "image"},
                       "prop": {"name": "prop", "pipeline": "model"}}
        path = "Assets/Published/dup.fbx"
        published = self.root / path
        published.parent.mkdir(parents=True, exist_ok=True)
        published.write_bytes(b"approved output")

        with patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipe = recipes.run_recipe(self.root, self.config, self.style,
                                        asset_types, self.manifest,
                                        "sample_pack", instance_name="intl_dup")
        stage = recipe["recipe_instance"]["stages"]["terminal"]
        asset = self.manifest["assets"][stage["asset_key"]]

        asset["status"] = "ready"
        asset["generator"] = {"workflow": "old.json", "seed": 1}
        asset["candidates"]["selected"] = 1
        asset["outputs"] = {"model": path}
        asset["artifacts"] = {"output.model": {
            "id": "output.model", "type": "model.fbx", "status": "ready",
            "path": path, "sha256": file_sha256(published),
            "approval": {"status": "approved", "approved_at": "historical"},
        }}
        published_ref = {"id": "dup-exec:published:model", "type": "model.fbx",
                         "path": path, "sha256": file_sha256(published),
                         "stage": "final_publication", "attempt": 1,
                         "derived_from": []}
        asset["published_artifacts"] = [published_ref]
        # Duplicate stage records: one succeeded, one failed
        asset["executions"] = [{"id": "dup-exec", "status": "succeeded",
            "stages": [
                {"name": "final_publication", "attempt": 1,
                 "status": "succeeded",
                 "outputs": [published_ref], "inputs": [], "settings": {}},
                {"name": "final_publication", "attempt": 1,
                 "status": "failed",
                 "outputs": [], "inputs": [], "settings": {}},
            ]}]
        stage["status"] = "approved"

        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}),                 patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style,
                                  asset_types, self.manifest, "intl_dup")

        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_wrong_output_identity_in_recorded_stage_is_rejected(self):
        """A reference with correct execution/stage but wrong artifact
        output identity must reject with a reason distinct from 'execution/stage missing'."""
        self.definition["children"] = [{"id": "terminal", "type": "prop", "description": "Brass relay"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(yaml.safe_dump(self.definition))
        asset_types = {"concept": {"name": "concept", "pipeline": "image"},
                       "prop": {"name": "prop", "pipeline": "model"}}
        path = "Assets/Published/wrong.fbx"
        published = self.root / path
        published.parent.mkdir(parents=True, exist_ok=True)
        published.write_bytes(b"approved output")

        with patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipe = recipes.run_recipe(self.root, self.config, self.style,
                                        asset_types, self.manifest,
                                        "sample_pack", instance_name="intl_wrong")
        stage = recipe["recipe_instance"]["stages"]["terminal"]
        asset = self.manifest["assets"][stage["asset_key"]]

        asset["status"] = "ready"
        asset["generator"] = {"workflow": "old.json", "seed": 1}
        asset["candidates"]["selected"] = 1
        asset["outputs"] = {"model": path}
        asset["artifacts"] = {"output.model": {
            "id": "output.model", "type": "model.fbx", "status": "ready",
            "path": path, "sha256": file_sha256(published),
            "approval": {"status": "approved", "approved_at": "historical"},
        }}
        # Real succeeded final_publication record with a real publication output
        stage_output = {"id": "execution:published:correct", "type": "model.fbx",
                        "path": path, "sha256": file_sha256(published),
                        "stage": "final_publication", "attempt": 1,
                        "derived_from": []}
        # Published reference points to the correct execution/stage but
        # the artifact ID suffix is wrong — no matching output record
        asset["published_artifacts"] = [{"id": "execution:published:model",
            "type": "model.fbx", "path": path, "sha256": file_sha256(published),
            "stage": "final_publication", "attempt": 1, "derived_from": []}]
        asset["executions"] = [{"id": "execution", "status": "succeeded",
            "stages": [{"name": "final_publication", "attempt": 1,
                        "status": "succeeded",
                        "outputs": [stage_output],
                        "inputs": [], "settings": {}}]}]
        stage["status"] = "approved"

        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}),                 patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style,
                                  asset_types, self.manifest, "intl_wrong")

        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")

    def test_duplicate_output_id_in_same_publication_stage_is_rejected(self):
        """Two stage outputs with the same artifact ID but conflicting
        path/SHA-256 must be rejected as ambiguous provenance — the
        current code hides the conflicting duplicate because it also
        filters on type, path, sha256 before checking uniqueness."""
        self.definition["children"] = [{"id": "terminal", "type": "prop",
                                         "description": "Brass relay"}]
        (self.root / "ai/recipes/sample_pack.yaml").write_text(
            yaml.safe_dump(self.definition))
        asset_types = {"concept": {"name": "concept", "pipeline": "image"},
                       "prop": {"name": "prop", "pipeline": "model"}}
        path = "Assets/Published/dupid.fbx"
        published = self.root / path
        published.parent.mkdir(parents=True, exist_ok=True)
        published.write_bytes(b"approved output")

        with patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipe = recipes.run_recipe(self.root, self.config, self.style,
                                        asset_types, self.manifest,
                                        "sample_pack", instance_name="intl_dupid")
        stage = recipe["recipe_instance"]["stages"]["terminal"]
        asset = self.manifest["assets"][stage["asset_key"]]

        asset["status"] = "ready"
        asset["generator"] = {"workflow": "old.json", "seed": 1}
        asset["candidates"]["selected"] = 1
        asset["outputs"] = {"model": path}
        asset["artifacts"] = {"output.model": {
            "id": "output.model", "type": "model.fbx", "status": "ready",
            "path": path, "sha256": file_sha256(published),
            "approval": {"status": "approved", "approved_at": "historical"},
        }}

        # Two stage outputs with the SAME artifact ID
        matching_output = {"id": "dup-exec:published:model",
                           "type": "model.fbx",
                           "path": path,
                           "sha256": file_sha256(published),
                           "stage": "final_publication", "attempt": 1,
                           "derived_from": []}
        dup_output = {"id": "dup-exec:published:model",
                      "type": "model.fbx",
                      "path": "conflicting.glb",   # wrong path
                      "sha256": "0" * 64,           # wrong hash
                      "stage": "final_publication", "attempt": 1,
                      "derived_from": []}
        asset["published_artifacts"] = [matching_output]
        asset["executions"] = [{"id": "dup-exec", "status": "succeeded",
            "stages": [{"name": "final_publication", "attempt": 1,
                        "status": "succeeded",
                        "outputs": [matching_output, dup_output],
                        "inputs": [], "settings": {}}]}]
        stage["status"] = "approved"

        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": True, "reasons": []}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style,
                                  asset_types, self.manifest, "intl_dupid")

        # Must be rejected: duplicate output IDs create ambiguity
        self.assertEqual(asset["artifacts"]["output.model"]["status"], "superseded")


# ================================================================
# Finding 2 tests: publication lineage must match recorded parents/inputs
# ================================================================
class Finding2PublicationLineageTests(unittest.TestCase):
    """Regression tests for Finding 2: publication readiness must validate lineage."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "Assets").mkdir(parents=True)

    def make_fixture(self, parent_id=None):
        """Build a valid publication fixture. Use `parent_id` to override the parent."""
        path = self.root / "Assets/approved.fbx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"approved output")
        real_sha = hashlib.sha256(path.read_bytes()).hexdigest()

        stage_input = {
            "id": "candidate:1", "type": "surface.swatch",
            "path": "Assets/src.png", "sha256": "b" * 64,
            "stage": "concept_generation", "attempt": 1, "derived_from": []
        }

        candidate_output = {
            "id": stage_input["id"], "type": stage_input["type"],
            "path": stage_input["path"],
            "sha256": stage_input["sha256"],
            "stage": stage_input["stage"], "attempt": stage_input["attempt"],
            "derived_from": stage_input["derived_from"]}
        candidate_stage = {"name": "material_assembly_export", "attempt": 1,
                           "status": "succeeded", "inputs": [], "settings": {},
                           "outputs": [candidate_output]}
        source_exec = {"id": "source-exec:1", "status": "succeeded",
                       "parent_execution_id": None, "identity_inputs": {},
                       "stages": [candidate_stage]}

        # pub-exec-1 is a clean ID (no :published: in it)
        pub_exec = {"id": "pub-exec-1", "status": "succeeded",
                    "parent_execution_id": parent_id or "source-exec:1",
                    "identity_inputs": {},
                    "stages": [{"name": "final_publication", "attempt": 1,
                                "status": "succeeded", "inputs": [stage_input],
                                "settings": {}, "outputs": []}]}

        published_ref = {
            "id": "pub-exec-1:published:model",
            "type": "model.fbx",
            "path": "Assets/approved.fbx",
            "sha256": real_sha,
            "stage": "final_publication", "attempt": 1,
            "derived_from": [{"artifact_id": candidate_output["id"],
                              "sha256": candidate_output["sha256"]}]
        }

        pub_exec["stages"][0]["outputs"] = [published_ref]

        asset = {
            "status": "ready",
            "artifacts": {"output.model": {
                "id": "output.model", "type": "model.fbx", "status": "ready",
                "path": "Assets/approved.fbx", "sha256": real_sha,
                "approval": {"status": "approved", "approved_at": "now"}
            }},
            "outputs": {"model": "Assets/approved.fbx"},
            "published_artifacts": [published_ref],
            "executions": [source_exec, pub_exec]
        }
        return asset, source_exec, pub_exec, published_ref, stage_input


class Finding2LineageValidationTests(Finding2PublicationLineageTests):
    """Tests for _published_output_provenance and readiness validation."""

    # A. otherwise valid publication execution with wrong/unrelated parent_execution_id
    #     -> readiness rejected
    def test_malformed_dictionary_publication_output_sibling_invalidates_readiness(self):
        from slopforge.recipes import _ready_output_error
        asset, _, publication, _, _ = self.make_fixture()
        publication["stages"][0]["outputs"].append({"id": "malformed"})
        self.assertIsNotNone(_ready_output_error(self.root, asset))

    def test_wrong_parent_execution_id_invalidates_readiness(self):
        """A publication execution whose parent points to an unrelated source
        should invalidate readiness."""
        from slopforge.recipes import _ready_output_error
        asset, source_exec, pub_exec, _, _ = self.make_fixture(
            parent_id="unrelated-exec:999")

        # Also remove the real source so the parent is unresolvable
        asset["executions"] = [e for e in asset["executions"]
                               if e["id"] != "source-exec:1"]

        error = _ready_output_error(self.root, asset)
        self.assertIsNotNone(error)

    # B. otherwise valid publication output whose derived_from disagrees
    #     with the recorded publication inputs -> readiness rejected
    def test_derived_from_disagrees_with_stage_inputs_invalidates_readiness(self):
        """Published output derived_from that does not match the final_publication
        stage inputs should invalidate readiness."""
        from slopforge.recipes import _published_output_provenance
        asset, source_exec, pub_exec, published_ref, stage_input = \
            self.make_fixture()

        # Break the lineage: derived_from no longer matches stage inputs
        published_ref["derived_from"] = [
            {"artifact_id": "ghost-input", "sha256": "fake_sha"}]

        error = _published_output_provenance(published_ref, asset["executions"])
        self.assertIsNotNone(error)

    def test_malformed_same_name_publication_attempt_invalidates_readiness(self):
        from slopforge.recipes import _ready_output_error
        asset, _, publication, _, _ = self.make_fixture()
        publication["stages"].append({**publication["stages"][0], "attempt": "1"})

        self.assertIsNotNone(_ready_output_error(self.root, asset))

    # C. publication execution parent and output derivation disagree with each other
    #     -> readiness rejected
    def test_parent_and_derivation_disagree_invalidates_readiness(self):
        """If the publication execution's parent and the output's derived_from
        trace to different sources, the lineage is internally inconsistent."""
        from slopforge.recipes import _published_output_provenance, _ready_output_error
        asset, source_exec, pub_exec, published_ref, stage_input = \
            self.make_fixture()

        # Create a separate source and make everything point to different things
        other_exe = {"id": "other-source:1", "status": "succeeded",
                     "parent_execution_id": None, "identity_inputs": {},
                     "stages": []}
        other_input = {"id": "other:cand:1", "type": "surface.swatch",
                       "path": "Assets/other.png", "sha256": "other_sha",
                       "stage": "concept_generation", "attempt": 1, "derived_from": []}

        # Make parent point to another source
        pub_exec["parent_execution_id"] = other_exe["id"]
        # While stage inputs + derived_from point to source_exec
        # This is the inconsistency: parent and derivation disagree
        asset["executions"].append(other_exe)

        error = _published_output_provenance(published_ref, asset["executions"])
        self.assertIsNotNone(error,
            "expected lineage inconsistency error")

    # D. missing required lineage evidence -> reject conservatively
    def test_missing_source_execution_invalidates_readiness(self):
        """If the publication execution's parent_execution_id references a
        missing source execution, readiness must be rejected."""
        from slopforge.recipes import _ready_output_error
        asset, source_exec, pub_exec, _, _ = self.make_fixture()

        # Remove source from executions and reference a non-existent parent
        pub_exec["parent_execution_id"] = "absent-exec"
        asset["executions"] = [e for e in asset["executions"]
                               if e["id"] != "source-exec:1"]

        error = _ready_output_error(self.root, asset)
        self.assertIsNotNone(error)

    # E. valid publication lineage chain -> readiness remains valid
    def test_valid_publication_lineage_preserves_readiness(self):
        """A valid lineage chain should preserve readiness."""
        from slopforge.recipes import _ready_output_error
        asset, source_exec, pub_exec, published_ref, stage_input = \
            self.make_fixture()

        error = _ready_output_error(self.root, asset)
        # Valid lineage: error should be None and status stays "ready"
        self.assertIsNone(error)
        self.assertEqual(asset["status"], "ready")

    # D. empty final_publication.inputs must not bypass lineage validation
    def test_empty_publication_inputs_invalidates_readiness(self):
        """An empty final_publication.inputs list must invalidate readiness.

        The production code in approve_texture records candidate artifact
        references as final_publication stage inputs. If those inputs are
        removed (empty list), the lineage is broken even if outputs and
        derived_from otherwise look valid.

        This test starts from an otherwise valid publication fixture
        and removes the stage inputs, keeping the publication output
        and derived_from intact. It should reject because required
        publication input lineage is missing."""
        from slopforge.recipes import _published_output_provenance
        asset, source_exec, pub_exec, published_ref, stage_input = \
            self.make_fixture()

        # Remove stage inputs — leave everything else identical
        pub_stage = pub_exec["stages"][0]
        pub_stage["inputs"] = []

        error = _published_output_provenance(published_ref, asset["executions"])
        self.assertIsNotNone(
            error,
            "expected error for empty publication inputs bypassing lineage")

    # E. malformed parent execution stages=None must not raise TypeError
    def test_parent_exec_stages_none_invalidates_readiness(self):
        """A parent execution with stages=None must be rejected silently.

        This is a concrete malformed-provenance shape that can reach this
        function. The validator must not raise TypeError; it must return a
        conservative rejection.

        Test starts from an otherwise valid publication lineage fixture and
        changes ONLY the parent execution's stages field to None."""
        from slopforge.recipes import _published_output_provenance
        asset, source_exec, pub_exec, published_ref, stage_input = \
            self.make_fixture()

        # Make parent execution stages = None (the malformed shape)
        parent_id = pub_exec["parent_execution_id"]
        parent_exe = [e for e in asset["executions"]
                      if e["id"] == parent_id][0]
        parent_exe["stages"] = None

        # Must not raise and must reject
        error = _published_output_provenance(published_ref, asset["executions"])
        self.assertIsNotNone(
            error,
            "expected error for malformed parent stages=None")

    # F. adjacent: p_stage outputs=None must not raise TypeError
    def test_parent_stage_outputs_none_invalidates_readiness(self):
        """A stage in the parent execution with outputs=None must be rejected.

        Same class of bug as test_parent_exec_stages_none: the .get(key, [])
        pattern returns None when the key exists with value None, and iterating
        over None raises TypeError. Must fail closed."""
        from slopforge.recipes import _published_output_provenance
        asset, source_exec, pub_exec, published_ref, stage_input = \
            self.make_fixture()

        # Put a valid stage with outputs=None inside parent execution
        parent_id = pub_exec["parent_execution_id"]
        parent_exe = next(e for e in asset["executions"]
                          if e["id"] == parent_id)
        parent_exe["stages"] = [{"id": "orphan", "outputs": None}]

        # Must not raise and must reject
        error = _published_output_provenance(published_ref, asset["executions"])
        self.assertIsNotNone(
            error,
            "expected error for malformed parent stage outputs=None")

    # G. valid matching stage + malformed sibling stage must reject provenance
    def test_malformed_sibling_stage_malformed_outputs_none(self):
        """A parent execution containing one valid stage with required outputs
        and one sibling stage whose outputs = None must reject provenance.

        The validator currently skips the malformed stage and can still accept
        the publication provenance using the valid stage. This must fail
closed."""
        from slopforge.recipes import _published_output_provenance
        asset, source_exec, pub_exec, published_ref, stage_input = \
            self.make_fixture()

        # Build parent with TWO stages:
        # Stage A: valid, contains the parent artifact
        valid_stage = {
            "name": "concept_generation", "attempt": 1,
            "status": "succeeded", "inputs": [], "settings": {},
            "outputs": [{
                "id": "candidate:1", "type": "surface.swatch",
                "path": "Assets/src.png",
                "sha256": "src_sha256", "stage": "concept_generation",
                "attempt": 1, "derived_from": []
            }]
        }
        # Stage B: structurally parseable but outputs = None (malformed)
        malformed_stage = {
            "id": "orphan_stage", "name": "orphan",
            "status": "succeeded", "inputs": [], "settings": {},
            "outputs": None
        }
        parent_exe = next(e for e in asset["executions"]
                          if e["id"] == source_exec["id"])
        parent_exe["stages"] = [valid_stage, malformed_stage]

        # Must reject: malformed sibling provenance
        error = _published_output_provenance(published_ref, asset["executions"])
        self.assertIsNotNone(
            error,
            "expected rejection for valid stage + malformed sibling outputs=None")

    # H. malformed stage entry (non-dict) in parent stages must reject
    def test_malformed_sibling_stage_non_dict_entry(self):
        """A parent execution containing one valid dict stage and one
        non-dict malformed stage entry must reject provenance."""
        from slopforge.recipes import _published_output_provenance
        asset, source_exec, pub_exec, published_ref, stage_input = \
            self.make_fixture()

        # Build parent with a valid stage and a non-dict malformed entry
        valid_stage = {
            "name": "concept_generation", "attempt": 1,
            "status": "succeeded", "inputs": [], "settings": {},
            "outputs": [{
                "id": "candidate:1", "type": "surface.swatch",
                "path": "Assets/src.png",
                "sha256": "src_sha256", "stage": "concept_generation",
                "attempt": 1, "derived_from": []
            }]
        }
        parent_exe = next(e for e in asset["executions"]
                          if e["id"] == source_exec["id"])
        parent_exe["stages"] = [valid_stage, "corrupted_entry"]

        error = _published_output_provenance(published_ref, asset["executions"])
        self.assertIsNotNone(
            error,
            "expected rejection for valid dict stage + non-dict malformed entry")


# ================================================================
# Finding 1 — Publication malformed-member rejection
# ================================================================
class Finding1PublicationMalformedMemberTests(unittest.TestCase):
    """Regression tests for Finding 1: _published_output_provenance
    must reject malformed provenance lists (not silently filter them
    out). Each test constructs a fixture that would PASS if the bad
    member is skipped, to prove the specific anti-pattern is fixed."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Create a valid fixture that passes all checks:
        # - publication execution exists
        # - final_publication stage unique and succeeded
        # - stage output matches reference
        # - parent execution has required derived_from artifacts
        # - inputs match derived_from IDs
        self.ref = {"id": "pub-exec:published:model", "type": "model.fbx",
                    "path": "test.glb", "sha256": "a" * 64,
                    "stage": "final_publication", "attempt": 1,
                    "derived_from": [{"artifact_id": "mesh:1", "sha256": "b" * 64}]}
        self.source = {"id": "source-exec", "status": "succeeded",
                       "parent_execution_id": None, "identity_inputs": {},
                       "stages": [{"name": "mesh_preparation", "attempt": 1,
                                   "status": "succeeded",
                                   "outputs": [{"id": "mesh:1", "type": "mesh.prepared",
                                              "path": "s.glb", "sha256": "b" * 64,
                                              "stage": "mesh_preparation", "attempt": 1,
                                              "derived_from": []}],
                                   "inputs": [], "settings": {}}]}
        matching_output = {"id": "pub-exec:published:model", "type": "model.fbx",
                           "path": "test.glb", "sha256": "a" * 64,
                           "stage": "final_publication", "attempt": 1,
                           "derived_from": [{"artifact_id": "mesh:1",
                                              "sha256": "b" * 64}]}
        self.valid_stage = {"name": "final_publication", "attempt": 1,
                            "status": "succeeded",
                            "outputs": [matching_output],
                            "inputs": [{"id": "mesh:1", "sha256": "b" * 64}],
                            "settings": {}}

    # A. valid publication execution + None execution sibling
    def test_valid_publication_execution_with_none_execution_sibling_rejects(self):
        """An executions list containing a valid publication execution
        plus a None sibling member must reject provenance."""
        from slopforge.recipes import _published_output_provenance
        pub_exec = {"id": "pub-exec", "status": "succeeded",
                    "parent_execution_id": "source-exec", "identity_inputs": {},
                    "stages": [self.valid_stage]}
        # None is a malformed member in the authoritative executions list
        executions = [pub_exec, None, self.source]
        error = _published_output_provenance(self.ref, executions)
        self.assertIsNotNone(error,
            "expected rejection for None sibling in executions list")

    # B. valid final_publication stage + None stage sibling
    def test_valid_publication_stage_with_none_stage_sibling_rejects(self):
        """A publication execution containing one valid final_publication
        stage plus a None sibling stage must reject provenance."""
        from slopforge.recipes import _published_output_provenance
        pub_exec = {"id": "pub-exec", "status": "succeeded",
                    "parent_execution_id": "source-exec", "identity_inputs": {},
                    "stages": [self.valid_stage, None]}  # None is malformed
        executions = [pub_exec, self.source]
        error = _published_output_provenance(self.ref, executions)
        self.assertIsNotNone(error,
            "expected rejection for None sibling in publication stages")

    # C. valid publication output + None output sibling
    def test_valid_publication_output_with_none_output_sibling_rejects(self):
        """A final_publication stage whose outputs list contains a valid
        matching output plus a None sibling must reject provenance."""
        from slopforge.recipes import _published_output_provenance
        # Construct a stage with proper derived_from + None sibling
        bad_stage = {
            "name": "final_publication", "attempt": 1,
            "status": "succeeded",
            "outputs": [  # None is malformed sibling
                {"id": "pub-exec:published:model", "type": "model.fbx",
                 "path": "test.glb", "sha256": "a" * 64,
                 "stage": "final_publication", "attempt": 1,
                 "derived_from": [{"artifact_id": "mesh:1",
                                    "sha256": "b" * 64}]},
                None
            ],
            "inputs": [{"id": "mesh:1", "sha256": "b" * 64}],
            "settings": {}
        }
        pub_exec = {"id": "pub-exec", "status": "succeeded",
                    "parent_execution_id": "source-exec", "identity_inputs": {},
                    "stages": [bad_stage]}
        executions = [pub_exec, self.source]
        error = _published_output_provenance(self.ref, executions)
        self.assertIsNotNone(error,
            "expected rejection for None sibling in output list")

    # D. non-dict member in parent execution stages
    def test_non_dict_parent_stage_member_rejects_provenance(self):
        """A parent execution containing a non-dict stage entry alongside
        a valid one must reject provenance."""
        from slopforge.recipes import _published_output_provenance
        bad_parent = {"id": "source-exec", "status": "succeeded",
                      "parent_execution_id": None, "identity_inputs": {},
                      "stages": [self.source["stages"][0], "corrupted_entry"]}
        pub_exec = {"id": "pub-exec", "status": "succeeded",
                    "parent_execution_id": "source-exec", "identity_inputs": {},
                    "stages": [self.valid_stage]}
        executions = [pub_exec, bad_parent]
        error = _published_output_provenance(self.ref, executions)
        self.assertIsNotNone(error,
            "expected rejection for non-dict parent stage entry")

    def test_valid_publication_with_malformed_dictionary_output_sibling_rejects(self):
        from slopforge.recipes import _published_output_provenance
        stage = {**self.valid_stage,
                 "outputs": [self.valid_stage["outputs"][0], {"id": "malformed"}]}
        execution = {"id": "pub-exec", "status": "succeeded",
                     "parent_execution_id": "source-exec", "identity_inputs": {},
                     "stages": [stage]}
        self.assertIsNotNone(_published_output_provenance(self.ref, [execution, self.source]))

    def test_malformed_dictionary_stage_sibling_rejects(self):
        from slopforge.recipes import _published_output_provenance
        execution = {"id": "pub-exec", "status": "succeeded",
                     "parent_execution_id": "source-exec", "identity_inputs": {},
                     "stages": [self.valid_stage, {"name": "final_publication"}]}
        self.assertIsNotNone(_published_output_provenance(self.ref, [execution, self.source]))

    def test_malformed_dictionary_execution_sibling_rejects(self):
        from slopforge.recipes import _published_output_provenance
        execution = {"id": "pub-exec", "status": "succeeded",
                     "parent_execution_id": "source-exec", "identity_inputs": {},
                     "stages": [self.valid_stage]}
        self.assertIsNotNone(
            _published_output_provenance(self.ref, [execution, {"id": "malformed"}, self.source]))

    def test_unhashable_publication_output_id_rejects_without_exception(self):
        from slopforge.recipes import _published_output_provenance
        output = {**self.valid_stage["outputs"][0], "id": []}
        stage = {**self.valid_stage, "outputs": [output]}
        execution = {"id": "pub-exec", "status": "succeeded",
                     "parent_execution_id": "source-exec", "identity_inputs": {},
                     "stages": [stage]}
        self.assertIsNotNone(_published_output_provenance(self.ref, [execution, self.source]))

    def test_unhashable_publication_lineage_hash_rejects_without_exception(self):
        from slopforge.recipes import _published_output_provenance
        output = {**self.valid_stage["outputs"][0],
                  "derived_from": [{"artifact_id": "mesh:1", "sha256": []}]}
        stage = {**self.valid_stage, "outputs": [output]}
        execution = {"id": "pub-exec", "status": "succeeded",
                     "parent_execution_id": "source-exec", "identity_inputs": {},
                     "stages": [stage]}
        self.assertIsNotNone(_published_output_provenance(self.ref, [execution, self.source]))


class RemainingPublicationMalformedParentOutputTest(unittest.TestCase):
    def test_malformed_parent_output_invalidates_ready_approval(self):
        from slopforge.recipes import _ready_output_error

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            published_path = root / "approved.fbx"
            published_path.write_bytes(b"approved")
            published_sha = hashlib.sha256(published_path.read_bytes()).hexdigest()
            source_sha = "b" * 64
            source_artifact = {
                "id": "mesh:1", "type": "mesh.prepared", "path": "source.blend",
                "sha256": source_sha, "stage": "mesh_preparation", "attempt": 1,
                "derived_from": [],
            }
            reference = {
                "id": "publication:1:published:model", "type": "model.fbx",
                "path": "approved.fbx", "sha256": published_sha,
                "stage": "final_publication", "attempt": 1,
                "derived_from": [{"artifact_id": "mesh:1", "sha256": source_sha}],
            }
            publication_stage = {
                "name": "final_publication", "attempt": 1, "status": "succeeded",
                "inputs": [{"id": "mesh:1", "sha256": source_sha}], "settings": {},
                "outputs": [reference],
            }
            publication = {
                "id": "publication:1", "status": "succeeded",
                "parent_execution_id": "source:1", "stages": [publication_stage],
            }
            source = {
                "id": "source:1", "status": "succeeded", "stages": [{
                    "name": "mesh_preparation", "attempt": 1, "status": "succeeded",
                    "outputs": [source_artifact, None],
                }],
            }
            asset = {
                "outputs": {"model": "approved.fbx"},
                "published_artifacts": [reference],
                "executions": [publication, source],
                "artifacts": {"output.model": {
                    "id": "output.model", "status": "ready", "path": "approved.fbx",
                    "sha256": published_sha,
                    "approval": {"status": "approved"},
                }},
            }

            self.assertIsNotNone(_ready_output_error(root, asset))


if __name__ == "__main__":
    unittest.main()
