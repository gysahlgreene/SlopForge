import tempfile
import unittest
from pathlib import Path

import yaml

from slopforge.animation import validate_animation_library
from slopforge.cli import parse_args


class AnimationLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        source = self.root / "Assets/Animations/idle.fbx"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"fixture")
        (self.root / "ai/animation_libraries").mkdir(parents=True)
        self.definition = {"version": 1, "skeleton_type": "humanoid", "clips": [
            {"id": "idle_v1", "name": "idle", "path": "Assets/Animations/idle.fbx",
             "loop": True, "root_motion": False, "bone_mapping": {"Hips": "pelvis", "LeftArm": "arm_l"}},
        ]}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        path = self.root / "ai/animation_libraries/base.yaml"
        path.write_text(yaml.safe_dump(self.definition))

    def test_resolves_project_local_clip_and_keeps_retarget_metadata(self):
        library = validate_animation_library(self.root, "base")
        self.assertEqual(library["skeleton_type"], "humanoid")
        self.assertEqual(library["clips"][0]["resolved_path"], self.root.resolve() / "Assets/Animations/idle.fbx")
        self.assertEqual(library["clips"][0]["bone_mapping"]["Hips"], "pelvis")

    def test_rejects_duplicate_targets_and_paths_outside_project(self):
        self.definition["clips"][0]["bone_mapping"] = {"LeftArm": "arm", "RightArm": "arm"}
        self.save()
        with self.assertRaisesRegex(ValueError, "target names must be unique"):
            validate_animation_library(self.root, "base")
        self.definition["clips"][0]["bone_mapping"] = {}
        self.definition["clips"][0]["path"] = "../outside.fbx"
        self.save()
        with self.assertRaisesRegex(ValueError, "stay inside"):
            validate_animation_library(self.root, "base")

    def test_rejects_unknown_clip_types_and_missing_files(self):
        self.definition["clips"][0]["name"] = "dance"
        self.save()
        with self.assertRaisesRegex(ValueError, "Unsupported prototype"):
            validate_animation_library(self.root, "base")
        self.definition["clips"][0]["name"] = "walk"
        self.definition["clips"][0]["path"] = "Assets/Animations/missing.fbx"
        self.save()
        with self.assertRaisesRegex(ValueError, "missing or outside"):
            validate_animation_library(self.root, "base")

    def test_cli_exposes_library_validation(self):
        args = parse_args(["--project", str(self.root), "animation", "validate", "base"])
        self.assertEqual((args.command, args.animation_action, args.name), ("animation", "validate", "base"))


if __name__ == "__main__":
    unittest.main()
