import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopforge.cli import main, parse_args
from slopforge.initializer import init_project
from slopforge.manifest import load_manifest, save_manifest
from slopforge import recipes


class RecipeCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "game"
        (self.root / "Assets").mkdir(parents=True)
        init_project(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_recipe_subcommands_parse_with_project_selection(self):
        run = parse_args(["--project", str(self.root), "recipe", "run", "starter_icons", "--name", "hud"])
        resume = parse_args(["--project", str(self.root), "recipe", "resume", "hud"])
        regenerate = parse_args(["--project", str(self.root), "recipe", "regenerate", "hud", "health"])

        self.assertEqual((run.command, run.recipe_action, run.recipe_name, run.name),
                         ("recipe", "run", "starter_icons", "hud"))
        self.assertEqual((resume.recipe_action, resume.name), ("resume", "hud"))
        self.assertEqual((regenerate.recipe_action, regenerate.name, regenerate.child_id),
                         ("regenerate", "hud", "health"))

    def test_recipe_list_and_run_use_project_data_and_persist_manifest(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--project", str(self.root), "recipe", "list"]), 0)
        self.assertIn("starter_icons", output.getvalue())

        def fake_pipeline(root, config, style, asset_type, child, manifest, key):
            candidate = {"number": 1, "path": f"ai/assets/candidates/{child['type']}/{manifest['assets'][key]['name']}/candidate_01.png",
                         "status": "candidate", "seed": 52,
                         "generator": {"workflow": "image.json", "seed": 52},
                         "validation": {"status": "passed", "errors": [], "warnings": []}}
            manifest["assets"][key]["candidates"]["items"].append(candidate)
            manifest["assets"][key]["status"] = "candidate"
            return [candidate]

        with patch.dict(recipes.PIPELINE_HANDLERS, {"image": fake_pipeline}), contextlib.redirect_stdout(io.StringIO()):
            result = main(["--project", str(self.root), "recipe", "run", "starter_icons", "--name", "hud"])

        self.assertEqual(result, 0)
        manifest = load_manifest(self.root / "ai/assets/manifest.json")
        recipe = manifest["assets"]["recipe:hud"]
        self.assertEqual(recipe["status"], "awaiting_approval")
        self.assertEqual(len(recipe["artifacts"]), 2)
        self.assertIn("icon:hud_mana", manifest["assets"])
        self.assertEqual(manifest["assets"]["icon:hud_health"]["parent_id"], recipe["id"])

    def test_recipe_resume_refreshes_aggregate_after_atomic_child_approval(self):
        def fake_pipeline(root, config, style, asset_type, child, manifest, key):
            name = manifest["assets"][key]["name"]
            candidate = {"number": 1, "path": f"ai/assets/candidates/{asset_type['name']}/{name}/candidate_01.png",
                         "status": "candidate", "seed": 4,
                         "generator": {"workflow": "image.json", "seed": 4},
                         "validation": {"status": "passed", "errors": [], "warnings": []}}
            manifest["assets"][key]["candidates"]["items"].append(candidate)
            manifest["assets"][key]["status"] = "candidate"
            return [candidate]

        with patch.dict(recipes.PIPELINE_HANDLERS, {"image": fake_pipeline}), contextlib.redirect_stdout(io.StringIO()):
            main(["--project", str(self.root), "recipe", "run", "starter_icons", "--name", "hud"])

        manifest_path = self.root / "ai/assets/manifest.json"
        manifest = load_manifest(manifest_path)
        health = manifest["assets"]["icon:hud_health"]
        health["status"] = "ready"
        health["candidates"]["items"][0]["approval"] = "approved"
        health["outputs"]["image"] = "Assets/Art/Generated/Icons/approved.png"
        approved_output = self.root / health["outputs"]["image"]
        approved_output.parent.mkdir(parents=True, exist_ok=True)
        approved_output.write_bytes(b"approved")
        save_manifest(manifest_path, manifest)

        with contextlib.redirect_stdout(io.StringIO()):
            result = main(["--project", str(self.root), "recipe", "resume", "hud"])

        self.assertEqual(result, 0)
        recipe = load_manifest(manifest_path)["assets"]["recipe:hud"]
        self.assertEqual(recipe["recipe_instance"]["stages"]["health"]["status"], "approved")
        self.assertEqual(recipe["artifacts"]["health.candidate.1"]["approval"]["status"], "approved")
        self.assertEqual(recipe["artifacts"]["health.output.image"]["type"], "image.icon")


if __name__ == "__main__":
    unittest.main()
