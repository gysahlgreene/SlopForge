import json

import pytest

from slopforge import providers
from slopforge.backends import video2rig
from slopforge.failures import StageFailure

RIGHTS = {"status": "cleared", "terms": "Replicate Terms of Service", "terms_version": "2026-04-01",
          "read_on": "2026-10-27"}


def config(tools=None, declared=None):
    return {"asset_pipeline": {"tools": tools or {}, **({"providers": declared} if declared is not None else {})}}


def test_existing_tool_keys_are_read_into_the_map():
    found = providers.load_providers(config({
        "comfy_url": "http://gpu:8188", "skintokens_host": "gpu", "skintokens_python": "/opt/st/bin/python",
        "skintokens_checkout": "/opt/st", "skintokens_checkpoint": "/opt/st/w.ckpt",
        "parts_host": "gpu", "parts_python": "/opt/parts/bin/python",
        "omnipart_python": "/opt/op/bin/python", "omnipart_checkout": "/opt/op"}))
    assert found["comfyui"]["type"] == "comfyui" and found["comfyui"]["url"] == "http://gpu:8188"
    assert (found["skintokens"]["type"], found["skintokens"]["host"]) == ("ssh_gpu", "gpu")
    assert (found["part_masks"]["type"], found["omnipart"]["type"]) == ("ssh_gpu", "ssh_gpu")
    for name in ("skintokens", "part_masks"):
        assert found[name]["output_rights"]["status"] == "cleared", name
    assert found["omnipart"]["output_rights"]["status"] == "restricted"
    assert "video2rig" not in found  # not configured
    local = providers.load_providers(config({"skintokens_python": "/opt/st/bin/python"}))
    assert local["skintokens"]["type"] == "local_tool"


@pytest.mark.parametrize("settings", [
    config(declared={"video2rig": {"type": "local_tool", "python": "/v/.venv/bin/python", "checkout": "/v/video2rig",
                                   "train_host": "gpu", "train_python": "/g/python", "train_checkout": "/g/video2rig"}}),
    config({"video2rig_python": "/v/.venv/bin/python", "video2rig_checkout": "/v/video2rig",
            "video2rig_train_host": "gpu", "video2rig_train_python": "/g/python",
            "video2rig_train_checkout": "/g/video2rig"}),  # the keys V0 shipped with
])
def test_video2rig_is_the_maps_first_entry_with_the_old_keys_still_read(settings):
    entry = providers.load_providers(settings)["video2rig"]
    assert entry["type"] == "local_tool"
    assert (entry["python"], entry["checkout"], entry["train_host"]) == ("/v/.venv/bin/python", "/v/video2rig", "gpu")
    assert entry["output_rights"] == video2rig.OUTPUT_RIGHTS
    assert video2rig.settings(settings) == {"python": "/v/.venv/bin/python", "checkout": "/v/video2rig",
                                            "train_host": "gpu", "train_python": "/g/python",
                                            "train_checkout": "/g/video2rig"}


def test_the_map_wins_over_the_old_keys_and_unset_names_the_new_ones(tmp_path):
    settings = config({"video2rig_python": "/old/python"}, {"video2rig": {"type": "local_tool", "python": "/new/python"}})
    assert video2rig.settings(settings)["python"] == "/new/python"
    report = video2rig.preflight(config(), tmp_path)
    assert "providers.video2rig.python" in report["local"]["reasons"][0]


def test_a_hosted_api_names_its_credential_and_never_holds_it(monkeypatch):
    declared = {"video_cloud": {"type": "hosted_api", "vendor": "replicate", "key_env": "REPLICATE_API_TOKEN",
                                "models": {"walk": "wan-video/wan-2.2-i2v-fast"}, "output_rights": RIGHTS}}
    found = providers.load_providers(config(declared=declared))
    assert found["video_cloud"]["output_rights"] == RIGHTS
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    report = providers.preflight("video_cloud", found["video_cloud"], config(declared=declared), ".")
    assert (report["status"], report["category"]) == ("unavailable", "configuration")
    assert "REPLICATE_API_TOKEN" in report["reasons"][0]
    with pytest.raises(StageFailure) as failure:
        providers.require_ready("video_cloud", report)
    assert failure.value.category == "configuration"
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_secret_value")
    report = providers.preflight("video_cloud", found["video_cloud"], config(declared=declared), ".")
    assert report["status"] == "ready" and "r8_secret_value" not in json.dumps(report)


@pytest.mark.parametrize("block, message", [
    ({"type": "hosted_api", "vendor": "replicate", "output_rights": RIGHTS}, "key_env"),
    ({"type": "hosted_api", "key_env": "r8_abc123", "output_rights": RIGHTS}, "key_env"),
    ({"type": "hosted_api", "key_env": "TOKEN", "api_key": "r8_abc", "output_rights": RIGHTS}, "api_key"),
    ({"type": "gpu_cloud"}, "type"),
    ({"type": "ssh_gpu", "host": "gpu", "python": "venv/bin/python", "checkout": "/c"}, "absolute"),
    ({"type": "local_tool", "output_rights": {"status": "cleared"}}, "providers.thing.output_rights"),
    ("not a mapping", "mapping"),
])
def test_malformed_provider_blocks_are_refused(block, message):
    with pytest.raises(ValueError, match=message):
        providers.load_providers(config(declared={"thing": block}))


def test_a_declared_provider_without_rights_is_unknown_and_the_map_must_be_a_mapping():
    found = providers.load_providers(config(declared={"thing": {"type": "local_tool"}}))
    assert found["thing"]["output_rights"]["status"] == "unknown"
    assert "providers.thing.output_rights" in found["thing"]["output_rights"]["reason"]
    with pytest.raises(ValueError, match="providers must be a mapping"):
        providers.load_providers(config(declared=["video2rig"]))


def test_bundled_workflows_state_every_models_rights():
    """The terms read on 2026-10-27 (docs/COMFYUI.md, Output rights): concepts, edits and the upscaler cleared, the
    TRELLIS.2 and Pixal3D graphs owe "Built with DINOv3."."""
    from slopforge.paths import tool_root
    from slopforge.providers import combine_rights
    from slopforge.workflow_requirements import workflow_output_rights
    expected = {"image_text2img_api.json": "cleared", "image_character_pose_api.json": "cleared",
                "image_seamless_inpaint_api.json": "cleared", "image_edit_qwen_api.json": "cleared",
                "image_views_qwen_edit_api.json": "cleared", "image_upscale_esrgan_api.json": "cleared",
                "video_wan22_i2v_api.json": "cleared"}   # Wan 2.2, umT5-XXL and the Wan VAE: Apache-2.0 (2026-10-28)
    for path in sorted((tool_root() / "workflows").glob("*_api.json")):
        entries = workflow_output_rights(path)
        assert all("states no output_rights" not in entry.get("reason", "") for entry in entries), path.name
        rights = combine_rights(entries)
        assert rights["status"] == expected.get(path.name, "attribution_required"), path.name
        if rights["status"] == "attribution_required":
            assert rights["notices"] == ["Built with DINOv3."], path.name


def test_omnipart_is_restricted_by_its_nvidia_dependencies():
    found = providers.load_providers(config({"omnipart_python": "/opt/op/bin/python", "omnipart_checkout": "/opt/op"}))
    rights = found["omnipart"]["output_rights"]
    assert rights["status"] == "restricted" and "non-commercial" in rights["reason"]
    assert providers.BUILTIN_RIGHTS["part_masks"]["status"] == "cleared"


def test_a_stage_records_a_providers_rights_from_the_map_with_the_users_reading_first():
    assert providers.rights_of(config(), "blender")[0]["source"] == "blender"
    assert providers.rights_of(config(), "background_removal")[0]["status"] == "cleared"
    tools = {"omnipart_python": "/opt/op/bin/python", "omnipart_checkout": "/opt/op"}
    assert providers.rights_of(config(tools), "omnipart")[0]["status"] == "restricted"
    reading = {"status": "cleared", "terms": "NVIDIA commercial licence for FlexiCubes and nvdiffrast",
               "terms_version": "signed 2026-11-01", "read_on": "2026-11-01"}
    own = config(tools, {"omnipart": {"type": "ssh_gpu", "host": "gpu", "python": "/opt/op/bin/python",
                                      "checkout": "/opt/op", "output_rights": reading}})
    assert providers.rights_of(own, "omnipart") == [{"source": "omnipart", **reading}]
    assert providers.rights_of(config(), "omnipart")[0]["status"] == "restricted"  # not configured: still its terms
    broken = providers.rights_of(config(declared={"omnipart": "nope"}), "omnipart")[0]
    assert broken["status"] == "unknown" and "providers" in broken["reason"]


def test_doctor_reports_every_providers_rights_and_each_workflows(tmp_path, monkeypatch, capsys):
    from unittest.mock import patch
    import yaml
    from slopforge.doctor import run_doctor
    from slopforge.initializer import init_project
    (tmp_path / "Assets").mkdir()
    init_project(tmp_path)
    project = tmp_path / "ai/project.yaml"
    settings = yaml.safe_load(project.read_text())
    settings["asset_pipeline"]["tools"].update(omnipart_python="/opt/op/bin/python", omnipart_checkout="/opt/op")
    settings["asset_pipeline"]["providers"] = {"video_cloud": {
        "type": "hosted_api", "vendor": "replicate", "key_env": "SLOPFORGE_TEST_UNSET_TOKEN",
        "output_rights": {"status": "unknown", "reason": "API terms not read yet"}}}
    project.write_text(yaml.safe_dump(settings))
    monkeypatch.delenv("SLOPFORGE_TEST_UNSET_TOKEN", raising=False)
    with patch("slopforge.doctor.ComfyUIClient.health", side_effect=OSError("offline")):
        assert run_doctor(tmp_path) == 0  # rights warn: experiments may proceed
    lines = capsys.readouterr().out.splitlines()
    line = lambda label: next(item for item in lines if label in item)
    assert line("Provider omnipart").startswith("WARN") and "restricted" in line("Provider omnipart")
    assert "non-commercial" in line("Provider omnipart") and "approve-texture" in line("Provider omnipart")
    assert line("Provider video_cloud").startswith("WARN") and "SLOPFORGE_TEST_UNSET_TOKEN" in line("Provider video_cloud")
    assert "API terms not read yet" in line("Provider video_cloud")
    assert line("Workflow rights").startswith("PASS") and "cleared" in line("Workflow rights")
    assert line("Model workflow rights").startswith("PASS") and "Built with DINOv3." in line("Model workflow rights")



def test_swapped_part_mask_models_are_not_the_ones_whose_terms_were_read():
    tools = {"parts_host": "gpu", "parts_python": "/opt/parts/bin/python"}
    assert providers.rights_of(config(tools), "part_masks")[0]["status"] == "cleared"
    swapped = providers.rights_of(config({**tools, "parts_models": {"sam": "someone/sam-finetune"}}), "part_masks")[0]
    assert swapped["status"] == "unknown" and "parts_models" in swapped["reason"]


@pytest.mark.parametrize("block", [
    {"type": "hosted_api", "key_env": "TOKEN", "api_token": "r8_abc"},
    {"type": "hosted_api", "key_env": "TOKEN", "apikey": "r8_abc"},
    {"type": "hosted_api", "key_env": "TOKEN", "headers": {"Authorization": "Bearer r8_abc"}},
    {"type": "hosted_api", "key_env": "TOKEN", "models": [{"walk": "x", "access_token": "r8"}]},
])
def test_credentials_anywhere_in_a_provider_block_are_refused(block):
    with pytest.raises(ValueError, match="credentials never go in the project file"):
        providers.load_providers(config(declared={"video_cloud": block}))


def test_a_broken_providers_block_stops_the_project_from_loading(tmp_path):
    """Otherwise every stage would record unknown rights for Blender and BiRefNet, and resume would copy them on."""
    import yaml
    from slopforge.config import load_project
    from slopforge.initializer import init_project
    (tmp_path / "Assets").mkdir()
    init_project(tmp_path)
    project = tmp_path / "ai/project.yaml"
    settings = yaml.safe_load(project.read_text())
    settings["asset_pipeline"]["providers"] = {"video_cloud": {"type": "hosted_api", "vendor": "replicate"}}
    project.write_text(yaml.safe_dump(settings))
    with pytest.raises(ValueError, match="providers.video_cloud.key_env"):
        load_project(tmp_path)


def test_the_upscaler_is_the_release_weights_converted_by_the_pinned_script():
    """The sidecar's hashes are the converter's: the .safetensors is xinntao's v0.1.0 .pth, converted by
    scripts/convert-realesrgan.py, so its source and terms are documented."""
    import runpy
    from slopforge.paths import tool_root
    from slopforge.workflow_requirements import load_workflow_requirements
    script = runpy.run_path(str(tool_root() / "scripts/convert-realesrgan.py"))
    model, = load_workflow_requirements(tool_root() / "workflows/image_upscale_esrgan_api.json")["models"]
    assert model["source"] == script["SOURCE_URL"]
    assert (model["source_sha256"], model["sha256"]) == (script["SOURCE_SHA256"], script["CONVERTED_SHA256"])
    assert model["output_rights"]["status"] == "cleared" and model["license"] == "BSD-3-Clause"
