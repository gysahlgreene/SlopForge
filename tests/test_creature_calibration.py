"""B2 orchestration: `creature calibrate` turns a rigged creature into a video2rig project (creature.json, rig export,
start frame, training set) and `creature synth` renders a known motion through its start cameras. video2rig, Blender
and ffmpeg are stubs; the decisions (creature.json, framing, panel checks) are the real code."""
import json
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from slopforge.creature_views import creature_config
from slopforge.failures import StageFailure
from slopforge.pipelines import creature as pipeline
from tests.test_creature_pipeline import project, stubs  # noqa: F401  (B1's stubs fixture)
from tests.test_creature_rig import creature


def cameras(views, widths, ortho=1.8):
    """Orthographic cameras about the fixture (its skin spans x -0.15..0.15, y -0.8..0.85, z 0..0.95)."""
    looks = {"side": ([10, 0.03, 0.5], [0, -1, 0]), "three-quarter": ([7, -7, 0.5], [0.71, 0.71, 0]),
             "front": ([0, -10, 0.5], [1, 0, 0]), "top": ([0, 0, 10], [1, 0, 0])}
    result, x0 = {"frame_px": [1920, 1080], "views": []}, 0
    for view, width in zip(views, widths):
        location, right = looks[view]
        result["views"].append({"name": f"v2r_{view}", "width_px": width, "height_px": 1080, "type": "ortho",
                                "location": location, "right": right, "up": [0, 0, 1], "ortho_height": ortho,
                                "ortho_width": ortho * width / 1080, "x0_px": x0})
        x0 += width
    return result


@pytest.fixture
def tool(monkeypatch):
    """video2rig's steps, Blender's synth_motion and ffmpeg as stubs that write what the real ones write."""
    calls = {"steps": [], "ortho": 1.8, "label_offset": 0.0}
    rig = creature(extra=0)

    def run(config, root, step, project, log, **options):
        calls["steps"].append((step, options))
        project = Path(project)
        if step == "export_rig":
            (project / "rig").mkdir(parents=True)
            np.savez(project / "rig/mesh.npz", verts=rig["vertices"] * 100)          # centimetres, as the Fox's
            (project / "rig/rig.json").write_text(json.dumps({"armature_world": np.diag([.01, .01, .01, 1]).tolist()}))
        elif step == "render_start":
            (project / "start").mkdir(parents=True)
            framing = options["framing"]
            (project / "start/cameras.json").write_text(json.dumps(cameras(framing["views"], framing["widths"],
                                                                            calls["ortho"])))
            Image.new("RGB", (1920, 1080)).save(project / "start/start.png")
        elif step == "prepare":
            (project / "reader").mkdir()
            np.savez(project / "reader/poses.npz", params=np.zeros((options["poses"], 4)))
            np.savez(project / "reader/visible.npz", seen=np.ones(4))
        elif step == "render_poses":
            out, frames = Path(options["out"]), len(np.load(options["motion"])["quats"])
            views = json.loads((project / "start/cameras.json").read_text())["views"]
            for view in views:
                if max(view["width_px"], view["height_px"]) == options["fit"]:
                    (out / view["name"]).mkdir(parents=True)
                    for index in range(frames):
                        Image.new("RGB", (view["width_px"], view["height_px"])).save(out / view["name"] / f"{index:04d}.jpg")
            heads = np.tile((rig["heads"] + [0, calls["label_offset"], 0])[None], (frames, 1, 1))
            np.savez(out / "labels.npz", names=np.array(rig["bones"]), heads=heads, tails=heads,
                     armature_world=np.eye(4))
        return None

    def synth(config, root, blend, request):
        calls["synth"] = request
        np.savez(request["out"], quats=np.zeros((request.get("frames", 96), 3, 4)))
        Path(request["truth"]).write_text(json.dumps({"kind": request["kind"], "seed": request["seed"]}))
        return {"status": "complete"}

    monkeypatch.setattr(pipeline, "_v2r", run)
    monkeypatch.setattr(pipeline, "_synth", synth)
    monkeypatch.setattr(pipeline, "_encode", lambda frames, mp4: Path(mp4).write_bytes(b"mp4"))
    monkeypatch.setattr(pipeline, "_video2rig_identity", lambda config, root: {"name": "video2rig",
                                                                                "output_rights": {"status": "cleared"}})
    return calls


@pytest.fixture
def rigged(tmp_path, stubs):  # noqa: F811
    root, config, manifest = project(tmp_path)
    pipeline.rig_creature(root, config, manifest, "wolf")
    return root, config, manifest


def test_calibration_writes_creature_json_frames_the_views_and_renders_the_training_set(rigged, tool):
    root, config, manifest = rigged
    result = pipeline.calibrate_creature(root, config, manifest, "wolf")
    asset = manifest["assets"]["creature:wolf"]
    project = root / asset["motion"]["project"]
    written = json.loads((project / "creature.json").read_text())
    assert written == creature_config("wolf", asset["rigging"], json.loads(json.dumps(
        __import__("yaml").safe_load((root / "ai/asset_types/creature.yaml").read_text())["joint_limits"])))
    assert written["joints"]["FrontPaw.L"]["range"] == pytest.approx(math.radians(150))
    steps = [step for step, _ in tool["steps"]]
    assert steps == ["export_rig", "render_start", "prepare"]
    framing = dict(tool["steps"])["render_start"]["framing"]
    assert framing["views"] == ["three-quarter", "side"] and sum(framing["widths"]) == 1920
    # the fixture is 1.65 long and 0.3 wide: three-quarter spans .77 x 1.65 + .64 x 0.3, side 1.65
    assert framing["widths"][0] / framing["widths"][1] == pytest.approx((0.77 * 1.65 + 0.64 * 0.3) / 1.65, rel=0.01)
    assert dict(tool["steps"])["prepare"]["poses"] == 3000
    assert result["status"] == asset["motion"]["status"] == "calibrated"
    execution = asset["executions"][-1]
    assert [stage["name"] for stage in execution["stages"]] == ["creature_calibration", "detector_training_set"]
    assert all(stage["status"] == "succeeded" and stage["outputs"] for stage in execution["stages"])
    assert execution["stages"][0]["inputs"][0]["type"] == "project.blend"
    assert execution["identity_inputs"]["creature"] == written


def test_declared_views_widths_and_pose_count_override_the_type(rigged, tool):
    root, config, manifest = rigged
    pipeline.calibrate_creature(root, config, manifest, "wolf", views=["front", "side"], widths=[640, 1280], poses=200)
    framing = dict(tool["steps"])["render_start"]["framing"]
    assert (framing["views"], framing["widths"]) == (["front", "side"], [640, 1280])
    assert dict(tool["steps"])["prepare"]["poses"] == 200


def test_a_start_frame_that_cuts_the_creature_off_is_refused(rigged, tool):
    root, config, manifest = rigged
    tool["ortho"] = 0.4
    with pytest.raises(StageFailure, match="leaves the start frame"):
        pipeline.calibrate_creature(root, config, manifest, "wolf")
    asset = manifest["assets"]["creature:wolf"]
    assert asset["executions"][-1]["stages"][0]["status"] == "failed"
    assert "prepare" not in [step for step, _ in tool["steps"]] and asset["motion"]["status"] == "failed"


def test_calibration_needs_a_rig_and_never_overwrites_a_project(rigged, tool):
    root, config, manifest = rigged
    asset = manifest["assets"]["creature:wolf"]
    rigging = asset.pop("rigging")
    with pytest.raises(ValueError, match="no rig"):
        pipeline.calibrate_creature(root, config, manifest, "wolf")
    asset["rigging"] = rigging
    pipeline.calibrate_creature(root, config, manifest, "wolf")
    with pytest.raises(FileExistsError, match="inspect or move it"):
        pipeline.calibrate_creature(root, config, manifest, "wolf")


def test_a_synthetic_clip_is_rendered_through_the_start_cameras_with_its_truth(rigged, tool):
    root, config, manifest = rigged
    with pytest.raises(ValueError, match="calibrate"):
        pipeline.synthesize_motion(root, config, manifest, "wolf", "random_s0", kind="random", seed=0)
    pipeline.calibrate_creature(root, config, manifest, "wolf")
    result = pipeline.synthesize_motion(root, config, manifest, "wolf", "random_s0", kind="random", seed=0, frames=24)
    asset = manifest["assets"]["creature:wolf"]
    project = root / asset["motion"]["project"]
    assert (project / "clips/random_s0.mp4").read_bytes() == b"mp4"
    assert (project / "exam/random_s0/labels.npz").is_file() and (project / "exam/random_s0/truth.json").is_file()
    assert tool["synth"]["creature"] == json.loads((project / "creature.json").read_text())
    assert (tool["synth"]["kind"], tool["synth"]["seed"], tool["synth"]["frames"]) == ("random", 0, 24)
    assert len(list((project / "exam/random_s0/frames").glob("*.png"))) == 24
    with Image.open(project / "exam/random_s0/frames/0000.png") as frame:
        assert frame.size == (1920, 1080)
    assert asset["motion"]["clips"]["random_s0"]["kind"] == "random" and result["clip"].endswith("random_s0.mp4")
    assert asset["executions"][-1]["stages"][-1]["name"] == "synthetic_motion"
    with pytest.raises(FileExistsError, match="inspect or move it"):
        pipeline.synthesize_motion(root, config, manifest, "wolf", "random_s0", kind="random", seed=0, frames=24)


def test_a_clip_is_not_made_from_a_creature_json_changed_since_calibration(rigged, tool):
    root, config, manifest = rigged
    pipeline.calibrate_creature(root, config, manifest, "wolf")
    path = root / manifest["assets"]["creature:wolf"]["motion"]["project"] / "creature.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "joints": {}}))
    with pytest.raises(ValueError, match="changed since calibration"):
        pipeline.synthesize_motion(root, config, manifest, "wolf", "gait", kind="gait", frames=24)


def test_a_clip_whose_motion_leaves_a_panel_is_refused(rigged, tool):
    root, config, manifest = rigged
    pipeline.calibrate_creature(root, config, manifest, "wolf")
    tool["label_offset"] = 3.0                         # the motion walks out of the frame
    with pytest.raises(StageFailure, match="leaves the frame"):
        pipeline.synthesize_motion(root, config, manifest, "wolf", "gait", kind="gait", frames=24)
    assert manifest["assets"]["creature:wolf"]["executions"][-1]["stages"][-1]["status"] == "failed"


def test_the_cli_calibrates_and_synthesizes(rigged, tool, capsys):
    from slopforge.cli import main
    from slopforge.manifest import load_manifest, save_manifest
    root, _config, manifest = rigged
    (root / "ai/styles/plain").mkdir(parents=True)
    (root / "ai/project.yaml").write_text("project: {name: Test}\nasset_pipeline: {active_style: plain}\n")
    (root / "ai/styles/plain/style.yaml").write_text(
        "name: Plain\nversion: 1\nidentity: {}\nshape_language: {preferred: [], avoid: []}\n"
        "palette: {}\nmaterials: {}\nsurface_language: {preferred: [], avoid: []}\n"
        "lighting: {}\nasset_rules: {}\nmaterial_generation: {rules: []}\n")
    save_manifest(root / "ai/assets/manifest.json", manifest)
    assert main(["--project", str(root), "creature", "calibrate", "wolf", "--views", "front,side",
                 "--widths", "640,1280", "--poses", "500"]) == 0
    assert "calibrated" in capsys.readouterr().out
    framing = dict(tool["steps"])["render_start"]["framing"]
    assert (framing["views"], framing["widths"], dict(tool["steps"])["prepare"]["poses"]) == \
        (["front", "side"], [640, 1280], 500)
    assert main(["--project", str(root), "creature", "synth", "wolf", "gait", "--kind", "gait", "--frames", "24"]) == 0
    assert "gait.mp4" in capsys.readouterr().out
    motion = load_manifest(root / "ai/assets/manifest.json")["assets"]["creature:wolf"]["motion"]
    assert motion["status"] == "calibrated" and motion["clips"]["gait"]["frames"] == 24


@pytest.mark.skipif(__import__("os").environ.get("SLOPFORGE_RUN_VIDEO2RIG") != "1", reason="opt-in external runtime")
def test_external_creature_calibration():
    """The live gate: calibrate a rigged creature of a configured project with the real video2rig and Blender, and
    render one known motion through its start cameras."""
    import os
    from slopforge.config import load_project
    from slopforge.manifest import load_manifest
    project, name = os.environ.get("SLOPFORGE_PROJECT_ROOT"), os.environ.get("SLOPFORGE_CREATURE")
    if not (project and name):
        pytest.skip("blocked: set SLOPFORGE_PROJECT_ROOT and SLOPFORGE_CREATURE (a creature with a rig)")
    config = load_project(project)
    manifest = load_manifest(Path(project) / config["asset_pipeline"]["manifest"])
    result = pipeline.calibrate_creature(project, config, manifest, name)
    assert result["status"] == "calibrated"
    clip = pipeline.synthesize_motion(project, config, manifest, name, "random_s0", kind="random", seed=0)
    assert (Path(project) / clip["clip"]).stat().st_size and clip["frames"] == 96
