import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from slopforge.cli import main
from slopforge.initializer import init_project
from slopforge.manifest import load_manifest


_OPTED_IN = os.environ.get("SLOPFORGE_RUN_H100") == "1" and bool(os.environ.get("COMFYUI_URL"))


@unittest.skipUnless(_OPTED_IN, "set SLOPFORGE_RUN_H100=1 and COMFYUI_URL for live recipe integration")
class RecipeH100IntegrationTests(unittest.TestCase):
    def test_starter_recipe_generates_and_retrieves_remote_image_candidates(self):
        with tempfile.TemporaryDirectory(prefix="slopforge-recipe-h100-") as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)

            with contextlib.redirect_stdout(io.StringIO()):
                result = main(["--project", str(project), "recipe", "run", "starter_icons", "--name", "h100_smoke"])
            self.assertEqual(result, 0)

            manifest = load_manifest(project / "ai/assets/manifest.json")
            recipe = manifest["assets"]["recipe:h100_smoke"]
            self.assertEqual(recipe["status"], "awaiting_approval")
            self.assertEqual({stage["status"] for stage in recipe["recipe_instance"]["stages"].values()}, {"completed"})
            self.assertEqual(len(recipe["artifacts"]), 2)
            for child_id, stage in recipe["recipe_instance"]["stages"].items():
                child = manifest["assets"][stage["asset_key"]]
                candidate = child["candidates"]["items"][0]
                self.assertEqual(candidate["status"], "candidate")
                self.assertTrue((project / candidate["path"]).is_file(), child_id)
                self.assertIsNotNone(candidate.get("generator", {}).get("workflow"))


if __name__ == "__main__":
    unittest.main()
