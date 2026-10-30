"""B3b: a trained reader examined on a known motion (exam v1) as a recorded stage. video2rig's check and run and the
Blender posing are stubbed; the measures and the verdict are slopforge/creature_exam.py's own."""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from slopforge.pipelines import creature as pipeline
from tests.test_creature_calibration import rigged, tool  # noqa: F401  (B1/B2 stubs)
from tests.test_creature_pipeline import stubs  # noqa: F401
from tests.test_creature_reader_pipeline import calibrated  # noqa: F401


def posed_walk(ends, frames=24, turn=0.0, fit_fps=24.0):
    """The hips and each leg's last bone hanging from them, the legs swinging in pairs; `turn` degrees on the first
    leg's fit."""
    names, parents = ["Hips", *ends], ["", *["Hips"] * len(ends)]
    heads, tails = np.zeros((frames, len(names), 3)), np.zeros((frames, len(names), 3))
    for i in range(frames):
        heads[i, 0], tails[i, 0] = (0, 0, 0.6), (0, -0.3, 0.6)
        for j, end in enumerate(ends, start=1):
            side = 0.15 if end.endswith(".L") else -0.15
            swing = 0.3 * math.sin(2 * math.pi * i / frames + (math.pi if j % 2 else 0))
            heads[i, j], tails[i, j] = (side, -0.3 * (j > 2), 0.6), (side, swing - 0.3 * (j > 2), 0.0)
    fit_tails = tails.copy()
    if turn:
        a = math.radians(turn)
        rotate = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
        fit_tails[:, 1] = heads[:, 1] + (tails[:, 1] - heads[:, 1]) @ rotate.T
    return {"names": np.array(names), "parents": np.array(parents), "root": "Hips", "fps": 24.0, "height": 1.0,
            "up": np.array([0, 0, 1.0]), "forward": np.array([0, -1.0, 0]), "true_heads": heads, "true_tails": tails,
            "fit_heads": heads, "fit_tails": fit_tails, "times": np.arange(frames) / fit_fps, "moved": np.array(names)}


@pytest.fixture
def trained(calibrated, monkeypatch):  # noqa: F811
    """The wolf's reader trained; video2rig's check and run and the Blender posing stubbed on a known walk."""
    root, config, manifest, calls, project = calibrated
    pipeline.train_creature(root, config, manifest, "wolf")
    asset = manifest["assets"]["creature:wolf"]
    ends = [chain[-1] for leg, chain in sorted(pipeline._legs(root, asset).items())]
    calls.update(turn=0.0, check={"verdict": "OK", "body": 0.004, "limbs": 0.011}, exam_steps=[], fit_fps=24.0,
                 label_gap=0.0)
    inner = pipeline._v2r

    def v2r(config_, root_, step, project_, log, **options):
        if step == "fit":       # the reading fitted again, as extraction fits a clip
            calls["exam_steps"].append(("fit", options["clip"]))
            calls["fit_options"] = options
            motion = Path(project_) / "out" / f"{options['clip']}{options['tag']}.npz"
            np.savez(motion, times=np.arange(24) / 24.0)
            return {"report": [{"frame": 0, "median_miss_px": 2.0}], "motion": motion}
        if step not in ("check", "run"):
            return inner(config_, root_, step, project_, log, **options)
        calls["exam_steps"].append((step, options["clip"]))
        work = Path(project_) / "work" / options["clip"]
        work.mkdir(parents=True, exist_ok=True)
        if step == "check":
            if calls.get("check_crashes"):
                raise RuntimeError("video2rig check exited with code 1")
            (work / "check.json").write_text(json.dumps(calls["check"]))
            return dict(calls["check"])
        (Path(project_) / "out").mkdir(exist_ok=True)
        np.savez(Path(project_) / "out" / f"{options['clip']}.npz", times=np.arange(24) / 24.0)
        np.savez(work / "reader.npz", conf=np.ones((24, 2, 1 + len(ends))), views=np.array(["v2r_front", "v2r_side"]),
                 keypoints=json.dumps([["hips", "Hips", 0.0]] + [[f"{end}.tip", end, 1.0] for end in ends]))
        (work / "report.json").write_text(json.dumps({"frames": 24}))
        return {"report": {"frames": 24}, "motion": Path(project_) / "out" / f"{options['clip']}.npz"}

    def exam_pose(config_, root_, blend, request):
        calls["pose_request"] = request
        np.savez(request["out"], **posed_walk(ends, turn=calls["turn"], fit_fps=calls["fit_fps"]))
        report = {"status": "complete", "label_gap": calls["label_gap"]}
        Path(request["report"]).write_text(json.dumps(report))
        return report
    monkeypatch.setattr(pipeline, "_v2r", v2r)
    monkeypatch.setattr(pipeline, "_exam_pose", exam_pose)
    return root, config, manifest, calls, project


def test_a_trained_reader_passes_exam_v1_on_a_known_walk_as_a_recorded_stage(trained):
    root, config, manifest, calls, project = trained
    result = pipeline.exam_creature(root, config, manifest, "wolf")
    assert result["status"] == "passed" and result["failures"] == []
    assert calls["synth"]["kind"] == "gait" and calls["exam_steps"] == [("check", "exam_gait_s0"),
                                                                        ("run", "exam_gait_s0"),
                                                                        ("fit", "exam_gait_s0")]
    assert calls["pose_request"]["facing"] == "-Y"
    asset = manifest["assets"]["creature:wolf"]
    stage = asset["executions"][-1]["stages"][-1]
    assert (stage["name"], stage["status"]) == ("reader_exam", "succeeded")
    # its parents: the reader the training made, and the known motion the synth stage made
    assert {(ref["stage"], ref["type"]) for ref in stage["inputs"]} == {
        ("detector_training", "model.joint_reader"), ("synthetic_motion", "data.known_motion"),
        ("synthetic_motion", "data.motion_truth"), ("synthetic_motion", "data.motion_labels"),
        ("synthetic_motion", "video.synthetic_clip")}
    assert {ref["type"] for ref in stage["outputs"]} >= {"report.motion_exam", "data.motion_fit"}
    exam = asset["motion"]["reader"]["exams"]["exam_gait_s0"]
    assert exam["status"] == "passed"
    assert exam["measured"]["views_body_pct"] == pytest.approx(0.4)
    report = json.loads((root / exam["report"]).read_text())
    assert report["verdict"]["status"] == "passed" and report["exam"]["frames_compared"] == 24


def test_a_reader_that_reads_a_leg_wrong_fails_the_exam_by_name_and_is_recorded(trained):
    root, config, manifest, calls, project = trained
    calls["turn"] = 40.0
    result = pipeline.exam_creature(root, config, manifest, "wolf")
    assert result["status"] == "failed"
    assert "worst_body_median_deg" in result["failures"] and "worst_body_p95_deg" in result["failures"]
    exam = manifest["assets"]["creature:wolf"]["motion"]["reader"]["exams"]["exam_gait_s0"]
    assert exam["status"] == "failed" and exam["failures"] == result["failures"]
    assert manifest["assets"]["creature:wolf"]["executions"][-1]["status"] == "succeeded"   # an answer, not an error


def test_the_exam_needs_a_trained_reader_as_it_was_trained(calibrated):  # noqa: F811
    root, config, manifest, calls, project = calibrated
    with pytest.raises(ValueError, match="creature train wolf"):
        pipeline.exam_creature(root, config, manifest, "wolf")
    pipeline.train_creature(root, config, manifest, "wolf")
    (project / "reader/reader.pt").write_bytes(b"another reader")
    with pytest.raises(ValueError, match="reader"):
        pipeline.exam_creature(root, config, manifest, "wolf")


def test_a_second_exam_reuses_the_known_motion(trained):
    root, config, manifest, calls, project = trained
    pipeline.exam_creature(root, config, manifest, "wolf")
    calls.pop("synth")
    assert pipeline.exam_creature(root, config, manifest, "wolf")["status"] == "passed"
    assert "synth" not in calls                                    # the truth is the same; it is not rendered again


def test_the_cli_examines_and_exits_nonzero_on_a_failed_exam(trained, capsys):
    from slopforge.cli import main
    from slopforge.manifest import save_manifest
    root, config, manifest, calls, project = trained
    (root / "ai/styles/plain").mkdir(parents=True)
    (root / "ai/project.yaml").write_text("project: {name: Test}\nasset_pipeline: {active_style: plain}\n")
    (root / "ai/styles/plain/style.yaml").write_text(
        "name: Plain\nversion: 1\nidentity: {}\nshape_language: {preferred: [], avoid: []}\n"
        "palette: {}\nmaterials: {}\nsurface_language: {preferred: [], avoid: []}\n"
        "lighting: {}\nasset_rules: {}\nmaterial_generation: {rules: []}\n")
    save_manifest(root / "ai/assets/manifest.json", manifest)
    calls["turn"] = 40.0
    assert main(["--project", str(root), "creature", "exam", "wolf"]) == 1
    out = capsys.readouterr().out
    assert "exam v1 failed" in out and "worst_body_p95_deg" in out


def test_the_exam_reads_only_the_reader_its_training_recorded(trained):
    """Review 2026-10-30: reader A trained, moved aside, B trained, A put back: the exam must not read A and record
    B as examined."""
    root, config, manifest, calls, project = trained
    first = (project / "reader/reader.pt").read_bytes()
    for name in ("reader.pt", "reader-train.json"):
        (project / "reader" / name).rename(project / "reader" / f"{name}.first")
    pipeline.train_creature(root, config, manifest, "wolf")
    (project / "reader/reader.pt").write_bytes(first)
    with pytest.raises(ValueError, match="not the reader creature train last made"):
        pipeline.exam_creature(root, config, manifest, "wolf")


@pytest.mark.parametrize("change", [{"fit_fps": 30.0}, {"label_gap": float("nan")}, {"label_gap": 0.01}])
def test_an_exam_counts_only_when_every_truth_frame_is_compared_with_the_truth_it_rendered(trained, change):
    from slopforge.failures import StageFailure
    root, config, manifest, calls, project = trained
    calls.update(change)     # read at 30 fps, 24 pairs reach only 20 truth frames; a truth unlike its render
    with pytest.raises(StageFailure, match="cannot count"):
        pipeline.exam_creature(root, config, manifest, "wolf")
    assert manifest["assets"]["creature:wolf"]["motion"]["reader"]["exams"]["exam_gait_s0"]["status"] == "error"


def test_a_view_check_with_no_reading_fails_its_measures(trained):
    root, config, manifest, calls, project = trained
    calls["check"] = {"verdict": "FAIL", "body": None, "limbs": None}
    result = pipeline.exam_creature(root, config, manifest, "wolf")
    assert result["status"] == "failed" and {"views_body_pct", "views_limbs_pct"} <= set(result["failures"])


def test_a_crashed_exam_is_an_error_not_a_verdict(trained):
    root, config, manifest, calls, project = trained
    calls["check_crashes"] = True
    with pytest.raises(RuntimeError):
        pipeline.exam_creature(root, config, manifest, "wolf")
    assert manifest["assets"]["creature:wolf"]["motion"]["reader"]["exams"]["exam_gait_s0"]["status"] == "error"


def test_each_readers_exam_keeps_its_own_fit_and_check(trained):
    root, config, manifest, calls, project = trained
    pipeline.exam_creature(root, config, manifest, "wolf")
    tag = manifest["assets"]["creature:wolf"]["motion"]["reader"]["sha256"][:12]
    stage = manifest["assets"]["creature:wolf"]["executions"][-1]["stages"][-1]
    kept = {ref["type"]: ref["path"] for ref in stage["outputs"]}
    assert kept["data.motion_fit"].endswith(f"exam/exam_gait_s0/fit-{tag}.npz")
    assert kept["report.view_check"].endswith(f"exam/exam_gait_s0/check-{tag}.json")


@pytest.mark.parametrize("change, words", [
    (lambda clip, stage: clip.update(frames=48), "frames"),
    (lambda clip, stage: stage["settings"].update(tool_sha256="an older synth_motion.py"), "synth_motion"),
])
def test_a_reused_exam_clip_must_be_the_known_motion_asked_for(trained, change, words):
    """Review 2026-10-30: an exam clip is reused by name; one made with other frames, or by an older gait (this
    package changed the gait), is not the same truth."""
    root, config, manifest, calls, project = trained
    pipeline.exam_creature(root, config, manifest, "wolf")
    asset = manifest["assets"]["creature:wolf"]
    synth = next(stage for execution in asset["executions"] for stage in execution["stages"]
                 if stage["name"] == "synthetic_motion")
    change(asset["motion"]["clips"]["exam_gait_s0"], synth)
    with pytest.raises(ValueError, match=words):
        pipeline.exam_creature(root, config, manifest, "wolf")


def test_the_posing_never_reads_an_earlier_report(tmp_path, monkeypatch):
    report = tmp_path / "pose.json"
    report.write_text('{"status": "complete", "label_gap": 0.0}')         # a crashed Blender leaves the old one
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "blender_executable", lambda config, root: "blender")   # CI has no Blender
    with pytest.raises(RuntimeError, match="wrote no report"):
        pipeline._exam_pose({}, tmp_path, tmp_path / "rig.blend",
                            {"report": str(report), "out": str(tmp_path / "posed.npz")})


def test_a_legs_tip_is_its_last_fitted_bone():
    legs = {"front.L": ["FrontPaw.L", "FrontToes.L"], "hind.L": ["HindToes.L", "HindToesEnd.L"]}
    assert pipeline._limb_ends(legs, ["FrontPaw.L", "FrontToes.L", "HindToes.L"]) == ["FrontToes.L", "HindToes.L"]


def test_the_exam_fits_the_reading_as_extraction_fits_a_walk(trained):
    """The exam measures what is delivered: the reading fitted again with the clip's rate (B2 renders known motions at
    24 fps, video2rig's own tuning) and the walk's fit ranges."""
    import math
    from slopforge.backends import video2rig
    root, config, manifest, calls, project = trained
    pipeline.exam_creature(root, config, manifest, "wolf")
    options = calls["fit_options"]
    assert options["tag"] == "-slopforge" and options["settings"] == video2rig.fit_settings(24)
    paws = {bone: joint["range"] for bone, joint in options["creature"]["joints"].items() if "FrontPaw" in bone}
    assert paws and all(value == math.radians(90) for value in paws.values())
    assert Path(calls["pose_request"]["fit"]).name.startswith("fit-")         # the exam's copy of the refit
