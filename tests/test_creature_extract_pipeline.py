"""B6 orchestration: `creature extract` takes one clip that passed intake through video2rig's run (the reader road)
and import_motion, bakes it in place and cut to its loop, and registers the FBX as a candidate animation with its
stride, period and review sheet; `animation approve` is the human gate. video2rig and the Blender bake are stubs; the
checks, records and decisions are the real code."""
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from slopforge.backends import video2rig
from slopforge.failures import StageFailure
from slopforge.pipelines import creature as pipeline
from slopforge.provenance import file_sha256
from tests.test_creature_calibration import rigged, tool  # noqa: F401  (B1/B2 stubs)
from tests.test_creature_pipeline import stubs  # noqa: F401
from tests.test_creature_video_pipeline import WALK, video  # noqa: F401

BAKED = {"status": "complete", "fps": 24.0, "keys": len(WALK), "height_m": 0.78,
         "plants": {"front.L": [5, 25], "front.R": [15, 35], "hind.L": [10, 30], "hind.R": [20, 40]},
         "cycles": 2, "weak_legs": ["hind.L"], "period_s": 1.25, "speed_mps": 0.4, "velocity": [0.0, -0.4], "stride_m": 0.5,
         "window": {"start": 2, "end": 22, "cycles": 1, "seam_deg": 3.1, "start_frame": 4, "end_frame": 34,
                    "start_s": 0.125, "end_s": 1.375, "seam_root_m": 0.004},
         "residual_travel_m": 0.03, "stance_slide_mps": 0.05}


@pytest.fixture
def extracted(video, monkeypatch):  # noqa: F811
    """One accepted walk (walk_s11) and stubs: video2rig's run writes `calls["fit"]`'s motion, import_motion a
    .blend, and the bake `calls["bake"]`'s report with its FBX, .blend and renders."""
    root, config, manifest, calls, project = video
    pipeline.video_creature(root, config, manifest, "wolf", "walk", count=1, seed=11)
    # the reader passed exam v1 (B3), as extraction needs
    manifest["assets"]["creature:wolf"]["motion"]["reader"] = {
        "status": "trained", "sha256": file_sha256(project / "reader/reader.pt"),
        "exams": {"exam_gait_s0": {"status": "passed", "fit": {"fps": 16.0, "settings": video2rig.fit_settings(16),
                                                                "joint_limits": {"FrontPaw": 90, "FrontToes": 60}}}}}
    creature = json.loads((project / "creature.json").read_text())
    timing = json.loads((project / "work/walk_s11/timing.json").read_text())["times"]
    calls.update(fit={"bones": list(creature["fit_bones"]), "times": timing}, bake=dict(BAKED), steps=[])
    inner = pipeline._v2r

    def v2r(config_, root_, step, project_, log, **options):
        if step == "run":
            calls["steps"].append("run")
            fit, n = calls["fit"], len(calls["fit"]["times"])
            out = Path(project_) / "out" / f"{options['clip']}.npz"
            out.parent.mkdir(exist_ok=True)
            quaternions = np.tile([1.0, 0, 0, 0], (n - int(fit.get("short", 0)), len(fit["bones"]), 1))
            if fit.get("nan"):
                quaternions[3, 0, 0] = np.nan
            np.savez(out, bones=np.array(fit["bones"]), root=np.array(creature["root_bone"]), quaternions=quaternions,
                     root_location=np.zeros((n, 3)), times=np.array(fit["times"]), armature_world=np.eye(4))
            report = {"frames": n, "warnings": ["v2r_side view: outline weak in frames 4-20"], "frames_under_floor": 2}
            (Path(project_) / "work" / options["clip"] / "report.json").write_text(json.dumps(report))
            return {"report": report, "motion": out}
        if step == "fit":   # the reading fitted again: settings for the clip's rate, the walk's ranges
            calls["steps"].append("fit")
            calls["fit_options"] = options
            motion = Path(project_) / "out" / f"{options['clip']}{options['tag']}.npz"
            with np.load(Path(project_) / "out" / f"{options['clip']}.npz") as run_fit:
                arrays = dict(run_fit)
            if len(arrays["quaternions"]) > 5:   # the refit snaps its second bone 78 degrees about X into frame 5
                arrays["quaternions"][5, 1] = [math.cos(math.radians(39)), math.sin(math.radians(39)), 0, 0]
            np.savez(motion, **arrays)
            # video2rig writes no miss for a frame in which no keypoint is seen
            return {"report": [{"frame": 0, "median_miss_px": 3.2}, {"frame": 1, "median_miss_px": 3.6},
                               {"frame": 2, "median_miss_px": None}], "motion": motion}
        if step == "import_motion":
            calls["steps"].append("import_motion")
            calls["import_options"] = options
            Path(options["save"]).write_bytes(b"blend with the imported action")
            return None
        return inner(config_, root_, step, project_, log, **options)

    def bake(config_, root_, source, request):
        calls["bake_request"] = request
        report = calls["bake"]
        if report["status"] == "complete":
            Path(request["fbx"]).write_bytes(b"fbx")
            Path(request["blend"]).write_bytes(b"baked blend")
            Path(request["renders"]).mkdir(parents=True)
            report["renders"] = []
            for view in ("v2r_front", "v2r_side"):
                for index in range(request["samples"]):
                    path = Path(request["renders"]) / f"{view}_{index:02d}.png"
                    Image.new("RGB", (96, 108), (90, 80, 70)).save(path)
                    report["renders"].append({"view": view, "index": index, "clip_frame": 2 + index, "path": str(path)})
                path = Path(request["renders"]) / f"{view}_seam.png"
                Image.new("RGB", (96, 108), (70, 80, 90)).save(path)
                report["renders"].append({"view": view, "index": "seam", "clip_frame": 22, "path": str(path)})
        Path(request["report"]).write_text(json.dumps(report))
        return report

    monkeypatch.setattr(pipeline, "_v2r", v2r)
    monkeypatch.setattr(pipeline, "_bake", bake)
    # the terms read for video2rig, as its real identity records them: animation approve's rights gate is real code
    monkeypatch.setattr(pipeline, "_video2rig_identity", lambda config_, root_, reader=None: {
        "name": "video2rig", "output_rights": video2rig.OUTPUT_RIGHTS,
        "weights_sha256": __import__("hashlib").sha256(Path(reader).read_bytes()).hexdigest() if reader else None})
    return root, config, manifest, calls, project


def test_an_accepted_clip_is_extracted_baked_in_place_and_registered_as_a_candidate_animation(extracted):
    root, config, manifest, calls, project = extracted
    result = pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    asset = manifest["assets"]["creature:wolf"]
    assert calls["steps"] == ["run", "fit", "import_motion"] and result["status"] == "review_required"
    request = calls["bake_request"]
    assert request["root_bone"] == "Hips" and set(request["legs"]) == {"front.L", "front.R", "hind.L", "hind.R"}
    assert all(len(bones) == 2 for bones in request["legs"].values())
    animation = asset["artifacts"]["animation.walk_s11"]
    assert animation["type"] == "animation.fbx" and animation["status"] == "candidate"
    assert animation["approval"]["status"] == "pending"
    assert {"loop": True, "root_motion": False, "stride_m": 0.5, "period_s": 1.25, "speed_mps": 0.4,
            "loop_periods": 1, "min_plants": 2}.items() <= animation["provenance"].items()
    assert "cycles" not in animation["provenance"]                   # B7 reads loop_periods; min_plants is the gait's
    reader = __import__("hashlib").sha256(b"trained reader").hexdigest()
    assert animation["provenance"]["provider"]["weights_sha256"] == reader
    assert animation["derived_from"] == [{"asset_id": asset["id"], "output_id": "rig"}]
    sources = {item["source"] for item in animation["provenance"]["output_rights"]}
    assert {"video2rig", "blender"} <= sources and any(source.endswith(".safetensors") for source in sources)
    extraction = asset["motion"]["clips"]["walk_s11"]["extraction"]
    assert extraction["status"] == "review_required" and extraction["stride_m"] == 0.5
    assert extraction["warnings"] == [f"{calls['fit']['bones'][1]} turns 78 degrees in one frame at frame 5",
                                      "hind.L planted once: its steps barely lift; watch it in the review sheet"]
    sheet = root / extraction["review_sheet"]
    assert sheet.is_file() and Image.open(sheet).size[0] > 4 * 200     # clip front | clip side | baked front | side
    assert Image.open(sheet).size[1] == (8 + 1) * 334                  # one cycle's 8 phases, then the loop's seam
    assert request["times"] == pytest.approx([k / 16 for k in range(len(WALK))])
    stages = {stage["name"]: stage for stage in asset["executions"][-1]["stages"]}
    assert stages["motion_extraction"]["status"] == stages["motion_bake"]["status"] == "succeeded"
    assert {output["type"] for output in stages["motion_bake"]["outputs"]} >= {
        "animation.fbx", "report.motion_bake", "image.motion_review"}
    clip_input = stages["motion_extraction"]["inputs"][0]
    assert clip_input["type"] == "video.generated_clip" and clip_input["stage"] == "video_generation"
    assert stages["motion_extraction"]["provenance"]["provider"]["weights_sha256"] == reader
    assert {item["type"] for item in stages["motion_bake"]["inputs"]} == {
        "data.motion_extraction", "project.blend", "video.generated_clip", "data.cameras"}


@pytest.mark.parametrize("change, words", [
    (lambda fit: fit.update(times=[k / 24 for k in range(len(fit["times"]))]), "frame times"),
    (lambda fit: fit.update(bones=fit["bones"][:-1]), "bones"),
    (lambda fit: fit.update(nan=True), "not finite"),
    (lambda fit: fit.update(short=1), "one rotation per frame"),
])
def test_a_fit_that_does_not_match_the_clip_or_the_creature_stops_before_the_bake(extracted, change, words):
    root, config, manifest, calls, project = extracted
    change(calls["fit"])
    with pytest.raises(StageFailure, match=words):
        pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    assert calls["steps"] == ["run", "fit"]                     # the refit is what is checked
    stage = manifest["assets"]["creature:wolf"]["executions"][-1]["stages"][-1]
    assert stage["name"] == "motion_extraction" and stage["status"] == "failed"


def test_a_clip_with_no_walk_cycle_is_refused_as_a_retryable_clip_failure_and_kept(extracted):
    root, config, manifest, calls, project = extracted
    calls["bake"] = {"status": "error", "errors": ["no full walk cycle: hind.L never planted"],
                     "failure_code": "motion_no_cycle", "measured": {"motion_min_plants": 0}}
    with pytest.raises(StageFailure) as caught:
        pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    assert caught.value.category == "candidate_quality" and "hind.L" in str(caught.value)
    asset = manifest["assets"]["creature:wolf"]
    stage = asset["executions"][-1]["stages"][-1]
    assert stage["name"] == "motion_bake" and stage["failure"]["retryable"] is True
    assert asset["motion"]["clips"]["walk_s11"]["extraction"]["status"] == "rejected"
    assert (project / "out/walk_s11.npz").is_file()                      # the fit is kept with the refusal


def test_only_a_clip_that_passed_intake_and_is_unchanged_is_extracted(extracted):
    root, config, manifest, calls, project = extracted
    with pytest.raises(ValueError, match="no accepted clip"):
        pipeline.extract_creature(root, config, manifest, "wolf", "walk_s12")
    (project / "clips/walk_s11.mp4").write_bytes(b"edited")
    with pytest.raises(ValueError, match="changed since intake"):
        pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    assert calls["steps"] == []


def test_an_extracted_clip_is_not_extracted_again_over_itself(extracted):
    root, config, manifest, calls, project = extracted
    pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    with pytest.raises(FileExistsError):
        pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")


def test_animation_approve_needs_confirmation_an_approved_rig_and_unchanged_outputs(extracted):
    root, config, manifest, calls, project = extracted
    pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    with pytest.raises(ValueError, match="--confirm"):
        pipeline.approve_motion(root, manifest, "wolf", "walk_s11")
    with pytest.raises(ValueError, match="rig is not approved"):
        pipeline.approve_motion(root, manifest, "wolf", "walk_s11", confirmed=True)
    pipeline.approve_rig(root, manifest, "wolf", confirmed=True)
    fbx = root / manifest["assets"]["creature:wolf"]["artifacts"]["animation.walk_s11"]["path"]
    fbx.write_bytes(b"edited fbx")
    with pytest.raises(ValueError, match="changed since"):
        pipeline.approve_motion(root, manifest, "wolf", "walk_s11", confirmed=True)
    fbx.write_bytes(b"fbx")
    result = pipeline.approve_motion(root, manifest, "wolf", "walk_s11", confirmed=True)
    asset = manifest["assets"]["creature:wolf"]
    assert result["status"] == "approved" and asset["artifacts"]["animation.walk_s11"]["approval"]["status"] == "approved"
    assert asset["motion"]["clips"]["walk_s11"]["extraction"]["status"] == "approved"


def test_the_cli_extracts_reports_the_gait_and_approves(extracted, capsys):
    from slopforge.cli import main
    from slopforge.manifest import load_manifest, save_manifest
    root, config, manifest, calls, project = extracted
    (root / "ai/styles/plain").mkdir(parents=True)
    (root / "ai/project.yaml").write_text("project: {name: Test}\nasset_pipeline: {active_style: plain}\n")
    (root / "ai/styles/plain/style.yaml").write_text(
        "name: Plain\nversion: 1\nidentity: {}\nshape_language: {preferred: [], avoid: []}\n"
        "palette: {}\nmaterials: {}\nsurface_language: {preferred: [], avoid: []}\n"
        "lighting: {}\nasset_rules: {}\nmaterial_generation: {rules: []}\n")
    pipeline.approve_rig(root, manifest, "wolf", confirmed=True)
    save_manifest(root / "ai/assets/manifest.json", manifest)
    assert main(["--project", str(root), "creature", "extract", "wolf", "walk_s11"]) == 0
    out = capsys.readouterr().out
    assert "stride 0.50 m every 1.25 s (0.40 m/s); a loop of 1 period, seam 3.1 deg" in out and "review.png" in out
    assert "slopforge animation approve wolf walk_s11 --confirm" in out
    assert main(["--project", str(root), "animation", "approve", "wolf", "walk_s11", "--confirm"]) == 0
    assert "walk_s11: approved" in capsys.readouterr().out
    saved = load_manifest(root / "ai/assets/manifest.json")["assets"]["creature:wolf"]
    assert saved["artifacts"]["animation.walk_s11"]["approval"]["status"] == "approved"


def test_a_malformed_gait_refusal_is_a_failed_extraction_not_a_rejected_clip(extracted):
    root, config, manifest, calls, project = extracted
    calls["bake"] = {"status": "error", "errors": ["no full walk cycle: hind.L never planted"],
                     "failure_code": "motion_no_cycle"}                 # no measure: B0 cannot call it a clip failure
    with pytest.raises(StageFailure):
        pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    asset = manifest["assets"]["creature:wolf"]
    assert asset["executions"][-1]["stages"][-1]["failure"]["retryable"] is False
    assert asset["motion"]["clips"]["walk_s11"]["extraction"]["status"] == "failed"


def test_the_start_cameras_must_be_the_calibrated_ones(extracted):
    root, config, manifest, calls, project = extracted
    cameras = json.loads((project / "start/cameras.json").read_text())
    cameras["views"][0]["ortho_width"] *= 1.1
    (project / "start/cameras.json").write_text(json.dumps(cameras))
    with pytest.raises(ValueError, match="cameras.json.*changed since calibration"):
        pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    assert calls["steps"] == []


def test_a_clip_is_extracted_only_on_the_rig_it_was_calibrated_on(extracted):
    root, config, manifest, calls, project = extracted
    calibration = next(stage for item in manifest["assets"]["creature:wolf"]["executions"] for stage in item["stages"]
                       if stage["name"] == "creature_calibration")
    calibration["inputs"][0]["sha256"] = "0" * 64                     # calibrated on another rig .blend
    with pytest.raises(ValueError, match="calibrated on another rig"):
        pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")


def test_a_clip_baked_on_one_rig_is_not_approved_on_another(extracted):
    root, config, manifest, calls, project = extracted
    pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    asset = manifest["assets"]["creature:wolf"]
    blend = root / asset["artifacts"]["rig_blend"]["path"]
    blend.write_bytes(blend.read_bytes() + b" re-rigged")             # a new rig, recorded as B1 records one
    for item in asset["executions"]:
        for stage in item["stages"]:
            for output in stage.get("outputs") or []:
                if stage["name"] == "rig_postprocess" and output["path"] == asset["artifacts"]["rig_blend"]["path"]:
                    output["sha256"] = __import__("hashlib").sha256(blend.read_bytes()).hexdigest()
    pipeline.approve_rig(root, manifest, "wolf", confirmed=True)
    with pytest.raises(ValueError, match="baked on another rig"):
        pipeline.approve_motion(root, manifest, "wolf", "walk_s11", confirmed=True)


@pytest.mark.parametrize("name", ["bake.json", "review.png"])
def test_animation_approve_refuses_a_changed_bake_report_or_sheet(extracted, name):
    root, config, manifest, calls, project = extracted
    pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    pipeline.approve_rig(root, manifest, "wolf", confirmed=True)
    path = project.parent / "walk_s11" / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed since the bake"):
        pipeline.approve_motion(root, manifest, "wolf", "walk_s11", confirmed=True)


@pytest.mark.parametrize("change", [
    lambda reader, project: reader["exams"]["exam_gait_s0"].update(status="failed"),
    lambda reader, project: reader.pop("exams"),
    # a pass on another fit is not a pass on this clip's: the 24 fps settings, other ranges, no record of its fit
    lambda reader, project: reader["exams"]["exam_gait_s0"]["fit"].update(settings=video2rig.fit_settings(24)),
    lambda reader, project: reader["exams"]["exam_gait_s0"]["fit"].update(joint_limits={"FrontPaw": 150}),
    lambda reader, project: reader["exams"]["exam_gait_s0"].pop("fit"),
    # review 2026-10-30: a pass on another seed does not outweigh a failed exam (no seed shopping)
    lambda reader, project: reader["exams"].update(exam_gait_s0={"status": "failed"}, exam_gait_s1={"status": "passed"}),
    lambda reader, project: (project / "reader/reader.pt").write_bytes(b"a reader the exam never saw"),
])
def test_a_reader_that_has_not_passed_the_exam_reads_no_clip(extracted, change):
    root, config, manifest, calls, project = extracted
    change(manifest["assets"]["creature:wolf"]["motion"]["reader"], project)
    with pytest.raises(ValueError, match="has not passed the motion exam.*creature exam wolf"):
        pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    assert calls["steps"] == []


def test_the_clip_is_fitted_again_with_settings_for_its_rate_and_the_walks_ranges(extracted):
    """2026-10-30 (the owner's fit D): video2rig's reader fit counts its thresholds in frames tuned at 24 fps, and its
    settings are reached only by refitting the reading (docs/CREATURES.md); the walk is fitted within its own paw
    ranges while the reader keeps the ranges it trained on."""
    from slopforge.backends import video2rig
    root, config, manifest, calls, project = extracted
    pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    assert calls["steps"][:3] == ["run", "fit", "import_motion"]
    options = calls["fit_options"]
    asset = manifest["assets"]["creature:wolf"]
    entry = asset["motion"]["clips"]["walk_s11"]
    assert options["tag"] == "-slopforge" and options["settings"] == video2rig.fit_settings(entry["fps"])
    trained = asset["motion"]["creature"]["joints"]
    for bone, joint in options["creature"]["joints"].items():
        role = bone.split(".")[0]
        expected = {"FrontPaw": math.radians(90), "FrontToes": math.radians(60)}.get(role, trained[bone]["range"])
        assert joint["range"] == pytest.approx(expected), bone
    assert json.loads((project / "creature.json").read_text())["joints"] == trained   # the reader's own, untouched
    # the refit is what is checked, imported and recorded
    assert Path(calls["import_options"]["motion"]).name == "walk_s11-slopforge.npz"
    extraction = entry["extraction"]
    assert extraction["fit"].endswith("out/walk_s11-slopforge.npz") and extraction["fit_median_miss_px"] == 3.4
    # its biggest one-frame turn is measured on the refit; run's report describes a fit nothing delivers
    bone = calls["fit"]["bones"][1]
    assert extraction["biggest_turn"] == {"deg": 78.0, "bone": bone, "frame": 5}
    assert extraction["warnings"][0] == f"{bone} turns 78 degrees in one frame at frame 5"
    assert "fit_report" not in extraction and not any("outline weak" in item for item in extraction["warnings"])
    identity = asset["executions"][-1]["identity_inputs"]
    assert identity["fit_settings"] == options["settings"] and identity["fit_joint_limits"] == {"FrontPaw": 90,
                                                                                                "FrontToes": 60}


def test_an_end_bone_is_fitted_within_its_chains_fit_range():
    """Review 2026-10-30: a fitted end bone takes its chain's range for training (creature_views._limit); the fit's
    narrower ranges reach it the same way."""
    creature = {"joints": {"FrontToes.L": {"range": 1.5}, "FrontToesEnd.L": {"range": 1.5},
                           "HindToesEnd.L": {"range": 1.5}}}
    fitted = pipeline._fit_creature(creature, {"FrontPaw": 90, "FrontToes": 60})["joints"]
    assert fitted["FrontToes.L"]["range"] == fitted["FrontToesEnd.L"]["range"] == pytest.approx(math.radians(60))
    assert fitted["HindToesEnd.L"]["range"] == 1.5 and creature["joints"]["FrontToesEnd.L"]["range"] == 1.5
