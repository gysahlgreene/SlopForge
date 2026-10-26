"""Choosing among SAM's candidate masks for a declared part box (processing/part_masks.py)."""
import unittest

import numpy as np

from processing.part_masks import choose_mask


def box_mask(shape, rows, cols):
    mask = np.zeros(shape, bool)
    mask[rows[0]:rows[1], cols[0]:cols[1]] = True
    return mask


class ChooseMaskTests(unittest.TestCase):
    def test_a_lid_box_takes_the_mask_that_fills_it_not_its_trim(self):
        # The 2026-10-25 chest: SAM's single answer for the lid box was the two iron band arcs (5% of the chest)
        alpha = box_mask((100, 100), (20, 90), (10, 90))
        box = [10, 20, 90, 50]  # x0, y0, x1, y1 in pixels: the lid, the top of the chest
        bands = box_mask(alpha.shape, (20, 50), (10, 14)) | box_mask(alpha.shape, (20, 50), (86, 90))
        lid = box_mask(alpha.shape, (20, 49), (10, 90))
        whole = alpha.copy()
        index, report = choose_mask([bands, lid, whole], [0.84, 0.80, 0.90], box, alpha)
        self.assertEqual(index, 1)
        self.assertEqual(len(report), 3)  # every candidate's fill and spill is recorded

    def test_a_tight_trigger_box_keeps_the_trigger_not_its_guard_or_the_frame(self):
        alpha = box_mask((100, 100), (10, 90), (10, 90))
        box = [40, 50, 50, 70]
        trigger = box_mask(alpha.shape, (52, 68), (43, 47))
        guard = trigger | box_mask(alpha.shape, (50, 75), (30, 70)) & ~box_mask(alpha.shape, (55, 70), (35, 65))
        frame = alpha.copy()
        index, _report = choose_mask([trigger, guard, frame], [0.70, 0.86, 0.95], box, alpha)
        self.assertEqual(index, 0)

    def test_between_equal_masks_the_higher_score_wins(self):
        alpha = box_mask((50, 50), (0, 50), (0, 50))
        a = box_mask(alpha.shape, (10, 30), (10, 30))
        index, _report = choose_mask([a, a.copy()], [0.5, 0.9], [10, 10, 30, 30], alpha)
        self.assertEqual(index, 1)


if __name__ == "__main__":
    unittest.main()


class CloseMaskTests(unittest.TestCase):
    def test_a_strap_across_a_lid_does_not_split_its_mask(self):
        # SAM's lid mask stopped at the iron band across the chest's lid, and OmniPart then left the band and the
        # lid's ends with the body (2026-10-25): gaps narrower than ~4% of the object close; nothing outside the
        # object is added.
        from processing.part_masks import close_mask
        alpha = box_mask((100, 100), (20, 90), (5, 95))
        lid = box_mask(alpha.shape, (20, 45), (5, 47)) | box_mask(alpha.shape, (20, 45), (51, 95))  # band at 47-51
        closed = close_mask(lid, alpha)
        self.assertTrue(closed[20:45, 47:51].all())
        self.assertFalse((closed & ~alpha).any())
        self.assertFalse(closed[60:90].any())  # the body below stays out

    def test_a_trigger_and_its_guard_stay_apart(self):
        from processing.part_masks import close_mask
        alpha = box_mask((200, 200), (10, 190), (10, 190))
        trigger = box_mask(alpha.shape, (100, 130), (90, 96))
        guard = box_mask(alpha.shape, (100, 140), (120, 126))  # another part, 24 px away: not in this mask
        closed = close_mask(trigger, alpha)
        self.assertFalse(closed[:, 110:].any())


class GridPointsTests(unittest.TestCase):
    def test_the_prompt_points_lie_on_the_object_inside_the_box(self):
        # SAM's three answers for a chest's lid box were each one row of planks (fill 0.04 at best, 2026-10-25); with
        # nine points on the object inside the box as well, it took the dome (0.65). A point the grid places off the
        # object (between a chest's legs, beside a trigger) moves to the nearest object pixel in the box.
        from processing.part_masks import grid_points
        alpha = np.zeros((100, 200), bool)
        alpha[20:60, 10:190] = True  # a body
        alpha[60:90, 10:30] = True  # a leg
        box = (0, 10, 200, 95)
        points = grid_points(alpha, box)
        self.assertEqual(len(points), 9)
        for x, y in points:
            self.assertTrue(alpha[int(y), int(x)], (x, y))
            self.assertTrue(box[0] <= x < box[2] and box[1] <= y < box[3], (x, y))
        self.assertEqual(len({tuple(point) for point in points}), 9)
        self.assertIn((29, 78), {tuple(point) for point in points})  # off the object, onto the leg beside it
