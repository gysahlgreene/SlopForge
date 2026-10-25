"""Labelling a generated surface's faces as parts with crease-aware graph cuts (slopforge/part_split.py)."""
import unittest

import numpy as np

from slopforge.part_split import binary_cut, label_faces


def strip(n, crease_at, crease_angle=80.0):
    """n faces in a row; face i touches face i+1 over an edge of length 1, the one at `crease_at` a crease."""
    pairs = np.array([(i, i + 1) for i in range(n - 1)])
    angles = np.array([crease_angle if i == crease_at else 2.0 for i in range(n - 1)])
    return pairs, np.ones(n - 1), angles, np.ones(n)


class BinaryCutTests(unittest.TestCase):
    def test_the_minimum_cut_matches_brute_force_on_a_small_graph(self):
        rng = np.random.default_rng(3)
        n = 7
        pairs = np.array([(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < 0.5])
        weights = rng.random(len(pairs)) * 2
        cost_in, cost_out = rng.random(n) * 3, rng.random(n) * 3
        chosen = binary_cut(n, cost_in, cost_out, pairs, weights)

        def energy(inside):
            unary = np.where(inside, cost_in, cost_out).sum()
            return unary + sum(w for (a, b), w in zip(pairs, weights) if inside[a] != inside[b])
        best = min(energy(np.array([(k >> i) & 1 for i in range(n)], bool)) for k in range(2 ** n))
        self.assertAlmostEqual(energy(chosen), best, places=2)


    def test_large_costs_and_undefined_angles_do_not_overflow(self):
        # a face far from a part costs thousands of units; a degenerate face has no angle (NaN)
        import warnings
        pairs = np.array([(0, 1), (1, 2)])
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            chosen = binary_cut(3, np.array([0.0, 5e4, 5e4]), np.array([5e4, 0.0, 0.0]), pairs,
                                np.array([np.nan, 1.0]))
        self.assertEqual(list(chosen), [True, False, False])


class LabelFacesTests(unittest.TestCase):
    def test_the_boundary_moves_to_the_nearest_crease(self):
        # Faces 0-9 are near the slide, 10-19 near the body by OmniPart's parts; the generated surface's own crease
        # sits between faces 12 and 13. The label boundary follows the crease, not the vote's midpoint.
        n = 20
        pairs, lengths, angles, areas = strip(n, crease_at=12)
        gap = np.linspace(-1.0, 1.0, n) * 0.004  # slide distance minus body distance, in weapon lengths
        distances = np.stack([np.maximum(-gap, 0) + 0.001, np.maximum(gap, 0) + 0.001], 1)  # body, slide
        labels = label_faces(distances, ["body", "slide"], pairs, lengths, angles, areas, lam=2.0)
        self.assertEqual(list(labels[:13]), ["slide"] * 13)
        self.assertEqual(list(labels[13:]), ["body"] * 7)

    def test_a_strong_vote_is_not_overruled_by_a_crease_far_away(self):
        n = 20
        pairs, lengths, angles, areas = strip(n, crease_at=17)
        gap = np.linspace(-1.0, 1.0, n) * 0.05  # a decisive vote: half a part's width
        distances = np.stack([np.maximum(-gap, 0) + 0.001, np.maximum(gap, 0) + 0.001], 1)
        labels = label_faces(distances, ["body", "slide"], pairs, lengths, angles, areas, lam=2.0)
        self.assertLess(int((labels == "slide").sum()), 12)

    def test_the_concept_mask_decides_where_the_parts_say_nothing(self):
        n = 10
        pairs, lengths, angles, areas = strip(n, crease_at=4)
        distances = np.full((n, 2), 0.01)  # OmniPart's parts are equally far: no 3D vote
        mask = np.array([1, 1, 1, 0, 0, 0, 0, -1, -1, -1])  # seen inside the lid mask, unseen, seen outside
        labels = label_faces(distances, ["body", "hinge"], pairs, lengths, angles, areas, masks={"hinge": mask})
        self.assertEqual(list(labels), ["hinge"] * 5 + ["body"] * 5)  # the unseen faces follow the crease

    def test_a_part_omnipart_misplaced_is_cut_where_the_mask_says(self):
        # Seed 1 of the 2026-10-25 live pistol: the mask's votes covered the slide, OmniPart's slide was a speck at the
        # muzzle, and its far-off distances outvoted the mask. OmniPart's vote counts as far as its part agrees with
        # the mask where the mask votes.
        n = 20
        pairs, lengths, angles, areas = strip(n, crease_at=9)
        distances = np.zeros((n, 2))  # body, slide
        distances[:, 0] = 0.001  # OmniPart's body is near every face
        distances[:, 1] = 0.2  # its slide is far from all of them
        mask = np.array([1] * 10 + [-1] * 10)
        labels = label_faces(distances, ["body", "slide"], pairs, lengths, angles, areas, masks={"slide": mask})
        self.assertEqual(list(labels), ["slide"] * 10 + ["body"] * 10)

    def test_a_trigger_is_cut_from_what_the_slide_leaves(self):
        n = 30
        pairs, lengths, angles, areas = strip(n, crease_at=9)
        angles[19] = 80.0
        distances = np.full((n, 3), 0.02)  # body, hinge, slide
        distances[:10, 2] = 0.0
        distances[10:20, 1] = 0.0
        distances[20:, 0] = 0.0
        labels = label_faces(distances, ["body", "hinge", "slide"], pairs, lengths, angles, areas)
        self.assertEqual(list(labels), ["slide"] * 10 + ["hinge"] * 10 + ["body"] * 10)


if __name__ == "__main__":
    unittest.main()


def l_shape(rng, n=4000):
    """Points on an asymmetric L: a long bar with a short leg at one end and a bump on top, so no turn fits twice."""
    bar = rng.uniform([-0.5, -0.05, 0.0], [0.5, 0.05, 0.12], (n, 3))
    leg = rng.uniform([0.25, -0.05, -0.35], [0.45, 0.05, 0.0], (n // 2, 3))
    bump = rng.uniform([-0.45, -0.03, 0.12], [-0.35, 0.03, 0.18], (n // 8, 3))
    return np.concatenate([bar, leg, bump])


class AlignTests(unittest.TestCase):
    def test_another_generators_frame_is_found_among_the_quarter_turns_and_refined(self):
        # TRELLIS.2 lays a pistol along Y, OmniPart along X (2026-10-25): the parts must land on the surface
        from scipy.spatial import cKDTree
        from slopforge.part_split import align
        rng = np.random.default_rng(7)
        target = l_shape(rng)
        turn = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)  # a quarter turn about z
        tilt = np.array([[1, 0, 0], [0, np.cos(0.08), -np.sin(0.08)], [0, np.sin(0.08), np.cos(0.08)]])
        source = (l_shape(rng) @ (tilt @ turn).T) * 1.04 + np.array([0.02, -0.01, 0.03])
        matrix, offset, error = align(source, target)
        moved = source @ matrix.T + offset
        self.assertLess(float(cKDTree(target).query(moved)[0].mean()), 0.012)
        self.assertLess(error, 0.012)


class PartDistancesTests(unittest.TestCase):
    def test_a_face_centre_is_measured_to_the_nearest_part_surface(self):
        from slopforge.part_split import part_distances
        square = (np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float), np.array([[0, 1, 2], [0, 2, 3]]))
        lifted = (square[0] + [0, 0, 1], square[1])
        distances = part_distances(np.array([[0.5, 0.5, 0.1], [0.5, 0.5, 0.8]]), [square, lifted], samples=20000)
        self.assertTrue(np.allclose(distances, [[0.1, 0.9], [0.8, 0.2]], atol=0.01))
