"""B6's gait measures on an extracted creature motion (AI motion sources plan, B6; docs/CREATURES.md, "Extraction and
bake"). Pure NumPy, so blender/bake_extracted_motion.py samples the rig and calls these, and the tests need no Blender.

- swings / gait: plants per leg (#149's plants.py rule), the period and, with the root's track, the speed and stride.
- in_place: the root's linear horizontal travel removed (the owner's D9 ruling: a delivered clip is in place; the
  Unity Generic controller moves the creature at stride / period).
- loop_window: the whole number of periods to deliver as the looping clip, where the seam's pose matches best.
"""
import numpy as np

SWING, PLANT = 0.03, 0.01   # a foot's lift as a share of the body height: a swing passes SWING, a plant is under PLANT


class GaitError(ValueError):
    """A motion that has no measurable cycle; `code` is its failure code (failures._KIND_CODES["motion"])."""

    def __init__(self, message, code="motion_no_cycle"):
        super().__init__(message)
        self.code = code


def swings(lift, *, swing=SWING, plant=PLANT):
    """[(lift frame, plant frame, peak lift)] for one foot's lift per frame (a share of the height); hysteresis, so
    jitter between the two shares is not a step."""
    found, start, peak = [], None, 0.0
    for frame, value in enumerate(np.asarray(lift, float)):
        if start is None:
            if value > swing:
                start, peak = frame, value
        else:
            peak = max(peak, value)
            if value < plant:
                found.append((start, frame, round(float(peak), 4)))
                start = None
    return found


TRAVEL_DEGREE = 3   # the travel is a smooth curve: #149's g2 sped up from 20 to 29 mm a frame; a step's sway is not


def in_place(root, times):
    """(root positions with the horizontal travel removed, the travel's mean velocity [x, y] in m/s). The travel is
    the least-squares cubic through the root's horizontal track: it follows a walk that speeds up or slows down, and
    the sway of each step, many times faster, stays. The height is untouched; the first frame keeps its place."""
    root, times = np.asarray(root, float), np.asarray(times, float)
    elapsed = times - times[0]
    travel = np.polynomial.polynomial.Polynomial.fit(elapsed, root[:, 0], TRAVEL_DEGREE), \
        np.polynomial.polynomial.Polynomial.fit(elapsed, root[:, 1], TRAVEL_DEGREE)
    curve = np.stack([fit(elapsed) - fit(0.0) for fit in travel], 1)
    still = root.copy()
    still[:, :2] -= curve
    velocity = np.polyfit(elapsed, root[:, :2], 1)[0]
    return still, velocity


REST = 10   # percentile of a foot's own height taken as its resting height: a walking foot stands most of the cycle


def gait(feet, times, height, *, root=None):
    """{plants, swings, period_s, cycles[, speed_mps, velocity, stride_m]} from each leg's foot height per frame (m).
    Each foot's lift is measured from its own resting height, not a shared floor: a fit sinks a foot under the floor in
    some frames, and a foot's lowest bone tail rests above the skin's sole (#149's g2). The period is the median
    interval between successive plants of one leg, over every leg; a leg planting fewer than twice gives none, and the
    motion is refused."""
    times = np.asarray(times, float)
    found = {}
    for leg, heights in feet.items():
        heights = np.asarray(heights, float)
        found[leg] = swings((heights - np.percentile(heights, REST)) / height)
    plants = {leg: [end for _, end, _ in steps] for leg, steps in found.items()}
    short = sorted(leg for leg, frames in plants.items() if len(frames) < 2)
    if short:
        raise GaitError(f"no walk cycle: {', '.join(short)} planted fewer than twice "
                        f"({', '.join(f'{leg} {len(plants[leg])}' for leg in short)})")
    intervals = np.concatenate([np.diff(times[frames]) for frames in plants.values()])
    result = {"plants": plants, "swings": found, "period_s": round(float(np.median(intervals)), 4),
              "cycles": min(len(frames) for frames in plants.values())}
    if root is not None:
        _, velocity = in_place(root, times)
        speed = float(np.hypot(*velocity))
        result.update(velocity=[round(float(v), 4) for v in velocity], speed_mps=round(speed, 4),
                      stride_m=round(speed * result["period_s"], 4))
    return result


def _seam_deg(rotations, a, b):
    """Mean angle (degrees) between the bones' rotations (quaternions) at frames a and b."""
    dot = np.abs(np.sum(rotations[a] * rotations[b], axis=-1)).clip(0.0, 1.0)
    return float(np.degrees(2 * np.arccos(dot)).mean())


def loop_window(rotations, times, period):
    """{start, end, cycles, seam_deg}: the most whole periods that fit in the motion, starting at the frame whose pose
    the frame a whole number of periods later matches best (bones' rotations as quaternions, [frames, bones, 4])."""
    rotations, times = np.asarray(rotations, float), np.asarray(times, float)
    cycles = int((times[-1] - times[0]) // period)
    if cycles < 1:
        raise GaitError(f"no walk cycle: the motion lasts {times[-1] - times[0]:.2f} s, under one period "
                        f"({period:.2f} s)")
    best = None
    for start, t in enumerate(times):
        if t + cycles * period > times[-1] + 1e-9:
            break
        end = int(np.argmin(np.abs(times - (t + cycles * period))))
        seam = _seam_deg(rotations, start, end)
        if best is None or seam < best["seam_deg"]:
            best = {"start": start, "end": end, "cycles": cycles, "seam_deg": round(seam, 3)}
    return best
