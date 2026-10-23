import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import yaml
from PIL import Image

from slopforge import scene as planner

ROOT = Path(__file__).resolve().parents[1]
RECIPE = yaml.safe_load((ROOT / "templates/recipes/moorland_ruin.yaml").read_text())


def _scene():
    scene = copy.deepcopy(RECIPE["scene"])
    scene["terrain"]["size"], scene["terrain"]["dressed"] = 200, 100  # smaller, for speed
    return scene


class ScenePlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = _scene()
        cls.terrain = planner.Terrain(cls.scene, resolution=513)
        cls.weights = planner.layer_weights(cls.scene, cls.terrain, size=256)

    def test_terrain_rises_at_hills_and_levels_and_sinks_at_the_structure(self):
        t = self.terrain
        self.assertTrue(0 <= t.heights.min() and t.heights.max() <= 1)
        self.assertGreater(t.ground(62, 70), t.ground(10, 10) + 2)  # the knoll
        chapel = self.scene["structures"][0]
        sx, sz = chapel["at"]
        floor_y = chapel["_plateau"] * t.height
        self.assertAlmostEqual(float(t.ground(sx + 7.5, sz)), floor_y, delta=0.05)  # level ground, outside the tiles
        self.assertAlmostEqual(float(t.ground(sx, sz)), floor_y - 0.3, delta=0.05)  # sunk under a floor tile

    def test_layers_share_each_texel_and_follow_their_rules(self):
        self.assertTrue(np.allclose(self.weights.sum(-1), 1, atol=1e-6))
        t, size = self.terrain, self.weights.shape[0]
        index = lambda x, z: (int(round((z + t.offset) / t.size * (size - 1))), int(round((x + t.offset) / t.size * (size - 1))))
        on_path = index(float(t.path_x(30)), 30)
        self.assertGreater(self.weights[on_path][2], 0.8)  # gravel down the path
        slope = t.slope_degrees(size)
        steep = np.unravel_index(np.argmax(slope), slope.shape)
        self.assertGreater(self.weights[steep][3], 0.5)  # granite on the steepest ground

    def test_scatter_keeps_its_rules_and_is_repeatable(self):
        first = planner.scatter(self.scene, self.terrain, np.random.default_rng(1))
        again = planner.scatter(self.scene, self.terrain, np.random.default_rng(1))
        self.assertEqual(first, again)
        path = planner.camera_path_samples(self.scene)
        self.assertIn((70.0, 52.0), {tuple(map(float, row)) for row in path})  # the tor still's camera
        chapel = self.scene["structures"][0]
        for item in first:
            x, z = item["x"] - self.terrain.offset, item["z"] - self.terrain.offset
            self.assertGreaterEqual(np.hypot(x - chapel["at"][0], z - chapel["at"][1]), chapel["clear"])
            self.assertGreaterEqual(np.min(np.hypot(path[:, 0] - x, path[:, 1] - z)), 4.5)
            if item["asset"].startswith("shrub"):
                self.assertGreaterEqual(float(self.terrain.path_distance(x, z)), 2.5)
        self.assertLessEqual(len([i for i in first if i["asset"] == "cliff"]), 7)
        self.assertTrue({i["asset"] for i in first} >= {"cliff", "boulder", "rock", "outcrop"})

    def test_cover_and_grass_keep_off_the_path_and_the_floor(self):
        groups = planner.cover(self.scene, self.terrain, self.weights, np.random.default_rng(2))
        heather = next(g for g in groups if g["foliage"] == "heather")
        for x, _, z, _, _ in heather["items"]:
            lx, lz = x - self.terrain.offset, z - self.terrain.offset
            self.assertLessEqual(np.hypot(lx - 62, lz - 70), 30)
        grass = planner.grass_density(self.scene, self.terrain, self.weights)
        d, cell = grass["density"], grass["cell"]
        at = lambda x, z: d[int((z + 10) / cell), int((x + 10) / cell)]
        self.assertEqual(at(float(self.terrain.path_x(30)), 30), 0)
        chapel = self.scene["structures"][0]
        self.assertEqual(at(chapel["at"][0], chapel["at"][1]), 0)  # under a floor tile
        cells = (np.arange(d.shape[0]) + 0.5) * cell - 10
        x, z = np.meshgrid(cells, cells)
        near, far = np.hypot(x - 36, z - 30) < 6, np.hypot(x - 100, z - 100) < 6  # the path still's camera; a far corner
        self.assertGreater(d[near & (d > 0)].mean(), 3 * d[far & (d > 0)].mean())  # dense by a camera, thin far away

    def test_structures_and_cameras_are_in_world_metres(self):
        planned = planner.structures(self.scene, self.terrain, np.random.default_rng(3))[0]
        off = self.terrain.offset
        window = next(p for p in planned["pieces"] if p["model"] == "ruin_window")
        self.assertEqual((window["align"], window["align_value"]), ("max_z", off + 46 + 6))
        self.assertEqual(sum(1 for p in planned["pieces"] if p.get("floor")), 7)
        crate = next(p for p in planned["props"] if p["model"] == "supply_crate")
        self.assertAlmostEqual(crate["y"], planned["floor_y"] + 0.05)
        frames = planner.flythrough(self.scene, self.terrain)
        self.assertEqual(len(frames), 360)
        self.assertTrue(all(frame["fov"] == 50 for frame in frames))  # a frame without one rendered at 0 degrees
        for frame in frames:
            x, y, z = frame["from"]
            self.assertGreaterEqual(y, float(self.terrain.ground(x - off, z - off)) + 1.19)

    def test_unknown_children_are_named(self):
        broken = _scene()
        broken["structures"][0]["props"].append({"model": "anvil", "at": [0, 0], "height": 1})
        with self.assertRaisesRegex(ValueError, "anvil"):
            planner.validate_scene(broken, [c["id"] for c in RECIPE["children"]])
        planner.validate_scene(_scene(), [c["id"] for c in RECIPE["children"]])
        boolean = _scene()
        boolean["structures"][0]["props"][0] = yaml.safe_load("{model: supply_crate, at: [0, 0], height: 1, on: 0.05}")
        with self.assertRaisesRegex(ValueError, "reads as True"):
            planner.validate_scene(boolean, [c["id"] for c in RECIPE["children"]])


class SceneRenderTests(unittest.TestCase):
    def test_render_builds_plants_and_hands_unity_a_complete_plan(self):
        from slopforge import unity_natural_scene
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            definition = copy.deepcopy(RECIPE)
            definition["scene"] = _scene()
            definition["scene"]["cameras"]["flythrough"]["seconds"] = 0.2
            manifest = {"assets": {}}
            stages = {}
            texture = root / "Assets/t.png"
            texture.parent.mkdir(parents=True)
            Image.new("RGB", (16, 16), (90, 120, 40)).save(texture)
            for child in definition["children"]:
                key = f"{child['type']}:run_{child['id']}"
                stages[child["id"]] = {"asset_key": key}
                outputs = {"image": "Assets/t.png", "tiling_basecolor": "Assets/t.png", "tiling_normal": "Assets/t.png",
                           "tiling_roughness": "Assets/t.png"}
                manifest["assets"][key] = {"name": f"run_{child['id']}", "status": "ready", "outputs": outputs,
                                           "unity_import": {"assets": {"fbx": {"path": f"Assets/{child['id']}.fbx"}}}}
            manifest["assets"]["recipe:run"] = {"name": "run", "recipe_instance": {"definition": definition, "stages": stages}}
            config = {"asset_pipeline": {"output_root": "Assets/Art/Generated"}}
            seen = {}

            def vegetation(root_, config_, manifest_, name, species, height, seed, bark, foliage):
                record = {"name": name, "generator": {"seed": seed},
                          "outputs": {"fbx": f"Assets/V/{name}.fbx", "bark_basecolor": "b", "bark_normal": "n", "leaves": "l"}}
                manifest_["assets"][f"vegetation:{name}"] = record
                return record

            def unity(command, **_):
                request_path = next(Path(p) for p in Path(root / "Assets/Editor").glob("*.cs"))
                script = request_path.read_text()
                request = json.loads(Path(json.loads(script.split("File.ReadAllText(")[1].split(")")[0])).read_text())
                seen.update(request)
                out = Path(request["out_dir"])
                (out / "report.json").write_text(json.dumps({"scene": request["scene_path"], "stills": [], "errors": []}))
            with patch.object(unity_natural_scene, "make_vegetation", side_effect=vegetation), \
                    patch.object(unity_natural_scene, "unity_cli", return_value="unity"), \
                    patch.object(unity_natural_scene.subprocess, "run", side_effect=unity), \
                    patch.object(unity_natural_scene.shutil, "which", return_value=None):
                report = unity_natural_scene.render_scene(root, config, manifest, "run")
            self.assertEqual(report["planned"]["plants"], sorted(definition["scene"]["plants"]))
            self.assertTrue(all(p["fbx"] for p in seen["placements"]))
            self.assertTrue(any(p["fbx"] == "Assets/V/run_oak_a.fbx" for p in seen["placements"]))
            self.assertEqual(len(seen["layers"]), 4)
            self.assertEqual(len(seen["frames"]), 6)
            self.assertTrue((root / "Assets/Art/Generated/Scenes/run/blade_palette.png").is_file())
            self.assertIn("ffmpeg", " ".join(report.get("warnings", [])))
            self.assertFalse(list((root / "Assets/Editor").glob("*.cs")))  # the editor script is removed afterwards
            self.assertEqual(report["scene_source"], "recipe run")

            # A layout change in the project's recipe file reaches the render without regenerating the children.
            changed = copy.deepcopy(definition)
            changed["scene"]["structures"][0]["pieces"][0]["turn"] = 90
            (root / "ai/recipes").mkdir(parents=True)
            (root / "ai/recipes/test.yaml").write_text(yaml.safe_dump(changed))
            manifest["assets"]["recipe:run"]["recipe_instance"]["definition_path"] = "ai/recipes/test.yaml"
            with patch.object(unity_natural_scene, "make_vegetation", side_effect=vegetation), \
                    patch.object(unity_natural_scene, "unity_cli", return_value="unity"), \
                    patch.object(unity_natural_scene.subprocess, "run", side_effect=unity), \
                    patch.object(unity_natural_scene.shutil, "which", return_value=None):
                again = unity_natural_scene.render_scene(root, config, manifest, "run")
            self.assertEqual(again["scene_source"], "ai/recipes/test.yaml")
            self.assertNotEqual(again["scene_sha256"], report["scene_sha256"])
            changed["scene"]["structures"][0]["props"].append({"model": "anvil", "at": [0, 0], "height": 1})
            (root / "ai/recipes/test.yaml").write_text(yaml.safe_dump(changed))
            with self.assertRaisesRegex(ValueError, "anvil"):  # a file naming a child the run lacks stops early
                unity_natural_scene.render_scene(root, config, manifest, "run")
