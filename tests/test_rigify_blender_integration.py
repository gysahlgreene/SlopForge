"""Opt-in real Blender/Rigify smoke: SLOPFORGE_RUN_BLENDER_RIGIFY=1 pytest this file."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from slopforge.backends.blender import blender_executable
from slopforge.config import load_project
from slopforge.initializer import init_project
from slopforge.manifest import load_manifest, new_record, register_artifact, save_manifest
from slopforge.cli import main


@unittest.skipUnless(os.environ.get("SLOPFORGE_RUN_BLENDER_RIGIFY") == "1",
                     "set SLOPFORGE_RUN_BLENDER_RIGIFY=1 to run the real Blender/Rigify smoke")
class RigifyBlenderIntegrationTests(unittest.TestCase):
    def test_watertight_humanoid_gets_weighted_fbx_and_deforming_review_poses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "game"
            (root / "Assets/Characters/pilot").mkdir(parents=True)
            fixture_script = root / "create_fixture.py"
            fixture_script.write_text('''
import bpy
from pathlib import Path
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
parts = [((0,0,0.98),(0.24,0.17,0.40)), ((0,0,1.45),(0.15,0.14,0.18)),
         ((0,0,1.73),(0.10,0.11,0.12)), ((0.39,0,1.31),(0.25,0.09,0.09)),
         ((-0.39,0,1.31),(0.25,0.09,0.09)), ((0.13,0,0.48),(0.12,0.14,0.36)),
         ((-0.13,0,0.48),(0.12,0.14,0.36)), ((0.13,-0.06,0.08),(0.12,0.22,0.08)),
         ((-0.13,-0.06,0.08),(0.12,0.22,0.08))]
objects=[]
for location, scale in parts:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, location=location)
    obj=bpy.context.object; obj.scale=scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    objects.append(obj)
bpy.ops.object.select_all(action="DESELECT")
for obj in objects: obj.select_set(True)
bpy.context.view_layer.objects.active=objects[0]
bpy.ops.object.join()
mesh=bpy.context.object
modifier=mesh.modifiers.new("VoxelUnion", "REMESH")
modifier.mode="VOXEL"; modifier.voxel_size=0.025
bpy.ops.object.modifier_apply(modifier=modifier.name)
material=bpy.data.materials.new("FixtureMaterial"); material.diffuse_color=(0.4,0.5,0.7,1)
mesh.data.materials.append(material)
bpy.ops.export_scene.gltf(filepath=str(Path(__file__).parent / "Assets/Characters/pilot/model.glb"),
                           export_format="GLB", use_selection=True)
''')
            blender = blender_executable({}, root)
            subprocess.run([blender, "--background", "--factory-startup", "--python", str(fixture_script)],
                           check=True, capture_output=True, text=True)
            init_project(root)
            config = load_project(root)
            manifest_path = root / config["asset_pipeline"]["manifest"]
            manifest = load_manifest(manifest_path)
            character = new_record("character", "pilot", "Synthetic Blender smoke fixture",
                                   {"name": "default", "version": 1}, {"strategy": "text_only"})
            manifest["assets"]["character:pilot"] = character
            register_artifact(manifest, "character:pilot", "model", "model.glb",
                              "Assets/Characters/pilot/model.glb", status="ready", approval_status="approved")
            save_manifest(manifest_path, manifest)

            self.assertEqual(main(["--project", str(root), "character", "rig", "pilot"]), 0)
            manifest = load_manifest(manifest_path)
            character = manifest["assets"]["character:pilot"]
            result = {"status": character["rigging"]["status"],
                      "rig_artifact": character["artifacts"]["rig"]}

            self.assertEqual(result["status"], "review_required")
            self.assertEqual(result["rig_artifact"]["approval"]["status"], "pending")
            rig_path = root / result["rig_artifact"]["path"]
            self.assertGreater(rig_path.stat().st_size, 0)
            evidence = character["rigging"]["deformation_evidence"]
            for pose in ("raised_arms", "crouch", "leg_lift", "elbow_bend", "shoulder_rotation"):
                self.assertGreater(evidence[pose]["max_vertex_displacement"], 0.01)
                artifact = character["artifacts"][f"rig_pose.{pose}"]
                self.assertGreater((root / artifact["path"]).stat().st_size, 0)
            self.assertEqual(sum(item["open_edges"] for item in character["rigging"]["mesh_repair"]["meshes"]), 0)


if __name__ == "__main__":
    unittest.main()
