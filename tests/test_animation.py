import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from slopforge.animation import retarget_animation, validate_animation_library
from slopforge.cli import parse_args
from slopforge.manifest import new_record, register_artifact


class AnimationLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / "ai/animation_libraries").mkdir(parents=True)
        self.clip_path = self.root / "Assets/Animations/walk.fbx"
        self.clip_path.parent.mkdir(parents=True)
        self.clip_path.write_bytes(b"source animation")
        self.definition = {"version": 1, "skeleton_type": "humanoid", "clips": [{
            "id": "walk", "name": "walk", "path": "Assets/Animations/walk.fbx",
            "loop": True, "root_motion": False, "bone_mapping": {"hips": "DEF-spine"},
        }]}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        path = self.root / "ai/animation_libraries/base.yaml"
        path.write_text(yaml.safe_dump(self.definition))
        return path

    def test_resolves_project_local_clip_and_keeps_retarget_metadata(self):
        library = validate_animation_library(self.root, "base")
        self.assertEqual(library["clips"][0]["resolved_path"], self.clip_path)
        self.assertEqual(library["clips"][0]["bone_mapping"], {"hips": "DEF-spine"})

    def test_rejects_duplicate_targets_and_paths_outside_project(self):
        self.definition["clips"][0]["bone_mapping"] = {"LeftArm": "arm", "RightArm": "arm"}
        self.save()
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_animation_library(self.root, "base")
        self.definition["clips"][0]["bone_mapping"] = {}
        self.definition["clips"][0]["path"] = "../outside.fbx"
        self.save()
        with self.assertRaisesRegex(ValueError, "inside the project"):
            validate_animation_library(self.root, "base")

    def test_rejects_unknown_clip_types_and_missing_files(self):
        self.definition["clips"][0]["name"] = "dance"
        self.save()
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            validate_animation_library(self.root, "base")
        self.definition["clips"][0]["name"] = "walk"
        self.definition["clips"][0]["path"] = "Assets/Animations/missing.fbx"
        self.save()
        with self.assertRaisesRegex(ValueError, "missing or outside"):
            validate_animation_library(self.root, "base")

    def test_cli_exposes_library_validation_and_retarget(self):
        args = parse_args(["--project", str(self.root), "animation", "validate", "base"])
        self.assertEqual((args.command, args.animation_action, args.name), ("animation", "validate", "base"))
        args = parse_args(["--project", str(self.root), "animation", "retarget", "base", "walk",
                           "--character", "pilot"])
        self.assertEqual((args.animation_action, args.name, args.clip, args.character),
                         ("retarget", "base", "walk", "pilot"))
        args = parse_args(["--project", str(self.root), "animation", "unity-setup", "pilot",
                           "--rig-type", "humanoid"])
        self.assertEqual((args.animation_action, args.character, args.rig_type), ("unity-setup", "pilot", "humanoid"))

    def _character_manifest(self, approval="approved"):
        rig = self.root / "Assets/Characters/pilot/rig.fbx"
        rig.parent.mkdir(parents=True, exist_ok=True)
        rig.write_bytes(b"approved rig")
        character = new_record("character", "pilot", "Pilot", {"name": "default", "version": 1},
                               {"strategy": "text_only"})
        manifest = {"assets": {"character:pilot": character}}
        register_artifact(manifest, "character:pilot", "rig", "model.fbx",
                          "Assets/Characters/pilot/rig.fbx", status="ready", approval_status=approval)
        return character, manifest

    def test_retarget_records_reviewable_clip_and_measured_provenance(self):
        character, manifest = self._character_manifest()

        def fake_blender(command, check):
            request = json.loads(Path(command[-1]).read_text())
            output = Path(request["output"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"retargeted FBX")
            Path(request["report"]).write_text(json.dumps({
                "status": "complete", "frames": 12, "max_vertex_displacement": 0.37,
                "bone_mapping": {"hips": "DEF-spine"},
            }))

        with patch("slopforge.animation.subprocess.run", side_effect=fake_blender) as run:
            result = retarget_animation(self.root, self.config(), manifest, "pilot", "base", "walk")
        run.assert_called_once()
        artifact = character["artifacts"]["animation.walk"]
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(artifact["approval"]["status"], "pending")
        self.assertEqual(artifact["type"], "animation.fbx")
        self.assertEqual(character["animations"]["walk"]["max_vertex_displacement"], 0.37)
        self.assertEqual(character["animations"]["walk"]["loop"], True)

    def test_retarget_rejects_unapproved_rig_without_invoking_blender(self):
        _, manifest = self._character_manifest(approval="pending")
        with patch("slopforge.animation.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "approved"):
                retarget_animation(self.root, self.config(), manifest, "pilot", "base", "walk")
        run.assert_not_called()

    def test_unity_setup_requires_approved_rig_and_clip_and_records_controller_prefab(self):
        from slopforge.unity_animation import build_character_animator

        character, manifest = self._character_manifest()
        clip = self.root / "Assets/Art/Generated/Characters/pilot/Animations/walk.fbx"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"retargeted clip")
        register_artifact(manifest, "character:pilot", "animation.walk", "animation.fbx",
                          "Assets/Art/Generated/Characters/pilot/Animations/walk.fbx", status="ready",
                          approval_status="approved")
        with patch("slopforge.unity_animation.unity_cli", return_value="unity"), \
                patch("slopforge.unity_animation.subprocess.run", side_effect=lambda *args, **kwargs: (
                    (self.root / "Assets/Art/Generated/Characters/pilot/Unity/pilot.controller").write_bytes(b"controller"),
                    (self.root / "Assets/Art/Generated/Characters/pilot/Unity/pilot.prefab").write_bytes(b"prefab"))):
            result = build_character_animator(self.root, {"asset_pipeline": {"output_root": "Assets/Art/Generated"}},
                                              manifest, "pilot", rig_type="generic")
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(character["artifacts"]["unity.animator_controller"]["approval"]["status"], "pending")
        self.assertEqual(character["artifacts"]["unity.character_prefab"]["approval"]["status"], "pending")

    def test_humanoid_setup_requires_and_applies_provider_bone_mapping(self):
        from slopforge.unity_animation import build_character_animator

        character, manifest = self._character_manifest()
        character["rigging"] = {"unity_humanoid_mapping": {
            "Hips": "torso", "Spine": "spine_fk.003", "Head": "ORG-face",
            "LeftUpperArm": "DEF-upper_arm.L", "LeftLowerArm": "DEF-forearm.L", "LeftHand": "DEF-hand.L",
            "RightUpperArm": "DEF-upper_arm.R", "RightLowerArm": "DEF-forearm.R", "RightHand": "DEF-hand.R",
            "LeftUpperLeg": "DEF-thigh.L", "LeftLowerLeg": "DEF-shin.L", "LeftFoot": "DEF-foot.L",
            "RightUpperLeg": "DEF-thigh.R", "RightLowerLeg": "DEF-shin.R", "RightFoot": "DEF-foot.R",
        }}
        clip = self.root / "Assets/Art/Generated/Characters/pilot/Animations/walk.fbx"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"retargeted clip")
        register_artifact(manifest, "character:pilot", "animation.walk", "animation.fbx",
                          "Assets/Art/Generated/Characters/pilot/Animations/walk.fbx", status="ready",
                          approval_status="approved")
        scripts = []

        def run_unity(command, check):
            scripts.extend(path.read_text() for path in (self.root / "Assets/Editor").glob("*.cs"))
            (self.root / "Assets/Art/Generated/Characters/pilot/Unity/pilot.controller").write_bytes(b"controller")
            (self.root / "Assets/Art/Generated/Characters/pilot/Unity/pilot.prefab").write_bytes(b"prefab")

        with patch("slopforge.unity_animation.unity_cli", return_value="unity"), \
                patch("slopforge.unity_animation.subprocess.run", side_effect=run_unity):
            build_character_animator(self.root, {"asset_pipeline": {"output_root": "Assets/Art/Generated"}},
                                     manifest, "pilot", rig_type="humanoid")

        self.assertEqual(len(scripts), 1)
        self.assertIn('humanDescription.human = new HumanBone[]', scripts[0])
        self.assertIn('humanName = "RightHand", boneName = "DEF-hand.R"', scripts[0])
        self.assertIn('importer.preserveHierarchy = true;', scripts[0])
        self.assertIn('savedAnimator.avatar.isHuman', scripts[0])
        self.assertIn('savedAnimator.runtimeAnimatorController != controller', scripts[0])
        self.assertLess(scripts[0].index('rigImporter.animationType = ModelImporterAnimationType.Human'),
                        scripts[0].index('humanDescription.human = new HumanBone[]'))
        self.assertLess(scripts[0].index('rigImporter.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel'),
                        scripts[0].index('humanDescription.human = new HumanBone[]'))
        self.assertLess(scripts[0].index('humanDescription.human = new HumanBone[]'),
                        scripts[0].rindex('rigImporter.animationType = ModelImporterAnimationType.Human'))
        self.assertLess(scripts[0].index('humanDescription.human = new HumanBone[]'),
                        scripts[0].rindex('rigImporter.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel'))

    def test_humanoid_setup_refuses_rig_without_explicit_unity_mapping(self):
        from slopforge.unity_animation import build_character_animator

        _, manifest = self._character_manifest()
        clip = self.root / "Assets/Art/Generated/Characters/pilot/Animations/walk.fbx"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(b"retargeted clip")
        register_artifact(manifest, "character:pilot", "animation.walk", "animation.fbx",
                          "Assets/Art/Generated/Characters/pilot/Animations/walk.fbx", status="ready",
                          approval_status="approved")
        with patch("slopforge.unity_animation.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "Unity Humanoid bone mapping"):
                build_character_animator(self.root, {"asset_pipeline": {"output_root": "Assets/Art/Generated"}},
                                          manifest, "pilot", rig_type="humanoid")
        run.assert_not_called()

    @staticmethod
    def config():
        return {"asset_pipeline": {"output_root": "Assets/Art/Generated", "tools": {"blender": "/fake/blender"}}}


if __name__ == "__main__":
    unittest.main()
