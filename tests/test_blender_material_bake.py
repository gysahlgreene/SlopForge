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


def _swatch(basecolor):
    """A surface swatch beside a fixture's base colour map: the pass refuses to bake the swatch over the map itself."""
    swatch = Path(basecolor).with_name("surface.png")
    shutil.copy(basecolor, swatch)
    return swatch
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
class BlenderConceptViewTests(unittest.TestCase):
    """blender/concept_view.py renders a candidate from the concept's fitted view. A weapon generated as parts is
    several mesh objects; the view must join them (2026-10-25: every parts candidate failed "Expected one mesh",
    so metal lightness and colour transfer never ran on that route)."""

    def test_a_candidate_of_several_meshes_renders_from_the_concept_view(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture.py").write_text("""import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
for name, centre, size in (('body', (0, 0, 0), (1.0, 0.2, 0.2)), ('slide', (0, 0, 0.15), (0.8, 0.1, 0.1))):
    bpy.ops.mesh.primitive_cube_add(size=1, location=centre)
    o = bpy.context.object; o.name = name; o.data.name = name; o.scale = size
    bpy.ops.object.transform_apply(location=True, scale=True)
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode='OBJECT')
    o.data.uv_layers[0].name = 'UVMap'
    o.data.materials.append(bpy.data.materials.new(name))
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB', use_selection=True)
""")
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(root / "fixture.py"),
                            "--", str(root / "parts.glb")], check=True, capture_output=True, text=True)
            concept = Image.new("RGBA", (200, 80), (0, 0, 0, 0))
            concept.paste((110, 110, 110, 255), (20, 30, 180, 50)); concept.paste((110, 110, 110, 255), (36, 22, 164, 30))
            concept.save(root / "concept.png")
            Image.new("RGB", (64, 64), (200, 40, 40)).save(root / "basecolor.png")
            request = {"model": str(root / "parts.glb"), "basecolor": str(root / "basecolor.png"),
                       "concept": str(root / "concept.png"), "prefix": str(root / "view"),
                       "report": str(root / "view.json"), "min_iou": 0.3, "uv": False, "size": 256}
            (root / "request.json").write_text(json.dumps(request))
            subprocess.run([BLENDER, "--background", "--python", str(ROOT / "blender/concept_view.py"), "--",
                            str(root / "request.json")], capture_output=True, text=True)
            report = json.loads((root / "view.json").read_text())
            self.assertEqual(report.get("status"), "rendered", report)
            rendered = np.asarray(Image.open(root / "view_base.png").convert("RGBA"))
            self.assertGreater((rendered[..., 3] > 0).mean(), 0.05)  # something of the joined weapon is in view
            self.assertGreater(rendered[rendered[..., 3] > 0][..., 0].mean(), 150)  # in the base colour


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderPreparePartsTests(unittest.TestCase):
    """blender/prepare_parts.py: generated parts (one textured GLB node each) are reduced to shares of the budget,
    unwrapped into one base-colour atlas with a metallic atlas by part, and exported with their node names kept."""

    def test_parts_are_reduced_into_one_atlas_with_their_names_kept(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "fixture.py"
            fixture.write_text("""import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
def part(name, size, colour, cuts):
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = bpy.context.object; o.name = name; o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.subdivide(number_cuts=cuts); bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode='OBJECT')
    image = bpy.data.images.new(name + '_tex', 16, 16); image.pixels = list(colour) * 256; image.pack()
    m = bpy.data.materials.new(name); m.use_nodes = True
    tex = m.node_tree.nodes.new('ShaderNodeTexImage'); tex.image = image
    m.node_tree.links.new(tex.outputs['Color'], m.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    m.node_tree.nodes['Principled BSDF'].inputs['Metallic'].default_value = 1.0  # glTF's default: a diffuse bake of a metal is black
    o.data.materials.append(m)
part('body', (2, 1, 1), (1, 0, 0, 1), 24)
import mathutils, random
random.seed(1)
body = bpy.data.objects['body']
for v in body.data.vertices:  # bumps the reduced mesh loses and the normal bake must keep
    v.co += v.normal * 0.02 * mathutils.noise.noise(v.co * 6.0)
part('slide', (2, 0.3, 0.3), (0, 0, 1, 1), 6)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB', use_selection=True)
""")
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(fixture), "--",
                            str(root / "parts.glb")], check=True, capture_output=True, text=True)
            (root / "parts.json").write_text(json.dumps({"parts": {"body": {"kind": "body"}, "slide": {"kind": "slide"}}}))
            prepared = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                       str(ROOT / "blender/prepare_parts.py"), "--", str(root / "parts.glb"),
                                       str(root / "processed.glb"), str(root / "processed.blend"),
                                       "--parts-json", str(root / "parts.json"), "--face-budget", "400",
                                       "--basecolor-output", str(root / "atlas.png"), "--metallic-output",
                                       str(root / "metal.png"), "--texture-size", "256",
                                       "--normal-output", str(root / "normal.png"),
                                       "--metal", "body=1", "--metal", "slide=0"], capture_output=True, text=True)
            self.assertEqual(prepared.returncode, 0, (prepared.stdout + prepared.stderr)[-3000:])
            probe, result = root / "probe.py", root / "probe.json"
            probe.write_text("""import bpy, json, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=sys.argv[-2])
report = {}
for o in [o for o in bpy.data.objects if o.type == 'MESH']:
    uv = o.data.uv_layers.active.data
    report[o.name] = {"faces": len(o.data.polygons), "uv_layers": len(o.data.uv_layers),
                      "uv_centre": [sum(uv[i].uv[k] for i in o.data.polygons[0].loop_indices) / len(o.data.polygons[0].loop_indices) for k in range(2)],
                      "images": [n.image.name for m in o.data.materials if m for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image]}
json.dump(report, open(sys.argv[-1], 'w'))
""")
            probed = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(probe), "--",
                                     str(root / "processed.glb"), str(result)], capture_output=True, text=True)
            self.assertEqual(probed.returncode, 0, (probed.stdout + probed.stderr)[-3000:])
            report = json.loads(result.read_text())
            self.assertEqual(sorted(report), ["body", "slide"])
            self.assertLessEqual(sum(item["faces"] for item in report.values()), 400)
            self.assertTrue(all(item["faces"] >= 8 for item in report.values()))
            self.assertEqual([item["uv_layers"] for item in report.values()], [1, 1])
            self.assertEqual([item["images"] for item in report.values()], [[], []])  # textures live in the atlas
            atlas = np.asarray(Image.open(root / "atlas.png").convert("RGB"), dtype=int)
            red = ((atlas[..., 0] > 150) & (atlas[..., 2] < 100)).mean()
            blue = ((atlas[..., 2] > 150) & (atlas[..., 0] < 100)).mean()
            self.assertGreater(red, 0.01); self.assertGreater(blue, 0.01)
            metal = np.asarray(Image.open(root / "metal.png").convert("L"), dtype=float) / 255
            for name, expected in (("body", 1.0), ("slide", 0.0)):
                u, v = report[name]["uv_centre"]
                x, y = int(u * (metal.shape[1] - 1)), int((1 - v) * (metal.shape[0] - 1))
                self.assertAlmostEqual(float(metal[y, x]), expected, delta=0.1, msg=name)
            self.assertIn("Part slide:", prepared.stdout)
            # the tangent normal baked from the part before its reduction: bumps on the body, flat on the slide
            normal = np.asarray(Image.open(root / "normal.png").convert("RGB"), dtype=float)
            body_island = (atlas[..., 0] > 150) & (atlas[..., 2] < 100)
            slide_island = (atlas[..., 2] > 150) & (atlas[..., 0] < 100)
            self.assertGreater(normal[body_island][:, :2].std(), 4.0)
            self.assertLess(normal[slide_island][:, :2].std(), 2.0)
            self.assertTrue((np.abs(normal[~(body_island | slide_island)] - (128, 128, 255)).mean() < 8))


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
                            "--surface-source", str(_swatch(maps[0])), "--preview-dir", str(previews)],
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
                            "--face-budget", "1000", "--surface-source", str(_swatch(maps[0])), "--preview-dir", str(previews)],
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
                            *map(str, maps), "--face-budget", "1000", "--surface-source", str(_swatch(maps[0])),
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
                                str(blend), *map(str, maps), "--face-budget", "5000", "--surface-source", str(_swatch(maps[0])),
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
                            *map(str, maps), "--face-budget", "20000", "--surface-source", str(_swatch(maps[0])),
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
class BlenderSurfaceSourceGuardTests(unittest.TestCase):
    def test_the_surface_source_may_not_be_the_base_colour_it_bakes_into(self):
        # Given a candidate's base colour map as the swatch, the pass tiled it over itself (2026-10-24).
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            maps = [root / f"{name}.png" for name in ("basecolor", "normal", "roughness", "metallic", "emission")]
            for path in maps:
                Image.new("RGB", (16, 16), (128, 128, 128)).save(path)
            script = root / "fixture.py"
            script.write_text("import bpy, sys\nbpy.ops.wm.read_factory_settings(use_empty=True)\n"
                              "bpy.ops.mesh.primitive_cube_add(size=1)\n"
                              "bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB')\n")
            subprocess.run([BLENDER, "--background", "--python", str(script), "--", str(root / "cube.glb")],
                           check=True, capture_output=True)
            result = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                     str(ROOT / "blender/prepare_model.py"), "--", str(root / "cube.glb"),
                                     str(root / "out.fbx"), str(root / "out.blend"), *map(str, maps),
                                     "--face-budget", "1000", "--surface-source", str(maps[0])],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("must not be the base colour map", result.stdout + result.stderr)
            with Image.open(maps[0]) as image:
                self.assertEqual(image.getpixel((0, 0)), (128, 128, 128))  # untouched


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderWeaponOrientationTests(unittest.TestCase):
    def orient(self, parts, turns, concept, grip, cuts=0, budget=1000, target="-,1.1,-", masks=None, extra=(),
               fixture_script=None, files=None, pivot="grip"):
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
            for name, text in (files or {}).items():
                (root / name).write_text(text)
            fixture.write_text(fixture_script or f"""import bpy, math, sys
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
            if grip is not None:
                grip.save(root / "grip.png")
            for name, mask in (masks or {}).items():
                mask.save(root / f"{name}.png")
            prepared = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                                       str(ROOT / "blender/prepare_model.py"), "--", str(glb), str(root / "weapon.fbx"),
                                       str(blend), *map(str, maps), "--face-budget", str(budget), "--surface-source",
                                       str(_swatch(maps[0])), "--target-size", target, "--pivot", pivot, "--concept",
                                       str(root / "concept.png"),
                                       *(["--grip-mask", str(root / "grip.png")] if grip is not None else []),
                                       *[str(root / value) if value.endswith((".png", ".json")) else value for value in extra]],
                                      capture_output=True, text=True)
            self.assertEqual(prepared.returncode, 0, (prepared.stdout + prepared.stderr)[-3000:])
            (root / "prepare.log").write_text(prepared.stdout + prepared.stderr)  # for a look when a probe fails
            probe, result = root / "probe.py", root / "probe.json"
            probe.write_text("""import bpy, json, sys
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
obj = next(o for o in meshes if o.parent is None)
group = obj.vertex_groups["slopforge_grip"].index if "slopforge_grip" in obj.vertex_groups else None
held = [v.co for v in obj.data.vertices if group is not None and any(g.group == group for g in v.groups)] or [obj.location]
ys, zs = [v.co.y for v in obj.data.vertices], [v.co.z for v in obj.data.vertices]
def record(o):
    points = [o.matrix_world @ v.co for v in o.data.vertices]
    uses = {}
    for p in o.data.polygons:
        for key in p.edge_keys:
            uses[key] = uses.get(key, 0) + 1
    open_edges = sum(1 for e in o.data.edges if uses.get(e.key, 0) == 1)
    cap = [(o.matrix_world @ o.data.vertices[i].co).z for p in o.data.polygons if not p.use_smooth for i in p.vertices]
    return {"parent": o.parent.name if o.parent else None, "origin": list(o.matrix_world.translation),
            "sharp": sum(1 for e in o.data.edges if e.use_edge_sharp),
            "cap_spread": (max(cap) - min(cap)) if cap else None,
            "min": [min(p[i] for p in points) for i in range(3)] if points else None,
            "max": [max(p[i] for p in points) for i in range(3)] if points else None,
            "faces": len(o.data.polygons), "open_edges": open_edges, "kind": o.get("slopforge_part"),
            "fills": sum(a.value for a in o.data.attributes["slopforge_fill"].data) if "slopforge_fill" in o.data.attributes else 0}
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

    PARTS_FIXTURE = """import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
def box(name, centre, size):
    bpy.ops.mesh.primitive_cube_add(size=1, location=centre)
    o = bpy.context.object; o.name = name; o.data.name = name; o.scale = size  # meshes named like the parts, as the tool writes them
    bpy.ops.object.transform_apply(location=True, scale=True)
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.subdivide(number_cuts=3); bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode='OBJECT')
    o.data.materials.append(bpy.data.materials.new(name))
box('slide', (0, 0, 0.15), (0.8, 0.1, 0.1))        # on top of the body, touching its top face; first on purpose
box('body', (0, 0, 0), (1.0, 0.2, 0.2))              # (review 2026-10-25: the join must not steal a part's name)
box('trigger', (0, 0, -0.15), (0.05, 0.02, 0.1))  # hangs below the body's middle, touching its underside
box('floating', (-0.2, 0, -0.5), (0.05, 0.05, 0.05))  # a hinge that touches nothing
box('grip', (0.4, 0, -0.1), (0.1, 0.22, 0.05))  # a static part: generated separately, keeps the body one piece
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB', use_selection=True)
"""
    PARTS_TABLE = json.dumps({"parts": {"body": {"kind": "body", "id": 4}, "slide": {"kind": "slide", "id": 1},
                                        "trigger": {"kind": "hinge", "id": 2}, "floating": {"kind": "hinge", "id": 3},
                                        "grip": {"kind": "grip", "id": 5}}})

    def test_parts_from_a_glb_become_children_with_pivots_by_kind(self):
        # A weapon generated as parts (OmniPart): the final pass tags each node's faces, joins, orients and scales
        # as one, then separates the hinges and slides with pivots by kind: a slide at its box centre, a hinge at
        # its contact with the body, or at its box centre when it touches nothing.
        concept = Image.new("RGBA", (200, 80), (0, 0, 0, 0))
        concept.paste((110, 110, 110, 255), (20, 30, 180, 50)); concept.paste((110, 110, 110, 255), (36, 22, 164, 30))
        concept.paste((110, 110, 110, 255), (96, 50, 104, 58))  # the trigger below the body
        grip = Image.new("L", (200, 80), 0); grip.paste(255, (150, 30, 180, 50))
        masks = {}
        for name, box in (("slide", (36, 22, 164, 30)), ("trigger", (96, 50, 104, 58)), ("floating", (0, 0, 16, 16))):
            masks[name] = Image.new("L", (200, 80), 0); masks[name].paste(255, box)  # floating's mask is nowhere near it
        measured = self.orient({}, [], concept, grip, budget=20000, target="-,1.0,-", masks=masks,
                               extra=("--part", "slide", "slide", "slide.png", "--part", "trigger", "hinge", "trigger.png",
                                      "--part", "floating", "hinge", "floating.png", "--parts-json", "parts.json"),
                               fixture_script=self.PARTS_FIXTURE, files={"parts.json": self.PARTS_TABLE})
        objects = measured["objects"]
        coverage = measured["inspection"]["part_coverage"]  # the generated part projected onto its mask
        self.assertGreaterEqual(coverage["slide"], 0.7)
        self.assertGreaterEqual(coverage["trigger"], 0.5)
        self.assertLessEqual(coverage["floating"], 0.2)
        overflow = measured["inspection"]["part_overflow"]  # recorded, not yet enforced: cells outside the mask
        self.assertGreaterEqual(overflow["floating"], 0.5)
        self.assertLess(overflow["slide"], overflow["floating"])  # coarse on this fixture's crude concept
        self.assertEqual(measured["inspection"]["part_components"]["slide"], 1)
        body = objects[measured["body"]]
        self.assertEqual({name: item["kind"] for name, item in objects.items() if item["parent"]},
                         {"slide": "slide", "trigger": "hinge", "floating": "hinge", "grip": "grip"})  # exact names
        self.assertEqual(measured["inspection"]["component_count"], 1)  # the body is one piece: every part is a child
        for name in ("slide", "floating"):  # box centres
            centre = [(objects[name]["min"][i] + objects[name]["max"][i]) / 2 for i in range(3)]
            for axis in range(3):
                self.assertAlmostEqual(objects[name]["origin"][axis], centre[axis], delta=0.005, msg=name)
        trigger = objects["trigger"]
        self.assertAlmostEqual(trigger["origin"][2], body["min"][2], delta=0.005)  # at the body's underside
        self.assertAlmostEqual(trigger["origin"][1], (trigger["min"][1] + trigger["max"][1]) / 2, delta=0.02)
        self.assertEqual(sorted(part["name"] for part in measured["fbx_inspection"]["parts"]),
                         ["floating", "grip", "slide", "trigger"])
        self.assertEqual(sum(1 for item in objects.values() if item["open_edges"]), 0)  # nothing was cut open
        self.assertGreater(objects[measured["body"]]["sharp"], 0)  # hard edges stay hard: sharp by angle on this route

    CHEST_FIXTURE = """import bpy, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
def box(name, centre, size):
    bpy.ops.mesh.primitive_cube_add(size=1, location=centre)
    o = bpy.context.object; o.name = name; o.data.name = name; o.scale = size
    bpy.ops.object.transform_apply(location=True, scale=True)
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.subdivide(number_cuts=3); bpy.ops.uv.smart_project(); bpy.ops.object.mode_set(mode='OBJECT')
    o.data.materials.append(bpy.data.materials.new(name))
box('body', (0, 0, 0.2), (0.6, 0.4, 0.4))
box('lid', (0, 0, 0.45), (0.6, 0.4, 0.1))  # on the body, touching along its whole rim
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB', use_selection=True)
"""

    HYBRID_FIXTURE = """import bpy, bmesh, sys
bpy.ops.wm.read_factory_settings(use_empty=True)
# one closed surface, as TRELLIS.2 makes it, cut into the glTF nodes hybrid_apply.py writes: open where they were cut
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.25))
whole = bpy.context.object; whole.scale = (0.6, 0.4, 0.5)
bpy.ops.object.transform_apply(location=True, scale=True)
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.subdivide(number_cuts=9); bpy.ops.mesh.quads_convert_to_tris(); bpy.ops.uv.smart_project()
bpy.ops.object.mode_set(mode='OBJECT')
whole.data.materials.append(bpy.data.materials.new('surface'))
def piece(name, keep):
    copy = whole.copy(); copy.data = whole.data.copy(); copy.name = copy.data.name = name
    bpy.context.collection.objects.link(copy)
    bm = bmesh.new(); bm.from_mesh(copy.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if not keep(f.calc_center_median())], context="FACES")
    bm.to_mesh(copy.data); bm.free()
PART_PIECES
bpy.data.objects.remove(whole)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format='GLB', use_selection=True)
"""

    def _hybrid(self, pieces, kind, motion):
        concept = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        concept.paste((120, 90, 60, 255), (20, 40, 100, 110)); concept.paste((120, 90, 60, 255), (20, 28, 100, 40))
        name = "lid" if kind == "hinge" else "drawer"
        masks = {name: Image.new("L", (120, 120), 0)}
        masks[name].paste(255, (20, 28, 100, 40) if kind == "hinge" else (30, 60, 90, 90))
        table = json.dumps({"parts": {"body": {"kind": "body", "id": 1}, name: {"kind": kind, "id": 2}},
                            "close_openings": True})
        return self.orient({}, [], concept, None, budget=20000, target="-,-,0.5", masks=masks, pivot="bottom_center",
                           extra=("--part", name, kind, f"{name}.png", *(("--anchor", "lid=back-bottom")
                                  if kind == "hinge" else ()), "--parts-json", "parts.json", "--motion", motion),
                           fixture_script=self.HYBRID_FIXTURE.replace("PART_PIECES", pieces),
                           files={"parts.json": table})

    def test_a_lid_cut_from_one_surface_is_closed_across_and_its_chest_hollowed(self):
        # Hybrid parts are pieces of one generated surface, open where they were cut apart (docs/WEAPONS.md, Hybrid
        # parts). The lid is closed by the interface between it and the body; the body's opening under the lid is a
        # container's and becomes a cavity. Neither piece of closing counts as a piece of its own.
        measured = self._hybrid("piece('body', lambda c: c.z < 0.4)\npiece('lid', lambda c: c.z >= 0.4)", "hinge",
                                "lid=x:-100..0")
        lid, body = measured["objects"]["lid"], measured["objects"][measured["body"]]
        self.assertGreater(lid["fills"], 0)  # its underside
        self.assertGreater(body["fills"], 0)  # the cavity
        self.assertEqual(measured["inspection"]["component_count"], 1)
        self.assertLessEqual(measured["inspection"]["part_penetration"]["lid"], 0.02)

    def test_a_drawer_cut_from_one_surface_closes_both_pieces(self):
        # A slide is not a container's lid: the body takes the interface too, flipped, where the drawer was cut out.
        measured = self._hybrid("piece('body', lambda c: not (c.y < -0.15 and 0.1 < c.z < 0.3))\n"
                                "piece('drawer', lambda c: c.y < -0.15 and 0.1 < c.z < 0.3)", "slide",
                                "drawer=z:0..0.2")
        drawer, body = measured["objects"]["drawer"], measured["objects"][measured["body"]]
        self.assertGreater(drawer["fills"], 0)
        self.assertGreater(body["fills"], 0)
        self.assertEqual(measured["inspection"]["component_count"], 1)

    def test_a_prop_with_a_lid_is_split_without_a_grip(self):
        # A chest: a hinge declared on a prop with a bottom-centre pivot. No grip mask, no full turn, no tip
        # check; the lid becomes a child with coverage measured, and the body stays one piece.
        concept = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        concept.paste((120, 90, 60, 255), (20, 40, 100, 110)); concept.paste((120, 90, 60, 255), (20, 28, 100, 40))
        masks = {"lid": Image.new("L", (120, 120), 0)}; masks["lid"].paste(255, (20, 28, 100, 40))
        parts_json = json.dumps({"parts": {"body": {"kind": "body", "id": 2}, "lid": {"kind": "hinge", "id": 1}}})
        measured = self.orient({}, [], concept, None, budget=20000, target="-,-,0.6", masks=masks, pivot="bottom_center",
                               extra=("--part", "lid", "hinge", "lid.png", "--anchor", "lid=back-top",
                                      "--parts-json", "parts.json", "--motion", "lid=x:-100..0"),
                               fixture_script=self.CHEST_FIXTURE, files={"parts.json": parts_json})
        objects = measured["objects"]
        # swept through its declared range (Unity's sense: a negative turn about x lifts a back-hinged lid): the
        # share of the lid's vertices inside the body over rest; the gate retries a seed that sweeps into the body
        self.assertLessEqual(measured["inspection"]["part_penetration"]["lid"], 0.02)
        # the faces of a box and its lid agree with their neighbours: a crumpled reduction would read ~0.5
        self.assertLess(max(measured["inspection"]["folded_edge_share"].values()), 0.05)
        sunk = self.orient({}, [], concept, None, budget=20000, target="-,-,0.6", masks=masks, pivot="bottom_center",
                           extra=("--part", "lid", "hinge", "lid.png", "--anchor", "lid=back-top",
                                  "--parts-json", "parts.json", "--motion", "lid=x:0..100"),
                           fixture_script=self.CHEST_FIXTURE, files={"parts.json": parts_json})
        self.assertGreater(sunk["inspection"]["part_penetration"]["lid"], 0.1)  # a positive turn sinks it
        self.assertEqual({name: item["kind"] for name, item in objects.items() if item["parent"]}, {"lid": "hinge"})
        self.assertEqual(measured["inspection"]["component_count"], 1)
        self.assertGreaterEqual(measured["inspection"]["part_coverage"]["lid"], 0.5)
        height = objects["lid"]["max"][2] - objects[measured["body"]]["min"][2]
        self.assertAlmostEqual(height, 0.6, delta=0.02)  # the target size held over body and lid together
        # a prop's frame: its width (the longer horizontal axis) along X, its depth along Y, front towards -Y; the
        # weapon rule (length to -Y) would turn the chest on its side and put the lid's "back" edge at an end
        body = objects[measured["body"]]
        self.assertAlmostEqual(body["max"][0] - body["min"][0], 0.72, delta=0.02)
        self.assertAlmostEqual(body["max"][1] - body["min"][1], 0.48, delta=0.02)
        # anchored back-top: the pivot on the lid's back edge (+Y) at its top (+Z), centred along X
        lid = objects["lid"]
        self.assertAlmostEqual(lid["origin"][1], lid["max"][1], delta=0.005)
        self.assertAlmostEqual(lid["origin"][2], lid["max"][2], delta=0.005)
        self.assertAlmostEqual(lid["origin"][0], (lid["min"][0] + lid["max"][0]) / 2, delta=0.005)

    def test_tag_parts_matches_gltf_names_after_blender_renames_a_second_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture.py").write_text(self.PARTS_FIXTURE)
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(root / "fixture.py"),
                            "--", str(root / "parts.glb")], check=True, capture_output=True, text=True)
            (root / "parts.json").write_text(self.PARTS_TABLE)
            probe = root / "probe.py"
            probe.write_text(f"""import bpy, json, sys
sys.path.insert(0, {str(ROOT / "blender")!r})
from mesh_cleanup import tag_parts
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={str(root / "parts.glb")!r})
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath={str(root / "parts.glb")!r})
second = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
table = json.load(open({str(root / "parts.json")!r}))["parts"]
tag_parts(second, table)
print("TAGS", json.dumps({{o.name: sorted(set(a.value for a in o.data.attributes["slopforge_part"].data)) for o in second}}))
""")
            probed = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(probe)],
                                    capture_output=True, text=True)
            self.assertEqual(probed.returncode, 0, (probed.stdout + probed.stderr)[-3000:])
            tags = json.loads(next(line for line in probed.stdout.splitlines() if line.startswith("TAGS "))[5:])
            self.assertEqual(tags, {"body.001": [4], "slide.001": [1], "trigger.001": [2], "floating.001": [3], "grip.001": [5]})

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
        # A jagged bottom edge on the slide mask, as SAM draws one: the cut is snapped to its fitted plane.
        for x in range(60, 452, 20):
            ImageDraw.Draw(masks["slide"]).rectangle((x, 94, x + 10, 104), fill=0)
        measured = self.orient(body, [], concept, masks["grip"], cuts=15, budget=20000, target="-,1.0,-",
                               masks={"slide": masks["slide"], "lever": masks["lever"]},
                               extra=("--part", "slide", "slide", "slide.png", "--part", "lever", "hinge", "lever.png"))
        objects, body_name = measured["objects"], measured["body"]
        self.assertEqual(sorted(objects), sorted([body_name, "slide", "slide_barrel", "lever"]))
        slide, lever, rest, barrel = objects["slide"], objects["lever"], objects[body_name], objects["slide_barrel"]
        self.assertEqual((slide["parent"], lever["parent"]), (body_name, body_name))
        self.assertEqual((slide["kind"], lever["kind"]), ("slide", "hinge"))
        for name, record in objects.items():
            self.assertEqual(record["open_edges"], 0, name)  # every piece is closed over its cut
        # Bottom-centred at 0: the lever is z 0-0.1, the slide 0.275-0.4, and the body keeps what lies between.
        self.assertAlmostEqual(lever["min"][2], 0.0, delta=0.01)
        self.assertAlmostEqual(lever["max"][2], 0.1, delta=0.03)
        self.assertAlmostEqual(slide["min"][2], 0.275, delta=0.03)
        # The cuts meet on their fitted planes, which the jagged mask tilts by a fraction of a degree over the length.
        self.assertAlmostEqual(rest["min"][2], lever["max"][2], delta=0.005)
        self.assertAlmostEqual(barrel["max"][2] - slide["min"][2], 0.8 * (slide["max"][2] - slide["min"][2]), delta=0.012)
        self.assertAlmostEqual(rest["max"][2], slide["min"][2], delta=0.005)
        self.assertLess(slide["cap_spread"], 0.005)  # the cut is one flat plane despite the jagged mask (was 0.1 deep)
        centre = [(low + high) / 2 for low, high in zip(slide["min"], slide["max"])]
        for axis in range(3):
            self.assertAlmostEqual(slide["origin"][axis], centre[axis], delta=1e-4)  # a slide pivots at its centre
        self.assertAlmostEqual(lever["origin"][2], lever["max"][2], delta=1e-4)  # a hinge pivots on its cut
        # A barrel, its own static child, fills the slide's cavity: a cylinder half way up the slide's height with
        # radius 0.3 of it, so its top is 0.8 of that height above the cut.
        self.assertEqual((barrel["parent"], barrel["kind"]), (body_name, "barrel"))
        inspection = measured["inspection"]
        self.assertEqual(sorted((part["name"], part["kind"], part["parent"]) for part in inspection["parts"]),
                         [("lever", "hinge", body_name), ("slide", "slide", body_name), ("slide_barrel", "barrel", body_name)])
        self.assertEqual(inspection["component_count"], 1)  # the parts are not stray pieces of the body
        exported = measured["fbx_inspection"]  # the FBX keeps the hierarchy, the pivots and each part's kind
        self.assertEqual(sorted((part["name"], part["kind"]) for part in exported["parts"]),
                         [("lever", "hinge"), ("slide", "slide"), ("slide_barrel", "barrel")])
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


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderSweepPenetrationTests(unittest.TestCase):
    def test_a_body_away_from_the_origin_is_swept_where_it_stands(self):
        # A weapon's body keeps its object location (the grip centre, 0.27 m from the origin on a hybrid pistol).
        # The sweep built its trees from the objects, in their own space, and cast from the part's world-space
        # vertices: every ray missed the body and a slide read 0.000 where Unity's prefab read 0.025 (2026-10-25).
        # A box above the body slid 0.3 down sinks wholly into it, wherever the body stands.
        script = f'''import bpy, sys
sys.path.insert(0, {str(ROOT / "blender")!r})
from mesh_cleanup import sweep_penetration
bpy.ops.wm.read_factory_settings(use_empty=True)
for location in ((0, 0, 0), (0.1, 0.3, 0.27)):
    for o in list(bpy.data.objects): bpy.data.objects.remove(o)
    bpy.ops.mesh.primitive_cube_add(size=0.4, location=location)
    body = bpy.context.object
    bpy.ops.mesh.primitive_cube_add(size=0.2, location=(location[0], location[1], location[2] + 0.301))
    part = bpy.context.object
    part.parent = body; part.matrix_parent_inverse = body.matrix_world.inverted(); part["slopforge_part"] = "slide"
    bpy.context.view_layer.update()
    print("SUNK", location, sweep_penetration(part, [body], "y", -0.3, 0.0))
'''
        result = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        sunk = [float(line.rsplit(" ", 1)[1]) for line in result.stdout.splitlines() if line.startswith("SUNK")]
        self.assertEqual(len(sunk), 2, result.stdout[-2000:])
        self.assertGreater(sunk[0], 0.9)  # at the origin
        self.assertGreater(sunk[1], 0.9)  # away from it


    def test_a_part_moved_into_a_pocket_of_an_open_body_is_not_inside_it(self):
        # Generated bodies are open: the hybrid pistol's kept 512 open edges after closing, and by ray parity half
        # its slide sat inside the body at rest (2026-10-25). A slab with no underside and a block open to the front,
        # and a box moved from in front of them into the pocket between, touching neither: rays up and back from the
        # pocket each cross one face, odd, so parity read it inside. The winding number sees it outside.
        script = f'''import bpy, bmesh, sys
sys.path.insert(0, {str(ROOT / "blender")!r})
from mesh_cleanup import sweep_penetration
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
def box(centre, size, drop=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=centre)
    o = bpy.context.object; o.scale = size
    bpy.ops.object.transform_apply(location=True, scale=True)
    if drop:
        bm = bmesh.new(); bm.from_mesh(o.data); bm.normal_update()
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.dot(drop) > 0.9], context="FACES")
        bm.to_mesh(o.data); bm.free()
    return o
slab = box((0, 0, 0.1), (0.05, 1.0, 0.2), drop=Vector((0, 0, -1)))  # no underside
block = box((0, 0.4, -0.1), (0.05, 0.2, 0.2), drop=Vector((0, -1, 0)))  # under the slab's back (+Y), open to the front
bpy.ops.object.select_all(action="DESELECT"); block.select_set(True); slab.select_set(True)
bpy.context.view_layer.objects.active = slab; bpy.ops.object.join()  # one body, as a generated one is
part = box((0, -0.8, -0.1), (0.02, 0.2, 0.1))  # in front of the body, below the slab
part.parent = slab; part.matrix_parent_inverse = slab.matrix_world.inverted(); part["slopforge_part"] = "slide"
bpy.context.view_layer.update()
# Unity z (forward) is Blender -Y: 0.7 back ends the box at y -0.2..0, under the slab, in front of the block
print("POCKET", sweep_penetration(part, [slab], "z", -0.7, 0.0))
'''
        result = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        pocket = [float(line.rsplit(" ", 1)[1]) for line in result.stdout.splitlines() if line.startswith("POCKET")]
        self.assertEqual(len(pocket), 1, result.stdout[-2000:])
        self.assertLessEqual(pocket[0], 0.02)


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderInterfaceTests(unittest.TestCase):
    def test_a_hollow_shell_cut_in_two_is_closed_across_its_inside(self):
        # TRELLIS.2 makes thin hollow shells: an inner wall a few millimetres inside the outer (a 2026-10-25 pistol).
        # A part cut from one is closed by the surface inside the solid where a point is as far from the part as
        # from the rest: across the hollow, not just the wall's thickness, facing away from the part, its rim on
        # the cut. A box with a wall 0.05 thick, its top above z 0.25 labelled a lid.
        script = f'''import bpy, bmesh, sys
import numpy as np
sys.path.insert(0, {str(ROOT / "blender")!r})
import mesh_cleanup
bm = bmesh.new()
for size, flip in ((1.0, False), (0.9, True)):
    made = bmesh.ops.create_cube(bm, size=size)
    faces = list({{f for v in made["verts"] for f in v.link_faces}})
    bmesh.ops.subdivide_edges(bm, edges=list({{e for f in faces for e in f.edges}}), cuts=7, use_grid_fill=True)
    if flip:
        inner = [f for f in bm.faces if max(abs(c) for c in f.calc_center_median()) < 0.46]
        bmesh.ops.reverse_faces(bm, faces=inner)
bmesh.ops.triangulate(bm, faces=bm.faces)
layer = bm.faces.layers.int.new("slopforge_part")
for f in bm.faces:
    f[layer] = 2 if f.calc_center_median().z > 0.25 else 1
solid = mesh_cleanup.solid_grid(bm, cells=60)
occupied, low, h = solid
centre = tuple(np.floor((np.zeros(3) - low) / h).astype(int))
print("CENTRE", bool(occupied[centre]))
vertices, polygons = mesh_cleanup.part_interface(bm, layer, 2, solid)
v = np.array(vertices)
normals = []
for poly in polygons:
    a, b, c = v[poly[0]], v[poly[1]], v[poly[2]]
    normals.append(np.cross(b - a, c - a))
normal = np.sum(normals, 0); normal /= np.linalg.norm(normal)
print("SPAN", float(np.ptp(v[:, 0])), float(np.ptp(v[:, 1])))
print("HEIGHT", float(np.median(v[:, 2])))
print("NORMAL", float(normal[2]))
rim = mesh_cleanup._rim(polygons)
print("RIM", float(np.max(np.abs(np.abs(v[list(rim)][:, :2]).max(1) - 0.5))) if rim else -1)
'''
        result = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        out = {line.split()[0]: line.split()[1:] for line in result.stdout.splitlines()
               if line.split() and line.split()[0] in ("CENTRE", "SPAN", "HEIGHT", "NORMAL", "RIM")}
        self.assertEqual(out["CENTRE"], ["True"])  # the hollow counts as solid
        self.assertGreater(float(out["SPAN"][0]), 0.85)  # across the inside, wall to wall
        self.assertGreater(float(out["SPAN"][1]), 0.85)
        self.assertAlmostEqual(float(out["HEIGHT"][0]), 0.25, delta=0.06)  # between the lid and the rest
        self.assertLess(float(out["NORMAL"][0]), -0.9)  # facing away from the lid, down into the body
        self.assertLess(float(out["RIM"][0]), 0.03)  # the rim on the outer wall, where the cut is


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class BlenderClosingTests(unittest.TestCase):
    def test_a_container_under_its_lid_gets_a_cavity_not_a_cap(self):
        # A chest under its lid: the opening becomes a cavity (a rim, inner walls, a floor) a player sees into when
        # the lid opens, not a flat panel at the rim (2026-10-25).
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "cavity.py"
            script.write_text(f'''import bpy, bmesh, sys
from mathutils import Vector
from mathutils.bvhtree import BVHTree
sys.path.insert(0, {str(ROOT / "blender")!r})
from mesh_cleanup import hollow_opening, _boundary_groups
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.5))
bpy.ops.object.transform_apply(location=True)
bm = bmesh.new(); bm.from_mesh(bpy.context.object.data)
bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z > 0.9], context="FACES_ONLY")
group = _boundary_groups(bm)[0]
faces = hollow_opening(bm, group, wall=0.05, depth=0.8)
bm.normal_update()
tree = BVHTree.FromBMesh(bm)
for x in (-0.3, 0.0, 0.3):
    for y in (-0.3, 0.0, 0.3):  # looking down into the opening: the floor, facing up, at 80% of the height
        hit = tree.ray_cast(Vector((x, y, 2)), Vector((0, 0, -1)))
        assert hit[0] is not None and abs(hit[0].z - 0.2) < 0.02 and hit[1].z > 0.9, (x, y, hit[0], hit[1])
hit = tree.ray_cast(Vector((0.48, 0.0, 2)), Vector((0, 0, -1)))  # on the rim: its top, facing up
assert hit[0] is not None and hit[0].z > 0.97 and hit[1].z > 0.9, hit
hit = tree.ray_cast(Vector((0.0, 0.0, 0.6)), Vector((1, 0, 0)))  # inside the cavity, looking at a wall: it faces in
assert hit[0] is not None and abs(hit[0].x - 0.45) < 0.02 and hit[1].x < -0.9, hit
print("CAVITY", len(faces))
''')
            result = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(script)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-2000:])
            self.assertIn("CAVITY", result.stdout)

    def test_a_hole_shows_as_the_backs_of_faces(self):
        # A piece left open where it was cut shows the backs of its far faces through the hole when its part moves:
        # 3.6% of a moved hybrid pistol's pixels, 0.4% once closed (2026-10-25). Seen along the axes and diagonals, a
        # closed box shows none; the same box without its top shows the inside of its walls and floor.
        script = f'''import bpy, sys
sys.path.insert(0, {str(ROOT / "blender")!r})
import mesh_cleanup
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0.3, 0.2, 0.5))
box = bpy.context.object
print("CLOSED", mesh_cleanup.visible_backfaces([box]))
import bmesh
bm = bmesh.new(); bm.from_mesh(box.data); bm.normal_update()
bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z > 0.9], context="FACES_ONLY")
bm.to_mesh(box.data); bm.free(); box.data.update()
print("OPEN", mesh_cleanup.visible_backfaces([box]))
'''
        result = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        out = {line.split()[0]: float(line.split()[1]) for line in result.stdout.splitlines()
               if line.startswith(("CLOSED", "OPEN"))}
        self.assertLess(out["CLOSED"], 0.001)
        self.assertGreater(out["OPEN"], 0.05)

    def test_a_standalone_fill_is_marked_and_not_counted_as_a_piece(self):
        # Interfaces and cavities are not stitched to the surface: as separate pieces they pushed live hybrid seeds
        # over the component budget (2026-10-25). They carry slopforge_fill; a piece made only of them is not counted.
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "fill_count.py"
            script.write_text(f'''import bpy, bmesh, sys
sys.path.insert(0, {str(ROOT / "blender")!r})
import mesh_cleanup
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1)
bm = bmesh.new(); bm.from_mesh(bpy.context.object.data)
bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z > 0.9], context="FACES_ONLY")
square = [(-0.45, -0.45, 0.45), (0.45, -0.45, 0.45), (0.45, 0.45, 0.45), (-0.45, 0.45, 0.45)]
fills = mesh_cleanup.add_interface(bm, square, [[0, 1, 2, 3]])  # under the open top, not stitched to it
mesh = bpy.data.meshes.new("closed"); bm.to_mesh(mesh)
assert mesh.attributes.get("slopforge_fill") is not None
values = [0] * len(mesh.polygons); mesh.attributes["slopforge_fill"].data.foreach_get("value", values)
assert sum(values) == len(fills) == 2, (sum(values), len(fills))
assert mesh_cleanup.solid_component_count(mesh) == 1, mesh_cleanup.solid_component_count(mesh)
print("FILL COUNT", sum(values))
''')
            result = subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(script)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-2000:])
            self.assertIn("FILL COUNT", result.stdout)
