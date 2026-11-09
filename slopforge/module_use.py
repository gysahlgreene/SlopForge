"""How a sized piece can be used, measured from ray grids that blender/inspect_model.py casts (issue #189).

Sizing fits a piece's outer bounds exactly, but a game uses dimensions inside them. On round 23's street kit
(2026-11-09) plinths and cornices set the walls' widths, so a row of them left 0.1-0.43 m gaps. A stair's parapets
and head wall set its height, so its landing ended 0.58 m low. A tunnel mouth 9 m wide had a 2.7 m opening.
Plain numpy, so Blender's Python and the tests share it.
"""
import math

import numpy as np

CELL = 0.1  # ray spacing in metres
WALK_CLEARANCE = 0.8  # a walking surface holds a square this wide; parapet tops and copings (0.3-0.6 m) do not
WALK_STEP = 0.05  # heights within this of a level belong to it
MAX_SILL = 0.3  # a passage starts within this of the ground
OPENING_STEP = 0.25  # the clear-opening profile's width step in metres


def row_gap(left, right, width):
    """The gap a row of the piece leaves: its bounds width less its median width over height bands.

    left and right hold each band's outermost hit from either end (nan where the band was not hit).
    """
    widths = np.asarray(right, float) - np.asarray(left, float)
    widths = widths[np.isfinite(widths)]
    return round(float(width - np.median(widths)), 3) if widths.size else None


def _holds_square(mask, size):
    total = np.pad(mask.astype(int).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    window = total[size:, size:] - total[:-size, size:] - total[size:, :-size] + total[:-size, :-size]
    return bool((window == size * size).any())


def walk_levels(heights, flat, cell=CELL):
    """Heights of the flat surfaces that hold a WALK_CLEARANCE square, highest first.

    heights is a top-down grid of the first surface hit (nan for a miss); flat marks hits facing up. A thick
    parapet's top can count (round 23's gate tower: 13.45 m over its 12.5 m roof), so a declared height is looked
    for among them rather than taken as the highest.
    """
    heights = np.where(np.asarray(flat, bool) & np.isfinite(heights), heights, np.nan)
    known = np.isfinite(heights)
    size = math.ceil(WALK_CLEARANCE / cell - 1e-9)
    levels = []
    for level in np.unique(np.round(heights[known] / WALK_STEP))[::-1]:
        mask = known & (np.abs(np.where(known, heights, 0) - level * WALK_STEP) <= WALK_STEP)
        if _holds_square(mask, size):
            height = round(float(np.median(heights[mask])), 3)
            if not levels or levels[-1] - height > 2 * WALK_STEP:
                levels.append(height)
    return levels


def clear_opening(through, cell=CELL, row_cell=None):
    """[[width, height], ...]: how tall the clearest passage of each width (OPENING_STEP apart) is, in metres.

    through is a front-view grid, rows from the ground up, marking rays that passed straight through the piece.
    A passage starts within MAX_SILL of the ground. cell spaces the columns, row_cell (default cell) the rows.
    """
    row_cell = row_cell or cell
    through = np.asarray(through, bool)
    rows, columns = through.shape
    best = np.zeros(columns + 1)  # best[w]: tallest passage w cells wide
    for start in range(min(rows, int(MAX_SILL / row_cell) + 1)):
        run = np.zeros(columns)
        for column in range(columns):
            closed = np.flatnonzero(~through[start:, column])
            run[column] = closed[0] if closed.size else rows - start
        for width in range(1, columns + 1):
            best[width] = max(best[width], np.lib.stride_tricks.sliding_window_view(run, width).min(-1).max())
    steps = int(columns * cell / OPENING_STEP + 1e-9)
    return [[round((step + 1) * OPENING_STEP, 2),
             round(float(best[min(columns, math.ceil((step + 1) * OPENING_STEP / cell - 1e-9))] * row_cell), 2)]
            for step in range(steps)]


def opening_height(profile, width):
    """How tall a passage at least `width` metres wide is, from a clear_opening profile (0 when none is)."""
    return next((height for wide, height in profile or [] if wide >= width - 1e-9), 0.0)
