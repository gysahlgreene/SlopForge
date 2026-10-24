import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageStat


ROOT = Path(__file__).resolve().parents[1]
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderMaterialBakeTests(unittest.TestCase):
    def test_mesh_preparation_preserves_closed_geometry_and_bakes_source_normals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target, blend = root / "source.glb", root / "prepared.glb", root / "prepared.blend"
            normal = root / "normal.png"
            fixture = root / "fixture.py"
            fixture.write_text("""import bpy,sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(fixture),
                            "--", str(source)], check=True, capture_output=True)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/prepare_model.py"), "--", str(source), str(target), str(blend),
                            "--mesh-only", "--face-budget", "100", "--normal-output", str(normal),
                            "--texture-size", "128"], check=True, capture_output=True)
            self.assertTrue(normal.is_file())
            with Image.open(normal) as image:
                self.assertEqual(image.size, (128, 128))
                self.assertEqual(image.getpixel((64, 64))[2], 255)
            snapshot = root / "snapshot.py"
            result = root / "snapshot.json"
            snapshot.write_text(f"""import bpy,json
bpy.ops.wm.open_mainfile(filepath={str(blend)!r})
meshes=[obj for obj in bpy.context.scene.objects if obj.type=='MESH']
json.dump({{'mesh_objects':len(meshes),'face_count':len(meshes[0].data.polygons),
            'positions':sorted(set(tuple(round(c,5) for c in v.co) for v in meshes[0].data.vertices))}},
          open({str(result)!r},'w'))
""")
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(snapshot)],
                           check=True, capture_output=True)

            data = json.loads(result.read_text())
            self.assertEqual(data["mesh_objects"], 1)
            self.assertEqual(data["face_count"], 12)
            self.assertEqual(len(data["positions"]), 8)
            self.assertEqual(data["positions"][0], [-1.0, -1.0, -1.0])
            self.assertEqual(data["positions"][-1], [1.0, 1.0, 1.0])
            fixture.write_text("""import bpy,sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24)
for polygon in bpy.context.object.data.polygons:
    polygon.use_smooth=True
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(fixture),
                            "--", str(source)], check=True, capture_output=True)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/prepare_model.py"), "--", str(source), str(target), str(blend),
                            "--mesh-only", "--face-budget", "100", "--normal-output", str(normal),
                            "--texture-size", "128"], check=True, capture_output=True)
            with Image.open(normal) as image:
                self.assertGreater(max(ImageStat.Stat(image).stddev), 10)
            fixture.write_text("""import bpy,sys,bmesh
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
mesh=bpy.context.object.data
bm=bmesh.new(); bm.from_mesh(mesh); bm.faces.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[bm.faces[0]], context='FACES')
bm.to_mesh(mesh); bm.free()
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(fixture),
                            "--", str(source)], check=True, capture_output=True)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/prepare_model.py"), "--", str(source), str(target), str(blend),
                            "--mesh-only", "--face-budget", "10000", "--voxel-resolution", "32"],
                           check=True, capture_output=True)
            snapshot.write_text(f"""import bpy,sys
sys.path.insert(0,{str(ROOT / 'blender')!r})
from inspect_model import topology_edge_counts
bpy.ops.wm.open_mainfile(filepath={str(blend)!r})
mesh=next(obj.data for obj in bpy.context.scene.objects if obj.type=='MESH')
assert topology_edge_counts(mesh,1e-7)==(0,0)
mesh.calc_loop_triangles()
assert len(mesh.loop_triangles)<=10000, len(mesh.loop_triangles)
""")
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(snapshot)],
                           check=True, capture_output=True)


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
inspector=runpy.run_path({str(ROOT / 'blender/inspect_model.py')!r})
components=inspector['connected_components'](mesh)
boundary, nonmanifold=inspector['topology_edge_counts'](mesh, 1e-5)
json.dump({{'uv_min':[min(p[i] for p in uvs) for i in (0,1)],'uv_max':[max(p[i] for p in uvs) for i in (0,1)],'components':len(components),'boundary_edges':boundary,'nonmanifold_edges':nonmanifold}},open({str(result)!r},'w'))
''')
            subprocess.run([BLENDER, "--background", "--python", str(snapshot)], check=True, capture_output=True)
            data = json.loads(result.read_text())
            self.assertEqual(data["components"], 1)
            self.assertEqual(data["boundary_edges"], 0)
            self.assertEqual(data["nonmanifold_edges"], 0)
            for actual, expected in zip(data["uv_min"] + data["uv_max"], (0.4,0.2,0.5,0.3)):
                self.assertAlmostEqual(actual, expected, places=5)

    def test_noisy_organic_mesh_keeps_most_of_its_atlas(self):
        # 2026-10-22 tree stump: bark and moss unwrapped into ~10,600 islands, and 12-texel padding left 4.4% of
        # the map for the surface. 4-texel padding and a concave repack keep a noisy surface usable.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb, prepared, blend = root / "stump.glb", root / "prepared.glb", root / "prepared.blend"
            fixture = root / "fixture.py"
            fixture.write_text('''import bpy, random, sys
random.seed(3)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=6)
for vertex in bpy.context.object.data.vertices:
    vertex.co *= 1 + random.uniform(-0.04, 0.04)
bpy.ops.object.shade_smooth()  # flat shading would split every face apart in the glTF export
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
''')
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)], check=True, capture_output=True)
            subprocess.run([BLENDER, "--background", "--python", str(ROOT / "blender/prepare_model.py"), "--", str(glb),
                            str(prepared), str(blend), "--mesh-only", "--no-voxel-repair", "--face-budget", "100000",
                            "--texture-size", "4096"], check=True, capture_output=True)
            result = root / "uv.json"
            snapshot = root / "snapshot.py"
            snapshot.write_text(f'''import bpy, json
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={str(prepared)!r})
mesh = next(o.data for o in bpy.data.objects if o.type == "MESH")
uv = mesh.uv_layers.active.data
area = sum(abs(sum(a.x * b.y - b.x * a.y for a, b in zip(p, p[1:] + p[:1]))) / 2
           for p in ([uv[i].uv for i in poly.loop_indices] for poly in mesh.polygons))
json.dump({{"area": area}}, open({str(result)!r}, "w"))
''')
            subprocess.run([BLENDER, "--background", "--python", str(snapshot)], check=True, capture_output=True)
            # This fixture measured 0.040 with the old 12-texel padding and 0.165 with 4 texels and a concave repack.
            self.assertGreater(json.loads(result.read_text())["area"], 0.12)

    def test_declared_glass_faces_get_their_own_material(self):
        # Issue #44: glass texels carry base colour alpha; their faces need a separate (transparent) engine material.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb, fbx, blend = [root / f"cube.{extension}" for extension in ("glb", "fbx", "blend")]
            maps = [root / f"{key}.png" for key in ("basecolor", "normal", "roughness", "metallic", "emission")]
            base = Image.new("RGBA", (64, 64), (60, 150, 90, 255))
            base.paste((60, 150, 90, 89), (0, 0, 32, 64))  # left half is glass
            base.save(maps[0])
            for path, color in zip(maps[1:], ((128, 128, 255), (128, 128, 128), (0, 0, 0), (0, 0, 0))):
                Image.new("RGB", (64, 64), color).save(path)
            fixture = root / "fixture.py"
            fixture.write_text('''import bpy,sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
mesh = bpy.context.object.data
for polygon in mesh.polygons:
    left = 0.1 if polygon.index < 3 else 0.6
    for corner, loop in enumerate(polygon.loop_indices):
        mesh.uv_layers.active.data[loop].uv = (left + (0.2 if corner in (1, 2) else 0), 0.4 + (0.2 if corner in (2, 3) else 0))
bpy.ops.export_scene.gltf(filepath=sys.argv[-1],export_format='GLB')
''')
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)], check=True, capture_output=True)
            subprocess.run([BLENDER, "--background", "--python", str(ROOT / "blender/prepare_model.py"), "--",
                            str(glb), str(fbx), str(blend), *map(str, maps), "--preserve-uvs"], check=True, capture_output=True)
            result = root / "snapshot.json"
            snapshot = root / "snapshot.py"
            snapshot.write_text(f'''import bpy,json
bpy.ops.wm.open_mainfile(filepath={str(blend)!r})
mesh=next(o.data for o in bpy.context.scene.objects if o.type=='MESH')
json.dump({{'materials':[m.name for m in mesh.materials],'faces':len(mesh.polygons),'glass':sorted(p.index for p in mesh.polygons if p.material_index == 1)}},open({str(result)!r},'w'))
''')
            subprocess.run([BLENDER, "--background", "--python", str(snapshot)], check=True, capture_output=True)
            data = json.loads(result.read_text())
            self.assertEqual(data["materials"], ["cube_PBR", "cube_Glass"])
            self.assertEqual(len(data["glass"]) * 2, data["faces"])  # the three glass quads, as triangles
            self.assertIn(b"cube_Glass", fbx.read_bytes())

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


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderUVCoverageTests(unittest.TestCase):
    def test_inspection_reports_uv_area_and_out_of_bounds_loops(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, blend, result = root / "fixture.py", root / "plane.blend", root / "inspection.json"
            fixture.write_text("""import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_plane_add()
obj = bpy.context.active_object
obj.data.uv_layers.new(name="UVMap")
for loop, uv in zip(obj.data.uv_layers.active.data, [(0, 0), (1, 0), (1, 2), (0, 2)]):
    loop.uv = uv
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
""")
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(fixture),
                            "--", str(blend)], check=True, capture_output=True)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/inspect_model.py"), "--", str(blend), str(result), "100"],
                           check=True, capture_output=True)
            measured = json.loads(result.read_text())["measured"]
            self.assertAlmostEqual(measured["uv_area_sum"], 2.0, places=4)
            self.assertAlmostEqual(measured["uv_loop_outside_unit_fraction"], 0.5)


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderFlatPreviewTests(unittest.TestCase):
    def test_flat_prop_previews_look_down_instead_of_edge_on(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb, fbx, blend, previews = root / "slab.glb", root / "slab.fbx", root / "slab.blend", root / "previews"
            maps = [root / f"{name}.png" for name in ("basecolor", "normal", "roughness", "metallic", "emission")]
            for path, color in zip(maps, ((200, 160, 60), (128, 128, 255), (128, 128, 128), (0, 0, 0), (0, 0, 0))):
                Image.new("RGB", (64, 64), color).save(path)
            fixture = root / "fixture.py"
            fixture.write_text("""import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.05))
bpy.context.object.scale = (1, 0.6, 0.1)
bpy.ops.object.transform_apply(scale=True)
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            subprocess.run([BLENDER, "--background", "--python", str(ROOT / "blender/prepare_model.py"), "--",
                            str(glb), str(fbx), str(blend), *map(str, maps), "--face-budget", "1000",
                            "--surface-source", str(maps[0]), "--preview-dir", str(previews)],
                           check=True, capture_output=True, text=True)
            front = Image.open(previews / "slab_front.png").convert("RGB")
            background = front.getpixel((0, 0))
            pixels = list(zip(*[iter(front.tobytes())] * 3))
            foreground = sum(max(abs(a - b) for a, b in zip(pixel, background)) > 24 for pixel in pixels)
            self.assertGreater(foreground / len(pixels), 0.2)


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderVoxelRepairTests(unittest.TestCase):
    def test_no_voxel_repair_keeps_open_thin_geometry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb = root / "open.glb"
            fixture = root / "fixture.py"
            fixture.write_text("""import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_grid_add(x_subdivisions=20, y_subdivisions=20, size=1, location=(0, 0, 0.5))
bpy.context.object.rotation_euler = (1.5708, 0, 0)
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            faces = {}
            for flag in ([], ["--no-voxel-repair"]):
                out = root / f"prepared{len(flag)}.glb"
                result = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                         str(ROOT / "blender/prepare_model.py"), "--", str(glb), str(out),
                                         str(root / f"prepared{len(flag)}.blend"), "--mesh-only",
                                         "--face-budget", "10000", "--voxel-resolution", "64", *flag],
                                        check=True, capture_output=True, text=True)
                faces[bool(flag)] = int(result.stdout.split("Input faces: ")[1].split()[0])
            self.assertEqual(faces[True], 800)  # 20x20 quads triangulated, untouched by voxel repair
            self.assertNotEqual(faces[False], 800)


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderPreviewFramingTests(unittest.TestCase):
    def test_three_quarter_preview_frames_the_footprint_diagonal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb, previews = root / "box.glb", root / "previews"
            maps = [root / f"{name}.png" for name in ("basecolor", "normal", "roughness", "metallic", "emission")]
            for path, color in zip(maps, ((200, 160, 60), (128, 128, 255), (128, 128, 128), (0, 0, 0), (0, 0, 0))):
                Image.new("RGB", (64, 64), color).save(path)
            fixture = root / "fixture.py"
            fixture.write_text("""import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.3))
bpy.context.object.scale = (1, 1, 0.6)
bpy.ops.object.transform_apply(scale=True)
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            subprocess.run([BLENDER, "--background", "--python", str(ROOT / "blender/prepare_model.py"), "--",
                            str(glb), str(root / "box.fbx"), str(root / "box.blend"), *map(str, maps),
                            "--face-budget", "1000", "--surface-source", str(maps[0]), "--preview-dir", str(previews)],
                           check=True, capture_output=True, text=True)
            image = Image.open(previews / "box_three_quarter.png").convert("RGB")
            background = image.getpixel((0, 0))
            edges = [image.getpixel((x, y)) for y in range(image.height) for x in (0, image.width - 1)]
            self.assertTrue(all(max(abs(a - b) for a, b in zip(pixel, background)) <= 24 for pixel in edges))


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderTurntableTests(unittest.TestCase):
    def test_turntable_renders_rotating_frames_from_a_prepared_blend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            blend, frames = root / "asset.blend", root / "frames"
            fixture = root / "fixture.py"
            fixture.write_text("""import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0.2, 0, 0.5))
bpy.context.object.scale = (1, 0.3, 1)
bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(blend)],
                           check=True, capture_output=True, text=True)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/render_turntable.py"), "--", str(blend), str(frames),
                            "--frames", "4", "--size", "64"], check=True, capture_output=True, text=True)
            rendered = sorted(frames.glob("frame_*.png"))
            self.assertEqual([path.name for path in rendered], [f"frame_{index:03d}.png" for index in range(4)])
            self.assertNotEqual(rendered[0].read_bytes(), rendered[1].read_bytes())


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderTargetSizeTests(unittest.TestCase):
    def test_target_size_scales_declared_axes_and_turns_the_long_side(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb, blend = root / "wall.glb", root / "wall.blend"
            maps = [root / f"{name}.png" for name in ("basecolor", "normal", "roughness", "metallic", "emission")]
            for path in maps:
                Image.new("RGB", (16, 16), (128, 128, 128)).save(path)
            fixture = root / "fixture.py"
            fixture.write_text("""import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.5))
bpy.context.object.scale = (0.2, 1.0, 0.9)
bpy.ops.object.transform_apply(scale=True)
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/prepare_model.py"), "--", str(glb), str(root / "wall.fbx"), str(blend),
                            *map(str, maps), "--face-budget", "1000", "--surface-source", str(maps[0]),
                            "--target-size", "3,-,3"], check=True, capture_output=True, text=True)
            result = root / "dims.json"
            probe = root / "probe.py"
            probe.write_text("""import bpy, json, sys
obj = [o for o in bpy.data.objects if o.type == 'MESH'][0]
json.dump(list(obj.dimensions) + [obj.get("slopforge_axis_stretch")], open(sys.argv[-1], 'w'))
""")
            subprocess.run([BLENDER, "--background", str(blend), "--python", str(probe), "--", str(result)],
                           check=True, capture_output=True, text=True)
            x, y, z, stretch = json.loads(result.read_text())
            self.assertAlmostEqual(x, 3.0, places=3)  # the 1.0-long side was turned onto X
            self.assertAlmostEqual(z, 3.0, places=3)
            self.assertLess(y, 1.0)  # free thickness keeps a proportional size
            # The face (1.0 x 0.9 scaled to 3 x 3) stretched 1.11; the thin depth axis does not count.
            self.assertAlmostEqual(stretch, 1.111, places=2)

    def test_declared_pivot_places_the_origin_and_inspection_reads_real_scale_and_footprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb = root / "corner.glb"
            maps = [root / f"{name}.png" for name in ("basecolor", "normal", "roughness", "metallic", "emission")]
            for path in maps:
                Image.new("RGB", (16, 16), (128, 128, 128)).save(path)
            fixture = root / "fixture.py"
            # An L of two arms; its open quadrant is +X+Y.
            fixture.write_text("""import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
for loc, scale in (((-0.4, 0, 0.5), (0.2, 1.0, 1.0)), ((0, -0.4, 0.5), (1.0, 0.2, 1.0))):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    bpy.context.object.scale = scale
bpy.ops.object.select_all(action='SELECT')
bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
bpy.ops.object.join()
bpy.ops.object.transform_apply(location=True, scale=True)
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.subdivide(number_cuts=6); bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            origins = {}
            for pivot in ("bottom_center", "top_center"):
                blend = root / f"{pivot}.blend"
                subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                str(ROOT / "blender/prepare_model.py"), "--", str(glb), str(root / f"{pivot}.fbx"),
                                str(blend), *map(str, maps), "--face-budget", "5000", "--surface-source", str(maps[0]),
                                "--target-size", "3,3,3", "--pivot", pivot], check=True, capture_output=True, text=True)
                report = root / f"{pivot}.json"
                subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                str(ROOT / "blender/inspect_model.py"), "--", str(blend), str(report), "5000",
                                "--real-scale"], check=True, capture_output=True, text=True)
                origins[pivot] = json.loads(report.read_text())
            for pivot, z in (("bottom_center", "bounds_min"), ("top_center", "bounds_max")):
                measured = origins[pivot]["measured"]
                self.assertAlmostEqual(measured["origins"][0][2], measured[z][2], places=3)
                self.assertAlmostEqual(measured["origins"][0][0], 0.0, places=3)
                self.assertNotIn("largest mesh dimension exceeds expected normalized scale", origins[pivot]["warnings"])
            # Quadrants run +X+Y, -X+Y, -X-Y, +X-Y; only the L's open corner is nearly empty.
            quadrants = origins["bottom_center"]["measured"]["footprint_quadrants"]
            self.assertLess(quadrants[0], 0.2)
            self.assertTrue(all(value > 0.3 for value in quadrants[1:]), quadrants)  # arms 0.2 wide: 0.375 and 0.61

    def test_corner_arms_are_brought_to_the_declared_thickness_inside_unchanged_bounds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb = root / "corner.glb"
            maps = [root / f"{name}.png" for name in ("basecolor", "normal", "roughness", "metallic", "emission")]
            for path in maps:
                Image.new("RGB", (16, 16), (128, 128, 128)).save(path)
            fixture = root / "fixture.py"
            # An L with thick arms (0.4 of its 1 m side); its open quarter is +X+Y.
            fixture.write_text("""import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
for loc, scale in (((-0.3, 0, 0.5), (0.4, 1.0, 1.0)), ((0, -0.3, 0.5), (1.0, 0.4, 1.0))):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    bpy.context.object.scale = scale
bpy.ops.object.select_all(action='SELECT')
bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
bpy.ops.object.join()
# Off-centre, as a generated mesh can be: the M2-v1 timber corner's rescale read bounds from before recentring.
bpy.context.object.location = (0.7, 0.4, 0.2)
bpy.ops.object.transform_apply(location=True, scale=True)
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.subdivide(number_cuts=8); bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            blend, report = root / "corner.blend", root / "corner.json"
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/prepare_model.py"), "--", str(glb), str(root / "corner.fbx"), str(blend),
                            *map(str, maps), "--face-budget", "20000", "--surface-source", str(maps[0]),
                            "--target-size", "3,3,3", "--arm-thickness", "0.75"], check=True, capture_output=True, text=True)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/inspect_model.py"), "--", str(blend), str(report), "20000", "--real-scale"],
                           check=True, capture_output=True, text=True)
            measured = json.loads(report.read_text())["measured"]
        self.assertEqual([round(value, 2) for value in measured["dimensions"]], [3.0, 3.0, 3.0])
        self.assertAlmostEqual(measured["axis_stretch"], 1.0, places=2)  # the 1 m L scaled evenly to 3 m
        # Before: arms 1.2 m thick (0.4 of 3 m). After: the declared 0.75 m.
        for thickness in measured["arm_thickness"]:
            self.assertAlmostEqual(thickness, 0.75, delta=0.05)
        self.assertLess(max(measured["arm_taper"]), 1.05)  # even slabs

    def test_wedge_corner_measures_its_arms_tapering(self):
        # M2-v2 run T2: a corner filled diagonally inside its L passed the open-quarter check.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb, report = root / "wedge.glb", root / "wedge.json"
            fixture = root / "fixture.py"
            fixture.write_text("""import bpy, bmesh, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("wedge"); bm = bmesh.new()
corners = [(-1.5, -1.5), (1.5, -1.5), (-1.5, 1.5)]  # a right-angled triangle: its open quarter is +X+Y
bottom = [bm.verts.new((x, y, 0)) for x, y in corners]; top = [bm.verts.new((x, y, 3)) for x, y in corners]
bm.faces.new(bottom[::-1]); bm.faces.new(top)
for i in range(3):
    bm.faces.new((bottom[i], bottom[(i + 1) % 3], top[(i + 1) % 3], top[i]))
bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=12, use_grid_fill=True)
bm.to_mesh(mesh); bpy.context.collection.objects.link(bpy.data.objects.new("wedge", mesh))
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/inspect_model.py"), "--", str(glb), str(report), "20000", "--real-scale"],
                           check=True, capture_output=True, text=True)
            measured = json.loads(report.read_text())["measured"]
        self.assertLessEqual(min(measured["footprint_quadrants"]), 0.15)  # it passes the open-quarter check
        self.assertGreater(min(measured["arm_taper"]), 1.25)


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderLocalRepairTests(unittest.TestCase):
    def test_local_repair_closes_holes_without_remeshing_detail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb, out = root / "holed.glb", root / "prepared.glb"
            fixture = root / "fixture.py"
            fixture.write_text("""import bpy, bmesh, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=0.5, location=(0, 0, 0.5))
obj = bpy.context.object
bm = bmesh.new(); bm.from_mesh(obj.data); bm.faces.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[bm.faces[i] for i in (100, 101, 102, 900, 901)], context="FACES")  # open holes
bm.to_mesh(obj.data); bm.free()
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format="GLB")
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            result = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                     str(ROOT / "blender/prepare_model.py"), "--", str(glb), str(out),
                                     str(root / "prepared.blend"), "--mesh-only", "--face-budget", "100000",
                                     "--voxel-resolution", "32", "--local-repair"],
                                    check=True, capture_output=True, text=True)
            self.assertIn("Local manifold repair left boundary=0 non_manifold=0", result.stdout)
            faces = int(result.stdout.split("Input faces: ")[1].split()[0])
            self.assertGreater(faces, 3500)  # a 32-voxel remesh would leave a few hundred faces


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderEnclosedShellTests(unittest.TestCase):
    def test_local_repair_removes_hidden_inner_shell_and_keeps_outer_parts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb = root / "shells.glb"
            fixture = root / "fixture.py"
            fixture.write_text("""import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.5, location=(0, 0, 0.5))
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=0.46, location=(0, 0, 0.5))  # inner shell
bpy.ops.mesh.primitive_cube_add(size=0.1, location=(0.7, 0, 0.5))  # separate outside part
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.join()
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format="GLB")
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            # Characters (local repair) and props (GPU-remeshed, no voxel repair) both drop the hidden shell:
            # on six 2026-10-20 props every non-main component was invisible from eight views.
            for flag in ("--local-repair", "--no-voxel-repair"):
                with self.subTest(flag=flag):
                    result = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                             str(ROOT / "blender/prepare_model.py"), "--", str(glb),
                                             str(root / "out.glb"), str(root / "out.blend"), "--mesh-only",
                                             "--face-budget", "100000", "--voxel-resolution", "32", flag],
                                            check=True, capture_output=True, text=True)
                    self.assertIn("Removed enclosed inner-shell vertices: 1106", result.stdout)
                    faces = int(result.stdout.split("Input faces: ")[1].split()[0])
                    self.assertEqual(faces, 48 * 24 * 2 - 2 * 48 + 12)  # outer sphere triangulated + cube


def _rotated(points, turns):
    """Points turned about world axes in order, as Blender applies each rotation_euler step."""
    for axis, degrees in turns:
        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
        i, j = {"X": (1, 2), "Y": (2, 0), "Z": (0, 1)}[axis]
        points = points.copy()
        points[:, i], points[:, j] = c * points[:, i] - s * points[:, j], s * points[:, i] + c * points[:, j]
    return points


def _boxes_seen_from_front(boxes, turns, size, scale, centre):
    """An RGBA image and an L mask per box of axis-aligned boxes {name: (centre, size)} posed by turns, drawn as seen
    from the front: image right is +X, up is +Z."""
    images = {name: Image.new("L", size, 0) for name in boxes}
    for name, (middle, extent) in boxes.items():
        draw = ImageDraw.Draw(images[name])
        for k in range(3):
            i, j = [axis for axis in range(3) if axis != k]
            for side in (-1, 1):
                quad = np.zeros((4, 3))
                quad[:, k] = side
                quad[:, i], quad[:, j] = (-1, 1, 1, -1), (-1, -1, 1, 1)
                points = _rotated(np.array(middle) + quad * np.array(extent) / 2, turns)
                draw.polygon([(centre[0] + x * scale, centre[1] - z * scale) for x, _, z in points], fill=255)
    concept = Image.new("RGBA", size, (0, 0, 0, 0))
    for mask in images.values():
        concept.paste((120, 120, 130, 255), mask=mask)
    return concept, images


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderWeaponOrientationTests(unittest.TestCase):
    def orient(self, parts, turns, concept, grip, cuts=0, budget=1000, target="-,1.1,-", masks=None, extra=()):
        """Box parts joined into one mesh (subdivided by cuts) and turned, then the final pass with --target-size and
        --pivot grip; masks are written beside the concept for extra arguments that name them. Returns the body's
        dimensions, extremes, grip centre and recorded concept view, and every mesh object's parent, origin, world
        bounds, face count and open edges."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glb, blend = root / "weapon.glb", root / "weapon.blend"
            maps = [root / f"{name}.png" for name in ("basecolor", "normal", "roughness", "metallic", "emission")]
            for path in maps:
                Image.new("RGB", (16, 16), (128, 128, 128)).save(path)
            fixture = root / "fixture.py"
            fixture.write_text(f"""import bpy, math, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
for location, scale in {list(parts.values())!r}:
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    bpy.context.object.scale = scale
bpy.ops.object.select_all(action='SELECT')
bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
bpy.ops.object.join()
bpy.ops.object.transform_apply(scale=True)
if {cuts}:
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.subdivide(number_cuts={cuts})
    bpy.ops.object.mode_set(mode='OBJECT')
for axis, degrees in {turns!r}:
    bpy.context.object.rotation_euler = [math.radians(degrees) if name == axis else 0 for name in 'XYZ']
    bpy.ops.object.transform_apply(rotation=True)
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')
""")
            subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(glb)],
                           check=True, capture_output=True, text=True)
            concept.save(root / "concept.png")
            grip.save(root / "grip.png")
            for name, mask in (masks or {}).items():
                mask.save(root / f"{name}.png")
            prepared = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                       str(ROOT / "blender/prepare_model.py"), "--", str(glb), str(root / "weapon.fbx"),
                                       str(blend), *map(str, maps), "--face-budget", str(budget), "--surface-source",
                                       str(maps[0]), "--target-size", target, "--pivot", "grip", "--concept",
                                       str(root / "concept.png"), "--grip-mask", str(root / "grip.png"),
                                       *[str(root / value) if value.endswith(".png") else value for value in extra]],
                                      capture_output=True, text=True)
            self.assertEqual(prepared.returncode, 0, (prepared.stdout + prepared.stderr)[-3000:])
            probe, result = root / "probe.py", root / "probe.json"
            probe.write_text("""import bpy, json, sys
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
obj = next(o for o in meshes if o.parent is None)
group = obj.vertex_groups["slopforge_grip"].index
held = [v.co for v in obj.data.vertices if any(g.group == group for g in v.groups)]
ys, zs = [v.co.y for v in obj.data.vertices], [v.co.z for v in obj.data.vertices]
def record(o):
    points = [o.matrix_world @ v.co for v in o.data.vertices]
    open_edges = sum(1 for e in o.data.edges if sum(e.key in p.edge_keys for p in o.data.polygons) == 1)
    return {"parent": o.parent.name if o.parent else None, "origin": list(o.matrix_world.translation),
            "min": [min(p[i] for p in points) for i in range(3)] if points else None,
            "max": [max(p[i] for p in points) for i in range(3)] if points else None,
            "faces": len(o.data.polygons), "open_edges": open_edges, "kind": o.get("slopforge_part")}
json.dump({"dims": list(obj.dimensions), "grip": [sum(c[i] for c in held) / len(held) for i in range(3)],
           "min_y": min(ys), "max_y": max(ys), "min_z": min(zs), "max_z": max(zs),
           "view": list(obj["slopforge_concept_view"]), "body": obj.name,
           "objects": {o.name: record(o) for o in meshes}}, open(sys.argv[-1], 'w'))
""")
            probed = subprocess.run([BLENDER, "--background", str(blend), "--python-exit-code", "1", "--python",
                                     str(probe), "--", str(result)], capture_output=True, text=True)
            self.assertEqual(probed.returncode, 0, (probed.stdout + probed.stderr)[-3000:])
            inspections = {}
            for label, model in (("inspection", blend), ("fbx_inspection", root / "weapon.fbx")):
                inspected = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                            str(ROOT / "blender/inspect_model.py"), "--", str(model),
                                            str(root / f"{label}.json"), str(budget), "--real-scale"],
                                           capture_output=True, text=True)
                self.assertEqual(inspected.returncode, 0, (inspected.stdout + inspected.stderr)[-3000:])
                inspections[label] = json.loads((root / f"{label}.json").read_text())["measured"]
            return {**json.loads(result.read_text()), **inspections}

    def test_a_weapon_turns_its_tip_forward_and_is_held_at_its_grip(self):
        # A sword drawn tip right; its mesh is turned 30 degrees, as a reconstruction can be. Final pass: tip along
        # -Y (Unity +Z), 1.1 m long, origin at the centre of what the grip mask covers. Its blade is drawn shallower
        # than built, as on the live longsword of 2026-10-24 (4.8% of the length drawn, 5.4% built), where tilting
        # the flat mesh fitted the outline better (0.92 at phi 30 against 0.83 at 0) and rolled it.
        parts = {"blade": ((0.5, 0, 0), (1.0, 0.01, 0.08)), "guard": ((-0.015, 0, 0), (0.03, 0.06, 0.3)),
                 "grip": ((-0.14, 0, 0), (0.22, 0.05, 0.05))}
        drawn = {**parts, "blade": ((0.5, 0, 0), (1.0, 0.01, 0.07))}
        concept, masks = _boxes_seen_from_front(drawn, [], (512, 128), 377.6, (114.4, 64))
        measured = self.orient(parts, [("Z", -30)], concept, masks["grip"])
        self.assertAlmostEqual(measured["dims"][1], 1.1, places=3)  # its length runs along y
        # Turned exactly, not in the fit's 5-degree steps, and not rolled about its length: x is the guard's 0.06
        # thickness and z its 0.3 height, at 1.1/1.25 scale.
        self.assertAlmostEqual(measured["dims"][0], 0.053, delta=0.003)
        self.assertAlmostEqual(measured["dims"][2], 0.264, delta=0.005)
        # The grip's centre is 1.14 of the sword's 1.25 units behind the tip: at 1.1 m the tip is 1.003 m forward
        # (-Y) of the origin and the pommel end 0.097 m behind it.
        self.assertAlmostEqual(measured["min_y"], -1.003, delta=0.03)
        self.assertAlmostEqual(measured["max_y"], 0.097, delta=0.03)
        fit, theta, _phi, alignment = measured["view"]
        self.assertGreater(fit, 0.7)  # boxes against a hand-drawn concept; generated weapons fit closer
        self.assertLessEqual(abs(abs(theta) - 30), 5)  # the fit searches in 5-degree steps
        self.assertGreater(alignment, 0.8)

    def test_a_weapon_rebuilt_facing_the_other_way_still_points_its_tip_forward(self):
        # TRELLIS.2 rebuilt three of four side-profile swords turned 180 degrees, so the concept's view is only
        # matched from behind (2026-10-24). The fit searches the full turn and the tip still ends forward.
        parts = {"blade": ((0.5, 0, 0), (1.0, 0.01, 0.08)), "guard": ((-0.015, 0, 0), (0.03, 0.06, 0.3)),
                 "grip": ((-0.14, 0, 0), (0.22, 0.05, 0.05))}
        concept, masks = _boxes_seen_from_front(parts, [], (512, 128), 377.6, (114.4, 64))
        measured = self.orient(parts, [("Z", 180)], concept, masks["grip"])
        self.assertAlmostEqual(measured["min_y"], -1.003, delta=0.03)  # the tip, forward
        self.assertAlmostEqual(measured["max_y"], 0.097, delta=0.03)
        fit, theta, _phi, alignment = measured["view"]
        self.assertGreater(fit, 0.7)  # boxes against a drawn concept, as above
        self.assertGreaterEqual(abs(theta), 175)

    def test_moving_parts_are_split_from_the_body_with_pivots_by_kind(self):
        # W8: a slide and a hinged part are cut from one connected body along masks drawn on its concept, closed, and
        # parented to the body: a slide pivots at its box centre, a hinge on its cut. The body is a finely divided
        # slab so the cuts run through it, on its 0.025 grid (z from -0.2 to 0.2).
        body = {"body": ((0, 0, 0), (1.0, 0.1, 0.4))}
        regions = {"slide": ((0, 0, 0.1375), (1.0, 0.1, 0.125)), "lever": ((0, 0, -0.15), (1.0, 0.1, 0.1)),
                   "grip": ((-0.375, 0, -0.0125), (0.15, 0.1, 0.125))}
        concept, masks = _boxes_seen_from_front({**body, **regions}, [], (512, 256), 400, (256, 128))
        # A one-vertex-wide gap across the slide mask: a strip of body faces inside the slide, as the ragged masks of
        # a live pistol left slivers along the cut (2026-10-24: 12-19 body pieces). Islands join the side around them.
        ImageDraw.Draw(masks["slide"]).rectangle((100, 75, 412, 81), fill=0)  # the vertex row at z 0.125
        measured = self.orient(body, [], concept, masks["grip"], cuts=15, budget=20000, target="-,1.0,-",
                               masks={"slide": masks["slide"], "lever": masks["lever"]},
                               extra=("--part", "slide", "slide", "slide.png", "--part", "lever", "hinge", "lever.png"))
        objects, body_name = measured["objects"], measured["body"]
        self.assertEqual(sorted(objects), sorted([body_name, "slide", "lever"]))
        slide, lever, rest = objects["slide"], objects["lever"], objects[body_name]
        self.assertEqual((slide["parent"], lever["parent"]), (body_name, body_name))
        self.assertEqual((slide["kind"], lever["kind"]), ("slide", "hinge"))
        for name, record in objects.items():
            self.assertEqual(record["open_edges"], 0, name)  # every piece is closed over its cut
        # Bottom-centred at 0: the lever is z 0-0.1, the slide 0.275-0.4, and the body keeps what lies between.
        self.assertAlmostEqual(lever["min"][2], 0.0, delta=0.01)
        self.assertAlmostEqual(lever["max"][2], 0.1, delta=0.03)
        self.assertAlmostEqual(slide["min"][2], 0.275, delta=0.03)
        self.assertAlmostEqual(rest["min"][2], lever["max"][2], delta=0.001)
        self.assertAlmostEqual(rest["max"][2], slide["min"][2], delta=0.001)
        centre = [(low + high) / 2 for low, high in zip(slide["min"], slide["max"])]
        for axis in range(3):
            self.assertAlmostEqual(slide["origin"][axis], centre[axis], delta=1e-4)  # a slide pivots at its centre
        self.assertAlmostEqual(lever["origin"][2], lever["max"][2], delta=1e-4)  # a hinge pivots on its cut
        inspection = measured["inspection"]
        self.assertEqual(sorted((part["name"], part["kind"], part["parent"]) for part in inspection["parts"]),
                         [("lever", "hinge", body_name), ("slide", "slide", body_name)])
        self.assertEqual(inspection["component_count"], 1)  # the parts are not stray pieces of the body
        exported = measured["fbx_inspection"]  # the FBX keeps the hierarchy, the pivots and each part's kind
        self.assertEqual(sorted((part["name"], part["kind"]) for part in exported["parts"]),
                         [("lever", "hinge"), ("slide", "slide")])
        for part in exported["parts"]:
            for axis in range(3):
                self.assertAlmostEqual(part["pivot"][axis], objects[part["name"]]["origin"][axis], delta=1e-3)

    def test_a_weapon_kept_in_its_concept_pose_is_levelled(self):
        # A crossbow drawn from above at three-quarters. Pixal3D keeps the concept's pose (2026-10-24), so the mesh
        # is turned 25 degrees and tilted 35 towards the camera, as drawn. Its bow spreads wider than its stock is
        # long, so only the grip tells which axis is the length. Final pass: stock along -Y tip first, bow across x,
        # lying flat with its grip below the stock.
        parts = {"stock": ((0, 0, 0), (1.0, 0.06, 0.08)), "bow": ((0.42, 0, 0), (0.04, 1.1, 0.03)),
                 "grip": ((-0.25, 0, -0.08), (0.08, 0.05, 0.08))}
        pose = [("Z", 25), ("X", 35)]
        concept, masks = _boxes_seen_from_front(parts, pose, (512, 384), 350, (256, 192))
        measured = self.orient(parts, pose, concept, masks["grip"])
        self.assertAlmostEqual(measured["dims"][1], 1.1, places=3)
        self.assertAlmostEqual(measured["dims"][0], 1.21, delta=0.01)  # the bow's 1.1 at 1.1 scale
        # Stock top to grip bottom, 0.16 at 1.1 scale; left tilted it measured 0.54. The grip below the stock
        # leans the fitted plane about a degree here, and up to 2 degrees on live crossbows (docs/WEAPONS.md).
        self.assertAlmostEqual(measured["dims"][2], 0.176, delta=0.03)
        self.assertLess(measured["min_y"], -0.7)  # the tip, 0.75 ahead of the grip at 1.1 scale, is forward
        self.assertGreater(measured["max_z"], -measured["min_z"])  # the stock sits above the grip
