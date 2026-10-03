import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderMaterialBakeTests(unittest.TestCase):
    def test_removes_only_single_face_islands(self):
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "check_cleanup.py"
            script.write_text(f'''import bpy, runpy
prepare = runpy.run_path({str(ROOT / "blender/mesh_cleanup.py")!r})
bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("cleanup")
mesh.from_pydata([(0,0,0),(1,0,0),(1,1,0),(0,1,0),(3,0,0),(4,0,0),(3,1,0)], [],
                 [(0,1,2),(0,2,3),(4,5,6)])
removed = prepare["remove_isolated_single_faces"](mesh)
assert removed == 1, removed
assert len(mesh.polygons) == 2, len(mesh.polygons)
''')
            subprocess.run([BLENDER, "--background", "--python", str(script)], check=True, capture_output=True)

    def test_native_maps_keep_uvs_and_seams_are_connected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb, fbx, blend = [root / f"cube.{extension}" for extension in ("glb", "fbx", "blend")]
            maps = [root / f"{key}.png" for key in ("basecolor", "normal", "roughness", "metallic", "emission")]
            for path, color in zip(maps, ((20,150,70), (128,128,255), (128,128,128), (0,0,0), (0,0,0))):
                Image.new("RGB", (64,64), color).save(path)
            originals = [path.read_bytes() for path in maps]
            fixture = root / "fixture.py"
            fixture.write_text('''import bpy,sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
for index,loop in enumerate(bpy.context.object.data.uv_layers.active.data):
    loop.uv = (0.4 + (0.1 if index%4 in (1,2) else 0), 0.2 + (0.1 if index%4 in (2,3) else 0))
bpy.ops.export_scene.gltf(filepath=sys.argv[-1],export_format='GLB')
''')
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)], check=True, capture_output=True)
            subprocess.run([BLENDER, "--background", "--python", str(ROOT / "blender/prepare_model.py"), "--",
                            str(glb), str(fbx), str(blend), *map(str,maps), "--preserve-uvs"], check=True, capture_output=True)
            self.assertEqual([path.read_bytes() for path in maps], originals)
            snapshot = root / "snapshot.py"
            result = root / "snapshot.json"
            snapshot.write_text(f'''import bpy,json,runpy
bpy.ops.wm.open_mainfile(filepath={str(blend)!r})
mesh=next(o.data for o in bpy.context.scene.objects if o.type=='MESH')
uvs=[tuple(loop.uv) for loop in mesh.uv_layers.active.data]
components=runpy.run_path({str(ROOT / 'blender/inspect_model.py')!r})['connected_components'](mesh)
json.dump({{'uv_min':[min(p[i] for p in uvs) for i in (0,1)],'uv_max':[max(p[i] for p in uvs) for i in (0,1)],'components':len(components)}},open({str(result)!r},'w'))
''')
            subprocess.run([BLENDER, "--background", "--python", str(snapshot)], check=True, capture_output=True)
            data = json.loads(result.read_text())
            self.assertEqual(data["components"], 1)
            for actual, expected in zip(data["uv_min"] + data["uv_max"], (0.4,0.2,0.5,0.3)):
                self.assertAlmostEqual(actual, expected, places=5)

    def test_bakes_generated_material_and_renders_three_mesh_views(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb, fbx, blend = root / "cube.glb", root / "cube.fbx", root / "cube.blend"
            surface = root / "surface.png"
            basecolor, normal, roughness, metallic, emission = [root / f"{name}.png" for name in
                                                                  ("basecolor", "normal", "roughness", "metallic", "emission")]
            previews = root / "previews"
            stage_mesh = root / "processed_mesh.blend"
            Image.new("RGB", (64, 64), (20, 150, 70)).save(surface)
            basecolor.write_bytes(surface.read_bytes())
            Image.new("RGB", (64, 64), (128, 128, 255)).save(normal)
            Image.new("L", (64, 64), 128).save(roughness)
            Image.new("L", (64, 64), 0).save(metallic)
            Image.new("RGB", (64, 64), (0, 0, 0)).save(emission)

            fixture = root / "fixture.py"
            fixture.write_text("""import bpy, sys
from pathlib import Path
target = Path(sys.argv[sys.argv.index('--') + 1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 1.0))
bpy.ops.export_scene.gltf(filepath=str(target), export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            command = [BLENDER, "--background", "--python", str(ROOT / "blender/prepare_model.py"), "--",
                       str(glb), str(fbx), str(blend), *(str(path) for path in
                       (basecolor, normal, roughness, metallic, emission)), "--face-budget", "1000",
                       "--surface-source", str(surface), "--preview-dir", str(previews),
                       "--stage-mesh-output", str(stage_mesh)]
            processed = subprocess.run(command, check=True, capture_output=True, text=True)

            front = previews / "cube_front.png"
            side = previews / "cube_side.png"
            rear = previews / "cube_rear.png"
            self.assertTrue(front.is_file(), processed.stdout + processed.stderr)
            self.assertTrue(side.is_file())
            self.assertTrue(rear.is_file())
            front_rgb = Image.open(front).convert("RGB")
            rgb = front_rgb.tobytes()
            green_pixels = sum(1 for r, g, b in zip(rgb[0::3], rgb[1::3], rgb[2::3])
                               if g > 80 and g > r * 1.6 and g > b * 1.2)
            self.assertGreater(green_pixels, 20)
            background = front_rgb.getpixel((0, 0))
            foreground = [index for index, (r, g, b) in enumerate(zip(rgb[0::3], rgb[1::3], rgb[2::3]))
                          if max(abs(r - background[0]), abs(g - background[1]), abs(b - background[2])) > 24]
            ys = [index // front_rgb.width for index in foreground]
            self.assertGreater(min(ys), 15)
            self.assertLess(max(ys), front_rgb.height - 16)
            self.assertLess(abs((min(ys) + max(ys)) / 2 - front_rgb.height / 2), 70)
            self.assertTrue(fbx.is_file())
            self.assertTrue(blend.is_file())
            self.assertTrue(stage_mesh.is_file())

            next_surface = root / "next_surface.png"
            Image.new("RGB", (64, 64), (30, 70, 210)).save(next_surface)
            next_basecolor = root / "next_basecolor.png"
            next_basecolor.write_bytes(next_surface.read_bytes())
            next_fbx, next_blend = root / "candidate_2.fbx", root / "candidate_2.blend"
            next_previews = root / "candidate_2_previews"
            next_command = [BLENDER, "--background", "--python", str(ROOT / "blender/prepare_model.py"), "--",
                            str(stage_mesh), str(next_fbx), str(next_blend), str(next_basecolor), str(normal),
                            str(roughness), str(metallic), str(emission), "--face-budget", "1000",
                            "--surface-source", str(next_surface),
                            "--preview-dir", str(next_previews), "--reuse-stage-mesh"]
            second_pass = subprocess.run(next_command, check=True, capture_output=True, text=True)
            for view in ("candidate_2_front.png", "candidate_2_side.png", "candidate_2_rear.png"):
                self.assertTrue((next_previews / view).is_file(), second_pass.stdout + second_pass.stderr)
            self.assertTrue(next_fbx.is_file())
            self.assertTrue(next_blend.is_file())


if __name__ == "__main__":
    unittest.main()
