import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from slopforge import character_rigging as rigging
from slopforge.character_rigging import run_skintokens_inference, skintokens_preflight, prepare_skintokens_runtime
from slopforge.doctor import run_doctor


def config(python=None, checkout=None, checkpoint=None):
    return {"asset_pipeline": {"tools": {
        "skintokens_python": str(python) if python else None,
        "skintokens_checkout": str(checkout) if checkout else None,
        "skintokens_checkpoint": str(checkpoint) if checkpoint else None,
    }}}


def test_preflight_reports_missing_settings_without_paths(tmp_path):
    report = skintokens_preflight(config(), tmp_path)
    assert report["status"] == "unavailable"
    assert any("skintokens_python" in reason for reason in report["reasons"])
    assert str(tmp_path) not in json.dumps(report)


def test_preflight_rejects_nonexecutable_python_and_noncheckout(tmp_path):
    python = tmp_path / "python"
    python.write_text("x")
    checkout = tmp_path / "repo"
    checkout.mkdir()
    checkpoint = tmp_path / "model.ckpt"
    checkpoint.write_bytes(b"weights")
    report = skintokens_preflight(config(python, checkout, checkpoint), tmp_path)
    assert report["status"] == "unavailable"
    assert "executable" in " ".join(report["reasons"])
    python.chmod(0o755)
    report = skintokens_preflight(config(python, checkout, checkpoint), tmp_path)
    assert "checkout" in " ".join(report["reasons"])


def test_preflight_rejects_unexpected_revision_and_missing_checkpoint(tmp_path):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "demo.py").write_text("pass\n")
    subprocess.run(["git", "-C", str(checkout), "add", "demo.py"], check=True)
    subprocess.run(["git", "-C", str(checkout), "-c", "user.name=test", "-c", "user.email=t@e", "commit", "-qm", "test"], check=True)
    report = skintokens_preflight(config(sys.executable, checkout, tmp_path / "missing.ckpt"), tmp_path)
    assert report["status"] == "unverified"
    assert "revision" in " ".join(report["reasons"])
    assert "checkpoint" in " ".join(report["reasons"])
    assert str(tmp_path) not in json.dumps(report)


def test_inference_requires_preflight_before_running(tmp_path):
    source = tmp_path / "source.glb"
    source.write_bytes(b"mesh")
    with pytest.raises(ValueError, match="SkinTokens preflight"):
        run_skintokens_inference(config(), source, tmp_path / "result.glb", seed=17)


def test_setup_is_revision_guarded_and_idempotent(tmp_path, monkeypatch):
    checkout = tmp_path / "repo"
    source = checkout / "src/model/tokenrig.py"
    source.parent.mkdir(parents=True)
    (checkout / ".git").mkdir()
    demo = checkout / "demo.py"
    demo.write_text("pass\n")
    monkeypatch.setattr(rigging, "SKINTOKENS_DEMO_SHA256", hashlib.sha256(demo.read_bytes()).hexdigest())
    original = b'attn_implementation="flash_attention_2"'
    source.write_bytes(original)
    monkeypatch.setattr(rigging, "SKINTOKENS_TOKENRIG_SHA256", hashlib.sha256(original).hexdigest())
    monkeypatch.setattr(rigging, "SKINTOKENS_PATCH_SHA256", hashlib.sha256(b'attn_implementation="sdpa"').hexdigest())
    monkeypatch.setattr(rigging, "_skintokens_revision", lambda _: "wrong")
    with pytest.raises(ValueError, match="revision"):
        prepare_skintokens_runtime(config(checkout=checkout), tmp_path)
    assert source.read_bytes() == original
    monkeypatch.setattr(rigging, "_skintokens_revision", lambda _: rigging.SKINTOKENS_REVISION)
    assert prepare_skintokens_runtime(config(checkout=checkout), tmp_path)["status"] == "prepared"
    assert prepare_skintokens_runtime(config(checkout=checkout), tmp_path)["status"] == "prepared"
    assert source.read_bytes() == b'attn_implementation="sdpa"'


def test_pinned_preflight_hashes_checkpoint_and_runner_records_seed(tmp_path, monkeypatch):
    checkout = tmp_path / "repo"
    tokenrig = checkout / "src/model/tokenrig.py"
    tokenrig.parent.mkdir(parents=True)
    (checkout / ".git").mkdir()
    demo = checkout / "demo.py"
    demo.write_text("pass\n")
    tokenrig.write_text('attn_implementation="sdpa"')
    checkpoint = tmp_path / "weights.ckpt"
    checkpoint.write_bytes(b"weights")
    vae = checkout / "experiments/skin_vae_2_10_32768/last.ckpt"
    vae.parent.mkdir(parents=True)
    vae.write_bytes(b"vae weights")
    qwen = checkout / "models/Qwen3-0.6B/config.json"
    qwen.parent.mkdir(parents=True)
    qwen.write_text('{"model_type":"qwen3"}')
    monkeypatch.setattr(rigging, "_skintokens_revision", lambda _: rigging.SKINTOKENS_REVISION)
    monkeypatch.setattr(rigging, "SKINTOKENS_DEMO_SHA256", hashlib.sha256(demo.read_bytes()).hexdigest())
    monkeypatch.setattr(rigging, "SKINTOKENS_PATCH_SHA256", hashlib.sha256(tokenrig.read_bytes()).hexdigest())
    monkeypatch.setattr(rigging, "_skintokens_checkout_changes", lambda *_: False)
    settings = config(sys.executable, checkout, checkpoint)
    settings["_project_root"] = tmp_path
    report = skintokens_preflight(settings, tmp_path)
    assert report["status"] == "ready"
    assert report["checkpoint_sha256"] == hashlib.sha256(b"weights").hexdigest()
    assert str(tmp_path) not in json.dumps(report)

    source = tmp_path / "source.glb"
    source.write_bytes(b"input")
    output = tmp_path / "out.glb"
    def fake_run(argv, **kwargs):
        assert argv[:2] == [str(Path(sys.executable).resolve()), "-c"]
        assert kwargs["cwd"] == checkout
        assert kwargs["env"]["PYTHONHASHSEED"] == "17"
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert kwargs["env"]["TRANSFORMERS_OFFLINE"] == "1"
        assert Path(kwargs["stdout"].name).is_relative_to(tmp_path / "ai/logs/skintokens")
        request = json.loads(Path(argv[-1]).read_text())
        assert request["seed"] == 17
        assert request["settings"]["top_k"] == 5
        Path(request["result"]).write_text('{"status":"complete"}')
        output.write_bytes(_glb())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(rigging.subprocess, "run", fake_run)
    result = run_skintokens_inference(settings, source, output, seed=17)
    assert result["seed"] == 17
    assert result["checkpoint_sha256"] == report["checkpoint_sha256"]
    assert str(tmp_path) not in json.dumps(result)


def test_preflight_requires_all_local_model_dependencies(tmp_path, monkeypatch):
    checkout = tmp_path / "repo"
    source = checkout / "src/model/tokenrig.py"
    source.parent.mkdir(parents=True)
    (checkout / ".git").mkdir()
    demo = checkout / "demo.py"
    demo.write_text("pass\n")
    source.write_text('attn_implementation="sdpa"')
    checkpoint = tmp_path / "weights.ckpt"
    checkpoint.write_bytes(b"weights")
    monkeypatch.setattr(rigging, "_skintokens_revision", lambda _: rigging.SKINTOKENS_REVISION)
    monkeypatch.setattr(rigging, "SKINTOKENS_DEMO_SHA256", hashlib.sha256(demo.read_bytes()).hexdigest())
    monkeypatch.setattr(rigging, "SKINTOKENS_PATCH_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    report = skintokens_preflight(config(sys.executable, checkout, checkpoint), tmp_path)
    assert report["status"] == "unverified"
    assert "FSQ" in " ".join(report["reasons"])
    assert "Qwen" in " ".join(report["reasons"])


@pytest.mark.parametrize("contents, expected", [("asset_pipeline: [invalid\n", 1), (None, 0)])
def test_doctor_does_not_reload_invalid_or_missing_project(tmp_path, contents, expected):
    if contents is not None:
        project_file = tmp_path / "ai/project.yaml"
        project_file.parent.mkdir()
        project_file.write_text(contents)
    assert run_doctor(tmp_path) == expected


def _glb(json_bytes=b'{"asset":{"version":"2.0"}}', *, chunk_type=b"JSON", size_delta=0):
    json_bytes += b" " * (-len(json_bytes) % 4)
    payload = len(json_bytes).to_bytes(4, "little") + chunk_type + json_bytes
    return b"glTF" + (2).to_bytes(4, "little") + (12 + len(payload) + size_delta).to_bytes(4, "little") + payload


@pytest.mark.parametrize("data", [
    _glb(b"{}"), _glb(chunk_type=b"BIN\0"), _glb()[:-1],
    _glb(size_delta=4), _glb() + b"extra",
    _glb()[:12] + (999).to_bytes(4, "little") + _glb()[16:],
])
def test_inference_rejects_malformed_glb(tmp_path, monkeypatch, data):
    monkeypatch.setattr(rigging, "skintokens_preflight", lambda *_: {
        "status": "ready", "revision": rigging.SKINTOKENS_REVISION,
        "checkpoint_id": "weights.ckpt", "checkpoint_sha256": "x", "compatibility_sha256": "y"})
    def fake_run(argv, **kwargs):
        request = json.loads(Path(argv[-1]).read_text())
        Path(request["result"]).write_text('{"status":"complete"}')
        Path(request["output"]).write_bytes(data)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(rigging.subprocess, "run", fake_run)
    source = tmp_path / "source.glb"
    source.write_bytes(b"input")
    with pytest.raises(RuntimeError, match="malformed GLB"):
        run_skintokens_inference(config(sys.executable, tmp_path, tmp_path / "weights.ckpt"),
                                 source, tmp_path / "out.glb", seed=1)


def test_preflight_rejects_unexpected_dirty_checkout(tmp_path, monkeypatch):
    checkout = tmp_path / "repo"
    tokenrig = checkout / "src/model/tokenrig.py"
    tokenrig.parent.mkdir(parents=True)
    tokenrig.write_text('attn_implementation="sdpa"')
    demo = checkout / "demo.py"
    demo.write_text("pass\n")
    (checkout / "src/other.py").write_text("pass\n")
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
    subprocess.run(["git", "-C", str(checkout), "-c", "user.name=test", "-c", "user.email=t@e", "commit", "-qm", "test"], check=True)
    vae = checkout / "experiments/skin_vae_2_10_32768/last.ckpt"
    vae.parent.mkdir(parents=True)
    vae.write_bytes(b"vae weights")
    qwen = checkout / "models/Qwen3-0.6B/config.json"
    qwen.parent.mkdir(parents=True)
    qwen.write_text('{"model_type":"qwen3"}')
    checkpoint = tmp_path / "weights.ckpt"
    checkpoint.write_bytes(b"weights")
    monkeypatch.setattr(rigging, "_skintokens_revision", lambda _: rigging.SKINTOKENS_REVISION)
    monkeypatch.setattr(rigging, "SKINTOKENS_DEMO_SHA256", hashlib.sha256(demo.read_bytes()).hexdigest())
    monkeypatch.setattr(rigging, "SKINTOKENS_PATCH_SHA256", hashlib.sha256(tokenrig.read_bytes()).hexdigest())
    settings = config(sys.executable, checkout, checkpoint)
    assert skintokens_preflight(settings, tmp_path)["status"] == "ready"
    (checkout / "src/other.py").write_text("changed\n")
    assert skintokens_preflight(settings, tmp_path)["status"] == "unverified"
    (checkout / "src/other.py").write_text("pass\n")
    (checkout / "src/evil.py").write_text("pass\n")
    assert skintokens_preflight(settings, tmp_path)["status"] == "unverified"


@pytest.mark.skipif(os.environ.get("SLOPFORGE_RUN_SKINTOKENS") != "1", reason="opt-in external runtime")
def test_external_skintokens_candidate():
    from slopforge.config import load_project
    project = os.environ.get("SLOPFORGE_PROJECT_ROOT")
    source = os.environ.get("SLOPFORGE_SKINTOKENS_SOURCE")
    output = os.environ.get("SLOPFORGE_SKINTOKENS_OUTPUT")
    if not all((project, source, output)):
        pytest.skip("blocked: set project, source, and output environment variables")
    settings = load_project(project)
    report = skintokens_preflight(settings, project)
    if report["status"] != "ready":
        pytest.skip("blocked: " + "; ".join(report["reasons"]))
    result = run_skintokens_inference(settings, source, output, seed=17)
    assert result["status"] == "complete"
