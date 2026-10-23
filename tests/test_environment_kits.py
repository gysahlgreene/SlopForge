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
        self.assertEqual(definition["kit_constraints"]["modules"]["wall"]["target_size"], [3, None, 3])

    def test_target_size_must_be_three_positive_sizes_or_null(self):
        from slopforge.recipes import _validate_kit_constraints
        for bad in ([3, 3], [None, None, None], [3, 0, 3], [3, "3", 3], [3, True, 3]):
            with self.subTest(target=bad), self.assertRaisesRegex(ValueError, "target_size"):
                _validate_kit_constraints({"kit_constraints": {"modules": {"wall": {"target_size": bad}}}}, {"wall"})
        _validate_kit_constraints({"kit_constraints": {"modules": {"wall": {"target_size": [3, None, 3]}}}}, {"wall"})

    def test_process_model_passes_module_target_size_to_blender(self):
        from unittest.mock import patch
        from slopforge.backends import blender
        with patch("slopforge.backends.blender.subprocess.run") as run, \
                patch("slopforge.backends.blender.blender_executable", return_value="blender"):
            blender.process_model("/tmp", {}, "in.glb", "out.fbx", "out.blend", [], 1000, target_size=[3, None, 3.5])
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--target-size") + 1], "3,-,3.5")

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

    def test_pivot_rules_include_top_center_and_reject_unknown(self):
        from slopforge.recipes import _validate_kit_constraints
        _validate_kit_constraints({"kit_constraints": {"pivot": "bottom_center",
                                                       "modules": {"floor": {"pivot": "top_center"}}}}, {"floor"})
        with self.assertRaisesRegex(ValueError, "pivot"):
            _validate_kit_constraints({"kit_constraints": {"modules": {"floor": {"pivot": "corner"}}}}, {"floor"})
        # 2026-10-23 audit: "origin" passed here, then Blender rejected it after the GPU had made the mesh.
        with self.assertRaisesRegex(ValueError, "pivot"):
            _validate_kit_constraints({"kit_constraints": {"modules": {"floor": {"pivot": "origin"}}}}, {"floor"})

    def test_layouts_place_model_children_on_quarter_turns(self):
        from slopforge.recipes import _validate_layouts
        children = [{"id": "floor", "type": "architecture"}, {"id": "wall", "type": "architecture"},
                    {"id": "stone", "type": "texture"}]
        types = {"architecture": {"pipeline": "model"}, "texture": {"pipeline": "image"}}
        good = {"layouts": {"courtyard": [{"module": "floor", "position": [1.5, -1.5]},
                                          {"module": "wall", "position": [0, 3, 0], "rotation": 90},
                                          {"module": "wall", "position": [3, 3], "rotation": "auto"}]}}
        _validate_layouts(good, children, types)
        for bad, message in (({"court": [{"module": "door", "position": [0, 0]}]}, "unknown module"),
                             ({"court": [{"module": "stone", "position": [0, 0]}]}, "3D module"),
                             ({"court": [{"module": "wall", "position": [0, 0], "rotation": 45}]}, "quarter turns"),
                             ({"court": [{"module": "wall", "position": [0]}]}, "position"),
                             ({"court": []}, "at least one")):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                _validate_layouts({"layouts": bad}, children, types)

    def test_process_model_passes_module_pivot_to_blender(self):
        from unittest.mock import patch
        from slopforge.backends import blender
        with tempfile.TemporaryDirectory() as temporary, \
                patch("slopforge.backends.blender.subprocess.run") as run, \
                patch("slopforge.backends.blender.blender_executable", return_value="blender"):
            report = Path(temporary) / "out.json"
            report.write_text("{}")
            blender.process_model("/tmp", {}, "in.glb", "out.fbx", "out.blend", [], 1000, pivot="bottom_center")
            blender.inspect_model("/tmp", {}, "out.blend", report, 1000, real_scale=True)
        process, inspect = (call.args[0] for call in run.call_args_list)
        self.assertEqual(process[process.index("--pivot") + 1], "bottom_center")
        self.assertIn("--real-scale", inspect)

    def test_run_recipe_gives_each_module_its_pivot_rule(self):
        from unittest.mock import patch
        from slopforge import recipes
        from slopforge.config import load_project
        from slopforge.style import load_style
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)
            (project / "ai/recipes/mini.yaml").write_text(json.dumps({
                "id": "mini", "version": 1, "description": "Two modules",
                "kit_constraints": {"pivot": "bottom_center", "modules": {
                    "floor": {"target_size": [3, 3, None], "pivot": "top_center"}, "wall": {"target_size": [3, None, 3]}}},
                "children": [{"id": "floor", "type": "architecture", "description": "A floor tile"},
                             {"id": "wall", "type": "architecture", "description": "A wall"}]}))
            config = load_project(project)
            manifest = load_manifest(project / "ai/assets/manifest.json")
            with patch("slopforge.recipes.model.generate", return_value=[{"number": 1, "status": "candidate"}]):
                recipes.run_recipe(project, config, load_style(project, config), load_taxonomy(project), manifest,
                                   "mini", instance_name="ruin")
        self.assertEqual(manifest["assets"]["architecture:ruin_floor"]["pivot"], "top_center")
        self.assertEqual(manifest["assets"]["architecture:ruin_wall"]["pivot"], "bottom_center")

    def test_kit_material_reaches_declared_modules_from_a_texture_child(self):
        from unittest.mock import patch
        from slopforge import recipes
        from slopforge.config import load_project
        from slopforge.style import load_style
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)
            definition = {"id": "mini", "version": 1, "description": "A wall, a crate and their stone",
                          "kit_constraints": {"material": {"source": "stone", "roughness": 0.75},
                                              "modules": {"wall": {"target_size": [3, None, 3]}}},
                          "children": [{"id": "stone", "type": "texture", "description": "Granite surface"},
                                       {"id": "wall", "type": "architecture", "description": "A wall"},
                                       {"id": "crate", "type": "prop", "description": "A crate"}]}
            recipe = project / "ai/recipes/mini.yaml"
            for bad in ({"source": "wall"}, {"source": "stone", "roughness": 1.5}):
                recipe.write_text(json.dumps({**definition, "kit_constraints": {
                    **definition["kit_constraints"], "material": bad}}))
                with self.subTest(material=bad), self.assertRaisesRegex(ValueError, "material"):
                    load_recipe(project, "mini", load_taxonomy(project))
            recipe.write_text(json.dumps(definition))
            config = load_project(project)
            manifest = load_manifest(project / "ai/assets/manifest.json")
            with patch("slopforge.recipes.model.generate", return_value=[{"number": 1, "status": "candidate"}]), \
                    patch("slopforge.recipes.image.generate", return_value=[{"number": 1, "status": "candidate"}]):
                recipes.run_recipe(project, config, load_style(project, config), load_taxonomy(project), manifest,
                                   "mini", instance_name="ruin")
        self.assertEqual(manifest["assets"]["architecture:ruin_wall"]["kit_material"],
                         {"asset_key": "texture:ruin_stone", "roughness": 0.75})
        self.assertNotIn("kit_material", manifest["assets"]["prop:ruin_crate"])  # not a declared module


    def test_corner_footprint_is_declared_copied_and_checked(self):
        from unittest.mock import patch
        from slopforge import recipes
        from slopforge.recipes import _validate_kit_constraints
        with self.assertRaisesRegex(ValueError, "footprint"):
            _validate_kit_constraints({"kit_constraints": {"modules": {"corner": {"footprint": "round"}}}}, {"corner"})
        recipe = {"name": "ruin", "recipe_instance": {"definition": {"kit_constraints": {
            "modules": {"corner": {"footprint": "corner"}}}},
            "stages": {"corner": {"asset_key": "architecture:corner", "asset_id": "corner-id"}}}}
        for quadrants, status in (([0.7, 0.9, 0.7, 0.0], "passed"), ([0.86] * 4, "failed")):
            manifest = {"assets": {"architecture:corner": {"type": "architecture", "status": "ready",
                "validation": {"measured": {"dimensions": [3.0, 3.0, 3.0], "bounds_min": [0, 0, 0],
                    "bounds_max": [3, 3, 3], "transforms_applied": True, "footprint_quadrants": quadrants}}}}}
            self.assertEqual(validate_environment_kit(recipe, manifest)["modules"]["corner"]["status"], status)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)
            from slopforge.config import load_project
            from slopforge.style import load_style
            config = load_project(project)
            manifest = load_manifest(project / "ai/assets/manifest.json")
            with patch("slopforge.recipes.model.generate", return_value=[{"number": 1, "status": "candidate"}]), \
                    patch("slopforge.recipes.image.generate", return_value=[{"number": 1, "status": "candidate"}]):
                recipes.run_recipe(project, config, load_style(project, config), load_taxonomy(project), manifest,
                                   "stone_ruin_kit", instance_name="ruin")
        self.assertEqual(manifest["assets"]["architecture:ruin_corner"]["footprint"], "corner")
        self.assertNotIn("footprint", manifest["assets"]["architecture:ruin_wall"])

    def test_corner_arm_thickness_is_declared_passed_on_and_checked(self):
        from unittest.mock import patch
        from slopforge.backends import blender
        from slopforge.recipes import _validate_kit_constraints
        for bad in ({"arm_thickness": 0.75}, {"footprint": "corner", "arm_thickness": 0},
                    {"footprint": "corner", "arm_thickness": 2.0, "target_size": [3, 3, 3]}):
            with self.subTest(rule=bad), self.assertRaisesRegex(ValueError, "arm_thickness"):
                _validate_kit_constraints({"kit_constraints": {"modules": {"corner": bad}}}, {"corner"})
        _validate_kit_constraints({"kit_constraints": {"modules": {"corner": {
            "footprint": "corner", "arm_thickness": 0.75, "target_size": [3, 3, 3]}}}}, {"corner"})
        with patch("slopforge.backends.blender.subprocess.run") as run, \
                patch("slopforge.backends.blender.blender_executable", return_value="blender"):
            blender.process_model("/tmp", {}, "in.glb", "out.fbx", "out.blend", [], 1000, arm_thickness=0.75)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--arm-thickness") + 1], "0.75")
        recipe = {"name": "ruin", "recipe_instance": {"definition": {"kit_constraints": {"snap_tolerance": 0.05,
            "modules": {"corner": {"footprint": "corner", "arm_thickness": 0.75}}}},
            "stages": {"corner": {"asset_key": "architecture:corner", "asset_id": "corner-id"}}}}
        for arms, status in (([0.76, 0.74], "passed"), ([1.0, 0.75], "failed")):
            manifest = {"assets": {"architecture:corner": {"type": "architecture", "status": "ready",
                "validation": {"measured": {"dimensions": [3.0, 3.0, 3.0], "bounds_min": [0, 0, 0],
                    "bounds_max": [3, 3, 3], "transforms_applied": True, "footprint_quadrants": [0.8, 0.9, 0.8, 0.0],
                    "arm_thickness": arms}}}}}
            self.assertEqual(validate_environment_kit(recipe, manifest)["modules"]["corner"]["status"], status)

    def test_max_stretch_is_declared_copied_and_checked(self):
        from unittest.mock import patch
        from slopforge import recipes
        from slopforge.recipes import _validate_kit_constraints
        for bad in ({"max_stretch": 0.9}, {"modules": {"wall": {"max_stretch": True}}}):
            with self.subTest(rule=bad), self.assertRaisesRegex(ValueError, "max_stretch"):
                _validate_kit_constraints({"kit_constraints": bad}, {"wall"})
        recipe = {"name": "ruin", "recipe_instance": {"definition": {"kit_constraints": {"max_stretch": 1.3,
            "modules": {"doorway": {}}}},
            "stages": {"doorway": {"asset_key": "architecture:doorway", "asset_id": "door-id"}}}}
        for stretch, status in ((1.12, "passed"), (1.45, "failed")):
            manifest = {"assets": {"architecture:doorway": {"type": "architecture", "status": "ready",
                "validation": {"measured": {"dimensions": [3.0, 0.75, 3.0], "bounds_min": [0, 0, 0],
                    "bounds_max": [3, 0.75, 3], "transforms_applied": True, "axis_stretch": stretch}}}}}
            self.assertEqual(validate_environment_kit(recipe, manifest)["modules"]["doorway"]["status"], status)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)
            from slopforge.config import load_project
            from slopforge.style import load_style
            config = load_project(project)
            manifest = load_manifest(project / "ai/assets/manifest.json")
            with patch("slopforge.recipes.model.generate", return_value=[{"number": 1, "status": "candidate"}]), \
                    patch("slopforge.recipes.image.generate", return_value=[{"number": 1, "status": "candidate"}]):
                recipes.run_recipe(project, config, load_style(project, config), load_taxonomy(project), manifest,
                                   "stone_ruin_kit", instance_name="ruin")
        self.assertEqual(manifest["assets"]["architecture:ruin_doorway"]["max_stretch"], 1.3)
        self.assertNotIn("max_stretch", manifest["assets"]["texture:ruin_stone"])

    def test_module_budgets_are_declared_applied_and_totalled(self):
        from slopforge.pipelines.model import _face_budget, _fit_texture_size
        from slopforge.recipes import _validate_kit_constraints
        from PIL import Image
        for bad in ({"face_budget": 0}, {"texture_size": 3000}, {"texture_size": 8192}):
            with self.subTest(rule=bad), self.assertRaisesRegex(ValueError, "face_budget|texture_size"):
                _validate_kit_constraints({"kit_constraints": {"modules": {"floor": bad}}}, {"floor"})
        pipeline = {"model_budgets": {"architecture_faces": 60000}}
        self.assertEqual(_face_budget(pipeline, {"face_budget": "architecture_faces"}, {}), 60000)
        self.assertEqual(_face_budget(pipeline, {"face_budget": "architecture_faces"}, {"face_budget": 8000}), 8000)
        with tempfile.TemporaryDirectory() as temporary:
            maps = {key: Path(temporary) / f"{key}.png" for key in ("basecolor", "normal", "roughness", "metallic")}
            for path in maps.values():
                Image.new("RGB", (64, 64), "grey").save(path)
            _fit_texture_size(maps, 32)
            self.assertEqual({Image.open(path).size for path in maps.values()}, {(32, 32)})
        recipe = {"name": "ruin", "recipe_instance": {"definition": {"kit_constraints": {"modules": {}}},
            "stages": {name: {"asset_key": f"architecture:{name}", "asset_id": name} for name in ("floor", "wall")}}}
        measured = lambda faces, size: {"dimensions": [3.0, 3.0, 0.2], "bounds_min": [0, 0, 0], "bounds_max": [3, 3, 0.2],
                                        "transforms_applied": True, "face_count": faces, "texture_size": [size, size]}
        manifest = {"assets": {
            "architecture:floor": {"type": "architecture", "status": "ready", "validation": {"measured": measured(8000, 1024)}},
            "architecture:wall": {"type": "architecture", "status": "ready", "validation": {"measured": measured(30000, 2048)}}}}
        report = validate_environment_kit(recipe, manifest)
        self.assertEqual(report["modules"]["floor"]["map_texels"], 4 * 1024 * 1024)
        self.assertEqual(report["budgets"], {"faces": 38000, "map_texels": 4 * (1024 ** 2 + 2048 ** 2)})

    def test_validation_checks_a_top_center_pivot(self):
        recipe = {"name": "court", "recipe_instance": {"definition": {"kit_constraints": {
            "grid_size": 1.0, "pivot_tolerance": 0.01, "modules": {"floor": {"pivot": "top_center"}}}},
            "stages": {"floor": {"asset_key": "architecture:floor", "asset_id": "floor-id"}}}}
        bounds = {"bounds_min": [-1.5, -1.5, -0.2], "bounds_max": [1.5, 1.5, 0.0]}
        measured = {"dimensions": [3.0, 3.0, 0.2], **bounds, "transforms_applied": True}
        for origin, status in (([0.0, 0.0, 0.0], "passed"), ([0.0, 0.0, -0.1], "failed")):
            objects = [{"name": "floor", **bounds, "origin": origin}]
            manifest = {"assets": {"architecture:floor": {"type": "architecture", "status": "ready",
                "outputs": {"blend": "floor.blend"}, "validation": {"measured": {**measured, "objects": objects}}}}}
            self.assertEqual(validate_environment_kit(recipe, manifest)["modules"]["floor"]["status"], status)

    def _scene_kit(self, wall_status="ready"):
        recipe = {"name": "ruin", "recipe_instance": {
            "definition": {"kit_constraints": {"grid_size": 1.0, "snap_tolerance": 0.05, "pivot": "bottom_center",
                                               "modules": {"floor": {"pivot": "top_center"}}},
                           "layouts": {"court": [{"module": "floor", "position": [0, 0]},
                                                 {"module": "wall", "position": [0, 1.5], "rotation": 90},
                                                 {"module": "wall", "position": [3, 0, 1.5], "rotation": "auto"}]}},
            "stages": {"floor": {"asset_key": "architecture:ruin_floor"}, "wall": {"asset_key": "architecture:ruin_wall"}}}}
        fbx = lambda name: {"unity_import": {"assets": {"fbx": {"path": f"Assets/Art/{name}.fbx"}}}}
        manifest = {"assets": {"architecture:ruin_floor": {"status": "ready", "pivot": "top_center", **fbx("floor")},
                               "architecture:ruin_wall": {"status": wall_status, "pivot": "bottom_center", **fbx("wall")}}}
        return recipe, manifest

    def test_scene_placements_resolve_published_modules_on_unity_axes(self):
        from slopforge.environment import scene_placements
        recipe, manifest = self._scene_kit()
        placements = scene_placements(recipe, manifest, "court")
        self.assertEqual(placements[0], {"module": "floor", "fbx": "Assets/Art/floor.fbx", "pivot": "top_center",
                                         "x": 0.0, "y": 0.0, "z": 0.0, "rotation": "0"})
        self.assertEqual([(item["x"], item["y"], item["z"], item["rotation"]) for item in placements[1:]],
                         [(0.0, 0.0, 1.5, "90"), (3.0, 0.0, 1.5, "auto")])
        with self.assertRaisesRegex(ValueError, "no layout"):
            scene_placements(recipe, manifest, "hall")
        recipe, manifest = self._scene_kit(wall_status="awaiting_texture_approval")
        with self.assertRaisesRegex(ValueError, "wall.*approve-texture"):
            scene_placements(recipe, manifest, "court")

    def test_cli_builds_the_scene_and_records_its_report(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "game"
            (project / "Assets").mkdir(parents=True)
            init_project(project)
            path = project / "ai/assets/manifest.json"
            manifest = load_manifest(path)
            recipe, kit = self._scene_kit()
            manifest["assets"]["recipe:ruin"] = {"id": "kit-id", "name": "ruin", "type": "recipe", "status": "partial",
                                                 "artifacts": {}, "outputs": {}, **recipe}
            for key, asset in kit["assets"].items():
                manifest["assets"][key] = {"id": key, "type": "architecture", "name": key.split(":")[1], **asset}
            save_manifest(path, manifest)
            calls = []

            def build(root, kit_name, layout, placements, **options):
                calls.append((kit_name, layout, len(placements), options["grid"], options["tolerance"],
                              options["output_root"]))  # the project's, not a hard-coded folder
                return {"scene": "Assets/Art/Generated/Scenes/ruin_court.unity", "render": options["render"],
                        "errors": ["wall 1 seam gap 0.2 m"], "instances": [], "seams": []}
            with patch("slopforge.unity_scene.build_kit_scene", side_effect=build):
                self.assertEqual(main(["--project", str(project), "environment-scene", "ruin", "court"]), 1)
            self.assertEqual(calls, [("ruin", "court", 3, 1.0, 0.05, "Assets/Art/Generated")])
            report = json.loads((project / "ai/assets/environment_scenes/ruin_court.json").read_text())
            self.assertEqual(report["errors"], ["wall 1 seam gap 0.2 m"])
            artifact = load_manifest(path)["assets"]["recipe:ruin"]["artifacts"]["kit.scene.court"]
            self.assertEqual(artifact["status"], "failed")


if __name__ == "__main__":
    unittest.main()
