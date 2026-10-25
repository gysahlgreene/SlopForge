import unittest

import numpy as np

from processing.part_model import coverage, object_frame, part_boxes, part_ids


def fixture():
    """A 100 wide, 60 tall object: a slide along the top band, a trigger below it, a hammer blob above the slide
    line at the left that no mask covers."""
    alpha = np.zeros((60, 100), bool)
    alpha[:, :] = True
    slide = np.zeros_like(alpha); slide[0:20, 10:100] = True
    trigger = np.zeros_like(alpha); trigger[25:35, 40:50] = True
    parts = [{"name": "slide", "kind": "slide"}, {"name": "trigger", "kind": "hinge"}]
    return alpha, {"slide": slide, "trigger": trigger}, parts


class PartIdTests(unittest.TestCase):
    def test_declared_parts_then_the_body_get_ids(self):
        alpha, masks, parts = fixture()
        ids, table = part_ids(alpha, masks, parts)
        self.assertEqual(table, [{"name": "slide", "kind": "slide", "id": 1}, {"name": "trigger", "kind": "hinge", "id": 2},
                                 {"name": "body", "kind": "body", "id": 3}])
        self.assertTrue((ids[0:20, 10:100] == 1).all())
        self.assertTrue((ids[25:35, 40:50] == 2).all())
        self.assertTrue((ids[0:20, 0:10] == 3).all())  # the hammer behind the slide stays body
        self.assertTrue((ids[20:60, 0:40] == 3).all())
        self.assertEqual(int((ids == 0).sum()), 0)

    def test_what_sits_on_a_slide_moves_with_it(self):
        # 2026-10-25 live pistol: the sights on top of the slide were body, so a rule keyed on "body above the
        # slide line" spanned the whole slide and OmniPart grew a second shell over it. A body speck resting on
        # the slide (body all the way down to the slide's top in its column) is the slide's; the hammer behind the
        # slide and the frame under it are not.
        alpha = np.zeros((60, 100), bool); alpha[10:60, :] = True; alpha[5:10, 20:25] = True; alpha[5:10, 85:90] = True
        alpha[0:10, 0:8] = True  # a hammer behind the slide, above its line
        slide = np.zeros_like(alpha); slide[10:30, 10:95] = True
        ids, table = part_ids(alpha, {"slide": slide}, [{"name": "slide", "kind": "slide"}])
        self.assertTrue((ids[5:10, 20:25] == 1).all())  # rear sight: on the slide
        self.assertTrue((ids[5:10, 85:90] == 1).all())  # front sight: on the slide
        self.assertTrue((ids[0:10, 0:8] == 2).all())  # the hammer is not on the slide
        self.assertTrue((ids[30:60, :] == 2).all())  # the frame under it is body

    def test_an_object_outside_every_mask_is_just_a_body(self):
        alpha = np.ones((8, 8), bool)
        ids, table = part_ids(alpha, {}, [])
        self.assertEqual(table, [{"name": "body", "kind": "body", "id": 1}])
        self.assertTrue((ids == 1).all())


def block_coords(x0, x1, z0, z1, y0=28, y1=36):
    xs, ys, zs = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1), np.arange(z0, z1), indexing="ij")
    return np.stack([np.zeros(xs.size, int), xs.ravel(), ys.ravel(), zs.ravel()], 1)


class PartBoxTests(unittest.TestCase):
    def test_x_sign_is_chosen_by_silhouette(self):
        # A wide, low block whose left two thirds are tall: the voxel footprint's tall end is at low x
        alpha = np.zeros((40, 60), bool); alpha[20:40, :] = True; alpha[0:20, 0:40] = True
        coords = np.concatenate([block_coords(0, 60, 0, 20), block_coords(0, 40, 20, 40)])
        frame = object_frame(alpha, coords)
        sign, lo, hi = frame.sign, frame.lo, frame.hi
        self.assertEqual((sign, frame.axis), (1, 0))
        self.assertEqual(object_frame(alpha[:, ::-1], coords).sign, -1)
        np.testing.assert_allclose(lo, [-0.5 + 0.5 / 64, -0.5 + 28.5 / 64, -0.5 + 0.5 / 64], atol=1e-6)
        np.testing.assert_allclose(hi, [-0.5 + 59.5 / 64, -0.5 + 35.5 / 64, -0.5 + 39.5 / 64], atol=1e-6)

    def test_an_object_lying_along_grid_y_maps_image_columns_to_y(self):
        # 2026-10-25 live rifle: OmniPart laid it along y; mapping columns to x gave every part a thin full-length box
        alpha = np.zeros((40, 60), bool); alpha[20:40, :] = True; alpha[0:20, 0:40] = True
        xs, ys, zs = np.meshgrid(np.arange(28, 36), np.arange(0, 60), np.arange(0, 20), indexing="ij")
        low = np.stack([np.zeros(xs.size, int), xs.ravel(), ys.ravel(), zs.ravel()], 1)
        xs, ys, zs = np.meshgrid(np.arange(28, 36), np.arange(0, 40), np.arange(20, 40), indexing="ij")
        tall = np.stack([np.zeros(xs.size, int), xs.ravel(), ys.ravel(), zs.ravel()], 1)
        coords = np.concatenate([low, tall])
        frame = object_frame(alpha, coords)
        self.assertEqual((frame.axis, frame.sign), (1, 1))
        top = np.zeros_like(alpha); top[0:20, 0:40] = True
        ids, table = part_ids(alpha, {"top": top}, [{"name": "top", "kind": "slide"}])
        boxes = part_boxes(ids, table, frame)
        lo, hi = frame.lo, frame.hi
        names = [entry["name"] for entry in sorted(table, key=lambda e: -np.where(ids == e["id"])[0].max())]
        box = boxes[names.index("top")]
        self.assertAlmostEqual(float(box[0][1]), float(lo[1]), places=6)  # along y, the first two thirds
        self.assertAlmostEqual(float(box[1][1]), float(lo[1] + (hi[1] - lo[1]) * 39 / 59), places=6)
        self.assertAlmostEqual(float(box[0][0]), float(lo[0]), places=6)  # the full thickness along x
        self.assertAlmostEqual(float(box[1][0]), float(hi[0]), places=6)
        self.assertGreaterEqual(coverage(ids, table, frame, {"top": tall})["top"], 0.9)

    def test_boxes_follow_a_tall_object(self):
        # A tall object (muzzle down): height along image rows maps to grid z, not to x
        alpha = np.ones((60, 20), bool)
        coords = block_coords(22, 42, 2, 62)
        frame = object_frame(alpha, coords)
        top = np.zeros_like(alpha); top[0:20, :] = True
        ids, table = part_ids(alpha, {"slide": top}, [{"name": "slide", "kind": "slide"}])
        boxes = part_boxes(ids, table, frame)
        names = [entry["name"] for entry in sorted(table, key=lambda e: -np.where(ids == e["id"])[0].max())]
        slide = boxes[names.index("slide")]
        lo, hi = frame.lo, frame.hi
        self.assertAlmostEqual(float(slide[1][2]), float(hi[2]), places=6)
        self.assertAlmostEqual(float(slide[0][2]), float(hi[2] - (hi[2] - lo[2]) * 19 / 59), places=6)
        self.assertAlmostEqual(float(slide[0][0]), float(lo[0]), places=6)
        self.assertAlmostEqual(float(slide[1][0]), float(hi[0]), places=6)

    def test_boxes_come_in_bottom_up_order_and_span_the_full_thickness(self):
        alpha, masks, parts = fixture()
        ids, table = part_ids(alpha, masks, parts)
        coords = block_coords(2, 62, 10, 46)
        frame = object_frame(alpha, coords)
        boxes = part_boxes(ids, table, frame)
        self.assertEqual(boxes.shape, (3, 2, 3))
        ordered = [entry["name"] for entry in sorted(table, key=lambda e: -np.where(ids == e["id"])[0].max())]
        self.assertEqual(ordered, ["body", "trigger", "slide"])
        for box in boxes:
            self.assertAlmostEqual(float(box[0][1]), float(frame.lo[1]), places=6)
            self.assertAlmostEqual(float(box[1][1]), float(frame.hi[1]), places=6)
        self.assertEqual([box[0][0] <= box[1][0] and box[0][2] <= box[1][2] for box in boxes], [True] * 3)


class CoverageTests(unittest.TestCase):
    def test_a_part_whose_box_holds_no_voxel_reports_zero_coverage(self):
        alpha, masks, parts = fixture()
        ids, table = part_ids(alpha, masks, parts)
        coords = block_coords(2, 62, 10, 46)
        frame = object_frame(alpha, coords)
        # the slide's voxels: the top band of the block; the trigger has none
        top = coords[coords[:, 3] >= 46 - 12]
        report = coverage(ids, table, frame, {"slide": top, "trigger": coords[:0]})
        self.assertEqual(sorted(report), ["slide", "trigger"])
        self.assertEqual(report["trigger"], 0.0)
        self.assertGreaterEqual(report["slide"], 0.9)


class MainTests(unittest.TestCase):
    def test_main_writes_parts_glb_and_report(self):
        import json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from PIL import Image
        from processing import part_model
        from processing.part_model import glb_json, pack_glb
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = Image.new("RGBA", (100, 60), (0, 0, 0, 0)); image.paste((90, 90, 90, 255), (0, 0, 100, 60))
            image.save(root / "concept.png")
            slide = Image.new("L", (100, 60), 0); slide.paste(255, (10, 0, 100, 20)); slide.save(root / "slide.png")
            request = {"image": str(root / "concept.png"), "masks": {"slide": str(root / "slide.png")},
                       "parts": [{"name": "slide", "kind": "slide"}], "seed": 7, "out_dir": str(root / "out")}
            (root / "request.json").write_text(json.dumps(request))
            coords = block_coords(2, 62, 10, 46)

            def omnipart(_request, out_dir, boxes_for, _mask_path):
                _frame, boxes = boxes_for(coords)
                self.assertEqual(boxes.shape, (2, 2, 3))
                # OmniPart's merged GLB: geometry_0 is its box visualisation, then one node per box in order
                # ... under a "world" root node without a mesh, as merge_parts writes it
                names = ["geometry_0", "geometry_1", "geometry_2"]
                doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [3]}],
                       "nodes": [*({"name": name, "mesh": index} for index, name in enumerate(names)),
                                 {"name": "world", "children": [0, 1, 2]}],
                       "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}
                                  for name in names],
                       "accessors": [{"count": 3, "type": "VEC3", "componentType": 5126},
                                     {"count": 36, "type": "SCALAR", "componentType": 5125}]}
                (Path(out_dir) / "mesh_textured.glb").write_bytes(pack_glb(doc, b""))
                top = coords[coords[:, 3] >= 34]
                return coords, [coords, top], {"provider": "omnipart", "version": "abc", "device": "H100"}, {"omnipart/OmniPart": "rev"}
            with patch.object(part_model, "_omnipart", side_effect=omnipart):
                part_model.main(str(root / "request.json"))
            doc = glb_json(root / "out/parts.glb")
            names = [node["name"] for node in doc["nodes"]]
            self.assertEqual(names, ["body", "slide", "world"])  # bottom-up order, box vis dropped
            self.assertEqual(doc["nodes"][2]["children"], [0, 1])
            report = json.loads((root / "out/parts.json").read_text())
            self.assertEqual(report["seed"], 7)
            self.assertEqual(report["parts"]["slide"]["kind"], "slide")
            self.assertGreaterEqual(report["parts"]["slide"]["structure_coverage"], 0.9)  # diagnostic, not the gate
            self.assertIsNone(report["parts"]["body"]["structure_coverage"])
            self.assertEqual(report["parts"]["slide"]["voxels"], int((coords[:, 3] >= 34).sum()))
            self.assertEqual(len(report["parts"]["slide"]["box"]), 2)
            self.assertEqual(report["parts"]["slide"]["faces"], 12)
            self.assertEqual(glb_json(root / "out/parts.glb")["scenes"][0]["nodes"], [2])
            self.assertEqual(report["backend"]["provider"], "omnipart")
            self.assertTrue((root / "out/mask.exr").is_file() or (root / "out/mask.png").is_file())


class DerivedMapTests(unittest.TestCase):
    def test_derive_part_maps_writes_four_maps_with_the_finish_roughness(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from slopforge.unity_material import derive_part_maps
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Image.new("RGB", (8, 8), (200, 30, 30)).save(root / "atlas.png")
            metal = Image.new("L", (8, 8), 0); metal.paste(255, (0, 0, 4, 8)); metal.save(root / "metal.png")
            maps = derive_part_maps(root / "atlas.png", root / "metal.png", "matte", root / "maps")
            self.assertEqual(sorted(maps), ["basecolor", "metallic", "normal", "roughness"])
            self.assertEqual(Image.open(maps["basecolor"]).getpixel((0, 0)), (200, 30, 30))
            self.assertEqual(Image.open(maps["normal"]).convert("RGB").getpixel((3, 3)), (128, 128, 255))
            self.assertEqual(Image.open(maps["roughness"]).convert("L").getpixel((3, 3)), round(0.7 * 255))
            metallic = Image.open(maps["metallic"]).convert("L")
            self.assertEqual((metallic.getpixel((1, 1)), metallic.getpixel((6, 6))), (255, 0))

    def test_finish_word(self):
        from slopforge.unity_material import finish_word
        self.assertEqual(finish_word([{"region": "blade", "class": "metal", "description": "polished steel"}]), "polished")
        self.assertEqual(finish_word([{"region": "frame", "class": "metal", "description": "blued steel"}]), "satin")
        self.assertEqual(finish_word([{"region": "frame", "class": "metal", "description": "matte black steel"},
                                      {"region": "grip", "class": "nonmetal", "description": "polished walnut"}]), "matte")

    def test_part_metal_by_region_name(self):
        from slopforge.unity_material import part_metal
        materials = [{"region": "slide and frame", "class": "metal", "description": "blued steel"},
                     {"region": "grips", "class": "nonmetal", "description": "checkered walnut"}]
        parts = [{"name": "grip", "kind": "grip"}, {"name": "slide", "kind": "slide"}, {"name": "trigger", "kind": "hinge"}]
        self.assertEqual(part_metal(parts, materials), {"grip": 0, "slide": 1, "trigger": 1})
        self.assertEqual(part_metal(parts, [{"region": "all", "class": "nonmetal", "description": "wood"}]),
                         {"grip": 0, "slide": 0, "trigger": 0})


class OmniPartBackendTests(unittest.TestCase):
    def _config(self, tools):
        return {"asset_pipeline": {"tools": {"parts_host": "gpu", "blender": "/usr/bin/blender", **tools}}}

    def test_missing_tools_fail_as_configuration_before_any_remote_call(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from slopforge.backends import omnipart
        from slopforge.failures import StageFailure
        with tempfile.TemporaryDirectory() as temporary, patch.object(omnipart, "run_remote_tool") as remote, \
                self.assertRaises(StageFailure) as caught:
            omnipart.generate_part_model(temporary, self._config({}), Path(temporary) / "c.png", "pistol",
                                         Path(temporary) / "m/pistol.glb", Path(temporary) / "m/generation.json", 1,
                                         [{"name": "slide", "kind": "slide"}], Path(temporary), 30000, [], "satin")
        self.assertEqual((caught.exception.category, caught.exception.operation), ("configuration", "part_model_preflight"))
        self.assertFalse(remote.called)

    def test_generate_part_model_runs_the_tool_then_blender_and_writes_generation_json(self):
        import json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from PIL import Image
        from slopforge.backends import omnipart
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cutout.png").write_bytes(b"png")
            masks = root / "masks"; masks.mkdir()
            for name in ("grip", "slide"):
                (masks / f"{name}.png").write_bytes(b"png")
            seen = {}

            def remote(host, python, script, request, uploads, downloads, **options):
                seen["remote"] = {"host": host, "python": python, "script": script.name, "request": request,
                                  "uploads": uploads, **options}
                out = downloads["."]; out.mkdir(parents=True)
                (out / "parts.glb").write_bytes(b"glb")
                (out / "parts.json").write_text(json.dumps({"seed": 5, "x_sign": 1,
                    "backend": {"provider": "omnipart", "version": "abc", "device": "H100"},
                    "model_weights": {"omnipart/OmniPart": "rev"},
                    "parts": {"body": {"kind": "body", "id": 3, "faces": 10, "box": [[0, 0, 0], [1, 1, 1]], "voxels": 9, "coverage": None},
                              "grip": {"kind": "grip", "id": 1, "faces": 4, "box": [[0, 0, 0], [1, 1, 1]], "voxels": 2, "coverage": None},
                              "slide": {"kind": "slide", "id": 2, "faces": 6, "box": [[0, 0, 0], [1, 1, 1]], "voxels": 4, "structure_coverage": 0.8}}}))

            def blender(command, **kwargs):
                seen["blender"] = command
                for flag, writer in (("--basecolor-output", lambda p: Image.new("RGB", (4, 4), (90, 90, 90)).save(p)),
                                     ("--metallic-output", lambda p: Image.new("L", (4, 4), 255).save(p))):
                    writer(command[command.index(flag) + 1])
                Path(command[command.index("--") + 2]).write_bytes(b"processed")
                Path(command[command.index("--") + 3]).write_bytes(b"blend")
            parts = [{"name": "grip", "kind": "grip"}, {"name": "slide", "kind": "slide", "axis": "z", "min": -0.03, "max": 0}]
            materials = [{"region": "slide and frame", "class": "metal", "description": "matte blued steel"},
                         {"region": "grips", "class": "nonmetal", "description": "walnut"}]
            with patch.object(omnipart, "run_remote_tool", side_effect=remote), \
                    patch.object(omnipart.subprocess, "run", side_effect=blender):
                omnipart.generate_part_model(root, self._config({"omnipart_python": "/opt/env/bin/python",
                                                                 "omnipart_checkout": "/opt/OmniPart"}),
                                             root / "cutout.png", "pistol", root / "mesh_01/pistol.glb",
                                             root / "mesh_01/generation.json", 5, parts, masks, 27000, materials,
                                             "matte")
            request = seen["remote"]["request"]
            self.assertEqual(request["image"], "concept.png")
            self.assertEqual(request["masks"], {"grip": "grip.png", "slide": "slide.png"})
            self.assertEqual(request["parts"], [{"name": "grip", "kind": "grip"}, {"name": "slide", "kind": "slide"}])
            self.assertEqual((request["seed"], seen["remote"]["cwd"], seen["remote"]["env"]["SPCONV_ALGO"]),
                             (5, "/opt/OmniPart", "native"))
            self.assertEqual(set(seen["remote"]["uploads"]), {"concept.png", "grip.png", "slide.png"})
            self.assertEqual(seen["remote"]["label"], "omnipart")
            command = seen["blender"]
            self.assertIn("--metal", command)
            self.assertEqual(command[command.index("--face-budget") + 1], "27000")  # the caller's reduction budget
            metal = {command[i + 1] for i, value in enumerate(command) if value == "--metal"}
            self.assertEqual(metal, {"grip=0", "slide=1", "body=1"})
            self.assertTrue((root / "mesh_01/pistol.glb").is_file())
            info = json.loads((root / "mesh_01/generation.json").read_text())
            self.assertEqual((info["textured"], info["part_model"], info["seed"]), (True, "omnipart", 5))
            self.assertEqual(sorted(info["textures"]), ["basecolor", "metallic", "normal", "roughness"])
            self.assertEqual(info["backend"]["provider"], "omnipart")
            self.assertEqual(info["provenance"]["model_weights"], {"omnipart/OmniPart": "rev"})
            self.assertEqual(info["parts"]["slide"]["structure_coverage"], 0.8)
            self.assertEqual(sorted(info["tool_sha256"]), ["part_model.py", "prepare_parts.py"])
            self.assertEqual(Image.open(root / "mesh_01/roughness.png").convert("L").getpixel((0, 0)), round(0.7 * 255))


if __name__ == "__main__":
    unittest.main()
