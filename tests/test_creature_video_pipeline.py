"""B5 orchestration: `creature video` generates seeded clips of a motion from the creature's start frame and keeps
every candidate with its intake numbers; a refused clip (duplicated frames, a drifting backdrop, a still or turning
creature, a refusal, views that disagree) is retained with its reason and the next seed is tried within the type's
budget. ComfyUI and video2rig are stubs; the intake and the decisions are the real code."""
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from slopforge.failures import StageFailure
from slopforge.pipelines import creature as pipeline
from tests.test_creature_calibration import rigged, tool  # noqa: F401  (B1/B2 stubs)
from tests.test_creature_pipeline import stubs  # noqa: F401
from tests.test_video_intake import clip

WALK, _ = clip()
GOOD_CHECK = {"verdict": "OK", "body": 0.006, "limbs": 0.008, "messages": []}


def pulldown():
    frames, _ = clip(n=48)
    return np.stack([frames[k] for k in range(48) for _ in range(3 if k % 2 == 0 else 2)]), 60.0


CASES = {   # seed -> what the provider returns: (frames, fps), or an exception
    "duplicated": pulldown,
    "drift": lambda: (clip(drift=22)[0], 16.0),
    "still": lambda: (clip(walk=False)[0], 16.0),
    "turning": lambda: (clip(turn=True)[0], 16.0),
    "refused": lambda: StageFailure("candidate_quality", "ComfyUI finished without a video",
                                    operation="video_generation", remedy="the next seed",
                                    evidence={"validation": {
                                        "status": "failed", "errors": ["the provider returned no video"],
                                        "failure_codes": ["video_refused"], "artifact_kind": "video",
                                        "measured": {"video_refusals": 1}, "limits": {"max_video_refusals": 0}}}),
    "disagree": lambda: (WALK, 16.0),
    "walk": lambda: (WALK, 16.0),
}


@pytest.fixture
def video(rigged, tool, monkeypatch):  # noqa: F811
    """A calibrated wolf whose start frame is the fixture clip's frame 0, a trained reader, and stub providers: the
    seeds play `plan` in order; video2rig's check says `checks[clip]` (OK by default)."""
    root, config, manifest = rigged
    stub = pipeline._v2r
    calls = {"generated": [], "checked": [], "plan": ["walk"], "checks": {}}

    def v2r(config_, root_, step, project, log, **options):
        if step == "check":
            calls["checked"].append(options["clip"])
            calls.setdefault("timing", {})[options["clip"]] = json.loads(
                (Path(project) / "work" / options["clip"] / "timing.json").read_text())
            answer = calls["checks"].get(options["clip"], GOOD_CHECK)
            if isinstance(answer, Exception):
                raise answer
            return answer
        result = stub(config_, root_, step, project, log, **options)
        if step == "render_start":   # the start frame Wan begins from: the fixture's frame 0 at 1920 x 1080
            Image.fromarray(WALK[0]).resize((1920, 1080), Image.NEAREST).save(Path(project) / "start/start.png")
        return result

    clips = {}

    def generate(config_, root_, workflow, prompt, negative, image, destination, seed, metadata, **options):
        case = calls["plan"][len(calls["generated"])]
        calls["generated"].append({"seed": seed, "prompt": prompt, "negative": negative, "image": str(image),
                                   "workflow": str(workflow), **options})
        made = CASES[case]()
        if isinstance(made, Exception):
            raise made
        clips[str(destination)] = made
        Path(destination).write_bytes(b"mp4 " + case.encode())
        Path(metadata).write_text(json.dumps({"seed": seed, "prompt_id": f"p{seed}", "output_rights": [
            {"source": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "status": "cleared"}]}))

    monkeypatch.setattr(pipeline, "_v2r", v2r)
    monkeypatch.setattr(pipeline, "_generate_video", generate)
    monkeypatch.setattr(pipeline, "_read_clip", lambda path: clips[str(path)])
    # the stubbed reader needs no ffmpeg; the preflight still asks for it (CI's runner has none)
    which = pipeline.shutil.which
    monkeypatch.setattr(pipeline.shutil, "which", lambda name, *args, **kwargs: (
        f"/usr/bin/{name}" if name in ("ffprobe", "ffmpeg") else which(name, *args, **kwargs)))
    pipeline.calibrate_creature(root, config, manifest, "wolf")
    project = root / manifest["assets"]["creature:wolf"]["motion"]["project"]
    (project / "reader/reader.pt").write_bytes(b"trained reader")
    return root, config, manifest, calls, project


def test_an_accepted_clip_records_provider_seed_prompt_and_every_intake_number(video):
    root, config, manifest, calls, project = video
    result = pipeline.video_creature(root, config, manifest, "wolf", "walk", count=1, seed=11)
    asset = manifest["assets"]["creature:wolf"]
    assert result["status"] == "accepted" and result["clips"] == ["walk_s11"] and result["rejected"] == []
    made = calls["generated"][0]
    assert made["seed"] == 11 and made["image"] == str(project / "start/start.png")
    assert made["workflow"].endswith("video_wan22_i2v_api.json") and made["workflow_inputs"] == {"10": {"length": 121}}
    assert "Left half: a fixed camera straight in front of the wolf" in made["prompt"] and "turning" in made["negative"]
    candidate = asset["motion"]["videos"]["walk"][0]
    assert candidate["status"] == "accepted" and candidate["seed"] == 11 and candidate["prompt"] == made["prompt"]
    assert candidate["intake"]["video_motion_share"] > 0.02 and candidate["intake"]["video_view_disagreement"] == 0.006
    assert candidate["check"]["verdict"] == "OK" and candidate["generation"]["prompt_id"] == "p11"
    assert asset["motion"]["clips"]["walk_s11"]["kind"] == "video"
    timing = calls["timing"]["walk_s11"]
    assert timing["times"][1] == pytest.approx(1 / 16) and len(timing["times"]) == len(WALK)
    intake = json.loads((project / "work/walk_s11/intake.json").read_text())
    assert intake["status"] == "passed" and intake["measured"]["video_container_fps"] == 16.0
    execution = asset["executions"][-1]
    assert execution["status"] == "succeeded" and execution["identity_inputs"]["prompt"] == made["prompt"]
    stage = execution["stages"][-1]
    assert stage["name"] == "video_generation" and stage["status"] == "succeeded"
    assert {output["type"] for output in stage["outputs"]} == {"video.generated_clip", "data.video_intake",
                                                               "data.video_generation"}
    assert stage["provenance"]["output_rights"][0]["status"] == "cleared"
    assert "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors" in stage["provenance"]["models"]
    assert stage["intake"]["measured"]["video_motion_share"] > 0.02 and stage["intake"]["check"]["verdict"] == "OK"
    assert execution["identity_inputs"]["reader_sha256"] == __import__("hashlib").sha256(b"trained reader").hexdigest()
    assert stage["provenance"]["provider"]["workflow"] == "video_wan22_i2v_api.json"


def test_every_refused_clip_is_kept_with_its_reason_and_the_next_seed_is_tried(video):
    root, config, manifest, calls, project = video
    path = root / "ai/asset_types/creature.yaml"
    declared = yaml.safe_load(path.read_text())
    declared["video_motions"]["walk"]["retries"] = 6
    path.write_text(yaml.safe_dump(declared, allow_unicode=True))
    calls["plan"] = ["duplicated", "drift", "still", "turning", "refused", "disagree", "walk"]
    calls["checks"]["walk_s6"] = {"verdict": "FAIL", "body": 0.031, "limbs": 0.012, "messages": ["FAIL: panels"]}
    result = pipeline.video_creature(root, config, manifest, "wolf", "walk", count=1, seed=1)
    assert result["clips"] == ["walk_s7"]
    candidates = manifest["assets"]["creature:wolf"]["motion"]["videos"]["walk"]
    codes = {item["clip"]: item["codes"] for item in candidates if item["status"] == "rejected"}
    assert codes == {"walk_s1": ["video_frame_rate"], "walk_s2": ["video_backdrop_drift"], "walk_s3": ["video_still"],
                     "walk_s4": ["video_turned"], "walk_s5": ["video_refused"], "walk_s6": ["video_views_disagree"]}
    assert all(item["reasons"] for item in candidates if item["status"] == "rejected")
    for name in ("walk_s1", "walk_s2", "walk_s3", "walk_s4", "walk_s6"):   # every clip that exists is retained
        assert (project / "clips" / f"{name}.mp4").is_file()
    assert calls["checked"] == ["walk_s6", "walk_s7"]          # video2rig reads only clips the intake passed
    stages = manifest["assets"]["creature:wolf"]["executions"][-1]["stages"]
    assert [stage["status"] for stage in stages] == ["failed"] * 6 + ["succeeded"]
    assert all(stage["failure"]["retryable"] for stage in stages[:6])


def test_a_spent_budget_fails_the_stage_and_keeps_every_reject(video):
    root, config, manifest, calls, project = video
    calls["plan"] = ["still"] * 5                              # the type's walk: retries 4, so five tries for one clip
    with pytest.raises(StageFailure, match="0 of 1"):
        pipeline.video_creature(root, config, manifest, "wolf", "walk", count=1)
    candidates = manifest["assets"]["creature:wolf"]["motion"]["videos"]["walk"]
    assert len(candidates) == 5 and {item["status"] for item in candidates} == {"rejected"}
    assert manifest["assets"]["creature:wolf"]["executions"][-1]["status"] == "failed"


def test_a_provider_fault_stops_at_once(video, monkeypatch):
    root, config, manifest, calls, project = video

    def down(*_args, **_kwargs):
        calls["generated"].append({})
        raise StageFailure("environment", "ComfyUI is not reachable", operation="video_generation",
                           remedy="start ComfyUI")
    monkeypatch.setattr(pipeline, "_generate_video", down)
    with pytest.raises(StageFailure, match="not reachable"):
        pipeline.video_creature(root, config, manifest, "wolf", "walk", count=1)
    assert len(calls["generated"]) == 1
    asset = manifest["assets"]["creature:wolf"]
    assert asset["executions"][-1]["stages"][-1]["status"] == "failed" and asset["executions"][-1]["status"] == "failed"
    candidate = asset["motion"]["videos"]["walk"][-1]
    assert candidate["status"] == "failed" and "not reachable" in candidate["reasons"][0]


@pytest.mark.parametrize("change, message", [
    (lambda project, asset: (project / "reader/reader.pt").unlink(), "reader"),
    (lambda project, asset: asset["motion"].update(status="calibrating"), "not calibrated"),
    (lambda project, asset: (project / "start/start.png").write_bytes(b"changed"), "start frame"),
])
def test_refuses_before_any_generation(video, change, message):
    root, config, manifest, calls, project = video
    change(project, manifest["assets"]["creature:wolf"])
    with pytest.raises(ValueError, match=message):
        pipeline.video_creature(root, config, manifest, "wolf", "walk")
    assert calls["generated"] == []


def test_an_unknown_motion_or_count_refuses(video):
    root, config, manifest, calls, project = video
    with pytest.raises(ValueError, match="no video motion 'run'"):
        pipeline.video_creature(root, config, manifest, "wolf", "run")
    with pytest.raises(ValueError, match="count"):
        pipeline.video_creature(root, config, manifest, "wolf", "walk", count=0)
    assert calls["generated"] == []


def test_the_cli_generates_and_reports_each_candidate(video, capsys):
    from slopforge.cli import main
    from slopforge.manifest import load_manifest, save_manifest
    root, config, manifest, calls, project = video
    (root / "ai/styles/plain").mkdir(parents=True)
    (root / "ai/project.yaml").write_text("project: {name: Test}\nasset_pipeline: {active_style: plain}\n")
    (root / "ai/styles/plain/style.yaml").write_text(
        "name: Plain\nversion: 1\nidentity: {}\nshape_language: {preferred: [], avoid: []}\n"
        "palette: {}\nmaterials: {}\nsurface_language: {preferred: [], avoid: []}\n"
        "lighting: {}\nasset_rules: {}\nmaterial_generation: {rules: []}\n")
    save_manifest(root / "ai/assets/manifest.json", manifest)
    calls["plan"] = ["still", "walk"]
    assert main(["--project", str(root), "creature", "video", "wolf", "walk", "--count", "1", "--seed", "3"]) == 0
    out = capsys.readouterr().out
    assert "walk_s3: rejected (a panel stands still" in out and "walk_s4: accepted" in out
    motion = load_manifest(root / "ai/assets/manifest.json")["assets"]["creature:wolf"]["motion"]
    assert [item["status"] for item in motion["videos"]["walk"]] == ["rejected", "accepted"]


@pytest.mark.skipif(__import__("os").environ.get("SLOPFORGE_RUN_VIDEO_GENERATION") != "1",
                    reason="opt-in: spends GPU time on the configured ComfyUI provider")
def test_external_creature_video():
    """The live gate: one walk clip of a calibrated creature with a trained reader, on the configured ComfyUI (Wan 2.2
    image-to-video) and the real video2rig check; the clip and every candidate's intake are kept."""
    import os
    from slopforge.config import load_project
    from slopforge.manifest import load_manifest
    project, name = os.environ.get("SLOPFORGE_PROJECT_ROOT"), os.environ.get("SLOPFORGE_CREATURE")
    if not (project and name):
        pytest.skip("blocked: set SLOPFORGE_PROJECT_ROOT and SLOPFORGE_CREATURE (a calibrated creature with a reader)")
    config = load_project(project)
    manifest = load_manifest(Path(project) / config["asset_pipeline"]["manifest"])
    result = pipeline.video_creature(project, config, manifest, name, "walk", count=1,
                                     seed=int(os.environ.get("SLOPFORGE_VIDEO_SEED", "1")))
    clip = manifest["assets"][f"creature:{name}"]["motion"]["clips"][result["clips"][0]]
    assert (Path(project) / clip["clip"]).stat().st_size and clip["kind"] == "video"



@pytest.mark.parametrize("answer", [
    {"verdict": "FAIL", "body": None, "limbs": None, "messages": ["no frame read surely in both panels"]},
    StageFailure("environment", "video2rig check exited with code 1", operation="video2rig check",
                 remedy="Read the log"),
])
def test_a_check_without_a_reading_or_that_crashes_refuses_that_clip(video, answer):
    """video2rig's check gives no body or limb value when no frame reads surely in both panels, and can crash on a
    clip; either refuses the clip and the next seed is tried, as any refusal."""
    root, config, manifest, calls, project = video
    calls["plan"] = ["walk", "walk"]
    calls["checks"]["walk_s1"] = answer
    assert pipeline.video_creature(root, config, manifest, "wolf", "walk")["clips"] == ["walk_s2"]
    first = manifest["assets"]["creature:wolf"]["motion"]["videos"]["walk"][0]
    assert first["status"] == "rejected" and first["codes"] == ["video_check_failed"]


def _graph(root, change):
    graph = json.loads((Path(__file__).resolve().parents[1] / "workflows/video_wan22_i2v_api.json").read_text())
    change(graph)
    (root / "ai/workflows").mkdir(parents=True, exist_ok=True)
    (root / "ai/workflows/video_wan22_i2v_api.json").write_text(json.dumps(graph))


@pytest.mark.parametrize("prepare, message", [
    (lambda root, mp: mp.setattr(pipeline, "_video2rig_identity", lambda *a: (_ for _ in ()).throw(
        ValueError("video2rig preflight: the checkout is missing"))), "video2rig"),
    (lambda root, mp: mp.setattr(pipeline.shutil, "which", lambda name: None), "ffprobe"),
    (lambda root, mp: _graph(root, lambda g: g["10"]["inputs"].update(width=832, height=480)), "832x480"),
    (lambda root, mp: _graph(root, lambda g: g.update({"16": {"class_type": "LoadImage", "inputs": {"image": "x"}}})),
     "LoadImage"),
])
def test_prerequisites_refuse_before_any_generation(video, monkeypatch, prepare, message):
    root, config, manifest, calls, project = video
    executions = len(manifest["assets"]["creature:wolf"]["executions"])
    prepare(root, monkeypatch)
    with pytest.raises(ValueError, match=message):
        pipeline.video_creature(root, config, manifest, "wolf", "walk")
    assert calls["generated"] == [] and len(manifest["assets"]["creature:wolf"]["executions"]) == executions


def test_a_seed_already_used_refuses_before_any_generation(video):
    root, config, manifest, calls, project = video
    (project / "clips").mkdir(exist_ok=True)
    (project / "clips/walk_s3.mp4").write_bytes(b"an earlier clip")
    executions = len(manifest["assets"]["creature:wolf"]["executions"])
    with pytest.raises(FileExistsError, match="walk_s3"):
        pipeline.video_creature(root, config, manifest, "wolf", "walk", seed=1)     # seeds 1-5 within the budget
    assert calls["generated"] == [] and len(manifest["assets"]["creature:wolf"]["executions"]) == executions


def test_an_interrupt_finishes_the_stage_and_the_execution(video, monkeypatch):
    root, config, manifest, calls, project = video

    def stop(*_args, **_kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(pipeline, "_generate_video", stop)
    with pytest.raises(KeyboardInterrupt):
        pipeline.video_creature(root, config, manifest, "wolf", "walk")
    execution = manifest["assets"]["creature:wolf"]["executions"][-1]
    assert execution["status"] == "failed" and execution["stages"][-1]["failure"]["category"] == "interruption"


def test_the_run_stops_once_the_clips_asked_for_are_out_of_reach(video):
    root, config, manifest, calls, project = video
    path = root / "ai/asset_types/creature.yaml"
    declared = yaml.safe_load(path.read_text())
    declared["video_motions"]["walk"]["retries"] = 0
    path.write_text(yaml.safe_dump(declared, allow_unicode=True))
    calls["plan"] = ["still", "walk"]
    with pytest.raises(StageFailure, match="0 of 2"):
        pipeline.video_creature(root, config, manifest, "wolf", "walk", count=2)
    assert len(calls["generated"]) == 1
