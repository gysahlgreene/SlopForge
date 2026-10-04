import tempfile
import unittest
import io
import contextlib
from pathlib import Path
from unittest.mock import patch

import yaml

from slopforge import prototypes
from slopforge.config import load_project
from slopforge.cli import main
from slopforge.initializer import init_project
from slopforge.manifest import new_record
from slopforge.taxonomy import load_taxonomy


class PrototypePlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "game"
        (self.root / "Assets").mkdir(parents=True)
        init_project(self.root)
        (self.root / "ai/recipes/sample.yaml").write_text(yaml.safe_dump({
            "id": "sample", "version": 1, "description": "A sample pack",
            "children": [{"id": "badge", "type": "icon", "description": "A sample badge"}],
        }))
        self.config = load_project(self.root)
        self.types = load_taxonomy(self.root)
        self.style = {"name": "default", "version": 1}
        self.manifest = {"assets": {}}

    def tearDown(self):
        self.temp.cleanup()

    def test_proposal_is_editable_and_generation_requires_approval(self):
        plan = prototypes.propose(self.root, "demo", "A tiny sci-fi game", self.style, self.types, self.config,
                                  recipe_names=["sample"], candidate_budget=5)
        self.assertEqual(plan["approval"]["status"], "proposed")
        self.assertEqual(plan["content_plan"][0]["description"], "A sample badge")
        with self.assertRaisesRegex(ValueError, "explicitly approved"):
            prototypes.run(self.root, self.config, self.style, self.types, self.manifest, "demo")
        self.assertEqual(self.manifest["assets"], {})

    def test_cli_propose_and_approve_are_local_and_do_not_generate(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--project", str(self.root), "prototype", "propose", "demo",
                                  "A tiny sci-fi game", "--recipe", "sample"]), 0)
            self.assertEqual(main(["--project", str(self.root), "prototype", "approve", "demo"]), 0)
        self.assertIn("1 estimated candidate(s)", output.getvalue())
        self.assertEqual(yaml.safe_load(prototypes.plan_path(self.root, "demo").read_text())
                         ["approval"]["status"], "approved")

    def test_edited_plan_must_be_reapproved_and_can_then_run_to_review_gate(self):
        prototypes.propose(self.root, "demo", "A tiny sci-fi game", self.style, self.types, self.config,
                           recipe_names=["sample"], candidate_budget=5)
        prototypes.approve(self.root, "demo")
        path = prototypes.plan_path(self.root, "demo")
        plan = yaml.safe_load(path.read_text())
        plan["art_direction"]["brief"] = "A dark tiny sci-fi game"
        path.write_text(yaml.safe_dump(plan, sort_keys=False))
        with self.assertRaisesRegex(ValueError, "changed after approval"):
            prototypes.run(self.root, self.config, self.style, self.types, self.manifest, "demo")
        prototypes.approve(self.root, "demo")

        def fake_run(root, config, style, types, manifest, recipe_name, *, instance_name, quality_tier, save):
            record = new_record("recipe", instance_name, "sample", style, {"strategy": "text_only"})
            record["status"] = "awaiting_approval"
            record["recipe_instance"] = {"quality_tier": quality_tier, "stages": {}}
            manifest["assets"][f"recipe:{instance_name}"] = record
            child = new_record("icon", f"{instance_name}_badge", "A badge", style, {"strategy": "text_only"})
            child["parent_id"] = record["id"]
            child["candidates"]["items"].append({"number": 1, "status": "candidate"})
            manifest["assets"][f"icon:{child['name']}"] = child
            return record

        with patch("slopforge.prototypes.recipes.run_recipe", side_effect=fake_run):
            result = prototypes.run(self.root, self.config, self.style, self.types, self.manifest, "demo")
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertEqual(result["prototype"]["stages"]["sample"]["status"], "awaiting_approval")
        recipe = self.manifest["assets"]["recipe:demo_sample"]
        self.assertEqual(recipe["parent_id"], result["id"])
        self.assertEqual(result["prototype"]["candidate_count"], 1)

    def test_stage_dependencies_reject_cycles(self):
        prototypes.propose(self.root, "demo", "A tiny sci-fi game", self.style, self.types, self.config,
                           recipe_names=["sample"])
        path = prototypes.plan_path(self.root, "demo")
        plan = yaml.safe_load(path.read_text())
        plan["stages"][0]["depends_on"] = ["sample"]
        path.write_text(yaml.safe_dump(plan, sort_keys=False))
        with self.assertRaisesRegex(ValueError, "cycle"):
            prototypes.load_plan(self.root, "demo")

    def test_candidate_budget_blocks_an_over_budget_stage_before_generation(self):
        definition = yaml.safe_load((self.root / "ai/recipes/sample.yaml").read_text())
        definition["children"][0]["count"] = 2
        (self.root / "ai/recipes/sample.yaml").write_text(yaml.safe_dump(definition))
        prototypes.propose(self.root, "demo", "A tiny sci-fi game", self.style, self.types, self.config,
                           recipe_names=["sample"], candidate_budget=1)
        prototypes.approve(self.root, "demo")
        with patch("slopforge.prototypes.recipes.run_recipe") as run_recipe:
            result = prototypes.run(self.root, self.config, self.style, self.types, self.manifest, "demo")
        run_recipe.assert_not_called()
        stage = result["prototype"]["stages"]["sample"]
        self.assertEqual(result["status"], "partial")
        self.assertIn("exceeds remaining candidate budget", stage["errors"][0])

    def test_resume_opens_downstream_stage_only_after_prior_pack_is_approved(self):
        second = {"id": "sample_two", "version": 1, "description": "A second pack",
                  "children": [{"id": "badge", "type": "icon", "description": "Another badge"}]}
        (self.root / "ai/recipes/sample_two.yaml").write_text(yaml.safe_dump(second))
        prototypes.propose(self.root, "demo", "A tiny sci-fi game", self.style, self.types, self.config,
                           recipe_names=["sample", "sample_two"])
        prototypes.approve(self.root, "demo")
        calls = []

        def fake_run(root, config, style, types, manifest, recipe_name, *, instance_name, quality_tier, save):
            calls.append(recipe_name)
            record = new_record("recipe", instance_name, recipe_name, style, {"strategy": "text_only"})
            record["status"] = "awaiting_approval"
            record["recipe_instance"] = {"quality_tier": quality_tier, "stages": {}}
            manifest["assets"][f"recipe:{instance_name}"] = record
            return record

        with patch("slopforge.prototypes.recipes.run_recipe", side_effect=fake_run):
            first = prototypes.run(self.root, self.config, self.style, self.types, self.manifest, "demo")
        self.assertEqual(calls, ["sample"])
        self.assertEqual(first["status"], "awaiting_approval")
        self.assertEqual(first["prototype"]["stages"]["sample_two"]["status"], "blocked")

        def approve_prior(root, config, style, types, manifest, instance_name, *, save):
            record = manifest["assets"][f"recipe:{instance_name}"]
            record["status"] = "ready"
            return record

        with (patch("slopforge.prototypes.recipes.resume_recipe", side_effect=approve_prior),
              patch("slopforge.prototypes.recipes.run_recipe", side_effect=fake_run)):
            resumed = prototypes.run(self.root, self.config, self.style, self.types, self.manifest, "demo")
        self.assertEqual(calls, ["sample", "sample_two"])
        self.assertEqual(resumed["prototype"]["stages"]["sample"]["status"], "approved")
        self.assertEqual(resumed["prototype"]["stages"]["sample_two"]["status"], "awaiting_approval")
        downstream = self.manifest["assets"]["recipe:demo_sample_two"]
        prior = self.manifest["assets"]["recipe:demo_sample"]
        self.assertEqual(downstream["parent_id"], resumed["id"])
        self.assertEqual(downstream["dependencies"], [{"asset_id": prior["id"]}])


if __name__ == "__main__":
    unittest.main()
