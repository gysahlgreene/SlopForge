import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from slopforge.backends import video2rig
from slopforge.backends import video2rig_runtime as runtime
from slopforge.failures import StageFailure

REPO = Path(__file__).resolve().parents[1]


def stub_install(root, *, net=True, cuda=False):
    """A video2rig install as scripts/install-video2rig.sh lays it out, with stand-ins for the tool and its torch."""
    checkout = root / "video2rig"
    (checkout / "video2rig/reader").mkdir(parents=True)
    for name in ("__init__.py", "check.py", "creature.py", "reader/__init__.py", "reader/train.py") + \
            (("reader/net.py",) if net else ()):
        (checkout / "video2rig" / name).write_text("")
    (checkout / "torch.py").write_text(
        f"__version__ = '2.7.0'\nclass cuda:\n    is_available = staticmethod(lambda: {cuda})\n"
        f"    is_bf16_supported = staticmethod(lambda: {cuda})\n")
    (checkout / "transformers.py").write_text(
        "import os\n__version__ = '5.20.1'\nclass Dinov2Model:\n    @staticmethod\n"
        "    def from_pretrained(name):\n        assert os.environ['HF_HUB_OFFLINE'] == '1', 'online load'\n"
        "        assert os.environ['HF_HUB_CACHE'] == os.path.join(os.environ['HF_HOME'], 'hub'), 'another cache'\n")
    (checkout / ".gitignore").write_text("__pycache__/\n*.pyc\n")  # as upstream's: the probe's imports leave bytecode
    git =["git", "-C", str(checkout), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(git + ["add", "."], check=True)
    subprocess.run(git + ["commit", "-qm", "stub"], check=True)
    hub = root / "hf/hub/models--facebook--dinov2-small"
    (hub / "refs").mkdir(parents=True)
    (hub / "refs/main").write_text(runtime.DINOV2_REVISION)
    weights = hub / "snapshots" / runtime.DINOV2_REVISION / "model.safetensors"
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"dinov2 weights")
    commit = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    return SimpleNamespace(checkout=checkout, commit=commit, weights=weights)


@pytest.fixture
def install(tmp_path, monkeypatch):
    stub = stub_install(tmp_path / "SlopForgeVideo2rig")
    monkeypatch.setattr(runtime, "VIDEO2RIG_REVISION", stub.commit)
    monkeypatch.setattr(runtime, "DINOV2_SHA256", hashlib.sha256(b"dinov2 weights").hexdigest())
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    monkeypatch.setenv("V2R_FFMPEG", str(ffmpeg))
    # A user's own cache setting outranks HF_HOME in huggingface_hub; the tool must still read the pinned snapshot.
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "elsewhere/hub"))
    blender = tmp_path / "blender"
    blender.write_text("#!/bin/sh\n")
    blender.chmod(0o755)
    stub.blender = str(blender)
    return stub


def check(stub, role="local"):
    return runtime.preflight(sys.executable, str(stub.checkout), role, blender=getattr(stub, "blender", None))


def test_preflight_passes_on_a_clean_checkout_at_the_pinned_commit(install):
    report = check(install)
    assert report["status"] == "ready", report["reasons"]
    assert report["revision"] == install.commit
    assert report["dinov2_revision"] == runtime.DINOV2_REVISION
    assert report["dinov2_sha256"] == hashlib.sha256(b"dinov2 weights").hexdigest()
    assert (report["torch"], report["transformers"], report["device"]) == ("2.7.0", "5.20.1", "cpu")


def test_environment_pins_the_backbone_cache_and_drops_inherited_paths(install, monkeypatch, tmp_path):
    for key in ("HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "PYTHONPATH"):
        monkeypatch.setenv(key, str(tmp_path / "other"))
    env = runtime.environment(install.checkout)
    hf = install.checkout.parent.resolve() / "hf"
    assert (env["HF_HOME"], env["HF_HUB_CACHE"], env["HF_HUB_OFFLINE"]) == (str(hf), str(hf / "hub"), "1")
    assert not {"HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "PYTHONPATH"} & set(env)


def test_blender_named_without_a_path_is_found_on_path(install, monkeypatch):
    monkeypatch.setenv("PATH", str(Path(install.blender).parent) + os.pathsep + os.environ["PATH"])
    install.blender = "blender"
    assert check(install)["status"] == "ready"


def test_preflight_refuses_another_commit(install, monkeypatch):
    monkeypatch.setattr(runtime, "VIDEO2RIG_REVISION", "0" * 40)
    report = check(install)
    assert report["status"] == "unverified"
    assert any("pinned commit" in reason for reason in report["reasons"])


@pytest.mark.parametrize("change", ["modified", "untracked"])
def test_preflight_refuses_a_changed_checkout(install, change):
    if change == "modified":
        (install.checkout / "video2rig/check.py").write_text("patched = True\n")
    else:
        (install.checkout / "video2rig/extra.py").write_text("")
    reasons = " ".join(check(install)["reasons"])
    assert "modified or untracked" in reasons
    assert f"video2rig/{'check' if change == 'modified' else 'extra'}.py" in reasons  # names what to clean up


def test_preflight_refuses_a_missing_import(tmp_path, monkeypatch):
    stub = stub_install(tmp_path / "v2r", net=False)
    monkeypatch.setattr(runtime, "VIDEO2RIG_REVISION", stub.commit)
    monkeypatch.setattr(runtime, "DINOV2_SHA256", hashlib.sha256(b"dinov2 weights").hexdigest())
    monkeypatch.setenv("V2R_FFMPEG", sys.executable)
    report = runtime.preflight(sys.executable, str(stub.checkout), "local", blender=sys.executable)
    assert report["status"] == "unverified"
    assert any("video2rig.reader.net" in reason for reason in report["reasons"])


def test_preflight_refuses_missing_ffmpeg_and_blender(install, monkeypatch, tmp_path):
    monkeypatch.setenv("V2R_FFMPEG", str(tmp_path / "no-ffmpeg"))
    install.blender = str(tmp_path / "no-blender")
    reasons = " ".join(check(install)["reasons"])
    assert "ffmpeg" in reasons and "Blender" in reasons
    # The training machine renders and encodes nothing (D15 (a)).
    assert "ffmpeg" not in " ".join(check(install, "train")["reasons"])


def test_training_needs_a_cuda_card_with_bfloat16(install, tmp_path, monkeypatch):
    assert "bfloat16" in " ".join(check(install, "train")["reasons"])
    gpu = stub_install(tmp_path / "gpu", cuda=True)
    monkeypatch.setattr(runtime, "VIDEO2RIG_REVISION", gpu.commit)
    report = runtime.preflight(sys.executable, str(gpu.checkout), "train")
    assert report["status"] == "ready", report["reasons"]
    assert report["device"] == "cuda"


@pytest.mark.parametrize("damage", ["ref", "weights"])
def test_preflight_refuses_an_unpinned_or_changed_backbone(install, damage):
    hub = install.checkout.parent / "hf/hub/models--facebook--dinov2-small"
    if damage == "ref":
        (hub / "refs/main").write_text("f" * 40)  # the tool's unpinned load would read another snapshot
    else:
        install.weights.write_bytes(b"other weights")
    report = check(install)
    assert report["status"] == "unverified"
    assert any("facebook/dinov2-small" in reason for reason in report["reasons"])


def test_preflight_reports_missing_settings(tmp_path):
    report = video2rig.preflight({"asset_pipeline": {"tools": {}}}, tmp_path)
    assert report["local"]["status"] == "unavailable"
    assert "providers.video2rig.python" in " ".join(report["local"]["reasons"])


def ready():  # a training machine's reply, for the pins in force (the fixtures swap them)
    return {"status": "ready", "reasons": [], "revision": runtime.VIDEO2RIG_REVISION,
            "dinov2_revision": runtime.DINOV2_REVISION, "dinov2_sha256": runtime.DINOV2_SHA256,
            "torch": "2.7.0+cu128", "transformers": "5.20.1", "device": "cuda"}


def config(stub, **tools):
    return {"asset_pipeline": {"tools": {"video2rig_python": sys.executable,
                                         "video2rig_checkout": str(stub.checkout),
                                         "blender": stub.blender, **tools}}}


def test_training_preflight_runs_the_runtime_on_the_gpu_provider_over_ssh(install, tmp_path, monkeypatch):
    calls = []
    real_run = subprocess.run

    def fake_run(argv, **kwargs):
        if argv[0] != "ssh":
            return real_run(argv, **kwargs)
        calls.append((argv, kwargs))
        # The standard-library runtime is streamed to the provider's own Python, never imported there.
        assert kwargs["input"] == Path(runtime.__file__).read_text()
        return SimpleNamespace(returncode=0, stdout="banner\n" + json.dumps(ready()) + "\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    settings = config(install, video2rig_train_host="gpu-box", video2rig_train_python="/opt/v2r/.venv/bin/python",
                      video2rig_train_checkout="/opt/v2r/video2rig")
    report = video2rig.preflight(settings, tmp_path)
    assert report["local"]["status"] == "ready", report["local"]["reasons"]
    assert report["train"] == {**ready(), "host": "gpu-box"}
    (argv, _), = calls
    assert argv[:4] == ["ssh", "-o", "BatchMode=yes", "gpu-box"]
    assert argv[4].startswith("/opt/v2r/.venv/bin/python - preflight ")
    assert json.loads(argv[4].split(" preflight ", 1)[1].strip("'")) == {
        "python": "/opt/v2r/.venv/bin/python", "checkout": "/opt/v2r/video2rig", "role": "train"}


def test_one_bad_setting_or_reply_never_hides_the_other_machine(install, tmp_path, monkeypatch):
    def train(**tools):
        report = video2rig.preflight(config(install, video2rig_train_host="gpu-box", **tools), tmp_path)
        assert report["local"]["status"] == "ready", report["local"]["reasons"]
        return report["train"]["status"], " ".join(report["train"]["reasons"])
    assert train(video2rig_train_checkout="/opt/v") == ("unavailable", "Set providers.video2rig.train_python")
    status, reason = train(video2rig_train_python="venv/bin/python", video2rig_train_checkout="/opt/v")
    assert status == "unavailable" and "absolute" in reason
    real_run = subprocess.run
    replies = iter(["", "not json\n", json.dumps({**ready(), "revision": "0" * 40}), json.dumps({"status": "fine"})])
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: real_run(argv, **kwargs) if argv[0] != "ssh" else
                        SimpleNamespace(returncode=0, stdout=next(replies), stderr=""))
    for _ in range(4):  # empty, not JSON, "ready" for another commit, an unknown status
        status, reason = train(video2rig_train_python="/opt/v/python", video2rig_train_checkout="/opt/v/video2rig")
        assert status in ("unavailable", "unverified") and "gpu-box" in reason
    monkeypatch.setattr(subprocess, "run", real_run)

    def no_blender(*_):
        raise FileNotFoundError("Blender executable not found")
    monkeypatch.setattr(video2rig, "blender_executable", no_blender)
    report = video2rig.preflight(config(install), tmp_path)
    assert report["local"] == {"status": "unavailable", "reasons": ["Blender executable not found"]}
    assert report["train"]["status"] == "unverified"  # still checked: no CUDA in the stub


def test_identity_records_the_tool_backbone_reader_and_output_rights(install, tmp_path):
    report = check(install)
    record = video2rig.identity(report)
    assert record["name"] == "video2rig" and record["model_id"] == "facebook/dinov2-small"
    assert record["revision"] == {"status": "known", "value": install.commit}
    assert record["weights_sha256"]["status"] == "unavailable"
    assert record["dinov2_revision"]["value"] == runtime.DINOV2_REVISION
    assert record["output_rights"]["status"] == "cleared"
    assert {"terms", "terms_version", "read_on"} <= set(record["output_rights"])
    assert record["environment"] == {"status": "known",
                                     "value": {"torch": "2.7.0", "transformers": "5.20.1", "device": "cpu"}}
    reader = tmp_path / "reader.pt"
    reader.write_bytes(b"reader")
    assert video2rig.identity(report, reader)["weights_sha256"] == {
        "status": "known", "value": hashlib.sha256(b"reader").hexdigest()}
    with pytest.raises(StageFailure, match="not ready"):
        video2rig.identity({"status": "unverified", "reasons": ["x"]})


def test_project_folder_lives_under_the_candidate(tmp_path):
    project = video2rig.project_folder(tmp_path / "candidate_01", {"name": "wolf"})
    assert project == tmp_path / "candidate_01/video2rig"
    assert json.loads((project / "creature.json").read_text()) == {"name": "wolf"}
    assert json.loads((video2rig.project_folder(tmp_path / "other") / "creature.json").read_text()) == {}
    assert video2rig.project_folder(tmp_path / "candidate_01", {"name": "wolf"}) == project
    with pytest.raises(StageFailure, match="creature.json"):  # a stale setting would read every clip wrongly
        video2rig.project_folder(tmp_path / "candidate_01", {"name": "fox"})


def test_commands_are_the_documented_command_lines(install, tmp_path):
    settings, project = config(install), tmp_path / "wolf"
    (project / "reader").mkdir(parents=True)
    (project / "reader/reader.pt").write_bytes(b"reader")
    py, blender, blend, save = sys.executable, install.blender, str(tmp_path / "wolf.blend"), str(tmp_path / "walk.blend")
    script = lambda name: [blender, blend, "--background", "--python-exit-code", "1", "--python",
                           str(install.checkout / "blender" / name), "--"]
    expected = {
        "export_rig": (script("export_rig.py") + ["--out", str(project / "rig")], {"blend": blend}),
        "render_start": (script("render_start.py") + ["--out", str(project / "start")], {"blend": blend}),
        "prepare": ([py, "-m", "video2rig.reader.prepare", str(project), "--blend", blend,
                     "--blender", blender, "--poses", "3000", "--skip-train"], {"blend": blend}),
        "train": ([py, "-m", "video2rig.reader.train", str(project), "--steps", "9000"], {"steps": 9000}),
        "check": ([py, "-m", "video2rig", "check", str(project), "walk"], {"clip": "walk"}),
        "run": ([py, "-m", "video2rig", "run", str(project), "walk", "--cpu"], {"clip": "walk"}),
        "review": ([py, "-m", "video2rig", "review", str(project), "walk"], {"clip": "walk"}),
        "import_motion": (script("import_motion.py") + ["--motion", str(project / "out/walk.npz"),
                                                         "--save", save],
                          {"blend": blend, "clip": "walk", "save": save}),
    }
    for step, (argv, options) in expected.items():
        assert video2rig.command(settings, tmp_path, step, project, **options) == argv, step


def test_run_refuses_the_older_road_without_a_reader(install, tmp_path):
    with pytest.raises(StageFailure, match="reader.pt") as failure:
        video2rig.command(config(install), tmp_path, "run", tmp_path / "wolf", clip="walk")
    assert failure.value.category == "configuration"
    with pytest.raises(ValueError, match="unknown video2rig step"):
        video2rig.command(config(install), tmp_path, "track", tmp_path / "wolf", clip="walk")
    with pytest.raises(ValueError, match="steps"):  # the tool's default trains for 8 minutes: as many steps as
        video2rig.command(config(install), tmp_path, "train", tmp_path / "wolf")  # the card manages
    with pytest.raises(ValueError, match="save"):
        video2rig.command(config(install), tmp_path, "import_motion", tmp_path / "wolf", blend="w.blend", clip="walk")


FAKE_TOOL = """#!{python}
import json, os, sys
from pathlib import Path
with open(os.environ["CALLS"], "a") as stream:
    stream.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "offline": os.environ.get("HF_HUB_OFFLINE"),
                             "hf_home": os.environ.get("HF_HOME")}}) + "\\n")
module, rest = sys.argv[2], sys.argv[3:]
if module == "video2rig.reader.train":
    reader = Path(rest[0]) / "reader"
    reader.mkdir(exist_ok=True)
    (reader / "reader.pt").write_bytes(b"reader")
    (reader / "reader-train.json").write_text(json.dumps({{"held_out": {{"v2r_front": {{"median_px": 3.1}}}}}}))
elif module == "video2rig":
    command, project, clip = rest[:3]
    work = Path(project) / "work" / clip
    work.mkdir(parents=True, exist_ok=True)
    if command == "check":
        if os.environ.get("CRASH_CHECK"):
            sys.exit(1)  # what an uncaught exception or SystemExit("clip not found") gives
        (work / "check.json").write_text(json.dumps({{"verdict": "FAIL", "messages": ["FAIL views differ"]}}))
        sys.exit(1)
    if command == "run":
        (Path(project) / "out").mkdir(exist_ok=True)
        (Path(project) / "out" / (clip + ".npz")).write_bytes(b"npz")
        (work / "report.json").write_text(json.dumps({{"frames": 120}}))
    if command == "review" and os.environ.get("FAIL_REVIEW"):
        print("review broke", file=sys.stderr)
        sys.exit(2)
"""


def test_run_spawns_the_providers_python_in_its_checkout_offline(install, tmp_path, monkeypatch):
    tool = tmp_path / "python"
    tool.write_text(FAKE_TOOL.format(python=sys.executable))
    tool.chmod(0o755)
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setenv("CALLS", str(calls))
    settings = config(install, video2rig_python=str(tool))
    project = video2rig.project_folder(tmp_path / "candidate")
    log = tmp_path / "video2rig.log"
    training = video2rig.run(settings, tmp_path, "train", project, log, steps=1)
    assert training["held_out"]["v2r_front"]["median_px"] == 3.1
    verdict = video2rig.run(settings, tmp_path, "check", project, log, clip="walk")
    assert verdict["verdict"] == "FAIL"  # a FAIL verdict is the check's answer, not a tool failure
    result = video2rig.run(settings, tmp_path, "run", project, log, clip="walk")
    assert result["report"] == {"frames": 120} and result["motion"] == project / "out/walk.npz"
    monkeypatch.setenv("FAIL_REVIEW", "1")
    with pytest.raises(StageFailure, match="review") as failure:
        video2rig.run(settings, tmp_path, "review", project, log, clip="walk")
    assert failure.value.category == "environment"
    seen = [json.loads(line) for line in calls.read_text().splitlines()]
    assert {call["cwd"] for call in seen} == {str(install.checkout.resolve())}
    assert {call["offline"] for call in seen} == {"1"}
    assert {call["hf_home"] for call in seen} == {str(install.checkout.parent.resolve() / "hf")}


@pytest.fixture
def fake_tool(install, tmp_path, monkeypatch):
    tool = tmp_path / "python"
    tool.write_text(FAKE_TOOL.format(python=sys.executable))
    tool.chmod(0o755)
    monkeypatch.setenv("CALLS", str(tmp_path / "calls.jsonl"))
    return config(install, video2rig_python=str(tool))


def test_a_crashed_check_never_returns_an_earlier_verdict(fake_tool, tmp_path, monkeypatch):
    project = video2rig.project_folder(tmp_path / "candidate")
    (project / "work/walk").mkdir(parents=True)
    (project / "work/walk/check.json").write_text('{"verdict": "OK"}')  # the clip's previous take
    monkeypatch.setenv("CRASH_CHECK", "1")
    with pytest.raises(StageFailure, match="check") as failure:
        video2rig.run(fake_tool, tmp_path, "check", project, tmp_path / "log", clip="walk")
    assert failure.value.category == "environment"


def test_relative_paths_never_land_in_the_pinned_checkout(install, fake_tool, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    video2rig.project_folder("candidate")
    video2rig.run(fake_tool, tmp_path, "train", "candidate/video2rig", "log", steps=1)
    assert (tmp_path / "candidate/video2rig/reader/reader.pt").is_file() and (tmp_path / "log").is_file()
    argv = video2rig.command(fake_tool, tmp_path, "import_motion", "candidate/video2rig", blend="wolf.blend",
                             clip="walk", save="walk.blend")
    assert argv[1] == str(tmp_path / "wolf.blend") and argv[-1] == str(tmp_path / "walk.blend")
    assert check(install)["status"] == "ready"  # nothing was written into the checkout


def test_training_is_refused_here_while_a_train_host_is_set(fake_tool, tmp_path):
    fake_tool["asset_pipeline"]["tools"]["video2rig_train_host"] = "gpu-box"
    with pytest.raises(StageFailure, match="gpu-box") as failure:
        video2rig.run(fake_tool, tmp_path, "train", video2rig.project_folder(tmp_path / "c"), tmp_path / "log", steps=1)
    assert failure.value.category == "configuration"


def test_run_reports_a_missing_or_invalid_output(install, tmp_path):
    project = video2rig.project_folder(tmp_path / "candidate")
    (project / "work/walk").mkdir(parents=True)
    (project / "work/walk/check.json").write_text('{"verdict": "MAYBE"}')
    with pytest.raises(StageFailure, match="check.json") as failure:
        video2rig.read_output(project, "check", "walk")
    assert failure.value.category == "processing_validation"
    with pytest.raises(StageFailure, match="report.json"):
        video2rig.read_output(project, "run", "walk")


def _imports_video2rig(tree):
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module or ""]
        elif isinstance(node, ast.Call) and node.args and \
                getattr(node.func, "attr", getattr(node.func, "id", "")) in {"import_module", "__import__", "run_module"}:
            first = node.args[0].values[0] if isinstance(node.args[0], ast.JoinedStr) and node.args[0].values else \
                node.args[0]
            names = [str(first.value)] if isinstance(first, ast.Constant) else []
        if any(name == "video2rig" or name.startswith("video2rig.") for name in names):
            return True
    return False


def test_import_guard_catches_imports_but_not_command_lines():
    assert _imports_video2rig(ast.parse("import video2rig.check"))
    assert _imports_video2rig(ast.parse("from video2rig.reader import net"))
    assert _imports_video2rig(ast.parse("importlib.import_module('video2rig.check')"))
    assert _imports_video2rig(ast.parse("importlib.import_module(f'video2rig.{name}')"))
    assert _imports_video2rig(ast.parse("runpy.run_module('video2rig', run_name='__main__')"))
    assert not _imports_video2rig(ast.parse("argv = ['-m', 'video2rig', 'run']\nPROBE = 'import video2rig.check'"))
    assert not _imports_video2rig(ast.parse("from . import video2rig_runtime"))


def test_slopforge_never_imports_or_vendors_video2rig():
    """video2rig is AGPL-3.0: SlopForge (MIT) runs it as a separate program and exchanges files with it only. This
    catches imports and a copied package folder; a patched checkout is the preflight's to refuse."""
    offenders = [str(path.relative_to(REPO)) for folder in ("slopforge", "processing", "blender", "scripts")
                 for path in sorted((REPO / folder).rglob("*.py"))
                 if _imports_video2rig(ast.parse(path.read_text(), str(path)))]
    assert offenders == []
    vendored = [str(path.relative_to(REPO)) for folder in ("slopforge", "processing", "blender", "scripts")
                for path in (REPO / folder).rglob("video2rig") if path.is_dir()]
    assert vendored == []


def test_doctor_lists_the_provider_with_its_identity_and_output_rights(tmp_path, monkeypatch, capsys):
    from unittest.mock import patch
    import yaml
    from slopforge.doctor import run_doctor
    from slopforge.initializer import init_project
    (tmp_path / "Assets").mkdir()
    init_project(tmp_path)
    doctor_output = lambda: capsys.readouterr().out
    with patch("slopforge.doctor.ComfyUIClient.health", side_effect=OSError("offline")):
        run_doctor(tmp_path)
        assert "video2rig" not in doctor_output()  # not configured, not listed
        project = tmp_path / "ai/project.yaml"
        settings = yaml.safe_load(project.read_text())
        settings["asset_pipeline"]["tools"].update(video2rig_python="/v/.venv/bin/python", video2rig_checkout="/v/c",
                                                   video2rig_train_host="gpu-box")
        project.write_text(yaml.safe_dump(settings))
        ready = {"status": "ready", "reasons": [], "revision": runtime.VIDEO2RIG_REVISION,
                 "dinov2_revision": runtime.DINOV2_REVISION, "dinov2_sha256": runtime.DINOV2_SHA256,
                 "torch": "2.7.0+cu128", "transformers": "5.20.1", "device": "cuda"}
        monkeypatch.setattr(video2rig, "preflight", lambda config, root: {
            "local": {"status": "unverified", "reasons": ["ffmpeg is not on PATH"]}, "train": {**ready, "host": "gpu-box"}})
        assert run_doctor(tmp_path) == 0
    lines = [line for line in doctor_output().splitlines() if "video2rig" in line]
    assert lines[0].startswith("WARN video2rig (this machine) — unverified: ffmpeg is not on PATH")
    assert lines[1].startswith("PASS video2rig training (gpu-box) — ready: commit 55d51b3, facebook/dinov2-small "
                               "ed25f3a, torch 2.7.0+cu128 cuda")
    assert all("output rights: cleared (AGPL-3.0" in line and "read 2026-10-27" in line for line in lines)


@pytest.mark.skipif(os.environ.get("SLOPFORGE_RUN_VIDEO2RIG") != "1", reason="opt-in external runtime")
def test_external_video2rig_preflight():
    from slopforge.config import load_project
    project = os.environ.get("SLOPFORGE_PROJECT_ROOT")
    if not project:
        pytest.skip("blocked: set SLOPFORGE_PROJECT_ROOT to a project with tools.video2rig_* configured")
    report = video2rig.preflight(load_project(project), project)
    for role in ("local", "train"):
        assert report[role]["status"] == "ready", (role, report[role]["reasons"])
    print(json.dumps({"train": report["train"], "identity": video2rig.identity(report["train"])}, indent=2))


def test_render_start_takes_the_creatures_framing_and_render_poses_its_motion(install, tmp_path):
    """#142: the client passes render_start's documented framing options; B2's known motions render through the
    start cameras with the tool's own render_poses.py, one pose per picture, each panel at its own size."""
    settings, project = config(install), tmp_path / "wolf"
    blender, blend = install.blender, str(tmp_path / "wolf.blend")
    script = lambda name: [blender, blend, "--background", "--python-exit-code", "1", "--python",
                           str(install.checkout / "blender" / name), "--"]
    framing = {"views": ["three-quarter", "side"], "widths": [958, 962], "margin": 1.8, "margin_wide": 1.45,
               "side": "left"}
    assert video2rig.command(settings, tmp_path, "render_start", project, blend=blend, framing=framing) == \
        script("render_start.py") + ["--out", str(project / "start"), "--views", "three-quarter,side",
                                     "--widths", "958,962", "--margin", "1.8", "--margin-wide", "1.45", "--side", "left"]
    out, motion = tmp_path / "renders", tmp_path / "poses.npz"
    assert video2rig.command(settings, tmp_path, "render_poses", project, blend=blend, motion=motion, out=out,
                             fit=962) == \
        script("render_poses.py") + ["--poses", str(motion), "--cameras", str(project / "start/cameras.json"),
                                     "--out", str(out), "--copies", "1", "--fit", "962", "--height", "1080",
                                     "--sharp", "--project", str(project)]
    with pytest.raises(ValueError, match="render_poses needs motion, out, fit"):
        video2rig.command(settings, tmp_path, "render_poses", project, blend=blend)


def test_render_start_takes_the_declared_facing(install, tmp_path):
    framing = {"views": ["three-quarter", "side"], "widths": [958, 962], "margin": 1.8, "margin_wide": 1.45,
               "side": "left", "facing": "-Y"}
    argv = video2rig.command(config(install), tmp_path, "render_start", tmp_path / "wolf", blend="w.blend",
                             framing=framing)
    assert argv[-1] == "--facing=-Y"     # "--facing -Y" reads -Y as an option to argparse
