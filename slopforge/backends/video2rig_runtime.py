"""Preflight of a video2rig install (docs/CREATURES.md), shared by the SlopForge machine and the GPU provider (SSH).

Standard library only: for a remote provider this file is streamed to video2rig's own Python
(`ssh host <python> - preflight <json>`), as skintokens_runtime is. It never imports video2rig (AGPL-3.0); it runs
the tool's Python on a short probe. The install is scripts/install-video2rig.sh's layout: <dir>/video2rig (the
checkout), <dir>/.venv, <dir>/hf (the pinned DINOv2-small snapshot the tool reads with HF_HUB_OFFLINE=1).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO2RIG_REVISION = "55d51b3b9685125a8ea27841d6af9523f6352aa1"  # its first and only commit, 2026-10-23
DINOV2_MODEL = "facebook/dinov2-small"
DINOV2_REVISION = "ed25f3a31f01632728cabb09d1542f84ab7b0056"
DINOV2_SHA256 = "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1"  # model.safetensors
IMPORTS = ("video2rig.check", "video2rig.creature", "video2rig.reader.net", "video2rig.reader.train")
_PROBE = """
import importlib, json, sys
for name in sys.argv[1:]:
    try:
        importlib.import_module(name)
    except Exception as exc:
        sys.exit(f"{name}: {type(exc).__name__}: {exc}")
import torch, transformers
transformers.Dinov2Model.from_pretrained("facebook/dinov2-small")
cuda = bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported())
print(json.dumps({"torch": torch.__version__, "transformers": transformers.__version__,
                  "device": "cuda" if cuda else "cpu"}))
"""


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hf_home(checkout):
    return Path(checkout).resolve().parent / "hf"


# HF_HUB_CACHE and the older cache variables outrank HF_HOME in huggingface_hub, and PYTHONPATH can put another
# torch or transformers ahead of the venv's: none of the user's may reach the tool (PR #131 review).
_INHERITED = ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "PYTHONPATH")


def environment(checkout):
    """The tool's environment: its unpinned backbone load resolves to the pinned snapshot, never to the network."""
    hf = hf_home(checkout)
    return {**{key: value for key, value in os.environ.items() if key not in _INHERITED},
            "HF_HOME": str(hf), "HF_HUB_CACHE": str(hf / "hub"), "HF_HUB_OFFLINE": "1"}


def _git(checkout, *args):
    result = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else None


def preflight(python, checkout, role, blender=None):
    """Inspect an install without changing it. role "local": the SlopForge machine (Blender renders, ffmpeg films,
    reading and fitting on the CPU); "train": the machine that trains readers (a CUDA card with bfloat16)."""
    if not python or not checkout:
        return {"status": "unavailable", "reasons": ["Set the video2rig python and checkout (scripts/install-video2rig.sh "
                                                     "prints them)"]}
    python, checkout = Path(python), Path(checkout)
    if not python.is_file() or not os.access(python, os.X_OK):
        return {"status": "unavailable", "reasons": [f"{python} is not an executable Python"]}
    if not (checkout / ".git").exists():
        return {"status": "unavailable", "reasons": [f"{checkout} is not a video2rig Git checkout"]}
    reasons = []
    if (_git(checkout, "rev-parse", "HEAD") or "").strip() != VIDEO2RIG_REVISION:
        reasons.append(f"the checkout is not at the pinned commit {VIDEO2RIG_REVISION[:7]}; run "
                       "scripts/install-video2rig.sh again")
    changes = _git(checkout, "status", "--porcelain", "--untracked-files=all")
    if changes is None:
        reasons.append("git status failed in the checkout")
    elif changes:
        paths = [line[3:] for line in changes.splitlines()]
        reasons.append(f"the checkout has modified or untracked files ({', '.join(paths[:5])}"
                       f"{', ...' if len(paths) > 5 else ''}); video2rig runs unmodified (a fix goes upstream)")
    hub = hf_home(checkout) / "hub/models--facebook--dinov2-small"
    weights = hub / "snapshots" / DINOV2_REVISION / "model.safetensors"
    ref = hub / "refs/main"
    if not ref.is_file() or ref.read_text().strip() != DINOV2_REVISION or not weights.is_file() or \
            sha256(weights) != DINOV2_SHA256:
        reasons.append(f"{DINOV2_MODEL} is not the pinned snapshot {DINOV2_REVISION[:7]} under {hf_home(checkout)}; "
                       "run scripts/install-video2rig.sh again")
    if role == "local":
        ffmpeg = os.environ.get("V2R_FFMPEG")
        if not (Path(ffmpeg).is_file() if ffmpeg else shutil.which("ffmpeg")):
            reasons.append("ffmpeg is not on PATH (or V2R_FFMPEG is not a file); the review film needs it")
        if not blender or not (Path(blender).is_file() or shutil.which(blender)):
            reasons.append("Blender was not found; set tools.blender or BLENDER_BIN")
    probe = subprocess.run([str(python), "-c", _PROBE, *IMPORTS], cwd=checkout, env=environment(checkout),
                           capture_output=True, text=True, check=False)
    facts = {}
    if probe.returncode != 0:
        reasons.append("video2rig's environment does not load: "
                       + (probe.stderr.strip().splitlines() or ["no output"])[-1])
    else:
        facts = json.loads(probe.stdout.strip().splitlines()[-1])
        if role == "train" and facts["device"] != "cuda":
            reasons.append("no CUDA card with bfloat16: video2rig trains readers in bfloat16 on an NVIDIA card")
    if reasons:
        return {"status": "unverified", "reasons": reasons}
    return {"status": "ready", "reasons": [], "revision": VIDEO2RIG_REVISION, "dinov2_revision": DINOV2_REVISION,
            "dinov2_sha256": DINOV2_SHA256, **facts}


def main():
    action, payload = sys.argv[1], json.loads(sys.argv[2])
    if action != "preflight":
        raise SystemExit(f"unknown action {action!r}")
    print(json.dumps(preflight(payload.get("python"), payload.get("checkout"), payload["role"],
                               payload.get("blender"))))


if __name__ == "__main__":
    main()
