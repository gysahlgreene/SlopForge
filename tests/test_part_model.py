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
    def test_declared_parts_then_body_then_rear_parts_get_ids(self):
        alpha, masks, parts = fixture()
        ids, table = part_ids(alpha, masks, parts)
        self.assertEqual([entry["name"] for entry in table], ["slide", "trigger", "body", "slide_rear"])
        self.assertEqual([entry["kind"] for entry in table], ["slide", "hinge", "body", "static"])
        self.assertEqual([entry["id"] for entry in table], [1, 2, 3, 4])
        self.assertTrue((ids[0:20, 10:100] == 1).all())
        self.assertTrue((ids[25:35, 40:50] == 2).all())
        self.assertTrue((ids[0:20, 0:10] == 4).all())  # the hammer blob: body pixels above the slide line
        self.assertTrue((ids[20:60, 0:40] == 3).all())
        self.assertEqual(int((ids == 0).sum()), 0)

    def test_body_pixels_above_each_slide_become_rear_parts(self):
        alpha = np.ones((60, 100), bool)
        upper = np.zeros_like(alpha); upper[0:10, 20:100] = True
        lower = np.zeros_like(alpha); lower[30:40, 20:100] = True
        parts = [{"name": "bolt", "kind": "slide"}, {"name": "release", "kind": "slide"}]
        ids, table = part_ids(alpha, {"bolt": upper, "release": lower}, parts)
        self.assertEqual([entry["name"] for entry in table], ["bolt", "release", "body", "bolt_rear", "release_rear"])
        self.assertTrue((ids[0:10, 20:100] == 1).all())
        self.assertTrue((ids[30:40, 20:100] == 2).all())  # the lower slide keeps its own pixels
        self.assertTrue((ids[0:10, 0:20] == 4).all())
        self.assertTrue((ids[10:40, 0:20] == 5).all())
        self.assertTrue((ids[40:60, :] == 3).all())

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
        sign, _bbox, lo, hi = object_frame(alpha, coords)
        self.assertEqual(sign, 1)
        self.assertEqual(object_frame(alpha[:, ::-1], coords)[0], -1)
        np.testing.assert_allclose(lo, [-0.5 + 0.5 / 64, -0.5 + 28.5 / 64, -0.5 + 0.5 / 64], atol=1e-6)
        np.testing.assert_allclose(hi, [-0.5 + 59.5 / 64, -0.5 + 35.5 / 64, -0.5 + 39.5 / 64], atol=1e-6)

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
        lo, hi = frame[2], frame[3]
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
        self.assertEqual(boxes.shape, (4, 2, 3))
        ordered = [entry["name"] for entry in sorted(table, key=lambda e: -np.where(ids == e["id"])[0].max())]
        self.assertEqual(ordered, ["body", "trigger", "slide", "slide_rear"])
        for box in boxes:
            self.assertAlmostEqual(float(box[0][1]), float(frame[2][1]), places=6)
            self.assertAlmostEqual(float(box[1][1]), float(frame[3][1]), places=6)
        self.assertEqual([box[0][0] <= box[1][0] and box[0][2] <= box[1][2] for box in boxes], [True] * 4)


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


if __name__ == "__main__":
    unittest.main()
