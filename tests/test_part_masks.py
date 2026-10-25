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
