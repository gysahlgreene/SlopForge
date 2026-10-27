"""video2rig as a local_tool provider: its command line only (docs/CREATURES.md, video2rig).

video2rig (github.com/canitcode/video2rig, AGPL-3.0) reads a creature's motion from a two-view video with a
per-creature joint reader on DINOv2-small and fits it to the rig. SlopForge (MIT) runs it as a separate program from
its own checkout and venv and exchanges files with it: it never imports, vendors or patches it
(tests/test_video2rig_provider.py guards against imports, the preflight against a modified checkout). Blender renders, reading and fitting run on the SlopForge machine;
readers train on the configured GPU provider (providers.video2rig.train_host), or here when none is set.
"""
import json
import os
import shlex
import subprocess
from pathlib import Path

from ..failures import StageFailure
from ..paths import blender_executable
from ..provenance import file_sha256, provenance_fact
from . import video2rig_runtime as runtime

# Read on 2026-10-27 at the pinned commit: the AGPL covers the tool, not its outputs, and the author's README says
# "The animations you make with it are yours" and "Use it for anything, commercial games included".
OUTPUT_RIGHTS = {"status": "cleared", "terms": "AGPL-3.0 (the tool) and the author's README statement on outputs",
                 "terms_version": f"video2rig commit {runtime.VIDEO2RIG_REVISION[:7]}", "read_on": "2026-10-27"}
# What each step needs; train needs a step count because the tool's default, 8 minutes, depends on the card's speed.
STEPS = {"export_rig": ("blend",), "render_start": ("blend",), "prepare": ("blend",), "train": ("steps",),
         "check": ("clip",), "run": ("clip",), "review": ("clip",), "import_motion": ("blend", "clip", "save"),
         "render_poses": ("blend", "motion", "out", "fit")}


KEYS = ("python", "checkout", "train_host", "train_python", "train_checkout")


def settings(config):
    """The provider's settings: providers.video2rig, else the tools.video2rig_* keys it was first configured with."""
    pipeline = config.get("asset_pipeline", {})
    block = (pipeline.get("providers") or {}).get("video2rig")
    tools = pipeline.get("tools") or {}
    return {key: (block.get(key) if isinstance(block, dict) else None) or tools.get(f"video2rig_{key}")
            for key in KEYS}


def _local(config, project_root):
    values = settings(config)
    # abspath, not resolve: a venv's python is a symlink, and the interpreter it points at has no venv
    return [Path(os.path.abspath(Path(project_root) / Path(values[key]).expanduser())) if values[key] else None
            for key in ("python", "checkout")]


def configured(config):
    return any(settings(config).values())


def _unavailable(reason):
    return {"status": "unavailable", "reasons": [reason]}


def _remote_preflight(tools, host):
    unset = [f"providers.video2rig.{key}" for key in ("train_python", "train_checkout") if not tools.get(key)]
    if unset:
        return _unavailable("Set " + " and ".join(unset))
    payload = {"python": tools["train_python"], "checkout": tools["train_checkout"], "role": "train"}
    if not all(str(payload[key]).startswith("/") for key in ("python", "checkout")):
        return _unavailable("providers.video2rig.train_python and .train_checkout must be absolute paths on "
                            "its train_host")
    completed = subprocess.run(["ssh", "-o", "BatchMode=yes", host,
                                shlex.join([payload["python"], "-", "preflight", json.dumps(payload)])],
                               input=Path(runtime.__file__).read_text(), capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return _unavailable(f"preflight on {host} failed: "
                            + (completed.stderr.strip().splitlines() or ["no output"])[-1])
    try:
        reply = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return _unavailable(f"preflight on {host} gave no readable reply")
    if not isinstance(reply, dict) or reply.get("status") not in ("ready", "unverified", "unavailable"):
        return _unavailable(f"preflight on {host} replied {str(reply)[:200]}")
    pins = (runtime.VIDEO2RIG_REVISION, runtime.DINOV2_REVISION, runtime.DINOV2_SHA256)
    if reply["status"] == "ready" and tuple(reply.get(key) for key in (
            "revision", "dinov2_revision", "dinov2_sha256")) != pins:
        return {"status": "unverified", "reasons": [f"{host} reports ready for other pins than this SlopForge's; run "
                                                    "scripts/install-video2rig.sh there again"]}
    return reply


def preflight(config, project_root):
    """Both machines' installs: "local" (the SlopForge machine) and "train" (the GPU provider, over SSH when
    providers.video2rig.train_host is set, else this machine). A bad setting or reply rejects its machine only."""
    tools = settings(config)
    python, checkout = _local(config, project_root)

    def checked(check):
        try:
            return check()
        except Exception as exc:  # a preflight reports; doctor must still list the other machine
            return _unavailable(str(exc))
    if not python or not checkout:
        unset = [f"providers.video2rig.{key}" for key in ("python", "checkout") if not tools.get(key)]
        local = _unavailable("Set " + " and ".join(unset) + " (scripts/install-video2rig.sh prints them)")
    else:
        local = checked(lambda: runtime.preflight(python, checkout, "local", blender_executable(config, project_root)))
    host = tools.get("train_host")
    if host:
        return {"local": local, "train": {**checked(lambda: _remote_preflight(tools, host)), "host": host}}
    train = checked(lambda: runtime.preflight(python, checkout, "train")) if python and checkout else dict(local)
    return {"local": local, "train": train}


def identity(report, reader=None):
    """The provider record a stage copies into provenance: the tool, the backbone, the creature's reader."""
    if report.get("status") != "ready":
        raise StageFailure("configuration", "video2rig is not ready: " + "; ".join(report.get("reasons", [])),
                           operation="video2rig preflight", remedy="Run slopforge doctor and fix what it reports")
    return {"name": "video2rig", "model_id": runtime.DINOV2_MODEL,
            "revision": provenance_fact("known", value=report["revision"]),
            "weights_sha256": provenance_fact("known", value=file_sha256(reader)) if reader else
            provenance_fact("unavailable", reason="no joint reader trained for this creature yet"),
            "dinov2_revision": provenance_fact("known", value=report["dinov2_revision"]),
            "dinov2_sha256": provenance_fact("known", value=report["dinov2_sha256"]),
            "environment": provenance_fact("known", value={key: report[key] for key in ("torch", "transformers",
                                                                                          "device")}),
            "output_rights": dict(OUTPUT_RIGHTS)}


def project_folder(candidate_dir, settings=None):
    """A creature's video2rig project (rig/, start/, reader/, clips/, work/, out/) under its candidate directory."""
    project = Path(candidate_dir) / "video2rig"
    project.mkdir(parents=True, exist_ok=True)
    path = project / "creature.json"
    if not path.is_file():
        path.write_text(json.dumps(settings or {}, indent=2) + "\n")
    elif settings is not None and json.loads(path.read_text()) != settings:
        raise StageFailure("configuration", f"{path} holds other settings than this run's",
                           operation="video2rig project", remedy="Use a new candidate directory for new settings")
    return project


def command(config, project_root, step, project, *, blend=None, clip=None, save=None, poses=3000, steps=None,
            framing=None, motion=None, out=None, fit=None):
    """The command line of one step as video2rig's README documents it ("The whole thing in six steps"). Its older
    road (the BootsTAPIR point tracker: `run` without a reader, `--old`, `track`, `solve`) is never built. Paths are
    made absolute: the tool runs in its checkout, and a relative one would land there. `framing` is render_start's
    documented view pair and framing (slopforge.creature_views.framing); render_poses renders a known motion
    (`motion`, a poses.npz) through the start cameras into `out`, each panel at `fit` pixels, one pose a picture."""
    if step not in STEPS:
        raise ValueError(f"unknown video2rig step {step!r}; expected one of {', '.join(STEPS)}")
    missing = [name for name in STEPS[step] if not {"blend": blend, "clip": clip, "save": save, "steps": steps,
                                                    "motion": motion, "out": out, "fit": fit}[name]]
    if missing:
        raise ValueError(f"video2rig {step} needs {', '.join(missing)}")
    python, checkout = _local(config, project_root)
    blender, project = blender_executable(config, project_root), Path(project).resolve()
    blend, save = (Path(path).resolve() if path else None for path in (blend, save))
    tool = [str(python), "-m", "video2rig"]
    # --python-exit-code: a failing video2rig Blender script fails the step instead of exiting 0
    script = lambda name: [blender, str(blend), "--background", "--python-exit-code", "1", "--python",
                           str(checkout / "blender" / name), "--"]
    if step == "export_rig":
        return script("export_rig.py") + ["--out", str(project / "rig")]
    if step == "render_start":
        return script("render_start.py") + ["--out", str(project / "start")] + ([
            "--views", ",".join(framing["views"]), "--widths", ",".join(map(str, framing["widths"])),
            "--margin", str(framing["margin"]), "--margin-wide", str(framing["margin_wide"]),
            "--side", framing["side"]] + (["--facing", framing["facing"]] if framing.get("facing") else [])
            if framing else [])
    if step == "render_poses":
        return script("render_poses.py") + [
            "--poses", str(Path(motion).resolve()), "--cameras", str(project / "start/cameras.json"),
            "--out", str(Path(out).resolve()), "--copies", "1", "--fit", str(fit), "--height", "1080", "--sharp",
            "--project", str(project)]
    if step == "prepare":  # D15 (a): the training pictures render here; training is the "train" step
        return tool[:2] + ["video2rig.reader.prepare", str(project), "--blend", str(blend), "--blender", blender,
                           "--poses", str(poses), "--skip-train"]
    if step == "train":
        return tool[:2] + ["video2rig.reader.train", str(project), "--steps", str(steps)]
    if step == "run" and not (project / "reader/reader.pt").is_file():
        raise StageFailure("configuration", f"{project / 'reader/reader.pt'} is missing: without a joint reader "
                           "video2rig takes its older road (a point tracker), which SlopForge does not use",
                           operation="video2rig run", remedy="Train the creature's reader first (prepare, then train)")
    if step in ("check", "run", "review"):
        return tool + [step, str(project), clip] + (["--cpu"] if step == "run" else [])
    return script("import_motion.py") + ["--motion", str(project / "out" / f"{clip}.npz"), "--save", str(save)]


_OUTPUTS = {"train": "reader/reader-train.json", "check": "work/{clip}/check.json", "run": "work/{clip}/report.json"}


def read_output(project, step, clip=None):
    path = Path(project) / _OUTPUTS[step].format(clip=clip)
    try:
        result = json.loads(path.read_text())
        if step == "check" and result.get("verdict") not in ("OK", "WARN", "FAIL"):
            raise ValueError("no OK/WARN/FAIL verdict")
    except (OSError, ValueError, AttributeError) as exc:
        raise StageFailure("processing_validation", f"video2rig {step} left no readable {path.name}: {exc}",
                           operation=f"video2rig {step}", remedy="Read the step's log beside it") from exc
    return result


def run(config, project_root, step, project, log, **options):
    """Run one step with the provider's Python in its checkout, offline against the pinned backbone, and return
    what it wrote: reader-train.json (train), check.json (check: a FAIL verdict is an answer, not an error),
    {"report", "motion"} (run), else None."""
    host = settings(config)["train_host"]
    if step == "train" and host:
        raise StageFailure("configuration", f"readers train on {host} (providers.video2rig.train_host), and sending a "
                           "project there is not built yet (plan package B3)", operation="video2rig train",
                           remedy="Unset providers.video2rig.train_host to train on this machine's CUDA card")
    project = Path(project).resolve()
    argv = command(config, project_root, step, project, **options)
    _, checkout = _local(config, project_root)
    output = project / _OUTPUTS[step].format(clip=options.get("clip")) if step in _OUTPUTS else None
    if output:
        output.unlink(missing_ok=True)  # a crashed step must not leave an earlier take's answer to read
    with open(log, "a") as stream:
        stream.write("$ " + shlex.join(argv) + "\n")
        stream.flush()
        completed = subprocess.run(argv, cwd=checkout, env=runtime.environment(checkout), stdout=stream,
                                   stderr=subprocess.STDOUT, check=False)
    # check exits 1 on a FAIL verdict, as it does on a crash; only a fresh check.json makes it an answer
    if completed.returncode != 0 and not (step == "check" and completed.returncode == 1 and output.is_file()):
        raise StageFailure("environment", f"video2rig {step} exited with code {completed.returncode}",
                           operation=f"video2rig {step}", remedy=f"Read {log}", evidence={"log": str(log)})
    if step == "run":
        return {"report": read_output(project, "run", options["clip"]),
                "motion": project / "out" / f"{options['clip']}.npz"}
    return read_output(project, step, options.get("clip")) if step in _OUTPUTS else None
