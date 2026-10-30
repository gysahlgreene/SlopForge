"""B7: a creature's approved rig and clips go into Unity as a Generic Animator Controller and prefab, played before
they are recorded. Unity's editor run and its test runner are stubbed; tests/test_creature_unity_blender.py runs
them."""
import json
import re
from pathlib import Path

import pytest

from slopforge.failures import StageFailure
from slopforge.pipelines import creature as pipeline
from tests.test_creature_calibration import rigged, tool  # noqa: F401  (B1/B2 stubs)
from tests.test_creature_extract_pipeline import extracted  # noqa: F401
from tests.test_creature_pipeline import stubs  # noqa: F401
from tests.test_creature_video_pipeline import video  # noqa: F401

UNITY = "Assets/Generated/Creatures/wolf/Unity"
MEASURES = {"faces_margin_m": 0.42, "height_m": 0.781,
            "clips": {"walk_s11": {"length_s": 1.25, "root_excursion_m": 0.04, "stance_slide_mps": 0.06}}}


@pytest.fixture
def unity(extracted, monkeypatch):  # noqa: F811
    """walk_s11 extracted; the editor run records its script and writes the controller and prefab; Play mode records
    its script, writes the NUnit results and the measures, and passes unless `calls["play_fails"]`."""
    root, config, manifest, calls, project = extracted
    pipeline.extract_creature(root, config, manifest, "wolf", "walk_s11")
    calls.update(editor=[], play=[])

    def editor(command, **kwargs):
        script = next((root / "Assets/Editor").glob("*.cs")).read_text()
        calls["editor"].append(script)
        for kind in ("controller", "prefab"):   # where the build script saves them
            (root / re.search(f'const string {kind}Path = "([^"]+)"', script).group(1)).write_bytes(kind.encode())

    def play(project_root, script, *, results):
        calls["play"].append(script)
        Path(results).write_text("<test-run/>")
        Path(results).with_suffix(".jsonl").write_text("".join(json.dumps(line) + "\n" for line in (
            {"faces_margin_m": 0.42, "height_m": 0.781}, {"clip": "walk_s11", "length_s": 1.25},
            {"clip": "walk_s11", "root_excursion_m": 0.04, "stance_slide_mps": 0.06})))
        if calls.get("play_fails"):
            raise StageFailure("processing_validation", "play-mode checks failed: InPlace(walk_s11): moved 0.6 m",
                               operation="play_mode_verification", remedy="the results file names each failure")
        return {"passed": ["FacesForwardAtItsSize", 'Plays("walk_s11")'], "failed": []}

    monkeypatch.setattr("slopforge.unity_animation.unity_cli", lambda root_: "unity")
    monkeypatch.setattr("slopforge.unity_animation.subprocess.run", editor)
    monkeypatch.setattr(pipeline, "verify_play_mode", play)
    return root, config, manifest, calls


def approve(root, manifest):
    pipeline.approve_rig(root, manifest, "wolf", confirmed=True)
    pipeline.approve_motion(root, manifest, "wolf", "walk_s11", confirmed=True)


def test_an_approved_creature_is_delivered_generic_in_place_at_its_clips_speed_and_played(unity):
    root, config, manifest, calls = unity
    approve(root, manifest)
    result = pipeline.creature_unity_setup(root, config, manifest, "wolf")

    build = calls["editor"][0]
    assert "ModelImporterAnimationType.Generic" in build and "ModelImporterAnimationType.Human" not in build
    assert '"walk_s11"' in build                                   # the state is the clip's name
    # D9: the clip is in place and the controller carries the speed a game moves the creature at
    assert ('name = "walk_s11_speed", type = AnimatorControllerParameterType.Float, defaultFloat = 0.4f'
            in build)
    assert "applyRootMotion = false" in build and "new bool[] {true}" in build
    # 2026-10-30 live: the clip FBX holds the armature alone and Unity folds a lone top-level node into the file's
    # root, so its curves (Hips/...) missed the rig's bones (Armature/Hips/...) and its root curves scaled the prefab
    # 100x; both importers keep their FBX root, so the clip's paths are the rig's
    assert "rigImporter.preserveHierarchy = true;" in build and "importer.preserveHierarchy = true;" in build
    play = calls["play"][0]
    assert f'"{UNITY}/wolf.prefab"' in play and '"walk_s11"' in play
    assert "FacesForwardAtItsSize" in play and "InPlace" in play

    asset = manifest["assets"]["creature:wolf"]
    for artifact_id in ("unity.animator_controller", "unity.creature_prefab"):
        artifact = asset["artifacts"][artifact_id]
        assert artifact["status"] == "candidate" and artifact["approval"]["status"] == "pending"
        assert artifact["derived_from"] == [{"asset_id": asset["id"], "output_id": "rig"},
                                            {"asset_id": asset["id"], "output_id": "animation.walk_s11"}]
    provenance = asset["artifacts"]["unity.creature_prefab"]["provenance"]
    assert provenance["clips"]["walk_s11"] == {"speed_mps": 0.4, "stride_m": 0.5, "period_s": 1.25}
    assert provenance["play_mode"]["measured"] == MEASURES and provenance["play_mode"]["failed"] == []
    assert provenance["delivered_rights"]["status"] in ("cleared", "attribution_required")
    # the notices the rig and clips owe ship beside the prefab (none are owed by the fixture's tools)
    assert (root / UNITY / "SlopForge-NOTICES.txt").is_file() == bool(provenance["delivered_rights"]["notices"])
    assert (root / UNITY / "wolf_playmode.xml").is_file()
    assert not any((root / "Assets/Editor").glob("*.cs"))
    assert result["status"] == "review_required" and result["clips"] == ["walk_s11"]


def test_a_creature_whose_rig_is_not_approved_is_refused_before_unity_runs(unity):
    root, config, manifest, calls = unity
    with pytest.raises(ValueError, match="rig is not approved"):
        pipeline.creature_unity_setup(root, config, manifest, "wolf")
    assert calls["editor"] == []


def test_a_creature_with_no_approved_clip_is_refused_before_unity_runs(unity):
    root, config, manifest, calls = unity
    pipeline.approve_rig(root, manifest, "wolf", confirmed=True)
    with pytest.raises(ValueError, match="no approved clip.*animation approve wolf"):
        pipeline.creature_unity_setup(root, config, manifest, "wolf")
    assert calls["editor"] == []


@pytest.mark.parametrize("change, words", [
    (lambda asset: asset["artifacts"]["rig"]["path"], "rig is missing or changed since it was approved"),
    (lambda asset: asset["artifacts"]["animation.walk_s11"]["path"], "walk_s11's animation.fbx is missing or changed"),
    (lambda asset: asset["motion"]["clips"]["walk_s11"]["extraction"]["bake"], "walk_s11's report.motion_bake"),
])
def test_an_approved_rig_or_clip_changed_since_its_approval_is_refused_before_unity_runs(unity, change, words):
    root, config, manifest, calls = unity
    approve(root, manifest)
    (root / change(manifest["assets"]["creature:wolf"])).write_bytes(b"edited")
    with pytest.raises(ValueError, match=words):
        pipeline.creature_unity_setup(root, config, manifest, "wolf")
    assert calls["editor"] == []


def test_a_clip_whose_rights_are_not_shippable_is_refused_before_unity_runs(unity):
    root, config, manifest, calls = unity
    approve(root, manifest)
    manifest["assets"]["creature:wolf"]["artifacts"]["animation.walk_s11"]["provenance"]["output_rights"] = [
        {"source": "a video model", "status": "unknown", "reason": "its terms were not read"}]
    with pytest.raises(StageFailure, match="its terms were not read"):
        pipeline.creature_unity_setup(root, config, manifest, "wolf")
    assert calls["editor"] == []


def test_existing_unity_outputs_are_not_overwritten(unity):
    root, config, manifest, calls = unity
    approve(root, manifest)
    (root / UNITY).mkdir(parents=True)
    (root / UNITY / "wolf.prefab").write_bytes(b"a game's prefab")
    with pytest.raises(FileExistsError, match="already exist"):
        pipeline.creature_unity_setup(root, config, manifest, "wolf")
    assert calls["editor"] == [] and (root / UNITY / "wolf.prefab").read_bytes() == b"a game's prefab"


def test_a_failed_play_mode_check_leaves_no_controller_or_prefab_and_keeps_its_results(unity):
    root, config, manifest, calls = unity
    approve(root, manifest)
    calls["play_fails"] = True
    with pytest.raises(StageFailure, match="InPlace"):
        pipeline.creature_unity_setup(root, config, manifest, "wolf")
    assert not (root / UNITY / "wolf.controller").exists() and not (root / UNITY / "wolf.prefab").exists()
    assert (root / UNITY / "wolf_playmode.xml").is_file() and (root / UNITY / "wolf_playmode.jsonl").is_file()
    assert not any(name.startswith("unity.") for name in manifest["assets"]["creature:wolf"]["artifacts"])


def test_the_cli_delivers_a_creature_generic_only(unity, capsys):
    from slopforge.cli import main
    from slopforge.manifest import load_manifest, save_manifest
    root, config, manifest, calls = unity
    (root / "ai/styles/plain").mkdir(parents=True)
    (root / "ai/project.yaml").write_text("project: {name: Test}\nasset_pipeline: {active_style: plain}\n")
    (root / "ai/styles/plain/style.yaml").write_text(
        "name: Plain\nversion: 1\nidentity: {}\nshape_language: {preferred: [], avoid: []}\n"
        "palette: {}\nmaterials: {}\nsurface_language: {preferred: [], avoid: []}\n"
        "lighting: {}\nasset_rules: {}\nmaterial_generation: {rules: []}\n")
    approve(root, manifest)
    save_manifest(root / "ai/assets/manifest.json", manifest)
    assert main(["--project", str(root), "animation", "unity-setup", "wolf", "--rig-type", "humanoid"]) == 1
    assert "a creature is delivered Generic" in capsys.readouterr().err and calls["editor"] == []
    assert main(["--project", str(root), "animation", "unity-setup", "wolf"]) == 0
    out = capsys.readouterr().out
    assert "wolf.prefab" in out and "walk_s11: 0.40 m/s (parameter walk_s11_speed)" in out
    assert "stance slide 0.06 m/s at that speed" in out
    saved = load_manifest(root / "ai/assets/manifest.json")["assets"]["creature:wolf"]
    assert saved["artifacts"]["unity.creature_prefab"]["approval"]["status"] == "pending"


def test_what_the_play_needs_is_read_before_unity_builds_anything(unity):
    root, config, manifest, calls = unity
    approve(root, manifest)
    (root / manifest["assets"]["creature:wolf"]["rigging"]["structure"]).unlink()
    with pytest.raises(FileNotFoundError):
        pipeline.creature_unity_setup(root, config, manifest, "wolf")
    assert calls["editor"] == [] and not (root / UNITY / "wolf.prefab").exists()
