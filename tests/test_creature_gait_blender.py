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
