"""B1 orchestration: `creature rig` keeps a candidate per SkinTokens seed, finishes the best passing one, and
`creature approve-rig` records the human review behind the delivery-rights gate. SkinTokens and Blender are stubs that
answer with the four-legged box fixture's real structure reports."""
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from slopforge.creature_rig import check_rig
from slopforge.failures import StageFailure
from slopforge.pipelines import creature as pipeline
from slopforge.provenance import file_sha256
from slopforge.providers import combine_rights
from tests.test_creature_rig import BONES, NAMES, creature

ROOT = Path(__file__).resolve().parents[1]
SHIFTED = {name: (((x + 0.02, y, z) if name.startswith("frontR") else (x, y, z)), parent)
           for name, ((x, y, z), parent) in BONES.items()}       # mirrors within 0.02 / 0.95 of the height
EXTRA = {**BONES, "frontRx": ((-0.1, -0.4, 0.17), "frontR2"), "frontR3": (BONES["frontR3"][0], "frontRx")}
OUTSIDE = {**BONES, "bone_8": ((0, 0.95, 0.58), "bone_7")}
PASSING = {1: EXTRA, 2: SHIFTED, 3: OUTSIDE, 4: BONES}           # seed 4 mirrors exactly: the best


def project(tmp_path, rights="cleared"):
    (tmp_path / "ai/asset_types").mkdir(parents=True)
    shutil.copy(ROOT / "templates/asset_types/creature.yaml", tmp_path / "ai/asset_types/creature.yaml")
    config = {"asset_pipeline": {"output_root": "Assets/Generated", "manifest": "ai/assets/manifest.json"},
              "_project_root": str(tmp_path)}
    fbx = tmp_path / "Assets/Generated/Creatures/wolf/wolf.fbx"
    fbx.parent.mkdir(parents=True)
    fbx.write_bytes(b"Kaydara FBX Binary  \x00")
    relative = fbx.relative_to(tmp_path).as_posix()
    published = {"id": "e:published:fbx", "type": "mesh.fbx", "path": relative, "sha256": file_sha256(fbx),
                 "stage": "final_publication", "attempt": 1, "derived_from": []}
    entry = ({"source": "trellis2", "status": rights, "reason": "its terms were not read"} if rights == "unknown"
             else {"source": "trellis2", "status": rights, "terms": "MIT", "terms_version": "v1", "read_on": "2026-10-27"})
    asset = {"id": "wolf-id", "name": "wolf", "type": "creature", "status": "ready", "outputs": {"fbx": relative},
             "published_artifacts": [published], "output_rights": combine_rights([entry]), "executions": [],
             "artifacts": {}}
    return tmp_path, config, {"schema_version": 4, "assets": {"creature:wolf": asset}}


@pytest.fixture
def stubs(monkeypatch):
    calls = {"infer": [], "blender": []}
    variants = dict(PASSING)

    def infer(config, source, raw, seed):
        calls["infer"].append(seed)
        if variants.get(seed) is None:
            raise RuntimeError("SkinTokens inference failed; inspect the project log")
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"glTF" + bytes([seed]))
        return {"status": "complete", "revision": "273b691", "checkpoint_sha256": "c" * 64, "seed": seed}

    def blender(config, root, request):
        calls["blender"].append(request["action"])
        if request["action"] == "check":
            seed = int(Path(request["raw"]).parent.name.removeprefix("seed_"))
            report = check_rig(creature(variants[seed]), request["limbs"], request["limits"])
            images = request["views"].values()
        else:
            calls["finished"] = int(Path(request["raw"]).parent.name.removeprefix("seed_"))
            assert Path(request["raw"]).read_bytes() == b"glTF" + bytes([calls["finished"]])   # that seed's raw rig
            assert Path(request["source"]).is_file()
            for key in ("rigged_model", "blend"):
                Path(request[key]).write_bytes(b"rig")
            report = {"status": "complete", "bone_names": list(request["names"].values()),
                      "material_coverage": {"base_color": 1.0}}
            images = request["pose_images"]
        for image in images:
            Path(image).parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (64, 48), (90, 90, 90)).save(image)
        Path(request["report"]).write_text(json.dumps(report))
        return report

    monkeypatch.setattr(pipeline, "_infer", infer)
    monkeypatch.setattr(pipeline, "_blender", blender)
    monkeypatch.setattr(pipeline, "_provider", lambda config, root: {
        "name": "SkinTokens", "version": "273b691", "source": "https://github.com/VAST-AI-Research/SkinTokens",
        "license": "MIT", "source_revision": "273b691", "checkpoint_sha256": "c" * 64})
    return calls, variants


def test_every_seed_is_kept_and_the_best_passing_rig_is_finished(tmp_path, stubs):
    root, config, manifest = project(tmp_path)
    result = pipeline.rig_creature(root, config, manifest, "wolf")
    asset = manifest["assets"]["creature:wolf"]
    assert stubs[0]["infer"] == [1, 2, 3, 4]
    statuses = {seed: asset["artifacts"][f"rig_candidate.seed_{seed}"]["status"] for seed in PASSING}
    assert statuses == {1: "failed", 2: "candidate", 3: "failed", 4: "candidate"}
    rejected = asset["artifacts"]["rig_candidate.seed_1"]["validation"]
    assert rejected["failure_codes"] == ["rig_asymmetric"] and rejected["errors"]
    assert asset["artifacts"]["rig_candidate.seed_3"]["validation"]["failure_codes"] == ["rig_bone_outside"]
    rigging = asset["rigging"]
    assert result["seed"] == rigging["seed"] == stubs[0]["finished"] == 4 and rigging["status"] == "review_required"
    assert rigging["names"] == NAMES and "FrontPaw.L" in rigging["fit_bones"]
    assert [item["seed"] for item in rigging["candidates"]] == [1, 2, 3, 4]
    rig = asset["artifacts"]["rig"]
    assert (rig["type"], rig["status"], rig["approval"]["status"]) == ("model.rigged", "candidate", "pending")
    assert rig["validation"]["status"] == "passed"
    assert {item["source"] for item in rig["provenance"]["output_rights"]} == {"skintokens", "blender"}
    for key in ("rig", "rig_blend", "rig_contact_sheet", "rig_seed_sheet"):
        assert (root / asset["artifacts"][key]["path"]).stat().st_size
    with Image.open(root / asset["artifacts"]["rig_contact_sheet"]["path"]) as sheet:
        assert sheet.width > sheet.height
    execution = asset["executions"][-1]
    assert execution["status"] == "succeeded"
    assert [stage["name"] for stage in execution["stages"]] == ["rig_candidate"] * 4 + ["rig_postprocess"]
    assert all(stage["status"] == "succeeded" and stage["outputs"] for stage in execution["stages"])
    assert execution["stages"][0]["inputs"][0]["type"] == "mesh.fbx"


def test_a_seed_that_crashes_is_recorded_and_the_others_still_run(tmp_path, stubs):
    stubs[1][1] = None
    root, config, manifest = project(tmp_path)
    pipeline.rig_creature(root, config, manifest, "wolf")
    asset = manifest["assets"]["creature:wolf"]
    first = asset["executions"][-1]["stages"][0]
    assert first["status"] == "failed" and "inference failed" in first["error"]
    assert first["failure"]["stage"] == "rig_candidate" and first["failure"]["attempt"] == 1
    assert asset["rigging"]["candidates"][0]["status"] == "error" and asset["rigging"]["seed"] == 4


def test_no_passing_seed_fails_the_run_and_keeps_every_reject(tmp_path, stubs):
    stubs[1].update({2: EXTRA, 4: OUTSIDE})
    root, config, manifest = project(tmp_path)
    with pytest.raises(StageFailure, match="no SkinTokens seed of 4 passed"):
        pipeline.rig_creature(root, config, manifest, "wolf")
    asset = manifest["assets"]["creature:wolf"]
    assert asset["rigging"]["status"] == "failed" and len(asset["rigging"]["candidates"]) == 4
    assert all(asset["artifacts"][f"rig_candidate.seed_{seed}"]["status"] == "failed" for seed in PASSING)
    assert (root / asset["artifacts"]["rig_seed_sheet"]["path"]).is_file()
    assert asset["executions"][-1]["status"] == "failed" and "rig" not in asset["artifacts"]


def test_a_rerun_never_overwrites_retained_candidates(tmp_path, stubs):
    root, config, manifest = project(tmp_path)
    pipeline.rig_creature(root, config, manifest, "wolf", seeds=2)
    with pytest.raises(FileExistsError, match="inspect or move them"):
        pipeline.rig_creature(root, config, manifest, "wolf", seeds=2)


def test_only_a_published_creature_can_be_rigged(tmp_path, stubs):
    root, config, manifest = project(tmp_path)
    asset = manifest["assets"]["creature:wolf"]
    asset["status"] = "awaiting_texture_approval"
    with pytest.raises(ValueError, match="approve its material first"):
        pipeline.rig_creature(root, config, manifest, "wolf")
    asset["status"], asset["type"] = "ready", "prop"
    with pytest.raises(ValueError, match="not a creature"):
        pipeline.rig_creature(root, config, manifest, "wolf")
    with pytest.raises(ValueError, match="seeds"):
        pipeline.rig_creature(root, config, {**manifest, "assets": {"creature:wolf": {**asset, "type": "creature"}}},
                              "wolf", seeds=9)


def test_approval_needs_confirmation_and_shippable_rights(tmp_path, stubs):
    root, config, manifest = project(tmp_path, rights="unknown")
    pipeline.rig_creature(root, config, manifest, "wolf")
    with pytest.raises(ValueError, match="confirmation"):
        pipeline.approve_rig(root, manifest, "wolf", confirmed=False)
    with pytest.raises(StageFailure, match="creature approve-rig"):
        pipeline.approve_rig(root, manifest, "wolf", confirmed=True)
    asset = manifest["assets"]["creature:wolf"]
    assert asset["artifacts"]["rig"]["approval"]["status"] == "pending"
    asset["output_rights"] = combine_rights([{"source": "dinov3", "status": "attribution_required", "terms": "DINOv3",
                                              "terms_version": "v1", "read_on": "2026-10-27",
                                              "notice": "Built with DINOv3."}])
    assert pipeline.approve_rig(root, manifest, "wolf", confirmed=True)["status"] == "approved"
    assert asset["artifacts"]["rig"]["approval"]["status"] == "approved"
    assert asset["rigging"]["status"] == "approved"
    assert asset["rigging"]["review"]["output_rights"]["status"] == "attribution_required"


def test_the_cli_rigs_and_approves_a_creature(tmp_path, stubs, capsys):
    from slopforge.cli import main
    from slopforge.manifest import load_manifest, save_manifest
    root, _config, manifest = project(tmp_path)
    (root / "ai/styles/plain").mkdir(parents=True)
    (root / "ai/project.yaml").write_text("project: {name: Test}\nasset_pipeline: {active_style: plain}\n")
    (root / "ai/styles/plain/style.yaml").write_text(
        "name: Plain\nversion: 1\nidentity: {}\nshape_language: {preferred: [], avoid: []}\n"
        "palette: {}\nmaterials: {}\nsurface_language: {preferred: [], avoid: []}\n"
        "lighting: {}\nasset_rules: {}\nmaterial_generation: {rules: []}\n")
    save_manifest(root / "ai/assets/manifest.json", manifest)
    assert main(["--project", str(root), "creature", "rig", "wolf", "--seeds", "4"]) == 0
    printed = capsys.readouterr().out
    assert "seed 4" in printed and "seed 1: failed" in printed and "approve-rig wolf --confirm" in printed
    assert main(["--project", str(root), "creature", "approve-rig", "wolf"]) == 1
    assert load_manifest(root / "ai/assets/manifest.json")["assets"]["creature:wolf"]["rigging"]["status"] == \
        "review_required"
    assert main(["--project", str(root), "creature", "approve-rig", "wolf", "--confirm"]) == 0
    assert load_manifest(root / "ai/assets/manifest.json")["assets"]["creature:wolf"]["rigging"]["status"] == "approved"
