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

    def test_a_barrel_above_a_pump_fore_end_stays_body(self):
        # Review 2026-10-25: the resting rule took the whole barrel above a pump shotgun's fore-end. Only a short
        # run that reaches the silhouette's top (a sight) rests on a slide; a run taller than half the slide's
        # height in that column (a barrel, a receiver) is body.
        alpha = np.zeros((60, 100), bool); alpha[10:40, :] = True
        fore_end = np.zeros_like(alpha); fore_end[30:40, 20:60] = True
        ids, table = part_ids(alpha, {"fore_end": fore_end}, [{"name": "fore_end", "kind": "slide"}])
        self.assertTrue((ids[10:30, 20:60] == 2).all())  # the barrel stays body

    def test_two_slides_keep_their_own_pixels_and_the_receiver_stays_body(self):
        alpha = np.zeros((60, 100), bool); alpha[0:40, :] = True
        bolt = np.zeros_like(alpha); bolt[0:10, 20:100] = True
        release = np.zeros_like(alpha); release[30:40, 50:60] = True
        ids, table = part_ids(alpha, {"bolt": bolt, "release": release},
                              [{"name": "bolt", "kind": "slide"}, {"name": "release", "kind": "slide"}])
        self.assertTrue((ids[0:10, 20:100] == 1).all())
        self.assertTrue((ids[30:40, 50:60] == 2).all())
        self.assertTrue((ids[10:30, :] == 3).all())  # the receiver between them is body

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


class BoxOrderTests(unittest.TestCase):
    def test_our_order_must_match_omniparts_ordered_mask(self):
        from processing.part_model import check_box_order, part_ids
        alpha, masks, parts = fixture()
        ids, table = part_ids(alpha, masks, parts)
        # OmniPart's ordered mask: our ids renumbered bottom-up on its coarse grid, as load_bottom_up_mask does
        from processing.part_model import coarse_ids
        coarse = coarse_ids(ids)
        order = sorted(np.unique(coarse[coarse > 0]), key=lambda i: -np.where(coarse == i)[0].max())
        renumbered = np.zeros_like(coarse)
        for new, old in enumerate(order, 1):
            renumbered[coarse == old] = new
        check_box_order(ids, table, renumbered)  # agrees: no error
        swapped = renumbered.copy(); swapped[renumbered == 1] = 2; swapped[renumbered == 2] = 1
        with self.assertRaisesRegex(RuntimeError, "order"):
            check_box_order(ids, table, swapped)


def omnipart_coarse(ids):
    """OmniPart's own reading of a mask (inference_utils.load_img_mask + smart_downsample_mask), ported as the oracle:
    a square crop 1.2x the object's larger side, zero-padded, then the most common non-zero id per 37x37 cell."""
    ys, xs = np.nonzero(ids > 0)
    bbox = [xs.min(), ys.min(), xs.max(), ys.max()]
    center = [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]
    hsize = max(bbox[2] - bbox[0], bbox[3] - bbox[1]) / 2 * 1.2
    aug = [int(center[0] - hsize), int(center[1] - hsize), int(center[0] + hsize), int(center[1] + hsize)]
    height, width = ids.shape
    pad = (max(0, -aug[1]), max(0, aug[3] - height)), (max(0, -aug[0]), max(0, aug[2] - width))
    mask = np.pad(ids, pad)
    aug = [aug[0] + pad[1][0], aug[1] + pad[0][0], aug[2] + pad[1][0], aug[3] + pad[0][0]]
    mask = mask[aug[1]:aug[3], aug[0]:aug[2]]
    h, w = mask.shape
    out = np.zeros((37, 37), int)
    for i in range(37):
        for j in range(37):
            region = mask[int(i * (h / 37)):min(int((i + 1) * (h / 37)), h), int(j * (w / 37)):min(int((j + 1) * (w / 37)), w)]
            values, counts = np.unique(region.flatten(), return_counts=True)
            nonzero = values > 0
            if nonzero.any():
                out[i, j] = values[nonzero][counts[nonzero].argmax()]
    return out


class CoarseGridTests(unittest.TestCase):
    def test_the_coarse_grid_is_omniparts_own_crop_of_the_object(self):
        from processing.part_model import coarse_ids
        ids = np.zeros((1024, 1024), np.int32)
        ids[300:700, 100:900] = 3  # a wide object: OmniPart's square crop reaches past the image
        ids[640:700, 100:260] = 1  # a grip at the bottom left
        ids[300:330, 500:620] = 2  # a bolt along the top
        self.assertTrue((coarse_ids(ids) == omnipart_coarse(ids)).all())
        tall = np.zeros((1024, 1024), np.int32)
        tall[50:1000, 400:560] = 2; tall[900:1000, 400:470] = 1
        self.assertTrue((coarse_ids(tall) == omnipart_coarse(tall)).all())

    def test_a_thin_part_keeps_a_cell_at_omniparts_resolution(self):
        from processing.part_model import coarse_ids
        alpha = np.ones((896, 1152), bool)
        trigger = np.zeros_like(alpha); trigger[487:523, 411:420] = True  # 324 px: the R2 rifle's trigger
        self.assertNotIn(1, coarse_ids(np.where(trigger, 1, 2)))  # the body outnumbers it in every 31x24 cell
        ids, table = part_ids(alpha, {"trigger": trigger}, [{"name": "trigger", "kind": "hinge"}])
        self.assertIn(1, coarse_ids(ids))  # so it is given the cell it fills most, or OmniPart drops it
        self.assertIn(1, omnipart_coarse(ids))
        self.assertLess(((ids == 1) & ~trigger).sum(), 38 * 38)  # one cell's object pixels, no more
        self.assertTrue((ids[trigger] == 1).all())

    def test_parts_whose_bottoms_share_a_coarse_row_order_by_id_like_omnipart(self):
        from processing.part_model import _ordered
        alpha = np.ones((370, 370), bool)  # ten pixels per coarse cell
        a = np.zeros_like(alpha); a[100:118, 50:150] = True  # bottom row 117: coarse row 11
        b = np.zeros_like(alpha); b[100:115, 200:300] = True  # bottom row 114: coarse row 11 too
        ids, table = part_ids(alpha, {"b": b, "a": a}, [{"name": "b", "kind": "hinge"}, {"name": "a", "kind": "hinge"}])
        self.assertEqual([e["name"] for e in _ordered(ids, table)], ["body", "b", "a"])


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

            def omnipart(request_, out_dir, boxes_for, _mask_path):
                self.assertEqual(request_.get("texture_size", 2048), 2048)  # the tool's default when absent
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

    def test_derive_part_maps_uses_a_baked_normal_when_given(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from slopforge.unity_material import derive_part_maps
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Image.new("RGB", (8, 8), (200, 30, 30)).save(root / "atlas.png")
            Image.new("L", (8, 8), 255).save(root / "metal.png")
            Image.new("RGB", (8, 8), (140, 120, 250)).save(root / "baked.png")
            maps = derive_part_maps(root / "atlas.png", root / "metal.png", "satin", root / "maps", normal=root / "baked.png")
            self.assertEqual(Image.open(maps["normal"]).convert("RGB").getpixel((3, 3)), (140, 120, 250))

    def test_derive_part_maps_fills_unused_texels_with_the_median_used_colour(self):
        # Unused atlas texels are exact black; at the smaller mips they darken every island's edge
        import tempfile
        from pathlib import Path
        import numpy as np
        from PIL import Image
        from slopforge.unity_material import derive_part_maps
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            atlas = Image.new("RGB", (16, 16), (0, 0, 0)); atlas.paste((180, 60, 40), (2, 2, 10, 10)); atlas.save(root / "atlas.png")
            Image.new("L", (16, 16), 255).save(root / "metal.png")
            maps = derive_part_maps(root / "atlas.png", root / "metal.png", "satin", root / "maps")
            base = np.asarray(Image.open(maps["basecolor"]).convert("RGB"))
            self.assertEqual(int((base.sum(-1) == 0).sum()), 0)
            self.assertEqual(tuple(base[5, 5]), (180, 60, 40))
            self.assertEqual(tuple(base[14, 14]), (180, 60, 40))

    def test_finish_word(self):
        from slopforge.unity_material import finish_word
        self.assertEqual(finish_word([{"region": "blade", "class": "metal", "description": "polished steel"}]), "polished")
        self.assertEqual(finish_word([{"region": "frame", "class": "metal", "description": "blued steel"}]), "satin")
        self.assertEqual(finish_word([{"region": "frame", "class": "metal", "description": "matte black steel"},
                                      {"region": "grip", "class": "nonmetal", "description": "polished walnut"}]), "matte")

    def test_a_non_metal_declared_without_a_colour_takes_its_parts_colour_in_the_concept(self):
        # A pistol's grips were declared "nonmetal: checkered walnut wood" with no colour; the generated metallic map
        # called the whole pistol metal and the metal steps greyed the grips (2026-10-25). The colour the rule needs
        # is in the concept under the grip's mask: the median of its coloured pixels (the frame's steel under the
        # same mask is left out). A declared colour is kept; a region that names no masked part gets none.
        import tempfile
        from pathlib import Path
        from PIL import Image
        from slopforge.unity_material import concept_part_colours
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            concept = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
            concept.paste((20, 20, 22, 255), (10, 10, 90, 50))  # black steel
            concept.paste((98, 37, 19, 255), (20, 50, 45, 95))  # walnut grip panel
            concept.paste((20, 20, 22, 255), (45, 50, 55, 95))  # steel beside it, under the grip's mask
            concept.save(root / "concept.png")
            mask = Image.new("L", (100, 100), 0); mask.paste(255, (15, 45, 55, 95)); mask.save(root / "grip.png")
            materials = [{"region": "slide and frame", "class": "metal", "description": "blued steel"},
                         {"region": "grips", "class": "nonmetal", "description": "walnut"},
                         {"region": "lanyard", "class": "nonmetal", "description": "cord"},
                         {"region": "sights", "class": "nonmetal", "color": "#ffffff", "description": "paint"}]
            parts = [{"name": "grip", "kind": "grip", "text": "the walnut grip panels"},
                     {"name": "slide", "kind": "slide", "text": "the slide"}]
            coloured = concept_part_colours(materials, parts, root, root / "concept.png")
        by_region = {item["region"]: item for item in coloured}
        self.assertEqual(by_region["grips"]["color"], "#622513")
        self.assertEqual(by_region["grips"]["color_source"], "concept under the grip mask")
        self.assertNotIn("color", by_region["lanyard"])  # names no part
        self.assertEqual(by_region["sights"]["color"], "#ffffff")  # declared
        self.assertNotIn("color", by_region["slide and frame"])  # metal

    def test_part_metal_by_region_text(self):
        # The rifle's declared non-metal "stock" named no part, so its walnut grip came out metal (2026-10-25);
        # a region word in the part's own description counts too
        from slopforge.unity_material import part_metal
        materials = [{"region": "stock", "class": "nonmetal", "description": "oiled walnut"},
                     {"region": "barrel, receiver and bolt", "class": "metal", "description": "blued steel"}]
        parts = [{"name": "grip", "kind": "grip", "text": "the chequered pistol grip of the stock"},
                 {"name": "bolt", "kind": "slide", "text": "the bolt handle and bolt on the receiver"},
                 {"name": "trigger", "kind": "hinge", "text": "the curved trigger inside the guard"}]
        self.assertEqual(part_metal(parts, materials), {"grip": 0, "bolt": 1, "trigger": 1})

    def test_colour_matching_on_the_parts_route(self):
        # OmniPart's textures are darker and duller than the concept all over (chest 2026-10-25: darkened 0.45-0.69,
        # chroma ratio 0.25-0.29). On that route the lightness moves the whole way to the concept's (within the cap)
        # and metal texels keep no more chroma than the concept's metal shows (the pink serrations).
        import tempfile
        from pathlib import Path
        import numpy as np
        from PIL import Image
        from slopforge.unity_material import match_concept_colours, match_metal_lightness
        from slopforge.validation import _lab
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cutout = np.zeros((64, 64, 4)); cutout[..., 3] = 255; cutout[..., :3] = (184, 132, 78)  # lit oak
            view = np.zeros((64, 64, 4)); view[..., 3] = 255; view[..., :3] = (70, 58, 48)  # dark, dull
            metal = np.zeros((64, 64, 4)); metal[..., 3] = 255  # no metal
            Image.new("RGB", (32, 32), (70, 58, 48)).save(root / "base.png")
            Image.new("L", (32, 32), 0).save(root / "metal.png")
            report = match_concept_colours(root / "base.png", root / "metal.png", cutout, view, metal, lightness_share=1.0)
            lab = _lab(np.asarray(Image.open(root / "base.png").convert("RGB"), dtype=float).reshape(-1, 3))
            self.assertGreater(float(np.median(lab[:, 0])), 55.0)  # from L* 26 towards the oak's 59
            self.assertGreater(float(np.median(np.hypot(lab[:, 1], lab[:, 2]))), 20.0)  # chroma restored
            self.assertTrue(any(entry.get("lightness", 1) > 1.4 for entry in report.values()))
            # metal: a grey concept, a dark base with a purplish patch; brightened, and the patch loses its tint
            cutout[..., :3] = (120, 120, 120)
            view[..., :3] = (35, 35, 36)
            metal[..., :3] = 255
            base = Image.new("RGB", (32, 32), (35, 35, 36)); base.paste((80, 50, 80), (8, 8, 16, 16)); base.save(root / "base2.png")
            Image.new("L", (32, 32), 255).save(root / "metal2.png")
            gain = match_metal_lightness(root / "base2.png", root / "metal2.png", cutout, view, metal)
            self.assertGreater(gain, 2.0)
            lab = _lab(np.asarray(Image.open(root / "base2.png").convert("RGB"), dtype=float)[8:16, 8:16].reshape(-1, 3))
            self.assertLess(float(np.median(np.hypot(lab[:, 1], lab[:, 2]))), 6.0)

    def test_a_dark_brown_non_metal_does_not_take_the_grey_steel_beside_it(self):
        # Walnut grips declared #622513: the colour rule (every channel within 48) also took dark grey steel (51, 51,
        # 51) as walnut, 6.8% of a pistol's texels; set to non-metal, the colour transfer then tinted them like the
        # wood and the barrel and trigger came out pink (2026-10-25). A coloured declaration takes only texels with
        # at least a quarter of its saturation (the generated walnut is duller than the concept's).
        import tempfile
        from pathlib import Path
        import numpy as np
        from PIL import Image
        from slopforge.unity_material import zero_metallic
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = Image.new("RGB", (64, 32), (51, 51, 51)); base.paste((67, 43, 28), (32, 0, 64, 32)); base.save(root / "base.png")
            Image.new("L", (64, 32), 255).save(root / "metal.png")
            zero_metallic(root / "base.png", root / "metal.png", [(98, 37, 19)])
            metal = np.asarray(Image.open(root / "metal.png").convert("L"))
        self.assertEqual(int(metal[16, 8]), 255)  # grey steel stays metal
        self.assertEqual(int(metal[16, 48]), 0)  # the walnut does not

    def test_a_coloured_non_metal_takes_its_darker_grain_but_not_a_screw(self):
        # The generated walnut on HP10's grips was (65, 45, 34) and its dark grain (49, 34, 24): 49 from #622513 in red,
        # outside the per-channel window, so the grain stayed metal and rendered as grey flecks across the grips, 9-11%
        # of each grip's texels (2026-10-26). Wood grain changes lightness, not hue. Stripes of wood and grain, a grey
        # screw head inside the grip, and grey steel beside it.
        import tempfile
        from pathlib import Path
        import numpy as np
        from PIL import Image
        from slopforge.unity_material import zero_metallic
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = Image.new("RGB", (256, 128), (51, 51, 51))  # steel on the left half
            for x in range(128, 256, 8):
                base.paste((65, 45, 34), (x, 0, x + 5, 128))  # wood
                base.paste((49, 34, 24), (x + 5, 0, x + 8, 128))  # dark grain
            base.paste((53, 52, 51), (176, 48, 208, 80))  # a screw head in the grip
            base.save(root / "base.png")
            Image.new("L", (256, 128), 255).save(root / "metal.png")
            zero_metallic(root / "base.png", root / "metal.png", [(98, 37, 19)])
            metal = np.asarray(Image.open(root / "metal.png").convert("L"))
        self.assertEqual(int(metal[64, 40]), 255)  # steel stays metal
        self.assertEqual(int(metal[64, 192]), 255)  # the screw head stays metal
        grip = np.concatenate([metal[:, 128:176], metal[:, 216:]], axis=1)[8:120]
        self.assertLessEqual(float((grip > 127).mean()), 0.01, "the grain stayed metal")

    def test_a_grey_colour_does_not_borrow_a_coloured_ones_shift(self):
        # A grey cluster within 20 CIELAB of the walnut's borrowed the walnut's a*b* shift (+19.6, +10.8) and steel
        # set to non-metal came out pink (2026-10-25). A colour borrows a shift only from one about as saturated.
        import tempfile
        from pathlib import Path
        import numpy as np
        from PIL import Image
        from slopforge.unity_material import match_concept_colours
        from slopforge.validation import _lab
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cutout = np.zeros((64, 64, 4)); cutout[..., 3] = 255; cutout[..., :3] = (98, 37, 19)  # walnut, seen
            view = np.zeros((64, 64, 4)); view[..., 3] = 255; view[..., :3] = (60, 42, 32)  # duller walnut
            metal = np.zeros((64, 64, 4)); metal[..., 3] = 255
            base = Image.new("RGB", (64, 64), (60, 42, 32)); base.paste((52, 52, 52), (0, 0, 8, 8)); base.save(root / "base.png")
            Image.new("L", (64, 64), 0).save(root / "metal.png")
            match_concept_colours(root / "base.png", root / "metal.png", cutout, view, metal)
            grey = _lab(np.asarray(Image.open(root / "base.png").convert("RGB"), dtype=float)[0:8, 0:8].reshape(-1, 3))
        self.assertLess(float(np.median(np.hypot(grey[:, 1], grey[:, 2]))), 4.0)

    def test_part_metal_by_region_name(self):
        from slopforge.unity_material import part_metal
        materials = [{"region": "slide and frame", "class": "metal", "description": "blued steel"},
                     {"region": "grips", "class": "nonmetal", "description": "checkered walnut"}]
        parts = [{"name": "grip", "kind": "grip"}, {"name": "slide", "kind": "slide"}, {"name": "trigger", "kind": "hinge"}]
        self.assertEqual(part_metal(parts, materials), {"grip": 0, "slide": 1, "trigger": 1})
        self.assertEqual(part_metal(parts, [{"region": "all", "class": "nonmetal", "description": "wood"}]),
                         {"grip": 0, "slide": 0, "trigger": 0})


def fixture_masks(root):
    """A 100x60 object cutout with a grip (30x40 px) and a slide (90x20 px) mask; returns the masks directory."""
    from PIL import Image
    cutout = Image.new("RGBA", (120, 80), (0, 0, 0, 0)); cutout.paste((90, 90, 90, 255), (10, 10, 110, 70))
    cutout.save(root / "cutout.png")
    masks = root / "masks"; masks.mkdir()
    grip = Image.new("L", (120, 80), 0); grip.paste(255, (20, 30, 50, 70)); grip.save(masks / "grip.png")
    slide = Image.new("L", (120, 80), 0); slide.paste(255, (20, 10, 110, 30)); slide.save(masks / "slide.png")
    return masks


class OmniPartBackendTests(unittest.TestCase):
    def test_a_part_under_three_cells_of_omniparts_grid_stops_before_the_run(self):
        # OmniPart's structure is 64 cells across its 1.2x crop of the object: a 100 px object has 1.9 px cells, and
        # the R2 rifle's 3.6x1.7-cell bolt and 2.8x2.2-cell trigger never came out (2026-10-25, three seeds each).
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from PIL import Image
        from slopforge.backends import omnipart
        from slopforge.failures import StageFailure
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            masks = fixture_masks(root)
            trigger = Image.new("L", (120, 80), 0); trigger.paste(255, (60, 40, 66, 45)); trigger.save(masks / "trigger.png")
            parts = [{"name": "grip", "kind": "grip"}, {"name": "slide", "kind": "slide"}, {"name": "trigger", "kind": "hinge"}]
            with patch.object(omnipart, "run_remote_tool") as remote, self.assertRaises(StageFailure) as caught:
                omnipart.generate_part_model(root, self._config({"omnipart_python": "/opt/env/bin/python",
                                                                 "omnipart_checkout": "/opt/OmniPart"}),
                                             root / "cutout.png", "pistol", root / "mesh_01/pistol.glb",
                                             root / "mesh_01/generation.json", 5, parts, masks, 27000, [], "matte")
            self.assertFalse(remote.called)
            self.assertIn("trigger", str(caught.exception))
            self.assertIn("3 cells", str(caught.exception))
            self.assertEqual(caught.exception.category, "configuration")  # the brief must change; no seed fixes it

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
            masks = fixture_masks(root)  # the real images: generate_part_model measures the parts before the run
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
                                     ("--metallic-output", lambda p: Image.new("L", (4, 4), 255).save(p)),
                                     ("--normal-output", lambda p: Image.new("RGB", (4, 4), (128, 128, 255)).save(p))):
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
                                             "matte", texture_size=4096, steps=40, cfg=5.0)
            request = seen["remote"]["request"]
            self.assertEqual((request["steps"], request["cfg"]), (40, 5.0))  # OmniPart's samplers, from the type
            self.assertEqual(request["image"], "concept.png")
            self.assertEqual(request["masks"], {"grip": "grip.png", "slide": "slide.png"})
            self.assertEqual(request["parts"], [{"name": "grip", "kind": "grip"}, {"name": "slide", "kind": "slide"}])
            self.assertEqual((request["seed"], seen["remote"]["cwd"], seen["remote"]["env"]["SPCONV_ALGO"]),
                             (5, "/opt/OmniPart", "native"))
            self.assertEqual(request["texture_size"], 4096)  # OmniPart's per-part bake, not its 1024 default
            self.assertEqual(set(seen["remote"]["uploads"]), {"concept.png", "grip.png", "slide.png"})
            self.assertEqual(seen["remote"]["label"], "omnipart")
            command = seen["blender"]
            self.assertIn("--metal", command)
            self.assertEqual(command[command.index("--face-budget") + 1], "27000")  # the caller's reduction budget
            self.assertEqual(command[command.index("--texture-size") + 1], "4096")
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


class HybridBackendTests(unittest.TestCase):
    def test_the_split_is_recorded_for_the_final_pass_and_the_stage(self):
        # generate_hybrid_parts writes parts.json (the final pass's part table, with close_openings) and records the
        # route, the split's quality and OmniPart's provenance in generation.json; the surface's recorded hash follows
        # its rewrite as nodes and the unsplit surface is kept as an output.
        import json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from slopforge.backends import hybrid
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            surface = root / "mesh_01/pistol.glb"
            surface.parent.mkdir()
            surface.write_bytes(b"whole")
            metadata = root / "mesh_01/generation.json"
            metadata.write_text(json.dumps({"workflow": "trellis2", "outputs": [{"path": "pistol.glb", "sha256": "old"}]}))
            masks = root / "masks"
            masks.mkdir()
            parts = [{"name": "grip", "kind": "grip"}, {"name": "slide", "kind": "slide"}]
            seen = {}

            def omnipart(config, cutout, parts_, masks_dir, out, seed, *args):
                seen["omnipart"] = (out.name, seed)
                out.mkdir(parents=True, exist_ok=True)
                return {"backend": {"provider": "omnipart"}, "model_weights": {"omnipart/OmniPart": "rev"}}

            def split(root_, config, surface_, parts_glb, cutout, masks_, parts_, work_dir):
                seen["split"] = (parts_glb.name, sorted(masks_))
                surface_.with_name("pistol_whole.glb").write_bytes(b"whole")
                surface_.write_bytes(b"nodes")
                return {"alignment_error": 0.014, "shares": {"body": 0.7, "slide": 0.3}, "cut_length": 8.1, "masks_dropped": [],
                        "parts": {"body": {"kind": "body", "id": 1}, "slide": {"kind": "slide", "id": 2}},
                        "tools": {"hybrid_graph.py": "abc"},
                        "view": {"theta": -90, "phi": 0, "fit": 0.96, "seen": 0.13, "through": True}}
            with patch.object(hybrid, "run_omnipart", side_effect=omnipart), \
                    patch.object(hybrid, "split_surface", side_effect=split):
                hybrid.generate_hybrid_parts(root, {}, root / "cutout.png", surface, metadata, 7, parts, masks)
            self.assertEqual(seen["omnipart"], ("parts", 7))
            self.assertEqual(seen["split"], ("parts.glb", ["slide"]))  # moving parts vote with their masks
            table = json.loads((surface.parent / "parts/parts.json").read_text())
            self.assertTrue(table["close_openings"])
            self.assertEqual(table["parts"]["slide"], {"kind": "slide", "id": 2})
            info = json.loads(metadata.read_text())
            self.assertEqual(info["part_model"], "hybrid")
            self.assertEqual(info["hybrid"]["alignment_error"], 0.014)
            self.assertTrue(info["hybrid"]["view"]["through"])  # whether the mask voted on every face
            self.assertEqual(info["part_generator"]["model_weights"], {"omnipart/OmniPart": "rev"})
            from slopforge.provenance import file_sha256
            self.assertEqual(info["outputs"][0]["sha256"], file_sha256(surface))
            self.assertEqual(info["outputs"][-1]["kind"], "mesh.whole")
