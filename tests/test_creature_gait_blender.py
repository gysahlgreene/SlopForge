"""B4 in real Blender: a procedural walk built on the B1 fixture quadruped's rig (blender/procedural_gait.py), then
baked by B6's own bake (blender/bake_extracted_motion.py), as a generated creature's walk would be."""
import json
import subprocess
from pathlib import Path

import pytest

from slopforge.creature_rig import deformation_poses
from slopforge.creature_views import outside_panels
from tests.test_creature_rig import LIMBS, LIMITS, creature
from tests.test_creature_rig_blender import BLENDER, ROOT, blender

FPS = 24


def rigged(tmp_path):
    """The fixture quadruped checked and finished as `creature rig` does; (rig .blend, check report)."""
    rig = creature(extra=0)
    fixture = {"vertices": rig["vertices"].tolist(), "triangles": rig["triangles"].tolist(), "bones": rig["bones"],
               "parents": rig["parents"], "heads": rig["heads"].tolist(),
               "leads": [rig["bones"][k] for k in rig["weights"].argmax(1)]}
    source, raw = str(tmp_path / "source.fbx"), str(tmp_path / "raw.glb")
    blender(tmp_path, {"action": "fixture", "fixture": fixture, "source": source, "raw": raw})
    report = blender(tmp_path, {"action": "check", "raw": raw, "limbs": LIMBS, "limits": LIMITS,
                                "views": {view: str(tmp_path / f"{view}.png") for view in ("front", "side")}})
    poses = deformation_poses(set(report["names"].values()))
    blender(tmp_path, {"action": "finish", "source": source, "raw": raw, "names": report["names"],
                       "facing": report["facing"], "rigged_model": str(tmp_path / "rig.fbx"),
                       "blend": str(tmp_path / "rig.blend"), "poses": poses,
                       "pose_images": [str(tmp_path / f"pose_{k}.png") for k in range(len(poses))]})
    return tmp_path / "rig.blend", report


def run_script(script, blend, request, path):
    path.write_text(json.dumps(request))
    process = subprocess.run([BLENDER, str(blend), "--background", "--factory-startup", "--python",
                              str(ROOT / script), "--", str(path)], capture_output=True, text=True)
    report = Path(request["report"])
    assert report.is_file(), process.stdout[-3000:] + process.stderr[-3000:]
    return json.loads(report.read_text())


@pytest.mark.skipif(not Path(BLENDER).is_file(), reason="Blender is not installed")
def test_a_procedural_walk_steps_every_leg_in_turn_with_planted_feet_and_loops(tmp_path):
    """B4 (plan: the procedural gait, M5's first gate and the video route's fallback): each foot planted on the
    ground in stance and swung to its next plant on a lifted arc, the legs following by IK baked to keys; B6's bake
    then finds every leg stepping on the walk's period with no partial step, planted feet that do not slide, and a
    loop of whole periods."""
    blend, report = rigged(tmp_path)
    names = report["names"]
    chains = {f"{limb['end']}.{limb['side']}": [names[bone] for bone in limb["chain"]] for limb in report["limbs"]}
    seconds = 6.0
    built = run_script("blender/procedural_gait.py", blend, {
        "motion": "walk", "legs": chains, "root": "Hips", "tail": sorted(n for n in names.values() if n.startswith("Tail")),
        "period_s": 1.2, "duty": 0.62, "stride_m": 0.45, "lift_m": 0.05, "seconds": seconds, "fps": FPS,
        "save": str(tmp_path / "walk.blend"), "cameras": str(tmp_path / "cameras.json"),
        "report": str(tmp_path / "walk.json")}, tmp_path / "walk_request.json")
    assert built["status"] == "complete", built
    assert built["frames"] == int(seconds * FPS) + 1
    assert built["ik_miss_max_m"] < 0.005, built                # each paw reaches its target
    # the body carries itself at one height, bobbing a little: it does not dip at each long reach
    assert built["hips_rise_m"] <= 0.03 * built["height_m"], built
    # each knee and elbow keeps bending the way it bends at rest: no leg bone turns half round on the way
    assert built["leg_turn_max_deg"] < 90, built
    times = [k / FPS for k in range(built["frames"])]
    baked = run_script("blender/bake_extracted_motion.py", tmp_path / "walk.blend", {
        "legs": {leg: chain[-2:] for leg, chain in chains.items()}, "root_bone": "Hips",
        "fit_bones": sorted(set(names.values())), "fbx": str(tmp_path / "walk.fbx"),
        "blend": str(tmp_path / "walk_baked.blend"), "renders": str(tmp_path / "renders"),
        "cameras": str(tmp_path / "cameras.json"), "times": times, "samples": 1,
        "report": str(tmp_path / "bake.json")}, tmp_path / "bake_request.json")
    assert baked["status"] == "complete", baked
    assert all(len(plants) >= 4 for plants in baked["plants"].values()), baked["plants"]
    assert baked["period_s"] == pytest.approx(1.2, abs=1.5 / FPS)
    last = built["frames"] - 1
    assert all(start == 0 or end == last for _, start, end in baked["partial_steps"]), baked["partial_steps"]
    assert built["period_s"] == pytest.approx(round(1.2 * FPS) / FPS, abs=1e-4)   # whole frames: the loop closes on a frame
    assert baked["window"]["cycles"] >= 3 and baked["window"]["seam_deg"] < 1
    assert baked["stance_slide_mps"] < 0.03                   # planted feet stay where they were set down
    assert baked["speed_mps"] == pytest.approx(0.45 / 1.2, rel=0.1)
    # the legs step in the walk's order: hind left, front left, hind right, front right, a quarter period apart
    first = {leg: min(plants) for leg, plants in baked["plants"].items()}
    order = sorted(first, key=lambda leg: first[leg] % round(1.2 * FPS))
    assert order in (["hind.L", "front.L", "hind.R", "front.R"], ["front.L", "hind.R", "front.R", "hind.L"],
                     ["hind.R", "front.R", "hind.L", "front.L"], ["front.R", "hind.L", "front.L", "hind.R"])
    # the review's own cameras, front and side, hold the whole creature as it stands (no video2rig start frame)
    cameras = json.loads((tmp_path / "cameras.json").read_text())
    assert [view["name"] for view in cameras["views"]] == ["front", "side"]
    assert outside_panels(cameras, creature(extra=0)["vertices"]) == {}
    assert {(item["view"], item["index"]) for item in baked["renders"]} == {
        (view, index) for view in ("front", "side") for index in (0, "seam")}
    assert all(Path(item["path"]).is_file() for item in baked["renders"])


@pytest.mark.skipif(not Path(BLENDER).is_file(), reason="Blender is not installed")
def test_a_procedural_idle_keeps_its_feet_planted_breathes_looks_round_and_closes_its_loop(tmp_path):
    """B4's idle: the feet stay where they stand, the body breathes and shifts its weight, the head looks to each
    side and the tail sways, all closing on one loop; B6's bake takes it whole as a still motion (no steps, no
    travel), its speed and stride 0."""
    blend, report = rigged(tmp_path)
    names = report["names"]
    chains = {f"{limb['end']}.{limb['side']}": [names[bone] for bone in limb["chain"]] for limb in report["limbs"]}
    role = lambda prefix: sorted(n for n in names.values() if n.rstrip("0123456789") == prefix)
    built = run_script("blender/procedural_gait.py", blend, {
        "motion": "idle", "legs": chains, "root": "Hips", "tail": role("Tail"), "neck": role("Neck") + ["Head"], "seconds": 6.0, "breaths": 3, "sway_m": 0.012, "look_deg": 12,
        "tail_deg": 6, "fps": FPS, "save": str(tmp_path / "idle.blend"), "cameras": str(tmp_path / "cameras.json"),
        "report": str(tmp_path / "idle.json")}, tmp_path / "idle_request.json")
    assert built["status"] == "complete", built
    assert built["frames"] == 145 and built["period_s"] == pytest.approx(6.0)
    assert built["ik_miss_max_m"] < 0.005 and built["leg_turn_max_deg"] < 90, built
    assert built["hips_rise_m"] > 0.002, built                 # it breathes
    # with its whole body: the front does not rise and fall over the hips (the owner, 2026-10-31: "the front of the
    # body moving up and down while idle is weird"; the wolf's neck rose 29 mm on 3 mm at the hips)
    assert built["front_rise_m"] <= built["hips_rise_m"] + 0.001, built
    assert built["head_turn_max_deg"] >= 10, built             # it looks round
    baked = run_script("blender/bake_extracted_motion.py", tmp_path / "idle.blend", {
        "legs": {leg: chain[-2:] for leg, chain in chains.items()}, "root_bone": "Hips",
        "fit_bones": sorted(set(names.values())), "fbx": str(tmp_path / "idle.fbx"),
        "blend": str(tmp_path / "idle_baked.blend"), "renders": None, "cameras": None, "still": True,
        "times": [k / FPS for k in range(built["frames"])], "samples": 0, "report": str(tmp_path / "bake.json")},
        tmp_path / "bake_request.json")
    assert baked["status"] == "complete", baked
    assert baked["speed_mps"] == 0 and baked["stride_m"] == 0 and baked["plants"] == {}
    window = baked["window"]
    assert (window["start"], window["end"], window["cycles"]) == (0, 144, 1) and window["seam_deg"] < 0.5
    assert baked["stance_slide_mps"] < 0.01                  # the feet stay where they stand
    assert Path(tmp_path / "idle.fbx").is_file()


@pytest.mark.skipif(not Path(BLENDER).is_file(), reason="Blender is not installed")
def test_a_procedural_hop_lands_in_pairs_leaves_the_floor_keeps_its_head_level_and_loops(tmp_path):
    """A rabbit's slow hop: the hind feet land and push off together, the body goes up and over with every foot off
    the floor, the front paws land one after the other, not as a mirror (the owner, 2026-11-01), and the hind feet come
    through as they lift. B6's bake measures it as it measures a walk."""
    blend, report = rigged(tmp_path)
    names = report["names"]
    chains = {f"{limb['end']}.{limb['side']}": [names[bone] for bone in limb["chain"]] for limb in report["limbs"]}
    role = lambda prefix: sorted(n for n in names.values() if n.rstrip("0123456789") == prefix)
    built = run_script("blender/procedural_gait.py", blend, {
        "motion": "hop", "legs": chains, "root": "Hips", "tail": [], "ears": role("Tail"),   # a chain as the ears
        "neck": role("Neck") + ["Head"], "spine": role("Spine") + ["Chest"], "period_s": 0.75, "duty": 0.36,
        "stride_m": 0.3, "lift_m": 0.05, "rise_m": 0.05, "pitch_deg": 6, "flex_deg": 12, "seconds": 6.0, "fps": FPS,
        "save": str(tmp_path / "hop.blend"), "cameras": str(tmp_path / "cameras.json"),
        "report": str(tmp_path / "hop.json")}, tmp_path / "hop_request.json")
    assert built["status"] == "complete", built
    assert built["ik_miss_max_m"] < 0.005 and built["leg_turn_max_deg"] < 90, built
    assert built["airborne_share"] > 0.05, built               # it leaves the floor, every foot at once
    assert built["hips_rise_m"] >= 0.04, built                 # the body goes up and over
    assert built["head_pitch_max_deg"] < 8, built              # the neck turns back most of the body's tip
    assert built["ear_turn_max_deg"] >= 5, built               # the ears trail behind
    baked = run_script("blender/bake_extracted_motion.py", tmp_path / "hop.blend", {
        "legs": {leg: chain[-2:] for leg, chain in chains.items()}, "root_bone": "Hips",
        "fit_bones": sorted(set(names.values())), "fbx": str(tmp_path / "hop.fbx"),
        "blend": str(tmp_path / "hop_baked.blend"), "renders": None, "cameras": None,
        "times": [k / FPS for k in range(built["frames"])], "samples": 0, "report": str(tmp_path / "bake.json")},
        tmp_path / "bake_request.json")
    assert baked["status"] == "complete", baked
    assert all(len(plants) >= 4 for plants in baked["plants"].values()), baked["plants"]
    assert baked["period_s"] == pytest.approx(0.75, abs=1.5 / FPS)
    assert baked["window"]["cycles"] >= 3 and baked["window"]["seam_deg"] < 1
    assert baked["stance_slide_mps"] < 0.03
    assert baked["speed_mps"] == pytest.approx(0.3 / 0.75, rel=0.1)
    # the hind feet land together; the left front paw leads the right by a frame or more, and the front pair lands
    # well after the hind pair
    period = round(0.75 * FPS)
    apart = lambda a, b: min((a - b) % period, (b - a) % period)
    first = {leg: min(plants) for leg, plants in baked["plants"].items()}
    assert apart(first["hind.L"], first["hind.R"]) <= 1, first
    assert 1 <= (first["front.R"] - first["front.L"]) % period <= 3, first
    assert apart(first["hind.L"], first["front.L"]) >= period / 4, first
