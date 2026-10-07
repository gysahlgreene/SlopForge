import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BLENDER = (os.environ.get("BLENDER_BIN") or shutil.which("blender")
           or "/Applications/Blender.app/Contents/MacOS/Blender")


@unittest.skipUnless(Path(BLENDER).is_file(), "Blender is not installed")
class CharacterReadinessBlenderTests(unittest.TestCase):
    def test_unused_textured_slot_does_not_cover_unassigned_faces(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "unassigned.py"
            fixture.write_text('''import bpy, sys
from pathlib import Path
root=Path(sys.argv[sys.argv.index("--")+1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
obj=bpy.context.object
obj.data.materials.append(None)
material=bpy.data.materials.new("UnusedPaint"); material.use_nodes=True
image=bpy.data.images.new("PackedColor", width=4, height=4)
image.pixels=[0.4,0.5,0.7,1.0]*16; image.pack()
texture=material.node_tree.nodes.new("ShaderNodeTexImage"); texture.image=image
material.node_tree.links.new(texture.outputs["Color"], material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"])
obj.data.materials.append(material)
for polygon in obj.data.polygons: polygon.material_index=0
bpy.ops.wm.save_as_mainfile(filepath=str(root/"source.blend"))
''')
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python", str(fixture),
                            "--", str(root)], check=True, capture_output=True, text=True)
            report = root / "report.json"
            subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python",
                            str(ROOT / "blender/inspect_model.py"), "--", str(root / "source.blend"),
                            str(report), "60000"], check=True, capture_output=True, text=True)
            result = json.loads(report.read_text())
            self.assertEqual(result["animation_readiness"]["status"], "fail")
            self.assertEqual(result["measured"]["mesh_without_material_count"], 1)
            self.assertEqual(result["measured"]["mesh_without_texture_count"], 1)
            self.assertEqual(result["measured"]["image_texture_count"], 0)

    def test_normalization_preserves_components_and_bakes_packed_color(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "fixture.py"
            fixture.write_text('''import bpy, sys
from pathlib import Path
root = Path(sys.argv[sys.argv.index("--") + 1])
bpy.ops.wm.read_factory_settings(use_empty=True)
image = bpy.data.images.new("PackedColor", width=16, height=16)
image.pixels = [0.8, 0.2, 0.1, 1.0] * 256
image.pack()
material = bpy.data.materials.new("Paint")
material.use_nodes = True
node = material.node_tree.nodes.new("ShaderNodeTexImage")
node.image = image
material.node_tree.links.new(node.outputs["Color"], material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"])
material.node_tree.links.new(node.outputs["Color"], material.node_tree.nodes.get("Principled BSDF").inputs["Roughness"])
second_material = material.copy()
second_material.name = "SecondaryPaint"
for name, x in (("Body", -0.8), ("Head", 0.8)):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, location=(x, 0, 0))
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    if name == "Body":
        obj.data.materials.append(second_material)
        for polygon in list(obj.data.polygons)[::2]:
            polygon.material_index = 1
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=str(root / "source.glb"), export_format="GLB", use_selection=True)
''')
            created = subprocess.run([BLENDER, "--background", "--python", str(fixture), "--", str(root)],
                                     capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            source = root / "source.glb"
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            request = root / "request.json"
            request.write_text(json.dumps({"source": str(source), "output": str(root / "normalized.glb"),
                                           "report": str(root / "report.json"), "face_budget": 60000}))
            result = subprocess.run([BLENDER, "--background", "--factory-startup", "--python",
                                     str(ROOT / "blender/normalize_character.py"), "--", str(request)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout[-1000:] + result.stderr[-1000:])
            self.assertTrue((root / "report.json").is_file(), result.stdout[-2000:] + result.stderr[-2000:])
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
            self.assertEqual({part["source"] for part in report["components"]}, {"Body", "Head"})
            for part in report["components"]:
                assignments = part["source_material_assignments"]
                self.assertEqual(sum(slot["face_count"] for slot in assignments), part["source_faces"])
            body = next(part for part in report["components"] if part["source"] == "Body")
            self.assertEqual(len(body["source_material_assignments"]), 2)
            self.assertTrue(all(slot["face_count"] > 0 for slot in body["source_material_assignments"]))
            self.assertEqual(report["uv_status"], "pass")
            self.assertEqual(report["channels"]["base_color"], "baked")
            self.assertEqual(report["channels"]["roughness"], "baked")
            self.assertEqual(report["channels"]["metallic"], "baked")
            self.assertEqual(report["channels"]["normal"], "absent")
            self.assertTrue((root / "normalized.glb").stat().st_size)
            for part in report["components"]:
                texture = root / part["textures"]["base_color"]
                self.assertTrue(texture.is_file() and texture.stat().st_size > 0)
            check = root / "check.py"
            check.write_text('''import bpy, sys, json
from pathlib import Path
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=sys.argv[sys.argv.index("--") + 1])
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
assert len(meshes) == 2
for obj in meshes:
    assert obj.data.uv_layers.active is not None
    assert any(n.type == "TEX_IMAGE" and n.image is not None for mat in obj.data.materials for n in mat.node_tree.nodes)
''')
            checked = subprocess.run([BLENDER, "--background", "--python", str(check), "--",
                                      str(root / "normalized.glb")], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stdout[-1000:] + checked.stderr[-1000:])

    def test_glb_fixtures_report_pass_review_and_fail_without_repairing_meshes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture_script = root / "make_fixtures.py"
            fixture_script.write_text(f'''import bpy, sys
from pathlib import Path
root = Path(sys.argv[sys.argv.index("--") + 1])
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
def export(name, vertices, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    uv = mesh.uv_layers.new(name="QualificationUV")
    for loop in mesh.loops:
        point = mesh.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = (point.x, point.z)
    image = bpy.data.images.new(name + "Color", width=4, height=4)
    image.pixels = [0.7, 0.4, 0.2, 1.0] * 16
    image.pack()
    material = bpy.data.materials.new(name + "Material")
    material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    material.node_tree.links.new(texture.outputs["Color"],
                                  material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"])
    obj.data.materials.append(material)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(root / (name + ".glb")), export_format="GLB", use_selection=True)
def voxel_mannequin():
    cells = set()
    cells.update((x,y,z) for x in range(-1,2) for y in range(-1,1) for z in range(3,7))
    cells.update((x,y,z) for x in range(-1,2) for y in range(-1,1) for z in range(7,9))
    cells.update((x,y,z) for x in list(range(-4,-1))+list(range(2,5)) for y in range(-1,1) for z in range(4,6))
    cells.update((x,y,z) for x in (-1,1) for y in range(-1,1) for z in range(0,3))
    directions = [
      ((1,0,0),[(1,0,0),(1,1,0),(1,1,1),(1,0,1)]), ((-1,0,0),[(0,0,0),(0,0,1),(0,1,1),(0,1,0)]),
      ((0,1,0),[(0,1,0),(0,1,1),(1,1,1),(1,1,0)]), ((0,-1,0),[(0,0,0),(1,0,0),(1,0,1),(0,0,1)]),
      ((0,0,1),[(0,0,1),(1,0,1),(1,1,1),(0,1,1)]), ((0,0,-1),[(0,0,0),(0,1,0),(1,1,0),(1,0,0)])]
    points, faces, indices = [], [], {{}}
    for cell in cells:
      for delta, corners in directions:
        if tuple(cell[i]+delta[i] for i in range(3)) in cells: continue
        face=[]
        for corner in corners:
          pos=tuple((cell[i]+corner[i])*0.2 for i in range(3))
          if pos not in indices: indices[pos]=len(points); points.append(pos)
          face.append(indices[pos])
        faces.append(face)
    return points,faces
reset()
export("valid_humanoid", *voxel_mannequin())
reset()
vertices = []
faces = []
cube_faces = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(3,7,6,2),(0,4,7,3),(1,2,6,5)]
for offset in (0,3):
    start = len(vertices)
    vertices.extend([(offset+x,y,z) for x,y,z in [(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0,0,1),(1,0,1),(1,1,1),(0,1,1)]])
    faces.extend([tuple(start+i for i in face) for index,face in enumerate(cube_faces)
                  if not (offset == 0 and index == 1)])
export("disconnected_open", vertices, faces)
reset()
export("unsuitable_generated", [(0,0,0),(1,0,0),(0,1,0)], [(0,1,2)])
''')
            generated = subprocess.run([BLENDER, "--background", "--python", str(fixture_script), "--", str(root)],
                                       capture_output=True, text=True)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            reports = {}
            for name in ("valid_humanoid", "disconnected_open", "unsuitable_generated"):
                report = root / f"{name}.json"
                inspected = subprocess.run([BLENDER, "--background", "--python", str(ROOT / "blender/inspect_model.py"),
                                             "--", str(root / f"{name}.glb"), str(report), "60000"],
                                            capture_output=True, text=True)
                self.assertEqual(inspected.returncode, 0, inspected.stderr)
                self.assertTrue(report.is_file(), inspected.stdout[-500:] + inspected.stderr[-500:])
                reports[name] = json.loads(report.read_text())

            self.assertEqual(reports["valid_humanoid"]["animation_readiness"]["status"], "needs_review")
            self.assertEqual(reports["valid_humanoid"]["measured"]["mesh_without_uv_count"], 0)
            self.assertEqual(reports["valid_humanoid"]["measured"]["mesh_without_material_count"], 0)
            self.assertEqual(reports["valid_humanoid"]["measured"]["image_texture_count"], 1)
            self.assertEqual(reports["valid_humanoid"]["measured"]["mesh_without_texture_count"], 0)
            self.assertEqual(reports["disconnected_open"]["animation_readiness"]["status"], "needs_review")
            self.assertEqual(reports["unsuitable_generated"]["animation_readiness"]["status"], "fail")
            self.assertIn("normal_count", reports["valid_humanoid"]["measured"])
            self.assertEqual(reports["disconnected_open"]["measured"]["boundary_edge_count"], 4)


if __name__ == "__main__":
    unittest.main()
