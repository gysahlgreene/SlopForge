import unittest
import json
import tempfile
from pathlib import Path

from slopforge.cli import main
from slopforge.environment import validate_environment_kit
from slopforge.initializer import init_project
from slopforge.manifest import load_manifest, save_manifest
from slopforge.recipes import load_recipe
from slopforge.taxonomy import load_taxonomy


class EnvironmentKitTests(unittest.TestCase):
    def test_starter_environment_recipe_loads_all_asset_types_and_constraints(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)
            definition, children = load_recipe(project, "starter_environment_kit", load_taxonomy(project))
        self.assertEqual(definition["kit_constraints"]["grid_size"], 1.0)
        self.assertIn("architecture", {child["type"] for child in children})
        self.assertIn("prop", {child["type"] for child in children})
        self.assertIn("texture", {child["type"] for child in children})
        self.assertIn("decal", {child["type"] for child in children})

    def test_validation_checks_grid_bounds_pivots_and_pending_children(self):
        recipe = {
            "name": "station",
            "recipe_instance": {
                "definition": {"kit_constraints": {
                    "grid_size": 1.0, "snap_tolerance": 0.05, "pivot_tolerance": 0.05,
                    "max_dimension": 5.0,
                    "modules": {"wall": {"snap_axes": [0, 2], "pivot": "center"}},
                }},
                "stages": {"wall": {"asset_key": "architecture:station_wall", "asset_id": "wall-id"},
                           "door": {"asset_key": "prop:station_door", "asset_id": "door-id"},
                           "material": {"asset_key": "texture:station_steel", "asset_id": "steel-id"}},
            },
        }
        manifest = {"assets": {
            "architecture:station_wall": {"type": "architecture", "status": "ready", "outputs": {"blend": "wall.blend"},
                "validation": {"measured": {"dimensions": [2.0, 0.25, 3.0], "bounds_min": [-1.0, -0.125, -1.5],
                    "bounds_max": [1.0, 0.125, 1.5], "origins": [[0.0, 0.0, 0.0]], "transforms_applied": True}}},
            "prop:station_door": {"type": "prop", "status": "planned"},
            "texture:station_steel": {"type": "texture", "status": "ready"},
        }}
        report = validate_environment_kit(recipe, manifest)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["modules"]["wall"]["status"], "passed")
        self.assertEqual(report["modules"]["door"]["status"], "pending")
        self.assertEqual(report["modules"]["material"]["status"], "not_applicable")

    def test_validation_reports_grid_and_transform_failures(self):
        recipe = {"name": "room", "recipe_instance": {"definition": {"kit_constraints": {
            "grid_size": 1.0, "snap_tolerance": 0.01,
            "modules": {"wall": {"snap_axes": [0], "vertical_axis": 0}}}},
            "stages": {"wall": {"asset_key": "architecture:wall", "asset_id": "wall-id"}}}}
        manifest = {"assets": {"architecture:wall": {"type": "architecture", "status": "ready",
            "outputs": {"blend": "wall.blend"}, "validation": {"measured": {
                "dimensions": [1.4, 0.2, 2.0], "bounds_min": [0, 0, 0], "bounds_max": [1.4, 0.2, 2.0],
                "origins": [[3, 0, 0]], "transforms_applied": False}}}}}
        report = validate_environment_kit(recipe, manifest)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["modules"]["wall"]["status"], "failed")
        self.assertTrue(report["modules"]["wall"]["errors"])
        self.assertTrue(any("vertical" in error for error in report["modules"]["wall"]["errors"]))

    def test_cli_saves_partial_check_and_provenance_without_approving_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)
            path = project / "ai/assets/manifest.json"
            manifest = load_manifest(path)
            manifest["assets"]["recipe:starter"] = {
                "id": "kit-id", "name": "starter", "type": "recipe", "status": "partial",
                "recipe_instance": {"definition": {"kit_constraints": {"grid_size": 1.0}},
                                    "stages": {"wall": {"asset_key": "architecture:wall", "asset_id": "wall-id"}}},
                "artifacts": {}, "outputs": {},
            }
            manifest["assets"]["architecture:wall"] = {"id": "wall-id", "type": "architecture", "name": "wall", "status": "planned"}
            save_manifest(path, manifest)
            self.assertEqual(main(["--project", str(project), "environment-check", "starter"]), 1)
            manifest = load_manifest(path)
            report = json.loads((project / "ai/assets/environment_checks/starter.json").read_text())
            self.assertEqual(report["status"], "partial")
            self.assertEqual(manifest["assets"]["recipe:starter"]["artifacts"]["kit.validation"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
