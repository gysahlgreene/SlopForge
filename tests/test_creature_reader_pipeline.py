"""B3a: a calibrated creature's reader trained as a recorded stage, on the GPU provider when one is set (the client's
transport is tested in tests/test_video2rig_provider.py). video2rig's steps are the calibration tool stubs."""
import json
from pathlib import Path

import pytest

from slopforge.failures import StageFailure
from slopforge.pipelines import creature as pipeline
from slopforge.provenance import file_sha256
from tests.test_creature_calibration import rigged, tool  # noqa: F401  (B1/B2 stubs)
from tests.test_creature_pipeline import stubs  # noqa: F401

TRAINED = {"held_out": {"v2r_front": {"median_px": 5.6, "p90_px": 28.6, "n": 6008},
                        "v2r_side": {"median_px": 4.04, "p90_px": 17.6, "n": 7116}},
           "steps": 9000, "batch": 24, "minutes": 11.4, "pictures": 6000}


@pytest.fixture
def calibrated(rigged, tool, monkeypatch):  # noqa: F811
    """The wolf calibrated; video2rig's train writes a reader and its report, or fails after writing a reader."""
    root, config, manifest = rigged
    pipeline.calibrate_creature(root, config, manifest, "wolf")
    project = root / manifest["assets"]["creature:wolf"]["motion"]["project"]
    inner = pipeline._v2r

    def v2r(config_, root_, step, project_, log, **options):
        if step != "train":
            return inner(config_, root_, step, project_, log, **options)
        tool["steps"].append((step, options))
        tool["trained"] = tool.get("trained", 0) + 1
        (Path(project_) / "reader/reader.pt").write_bytes(f"trained reader {tool['trained']}".encode())
        if tool.get("train_fails"):
            raise StageFailure("environment", "video2rig train on gpu-box: train exited with code 1",
                               operation="video2rig train", remedy="Read the log")
        (Path(project_) / "reader/reader-train.json").write_text(json.dumps(TRAINED))
        return dict(TRAINED)
    monkeypatch.setattr(pipeline, "_v2r", v2r)
    return root, config, manifest, tool, project


def test_a_calibrated_creatures_reader_is_trained_as_a_recorded_stage(calibrated):
    root, config, manifest, calls, project = calibrated
    result = pipeline.train_creature(root, config, manifest, "wolf", steps=9000)
    assert calls["steps"][-1] == ("train", {"steps": 9000})
    asset = manifest["assets"]["creature:wolf"]
    stage = asset["executions"][-1]["stages"][-1]
    assert (stage["name"], stage["status"]) == ("detector_training", "succeeded")
    # its parents are the training set calibration made, as it is now
    assert {(ref["stage"], Path(ref["path"]).name) for ref in stage["inputs"]} == {
        ("detector_training_set", "poses.npz"), ("detector_training_set", "visible.npz")}
    outputs = {ref["type"]: ref for ref in stage["outputs"]}
    assert set(outputs) == {"model.joint_reader", "report.reader_training"}
    assert outputs["model.joint_reader"]["sha256"] == file_sha256(project / "reader/reader.pt")
    assert stage["settings"]["steps"] == 9000
    assert stage["provenance"]["held_out"] == TRAINED["held_out"]
    assert stage["provenance"]["reproducibility"]["status"] == "not_recorded"   # GPU training is not bit-repeatable
    # review 2026-10-30: the machine that trains is the one checked and recorded, not this one
    assert stage["provenance"]["provider"]["role"] == "train"
    reader = asset["motion"]["reader"]
    assert reader["status"] == "trained" and reader["sha256"] == file_sha256(project / "reader/reader.pt")
    assert reader["held_out_median_px"] == {"v2r_front": 5.6, "v2r_side": 4.04}
    assert result["held_out_median_px"] == {"v2r_front": 5.6, "v2r_side": 4.04}


def test_a_reader_is_trained_only_for_a_calibrated_creature(rigged, tool):  # noqa: F811
    root, config, manifest = rigged
    with pytest.raises(ValueError, match="not calibrated"):
        pipeline.train_creature(root, config, manifest, "wolf")
    assert not [step for step, _ in tool["steps"] if step == "train"]


@pytest.mark.parametrize("left", ["reader.pt", "reader-train.json"])
def test_an_existing_reader_or_its_report_is_not_replaced(calibrated, left):
    root, config, manifest, calls, project = calibrated
    (project / "reader" / left).write_bytes(b"made by hand")
    with pytest.raises(FileExistsError, match="move reader.pt and reader-train.json aside"):
        pipeline.train_creature(root, config, manifest, "wolf")
    assert (project / "reader" / left).read_bytes() == b"made by hand"
    assert not [step for step, _ in calls["steps"] if step == "train"]


def test_a_training_set_changed_since_calibration_is_refused(calibrated):
    root, config, manifest, calls, project = calibrated
    (project / "reader/poses.npz").write_bytes(b"other poses")
    with pytest.raises(ValueError, match="poses.npz"):
        pipeline.train_creature(root, config, manifest, "wolf")
    assert not [step for step, _ in calls["steps"] if step == "train"]


def test_a_failed_training_is_recorded_and_leaves_no_reader(calibrated):
    from slopforge.manifest import load_manifest
    root, config, manifest, calls, project = calibrated
    calls["train_fails"] = True
    with pytest.raises(StageFailure, match="train"):
        pipeline.train_creature(root, config, manifest, "wolf")
    assert not (project / "reader/reader.pt").exists()    # a partial reader would pass for a trained one
    saved = load_manifest(root / config["asset_pipeline"]["manifest"])["assets"]["creature:wolf"]
    assert saved["executions"][-1]["stages"][-1]["name"] == "detector_training"
    assert saved["executions"][-1]["status"] == "failed" and saved["motion"]["reader"]["status"] == "failed"


def test_the_cli_trains_and_reports_the_held_out_error(calibrated, capsys):
    from slopforge.cli import main
    from slopforge.manifest import save_manifest
    root, config, manifest, calls, project = calibrated
    (root / "ai/styles/plain").mkdir(parents=True)
    (root / "ai/project.yaml").write_text("project: {name: Test}\nasset_pipeline: {active_style: plain}\n")
    (root / "ai/styles/plain/style.yaml").write_text(
        "name: Plain\nversion: 1\nidentity: {}\nshape_language: {preferred: [], avoid: []}\n"
        "palette: {}\nmaterials: {}\nsurface_language: {preferred: [], avoid: []}\n"
        "lighting: {}\nasset_rules: {}\nmaterial_generation: {rules: []}\n")
    save_manifest(root / "ai/assets/manifest.json", manifest)
    assert main(["--project", str(root), "creature", "train", "wolf", "--steps", "500"]) == 0
    out = capsys.readouterr().out
    assert calls["steps"][-1] == ("train", {"steps": 500})
    assert "held-out median 5.6 px (v2r_front), 4.04 px (v2r_side)" in out and "reader.pt" in out
