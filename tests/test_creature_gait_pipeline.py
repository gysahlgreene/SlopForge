"""B4 orchestration: `creature gait` computes a motion the creature type declares on its rig (blender/procedural_gait.py),
bakes it with B6's own bake and registers the FBX as a candidate animation with its stride, period and review sheet,
as `creature extract` does a clip; `animation approve` and Unity delivery then take it unchanged. No video2rig
calibration is needed. The Blender runs are stubs; the checks, records and decisions are the real code."""
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from slopforge.pipelines import creature as pipeline
from tests.test_creature_calibration import rigged, tool  # noqa: F401  (B1/B2 stubs)
from tests.test_creature_pipeline import stubs  # noqa: F401

BUILT = {"status": "complete", "frames": 145, "fps": 24, "period_s": 1.2083, "speed_mps": 0.4841, "height_m": 0.95,
         "ik_miss_max_m": 0.0, "body_drop_m": 0.04, "hips_rise_m": 0.018, "leg_turn_max_deg": 48.3}
BAKED = {"status": "complete", "fps": 24.0, "keys": 145, "height_m": 0.95,
         "plants": {"front.L": [13, 42], "front.R": [27, 56], "hind.L": [6, 35], "hind.R": [20, 49]},
         "cycles": 4, "weak_legs": [], "period_s": 1.2083, "speed_mps": 0.4841, "velocity": [0.0, -0.4841],
         "stride_m": 0.585, "partial_steps": [["front.L", 0, 6]], "clean": [6, 144],
         "window": {"start": 6, "end": 122, "cycles": 4, "seam_deg": 0.14, "start_frame": 7, "end_frame": 123,
                    "start_s": 0.25, "end_s": 5.0833, "seam_root_m": 0.003},
         "residual_travel_m": 0.0, "stance_slide_mps": 0.001}
MATERIAL = "Assets/Generated/Creatures/wolf/Unity/wolf_preview_PBR.mat"


@pytest.fixture
def gaited(rigged, monkeypatch):  # noqa: F811
    """The rigged fixture wolf, never calibrated; the gait run writes its .blend, cameras and `calls["built"]`'s
    report, and the bake `calls["baked"]`'s with its FBX, .blend and renders through those cameras."""
    root, config, manifest = rigged
    calls = {"built": dict(BUILT), "baked": dict(BAKED)}

    def gait(config_, root_, blend, request):
        calls["gait"] = (blend, request)
        if calls["built"]["status"] == "complete":
            Path(request["save"]).write_bytes(b"blend with the computed walk")
            views = [{"name": name, "width_px": width, "height_px": 540, "type": "ortho"}
                     for name, width in (("front", 240), ("side", 640))]
            Path(request["cameras"]).write_text(json.dumps({"frame_px": [880, 540], "views": views}))
        Path(request["report"]).write_text(json.dumps(calls["built"]))
        return calls["built"]

    def bake(config_, root_, source, request):
        calls["bake"] = (source, request)
        report = calls["baked"]
        Path(request["fbx"]).write_bytes(b"fbx")
        Path(request["blend"]).write_bytes(b"baked blend")
        Path(request["renders"]).mkdir(parents=True)
        report["renders"] = []
        for view in json.loads(Path(request["cameras"]).read_text())["views"]:
            for index in [*range(request["samples"]), "seam"]:
                path = Path(request["renders"]) / f"{view['name']}_{index}.png"
                Image.new("RGB", (96, 108), (90, 80, 70)).save(path)
                report["renders"].append({"view": view["name"], "index": index, "clip_frame": 7, "path": str(path)})
        Path(request["report"]).write_text(json.dumps(report))
        return report

    monkeypatch.setattr(pipeline, "_gait", gait)
    monkeypatch.setattr(pipeline, "_bake", bake)
    return root, config, manifest, calls


def test_a_computed_walk_is_built_on_the_rig_baked_and_registered_as_a_candidate_animation(gaited):
    root, config, manifest, calls = gaited
    result = pipeline.gait_creature(root, config, manifest, "wolf", "walk")
    asset = manifest["assets"]["creature:wolf"]
    assert result["status"] == "review_required" and asset["motion"].get("status") is None   # not calibrated
    blend, request = calls["gait"]
    assert Path(blend) == root / asset["artifacts"]["rig_blend"]["path"]
    structure = json.loads((root / asset["rigging"]["structure"]).read_text())
    height = structure["measured"]["height"]
    # the type's walk: stride and lift as shares of the creature's height; the whole leg chains for the IK
    assert {"motion": "walk", "root": "Hips", "period_s": 1.2, "duty": 0.62, "seconds": 6.0, "fps": 24}.items() \
        <= request.items()
    assert request["stride_m"] == pytest.approx(0.75 * height) and request["lift_m"] == pytest.approx(0.06 * height)
    assert set(request["legs"]) == {"front.L", "front.R", "hind.L", "hind.R"}
    assert all(len(chain) == len(limb["chain"]) for chain, limb in zip(
        (request["legs"][f"{limb['end']}.{limb['side']}"] for limb in structure["limbs"]), structure["limbs"]))
    assert request["tail"] == ["Tail1", "Tail2"]
    source, baking = calls["bake"]
    assert Path(source) == Path(request["save"]) and baking["cameras"] == request["cameras"]
    assert all(len(bones) == 2 for bones in baking["legs"].values()) and baking["root_bone"] == "Hips"
    assert baking["times"] == pytest.approx([k / 24 for k in range(145)])     # the built walk's own frames
    animation = asset["artifacts"]["animation.gait_walk"]
    assert animation["status"] == "candidate" and animation["approval"]["status"] == "pending"
    assert {"loop": True, "root_motion": False, "stride_m": 0.585, "period_s": 1.2083, "loop_periods": 4,
            "procedural": {"motion": "walk", "period_s": 1.2, "duty": 0.62, "stride": 0.75, "lift": 0.06,
                           "seconds": 6.0}}.items() <= animation["provenance"].items()
    assert {item["source"] for item in animation["provenance"]["output_rights"]} == {"blender"}
    entry = asset["motion"]["clips"]["gait_walk"]
    assert entry["kind"] == "procedural" and entry["motion"] == "walk"
    assert entry["extraction"]["status"] == "review_required" and entry["extraction"]["speed_mps"] == 0.4841
    sheet = Image.open(root / entry["extraction"]["review_sheet"])
    assert sheet.size[1] == (8 // 2 + 1) * 334          # two phases a row in both views, then the loop's seam
    stages = {stage["name"]: stage for stage in asset["executions"][-1]["stages"]}
    assert stages["procedural_motion"]["status"] == stages["motion_bake"]["status"] == "succeeded"
    assert stages["procedural_motion"]["inputs"][0]["type"] == "project.blend"
    assert {output["type"] for output in stages["procedural_motion"]["outputs"]} == {
        "project.blend", "report.procedural_motion", "data.cameras"}
    assert {output["type"] for output in stages["motion_bake"]["outputs"]} >= {
        "animation.fbx", "report.motion_bake", "image.motion_review"}


def test_a_computed_walk_is_not_made_again_over_itself(gaited):
    root, config, manifest, calls = gaited
    pipeline.gait_creature(root, config, manifest, "wolf", "walk")
    with pytest.raises(FileExistsError, match="gait_walk"):
        pipeline.gait_creature(root, config, manifest, "wolf", "walk")


def test_a_motion_the_type_does_not_compute_is_refused_before_blender(gaited):
    root, config, manifest, calls = gaited
    with pytest.raises(ValueError, match="no procedural motion 'gallop'"):
        pipeline.gait_creature(root, config, manifest, "wolf", "gallop")
    assert "gait" not in calls


def test_a_walk_the_gait_refuses_fails_its_stage_and_is_recorded(gaited):
    root, config, manifest, calls = gaited
    calls["built"] = {"status": "error", "errors": ["ValueError: a leg bone turns 180 degrees from its rest pose"]}
    with pytest.raises(RuntimeError, match="turns 180 degrees"):
        pipeline.gait_creature(root, config, manifest, "wolf", "walk")
    asset = manifest["assets"]["creature:wolf"]
    stage = asset["executions"][-1]["stages"][-1]
    assert stage["name"] == "procedural_motion" and stage["status"] == "failed" and "bake" not in calls
    assert asset["motion"]["clips"]["gait_walk"]["extraction"]["status"] == "failed"


def test_a_computed_walk_is_approved_as_a_clip_is(gaited):
    root, config, manifest, calls = gaited
    pipeline.gait_creature(root, config, manifest, "wolf", "walk")
    pipeline.approve_rig(root, manifest, "wolf", confirmed=True)
    result = pipeline.approve_motion(root, manifest, "wolf", "gait_walk", confirmed=True)
    assert result["status"] == "approved"
    assert manifest["assets"]["creature:wolf"]["artifacts"]["animation.gait_walk"]["approval"]["status"] == "approved"


def test_calibrating_after_a_computed_walk_keeps_it(gaited, tool):  # noqa: F811
    root, config, manifest, calls = gaited
    pipeline.gait_creature(root, config, manifest, "wolf", "walk")
    pipeline.calibrate_creature(root, config, manifest, "wolf")
    clips = manifest["assets"]["creature:wolf"]["motion"]["clips"]
    assert manifest["assets"]["creature:wolf"]["motion"]["status"] == "calibrated" and "gait_walk" in clips


def test_a_computed_walk_is_delivered_to_unity_on_a_creature_never_calibrated(gaited, monkeypatch):
    root, config, manifest, calls = gaited
    pipeline.gait_creature(root, config, manifest, "wolf", "walk")
    pipeline.approve_rig(root, manifest, "wolf", confirmed=True)
    pipeline.approve_motion(root, manifest, "wolf", "gait_walk", confirmed=True)
    played = deliverable(root, manifest, monkeypatch)
    result = pipeline.creature_unity_setup(root, config, manifest, "wolf")
    assert result["clips"] == ["gait_walk"] and result["speeds"] == {"gait_walk": 0.4841}
    assert '"Hips"' in played[0]                        # the root bone the play keeps in place


def deliverable(root, manifest, monkeypatch):
    """The approved material, a Unity version, and the editor and Play mode as stubs; the scripts Play mode ran."""
    (root / "ProjectSettings").mkdir(exist_ok=True)
    (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
    (root / MATERIAL).parent.mkdir(parents=True, exist_ok=True)
    (root / MATERIAL).write_text("%YAML 1.1\nMaterial: wolf_preview_PBR\n")
    manifest["assets"]["creature:wolf"]["unity_import"] = {"assets": {"material": {"path": MATERIAL}}}
    played = []

    def editor(command, **kwargs):
        script = next((root / "Assets/Editor").glob("*.cs")).read_text()
        for kind in ("controller", "prefab"):
            (root / re.search(f'const string {kind}Path = "([^"]+)"', script).group(1)).write_bytes(kind.encode())

    def play(project_root, script, *, results, remedy=None):
        played.append(script)
        Path(results).write_text("<test-run/>")
        Path(results).with_suffix(".jsonl").write_text(json.dumps({"height_m": 0.95}) + "\n")
        return {"passed": ["FacesForwardAtItsSize"], "failed": []}

    monkeypatch.setattr("slopforge.unity_animation.unity_cli", lambda root_: "unity")
    monkeypatch.setattr("slopforge.unity_animation.subprocess.run", editor)
    monkeypatch.setattr(pipeline, "verify_play_mode", play)
    monkeypatch.setattr(pipeline, "editor_binary", lambda root_: "Unity")
    return played


def test_the_cli_computes_a_walk(gaited, capsys):
    from slopforge.cli import main
    from slopforge.manifest import save_manifest
    root, config, manifest, calls = gaited
    (root / "ai/styles/plain").mkdir(parents=True)
    (root / "ai/project.yaml").write_text("project: {name: Test}\nasset_pipeline: {active_style: plain}\n")
    (root / "ai/styles/plain/style.yaml").write_text(
        "name: Plain\nversion: 1\nidentity: {}\nshape_language: {preferred: [], avoid: []}\n"
        "palette: {}\nmaterials: {}\nsurface_language: {preferred: [], avoid: []}\n"
        "lighting: {}\nasset_rules: {}\nmaterial_generation: {rules: []}\n")
    save_manifest(root / "ai/assets/manifest.json", manifest)
    assert main(["--project", str(root), "creature", "gait", "wolf", "walk"]) == 0
    out = capsys.readouterr().out
    assert "stride 0.58 m every 1.21 s (0.48 m/s)" in out and "a loop of 4 periods, seam 0.1 deg" in out
    assert "slopforge animation approve wolf gait_walk --confirm" in out
    calls.update(built=dict(IDLE_BUILT), baked=dict(IDLE_BAKED))
    assert main(["--project", str(root), "creature", "gait", "wolf", "idle"]) == 0
    assert "gait_idle: review_required; standing in place, a loop of 6.00 s, seam 0.0 deg" in capsys.readouterr().out


IDLE_BUILT = {"status": "complete", "frames": 145, "fps": 24, "period_s": 6.0, "speed_mps": 0.0, "height_m": 0.95,
              "ik_miss_max_m": 0.0, "body_drop_m": 0.0, "hips_rise_m": 0.012, "leg_turn_max_deg": 6.0,
              "head_turn_max_deg": 12.4}
IDLE_BAKED = {"status": "complete", "fps": 24.0, "keys": 145, "height_m": 0.95, "plants": {}, "cycles": 0,
              "weak_legs": [], "period_s": 6.0, "speed_mps": 0.0, "velocity": [0.0, 0.0], "stride_m": 0.0,
              "partial_steps": [], "clean": [0, 144],
              "window": {"start": 0, "end": 144, "cycles": 1, "seam_deg": 0.0, "start_frame": 1, "end_frame": 145,
                         "start_s": 0.0, "end_s": 6.0, "seam_root_m": 0.0},
              "residual_travel_m": 0.0, "stance_slide_mps": 0.0}


def test_a_computed_idle_is_built_baked_whole_and_registered_still(gaited):
    root, config, manifest, calls = gaited
    calls.update(built=dict(IDLE_BUILT), baked=dict(IDLE_BAKED))
    result = pipeline.gait_creature(root, config, manifest, "wolf", "idle")
    asset = manifest["assets"]["creature:wolf"]
    _, request = calls["gait"]
    height = json.loads((root / asset["rigging"]["structure"]).read_text())["measured"]["height"]
    assert {"motion": "idle", "seconds": 6.0, "breaths": 3, "look_deg": 7, "tail_deg": 4}.items() <= request.items()
    assert request["sway_m"] == pytest.approx(0.007 * height) and "stride_m" not in request
    assert request["neck"] == ["Neck1", "Head"] and "spine" not in request
    _, baking = calls["bake"]
    assert baking["still"] is True and baking["times"] == pytest.approx([k / 24 for k in range(145)])
    animation = asset["artifacts"]["animation.gait_idle"]
    assert {"loop": True, "root_motion": False, "speed_mps": 0.0, "stride_m": 0.0, "period_s": 6.0,
            "loop_periods": 1}.items() <= animation["provenance"].items()
    assert asset["motion"]["clips"]["gait_idle"]["extraction"]["gait"]["head_turn_max_deg"] == 12.4
    assert result["clip"] == "gait_idle"


def test_a_computed_walks_bake_is_not_still(gaited):
    root, config, manifest, calls = gaited
    pipeline.gait_creature(root, config, manifest, "wolf", "walk")
    assert calls["bake"][1]["still"] is False and "breaths" not in calls["gait"][1]


def test_an_approved_computed_idle_is_delivered_to_unity_standing_still(gaited, monkeypatch):
    root, config, manifest, calls = gaited
    calls.update(built=dict(IDLE_BUILT), baked=dict(IDLE_BAKED))
    pipeline.gait_creature(root, config, manifest, "wolf", "idle")
    pipeline.approve_rig(root, manifest, "wolf", confirmed=True)
    pipeline.approve_motion(root, manifest, "wolf", "gait_idle", confirmed=True)
    played = deliverable(root, manifest, monkeypatch)
    result = pipeline.creature_unity_setup(root, config, manifest, "wolf")
    assert result["speeds"] == {"gait_idle": 0.0}
    assert '[TestCase("gait_idle", ' in played[0]
