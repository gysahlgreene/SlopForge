"""Opt-in real Blender retarget smoke: SLOPFORGE_RUN_BLENDER_ANIMATION=1 pytest this file."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from slopforge.cli import main
from slopforge.config import load_project
from slopforge.initializer import init_project
from slopforge.manifest import load_manifest, new_record, register_artifact, save_manifest
from slopforge.paths import blender_executable


@unittest.skipUnless(os.environ.get("SLOPFORGE_RUN_BLENDER_ANIMATION") == "1",
                     "set SLOPFORGE_RUN_BLENDER_ANIMATION=1 to run Blender retarget smoke")
class BlenderAnimationIntegrationTests(unittest.TestCase):
    def test_animation_is_baked_onto_approved_rig_and_registered_pending_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "game"
            (root / "Assets/Characters/pilot").mkdir(parents=True)
            fixture = root / "create_animation_fixture.py"
            fixture.write_text('''
import bpy
from pathlib import Path
root=Path(__file__).parent
(root/"Assets/Animations").mkdir(parents=True, exist_ok=True)
def make_rig(name):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.object.armature_add()
    rig=bpy.context.object; rig.name=name; rig.data.name=name
    bone=rig.data.bones[0]; bone.name="hips"
    bpy.ops.object.mode_set(mode="EDIT")
    bone=rig.data.edit_bones["hips"]; bone.head=(0,0,0); bone.tail=(0,0,1)
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig
rig=make_rig("Target")
bpy.ops.mesh.primitive_cube_add(size=1, location=(0,0,0.5))
mesh=bpy.context.object; mesh.name="CharacterMesh"; mesh.scale=(0.2,0.2,0.8)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
mesh.vertex_groups.new(name="hips").add(list(range(len(mesh.data.vertices))), 1.0, "REPLACE")
modifier=mesh.modifiers.new("Skin", "ARMATURE"); modifier.object=rig
bpy.ops.object.select_all(action="DESELECT"); rig.select_set(True); mesh.select_set(True)
bpy.context.view_layer.objects.active=rig
bpy.ops.export_scene.fbx(filepath=str(root/"Assets/Characters/pilot/rig.fbx"), use_selection=True,
    object_types={"ARMATURE","MESH"}, add_leaf_bones=False, bake_anim=False)
source=make_rig("AnimationSource")
bone=source.pose.bones["hips"]
scene=bpy.context.scene; scene.frame_set(1); bone.rotation_mode="XYZ"; bone.rotation_euler=(0,0,0)
scene.frame_start=1; scene.frame_end=12
bone.keyframe_insert(data_path="rotation_euler", frame=1)
scene.frame_set(12); bone.rotation_euler=(0,0.7,0)
bone.keyframe_insert(data_path="rotation_euler", frame=12)
bpy.ops.object.select_all(action="DESELECT"); source.select_set(True); bpy.context.view_layer.objects.active=source
bpy.ops.export_scene.fbx(filepath=str(root/"Assets/Animations/walk.fbx"), use_selection=True,
    object_types={"ARMATURE"}, add_leaf_bones=False, bake_anim=True, bake_anim_use_nla_strips=False,
    bake_anim_use_all_actions=False, bake_anim_force_startend_keying=True, bake_anim_step=1.0)
''')
            subprocess.run([blender_executable({}, root), "--background", "--factory-startup", "--python",
                            str(fixture)], check=True, capture_output=True, text=True)
            init_project(root)
            config = load_project(root)
            library_path = root / "ai/animation_libraries/base.yaml"
            library_path.parent.mkdir(parents=True, exist_ok=True)
            library_path.write_text(yaml.safe_dump({"version": 1, "skeleton_type": "humanoid", "clips": [{
                "id": "walk", "name": "walk", "path": "Assets/Animations/walk.fbx", "loop": True,
                "root_motion": False, "bone_mapping": {"hips": "hips"}}]}))
            manifest_path = root / config["asset_pipeline"]["manifest"]
            manifest = load_manifest(manifest_path)
            character = new_record("character", "pilot", "Animation fixture", {"name": "default", "version": 1},
                                   {"strategy": "text_only"})
            manifest["assets"]["character:pilot"] = character
            register_artifact(manifest, "character:pilot", "rig", "model.rigged",
                              "Assets/Characters/pilot/rig.fbx", status="ready", approval_status="approved")
            save_manifest(manifest_path, manifest)

            self.assertEqual(main(["--project", str(root), "animation", "retarget", "base", "walk",
                                   "--character", "pilot"]), 0)
            manifest = load_manifest(manifest_path)
            character = manifest["assets"]["character:pilot"]
            artifact = character["artifacts"]["animation.walk"]
            self.assertEqual(artifact["approval"]["status"], "pending")
            self.assertGreater((root / artifact["path"]).stat().st_size, 0)
            self.assertEqual(character["animations"]["walk"]["frames"], 12)
            self.assertGreater(character["animations"]["walk"]["max_vertex_displacement"], 0.05)

            if os.environ.get("SLOPFORGE_RUN_UNITY_ANIMATION") == "1":
                from slopforge.unity_animation import build_character_animator

                (root / "ProjectSettings").mkdir(parents=True)
                (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
                (root / "Packages").mkdir()
                (root / "Packages/manifest.json").write_text('{"dependencies": {}}\n')
                for artifact_id in ("rig", "animation.walk"):
                    character["artifacts"][artifact_id]["status"] = "ready"
                    character["artifacts"][artifact_id]["approval"]["status"] = "approved"
                save_manifest(manifest_path, manifest)
                result = build_character_animator(root, config, manifest, "pilot", rig_type="generic")
                self.assertEqual(result["status"], "review_required")
                for item in (result["controller"], result["prefab"]):
                    self.assertEqual(item["approval"]["status"], "pending")
                    self.assertTrue((root / item["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
