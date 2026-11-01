"""B6's gait measures on an extracted creature motion (AI motion sources plan, B6; docs/CREATURES.md, "Extraction and
bake"). Pure NumPy, so blender/bake_extracted_motion.py samples the rig and calls these, and the tests need no Blender.

- steps / gait: each leg's steps (the foot swinging forward relative to the hips), its plants, the period, the clean
  stretch the loop may use and, with the root's track, the speed and stride.
- in_place: the root's linear horizontal travel removed (the owner's D9 ruling: a delivered clip is in place; the
  Unity Generic controller moves the creature at stride / period).
- loop_window: the whole number of periods to deliver as the looping clip, where the seam's pose matches best.
- gait_settings: a creature type's computed motion (B4, blender/procedural_gait.py), which the same bake measures.
"""
import numpy as np

PLANT = 0.01   # a planted foot's lift as a share of the body height (the bake's stance slide)
# A step swings the foot forward, relative to the hips, over STEP of the height; one under PARTIAL of its leg's median
# step is partial (2026-10-31: the wolf's front legs got going with 8-23 cm half steps against about 47; 0.5 let a
# 22 cm one through, 0.6 caught it on five Wan walks and kept a four-period loop in four of them)
STEP, PARTIAL = 0.05, 0.6
MIN_PLANTS = 2              # a leg's period is the interval between two of its plants; a full cycle needs one each
# B0's limits for each refusal (failures._KIND_CODES["motion"]): every leg plants once; some leg plants twice; a whole
# period with no partial step
GAIT_LIMITS = {"motion_no_cycle": {"min_motion_plants": 1}, "motion_no_period": {"min_motion_max_plants": MIN_PLANTS},
               "motion_no_clean_period": {"min_motion_clean_periods": 1}}


class GaitError(ValueError):
    """A motion that has no measurable cycle; `code` and `measured` are B0's (failures._KIND_CODES["motion"])."""

    def __init__(self, message, measured, code="motion_no_cycle"):
        super().__init__(message)
        self.code, self.measured = code, measured


def steps(forward, height, *, step=STEP):
    """[(start frame, end frame, reach m)] for one foot's forward offset from the hips per frame (m): each run of
    frames it moves forward (a 3-frame mean of its motion, so a frame's jitter does not split a swing), its ends moved
    to the lowest and highest offsets beside them, reaching over `step` of the height. A swing cut by the clip's first
    or last frame reaches less than it would."""
    forward = np.asarray(forward, float)
    moving = np.convolve(np.diff(forward), np.ones(3) / 3, mode="same") > 0
    found, start = [], None
    for frame, ahead in enumerate([*moving, False]):
        if ahead and start is None:
            start = frame
        elif not ahead and start is not None:
            low = max(start - 1, 0) + int(np.argmin(forward[max(start - 1, 0):start + 2]))
            high = frame - 1 + int(np.argmax(forward[frame - 1:frame + 2]))
            reach = float(forward[high] - forward[low])
            if reach > step * height:
                found.append((low, high, round(reach, 4)))
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


def gait(feet, times, height, *, root=None):
    """{plants, steps, partial, clean, period_s, cycles, weak_legs[, speed_mps, velocity, stride_m]} from each leg's
    foot offset forward of the hips per frame (m). A step is the foot swinging forward (steps); its plant is where the
    swing ends. Steps under PARTIAL of their leg's median are partial: a creature getting going, or a shuffle. A full
    cycle is every leg planting at least once (`cycles` is the fewest plants of any leg); the period is the median
    interval between successive plants of one leg, over the legs that plant twice or more; legs planting once are
    `weak_legs`. `clean` is the longest stretch [first, last frame] with no partial step: the loop is cut from it.
    A leg that never plants, no leg planting twice, or no whole period in the clean stretch refuses the motion.
    2026-10-31: lift (over 3 % of the height) found one front step where the B1 wolf's foot swung forward six times,
    so the period came out 2.5 s for 1.2 and the loop took in the front legs' half steps while getting going."""
    times = np.asarray(times, float)
    found, partial = {}, []
    last = len(times) - 1
    for leg, forward in feet.items():
        runs = steps(forward, height)
        whole = [run for run in runs if 0 < run[0] and run[1] < last]   # a swing the clip cuts has no known end
        median = float(np.median([reach for _, _, reach in whole])) if whole else 0.0
        found[leg] = [run for run in whole if run[2] >= PARTIAL * median]
        partial += [[leg, start, end] for start, end, reach in runs if (start, end, reach) not in found[leg]]
    plants = {leg: [end for _, end, _ in runs] for leg, runs in found.items()}
    fewest = min(len(frames) for frames in plants.values())
    never = sorted(leg for leg, frames in plants.items() if not frames)
    if never:
        raise GaitError(f"no full walk cycle: {', '.join(never)} never planted", {"motion_min_plants": fewest})
    timed = [frames for frames in plants.values() if len(frames) >= MIN_PLANTS]
    if not timed:
        raise GaitError("no walk period: no leg planted twice",
                        {"motion_max_plants": max(len(frames) for frames in plants.values())}, code="motion_no_period")
    period = float(np.median(np.concatenate([np.diff(times[frames]) for frames in timed])))
    # the gaps between partial steps; the longest is the clean stretch
    gaps, reach = [], 0
    for _, start, end in sorted(partial, key=lambda item: item[1]):
        gaps.append((reach, start))
        reach = max(reach, end)
    gaps.append((reach, len(times) - 1))
    clean = max(gaps, key=lambda gap: times[gap[1]] - times[gap[0]])
    periods = int((times[clean[1]] - times[clean[0]]) // period)
    if periods < 1:
        raise GaitError(f"no clean walk period: partial steps leave {times[clean[1]] - times[clean[0]]:.2f} s at most "
                        f"without one, under a period ({period:.2f} s)", {"motion_clean_periods": periods},
                        code="motion_no_clean_period")
    result = {"plants": plants, "steps": found, "partial": sorted(partial, key=lambda item: item[1]),
              "clean": [int(clean[0]), int(clean[1])], "period_s": round(period, 4), "cycles": fewest,
              "weak_legs": sorted(leg for leg, frames in plants.items() if len(frames) < MIN_PLANTS)}
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


def loop_window(rotations, times, period, *, allowed=None):
    """{start, end, cycles, seam_deg}: the most whole periods that fit in the motion, starting at the frame whose pose
    the frame a whole number of periods later matches best (bones' rotations as quaternions, [frames, bones, 4]).
    `allowed` marks the frames a window may start and end on (the keys on whole scene frames, which the FBX export
    bakes exactly); every frame by default."""
    rotations, times = np.asarray(rotations, float), np.asarray(times, float)
    allowed = np.ones(len(times), bool) if allowed is None else np.asarray(allowed, bool)
    ends = np.flatnonzero(allowed)
    cycles = int((times[-1] - times[0]) // period)
    if cycles < 1:
        raise ValueError(f"no loop window: the motion lasts {times[-1] - times[0]:.2f} s, under one period "
                         f"({period:.2f} s)")
    best = None
    for start, t in enumerate(times):
        if t + cycles * period > times[-1] + 1e-9:
            break
        if not allowed[start]:
            continue
        end = int(ends[np.argmin(np.abs(times[ends] - (t + cycles * period)))])
        seam = _seam_deg(rotations, start, end)
        if best is None or seam < best["seam_deg"]:
            best = {"start": start, "end": end, "cycles": cycles, "seam_deg": round(seam, 3)}
    if best is None:
        raise ValueError(f"no loop window: no key on a whole scene frame starts {cycles} periods")
    return best


GAIT_FPS = 24   # a computed motion's key rate; its period is snapped to whole frames so its loop closes on one
# a computed motion's declaration: (low, high) for each number. A walk's duty over half keeps three feet down, and
# seconds over four periods leave whole periods between the partial steps at its two ends. An idle is one loop of
# whole breaths, its sway a share of the height, its head's look and tail's sway in degrees to each side. A hop's duty
# under half leaves a moment with every foot in the air; its rise is a share of the height, its tip and arch in degrees.
GAIT_RANGES = {"walk": {"period_s": (0.3, 4.0), "duty": (0.5, 0.95), "stride": (0.05, 2.0), "lift": (0.005, 0.3),
                        "seconds": (0.0, 60.0)},
               "idle": {"seconds": (1.0, 30.0), "breaths": (0, 20), "sway": (0.0, 0.1), "look_deg": (0.0, 45.0),
                        "tail_deg": (0.0, 45.0)},
               "hop": {"period_s": (0.3, 4.0), "duty": (0.1, 0.49), "stride": (0.05, 2.0), "lift": (0.005, 0.3),
                       "rise": (0.0, 0.5), "pitch_deg": (0.0, 45.0), "flex_deg": (0.0, 60.0),
                       "seconds": (0.0, 60.0)}}


def gait_settings(asset_type, motion):
    """A motion the type computes (procedural_motions), as blender/procedural_gait.py takes it: a walk's {period_s,
    duty, stride, lift, seconds}, stride and lift shares of the creature's height; an idle's {seconds, breaths, sway,
    look_deg, tail_deg}; a hop's walk numbers and {rise, pitch_deg, flex_deg}, rise a share of the height. ValueError names a bad declaration."""
    name, motions = asset_type.get("name"), asset_type.get("procedural_motions")
    if not isinstance(motions, dict) or motion not in motions:
        known = ", ".join(sorted(motions)) if isinstance(motions, dict) else "none"
        raise ValueError(f"asset type {name!r} has no procedural motion {motion!r} (declared: {known})")
    if motion not in GAIT_RANGES:
        raise ValueError(f"asset type {name!r}: the gait computes {' and '.join(sorted(GAIT_RANGES))}, not {motion!r}")
    spec = motions[motion] if isinstance(motions[motion], dict) else {}
    for key, (low, high) in GAIT_RANGES[motion].items():
        value = spec.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low < value <= high:
            raise ValueError(f"procedural motion {motion!r}: {key} must be a number above {low:g} and at most "
                             f"{high:g}, got {value!r}")
    if motion in ("walk", "hop") and spec["seconds"] <= 4 * spec["period_s"]:
        raise ValueError(f"procedural motion {motion!r}: seconds must be over four periods "
                         f"({4 * spec['period_s']:g} s), got {spec['seconds']!r}")
    if motion == "idle" and not isinstance(spec["breaths"], int):
        raise ValueError(f"procedural motion {motion!r}: breaths must be a whole number, so the loop closes, got "
                         f"{spec['breaths']!r}")
    return {key: spec[key] for key in GAIT_RANGES[motion]}
