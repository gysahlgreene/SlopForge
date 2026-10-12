import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from slopforge import recipes
from slopforge.manifest import load_manifest, new_record, save_manifest


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
        stage["status"] = "approved"

        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": False, "reasons": ["brief changed"]}), \
                patch.dict(recipes.PIPELINE_HANDLERS,
                           {"model": lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("replacement failed"))}):
            result = recipes.resume_recipe(self.root, self.config, self.style, asset_types, self.manifest, "demo")

        self.assertEqual(stage["status"], "stale")
        self.assertEqual(asset["status"], "stale")
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
        stage["status"] = "approved"

        with patch("slopforge.recipes.model.prop_child_reuse_decision",
                   return_value={"reusable": False, "reasons": ["brief changed"]}), \
                patch.dict(recipes.PIPELINE_HANDLERS, {"model": self.fake_pipeline}):
            recipes.resume_recipe(self.root, self.config, self.style, asset_types, self.manifest, "demo")

        self.assertEqual(stage["status"], "completed")
        self.assertNotEqual(asset["status"], "ready")

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


if __name__ == "__main__":
    unittest.main()
