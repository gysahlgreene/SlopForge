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
    for name in ("skintokens", "part_masks", "omnipart"):
        assert found[name]["output_rights"]["status"] == "cleared", name
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
