"""approve-texture in a project whose engine is Unreal (docs/UNREAL.md): no Unity, an ORM map and a DirectX normal."""
import json
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from test_nonmetal_roughness import PublicationFloorTests


class UnrealPublicationTests(unittest.TestCase):
    def test_an_unreal_project_publishes_without_unity_and_with_unreal_maps(self):
        exports, seen = [], {}

        def export(config, blender, blend, name, out_dir, work, break_parts):
            exports.append((name, break_parts))
            (out_dir / f"{name}.fbx").write_bytes(b"unreal fbx")
            return {"name": name, "size_m": [1, 1, 1]}

        def inspect(final, asset):
            seen["report"] = json.loads((final["directory"] / "unreal.json").read_text())
            seen["fbx"] = final["fbx"].read_bytes()
            seen["orm"] = np.asarray(Image.open(final["metallic"].with_name("relic_orm.png")).convert("RGB"))
            seen["normal"] = Image.open(final["normal"]).convert("RGB").getpixel((0, 0))
            seen["unity_files"] = [*final["directory"].rglob("*.meta"), *final["directory"].rglob("*.mat"),
                                   *final["directory"].rglob("*metallic_gloss*")]

        never = AssertionError("an Unreal project does not use Unity")
        stubs = [patch("slopforge.pipelines.model.export_unreal", side_effect=export),
                 patch("slopforge.pipelines.model.blender_executable", return_value="blender")]  # CI has no Blender
        with patch("slopforge.pipelines.model.unity_cli", side_effect=never):
            _roughness, _alpha, asset = PublicationFloorTests.publish(
                self, {}, engine="unreal", inspect=inspect, stubs=stubs + [
                    patch("slopforge.pipelines.model.unity_cli", side_effect=never),
                    patch("slopforge.pipelines.model.build_unity_material", side_effect=never)])
        self.assertEqual(exports, [("relic", None)])
        self.assertEqual(seen["report"]["name"], "relic")
        self.assertEqual(seen["fbx"], b"unreal fbx")
        self.assertEqual(seen["unity_files"], [])
        self.assertEqual(tuple(seen["orm"][0, 0]), (255, round(0.75 * 255), 0))  # no occlusion, floored wood, no metal
        self.assertEqual(seen["orm"][2, 0, 2], 255)  # iron is metal
        self.assertEqual(seen["normal"], (90, 165, 255))  # DirectX: green flipped
        self.assertNotIn("unity_material", asset["outputs"])
        self.assertIn("orm", asset["outputs"])
        self.assertNotIn("unity_import", asset)

    def test_break_parts_need_an_unreal_project(self):
        with self.assertRaisesRegex(ValueError, "engine: unreal"):
            from slopforge.pipelines import model
            model.approve_texture("/nonexistent", {"project": {"engine": "unity"}},
                                  {"assets": {"prop:x": {"name": "x", "material_candidates": {"items": [
                                      {"number": 1, "status": "candidate"}]}}}}, "prop:x", 1,
                                  break_parts={"body": "chest"})


    def test_a_break_parts_file_names_a_body_and_a_parent_for_every_other_part(self):
        import tempfile
        from pathlib import Path
        from slopforge.unreal import load_break_parts
        good = {"body": "chest", "parents": {"head": "chest"},
                "views": {"front": {"chest": [0.3, 0.2, 0.7, 0.5], "head": [0.4, 0.0, 0.6, 0.2]}}}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "parts.json"
            path.write_text(json.dumps(good))
            self.assertEqual(load_break_parts(path)["body"], "chest")
            for bad, message in (({**good, "parents": {}}, "need a parent"), ({**good, "body": "pelvis"}, "has no box"),
                                 ({**good, "views": {"side": good["views"]["front"]}}, "views front, back"),
                                 ({**good, "views": {"front": {"chest": [0.7, 0.2, 0.3, 0.5]}}}, "--part-box")):
                path.write_text(json.dumps(bad))
                with self.assertRaisesRegex(ValueError, message):
                    load_break_parts(path)


    def test_a_model_whose_hidden_faces_were_removed_is_not_broken_apart(self):
        from slopforge.pipelines import model
        manifest = {"assets": {"hero_prop:x": {"name": "x", "type": "hero_prop", "generator": {"workflow": {}, "seed": {}},
                                               "material_candidates": {"items": [{"number": 1, "status": "candidate"}]}}}}
        with patch("slopforge.pipelines.model.load_taxonomy", return_value={"hero_prop": {"remove_hidden_faces": True}}):
            with self.assertRaisesRegex(ValueError, "remove_hidden_faces: false"):
                model.approve_texture("/nonexistent", {"project": {"engine": "unreal"}}, manifest, "hero_prop:x", 1,
                                      break_parts={"body": "chest"})


if __name__ == "__main__":
    unittest.main()
