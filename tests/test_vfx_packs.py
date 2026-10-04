import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from slopforge.initializer import init_project
from slopforge.cli import main
from slopforge.manifest import load_manifest, save_manifest
from slopforge.recipes import load_recipe
from slopforge.taxonomy import load_taxonomy


class VFXPackTests(unittest.TestCase):
    def test_vfx_recipe_composes_effect_sheets_and_impact_decal(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)
            types = load_taxonomy(project)
            definition, children = load_recipe(project, "starter_vfx_pack", types)

        self.assertEqual(definition["id"], "starter_vfx_pack")
        self.assertIn("fire", [child["id"] for child in children])
        self.assertIn("impact_decal", [child["id"] for child in children])
        self.assertTrue(all("style" in child["generation_prompt"].lower() for child in children))
        self.assertEqual({child["type"] for child in children}, {"vfx_sheet", "decal"})

    def test_approved_vfx_sheet_packages_frames_and_registers_optional_particle_prefab(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)
            source = project / "Assets/Art/Generated/VisualEffects/Spritesheets/fire.png"
            source.parent.mkdir(parents=True)
            image = Image.new("RGBA", (4, 2), (0, 0, 0, 0))
            image.putpixel((0, 0), (255, 20, 0, 255))
            image.putpixel((2, 0), (255, 180, 0, 255))
            image.save(source)
            manifest_path = project / "ai/assets/manifest.json"
            manifest = load_manifest(manifest_path)
            manifest["assets"]["vfx_sheet:fire"] = {
                "id": "fire-id", "type": "vfx_sheet", "name": "fire", "description": "Flame",
                "status": "ready", "candidates": {"selected": 1, "items": [{"number": 1, "approval": "approved"}]},
                "outputs": {"image": "Assets/Art/Generated/VisualEffects/Spritesheets/fire.png"},
                "artifacts": {}, "generator": {"workflow": "vfx.json", "seed": 27},
            }
            save_manifest(manifest_path, manifest)
            def make_unity(project_root, atlas, prefab, material, **kwargs):
                prefab.parent.mkdir(parents=True, exist_ok=True)
                prefab.write_text("prefab")
                material.write_text("material")
                self.assertEqual((kwargs["columns"], kwargs["rows"], kwargs["loop"]), (2, 1, False))
            with patch("slopforge.cli.create_particle_prefab", side_effect=make_unity):
                self.assertEqual(main(["--project", str(project), "spritepack", "fire", "--animation", "burst",
                                       "--grid", "2", "1", "--fps", "12", "--no-loop",
                                       "--particle-prefab"]), 0)
            asset = load_manifest(manifest_path)["assets"]["vfx_sheet:fire"]
            self.assertIn("vfx.burst.frame_000", asset["artifacts"])
            self.assertEqual(asset["artifacts"]["vfx.burst.prefab"]["type"], "unity.particle_prefab")
            self.assertEqual(asset["artifacts"]["vfx.burst.material"]["approval"]["status"], "approved")


if __name__ == "__main__":
    unittest.main()
