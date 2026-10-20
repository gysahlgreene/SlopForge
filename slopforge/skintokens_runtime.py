"""Audited SkinTokens runtime checks and launcher, shared by local and remote (SSH) execution.

Standard library only: for a remote host this file is streamed to the configured SkinTokens Python
(`ssh host <python> - <action> <json>`), so the same preflight, setup and seeded launch run there.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SKINTOKENS_REVISION = "273b691d35989d71cd17ff2895fdc735097b92d1"
SKINTOKENS_DEMO_SHA256 = "8e6d058225c39caad0fccf7c4d6942f8e7e32e3f57c5b14cdc60cf2d6cb5d316"
SKINTOKENS_TOKENRIG_SHA256 = "bf27b72201c5fb23028a9f8a8e63b568462abfa2b4e4b15e50529cdbfc15a222"
SKINTOKENS_PATCH_SHA256 = "e9bb33fd067461aa3f12621bfa32d66a8fc6489e6bfafbd4a2866bef9c29f796"
_SKINTOKENS_VAE = "experiments/skin_vae_2_10_32768/last.ckpt"
_SKINTOKENS_QWEN = "models/Qwen3-0.6B/config.json"
_ATTENTION_BEFORE = b'attn_implementation="flash_attention_2"'
_ATTENTION_AFTER = b'attn_implementation="sdpa"'
# use_postprocess masks predicted weights by voxel reachability from each joint; without it, sampled
# decoding sometimes weights a patch of trouser leg to a fingertip, which tears in animation.
SKINTOKENS_SETTINGS = {"top_k": 5, "top_p": 0.95, "temperature": 1.0,
                       "repetition_penalty": 2.0, "num_beams": 10, "use_transfer": True,
                       "use_postprocess": True}
_SKINTOKENS_LAUNCHER = """
import json, random, runpy, sys
with open(sys.argv[1]) as stream:
    request = json.load(stream)
seed = request['seed']
random.seed(seed)
import numpy as np
np.random.seed(seed % (2**32))
import torch
torch.manual_seed(seed)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(seed)
sys.argv = ['demo.py', '--input', request['source'], '--output', request['output'],
            '--model_ckpt', request['checkpoint']]
for key, value in request['settings'].items():
    if value is True:
        sys.argv.append('--' + key)
    else:
        sys.argv.extend(('--' + key, str(value)))
runpy.run_path('demo.py', run_name='__main__')
with open(request['result'], 'w') as stream:
    json.dump({'status': 'complete'}, stream)
"""


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def revision(checkout):
    result = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def checkout_changes(checkout, checkpoint, source_hash):
    result = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain=v1", "-z",
                             "--untracked-files=all"], capture_output=True, check=False)
    if result.returncode != 0:
        return True
    allowed_untracked = {_SKINTOKENS_VAE, _SKINTOKENS_QWEN}
    if checkpoint.is_relative_to(checkout):
        allowed_untracked.add(checkpoint.relative_to(checkout).as_posix())
    for item in result.stdout.split(b"\0"):
        if not item:
            continue
        entry = item.decode("utf-8", "surrogateescape")
        status, name = entry[:2], entry[3:]
        if status == " M" and name == "src/model/tokenrig.py" and source_hash == SKINTOKENS_PATCH_SHA256:
            continue
        if status == "??" and (name in allowed_untracked or
                               name.startswith("models/Qwen3-0.6B/") and
                               Path(name).suffix in {".json", ".txt", ".md"}):
            continue
        return True
    return False


def preflight(python, checkout, checkpoint):
    """Inspect a configured runtime without importing or changing upstream code."""
    reasons = []
    for key, path in zip(("skintokens_python", "skintokens_checkout", "skintokens_checkpoint"),
                         (python, checkout, checkpoint)):
        if path is None:
            reasons.append(f"Set tools.{key}")
    if reasons:
        return {"status": "unavailable", "reasons": reasons}
    python, checkout, checkpoint = Path(python), Path(checkout), Path(checkpoint)
    if not python.is_file() or not os.access(python, os.X_OK):
        reasons.append("skintokens_python must be an executable file")
    if not checkout.is_dir() or not (checkout / ".git").exists():
        reasons.append("skintokens_checkout must be a Git checkout")
    if reasons:
        return {"status": "unavailable", "reasons": reasons}
    if revision(checkout) != SKINTOKENS_REVISION:
        reasons.append("skintokens_checkout revision differs from audited revision")
    demo = checkout / "demo.py"
    if not demo.is_file() or sha256(demo) != SKINTOKENS_DEMO_SHA256:
        reasons.append("skintokens_checkout demo.py differs from audited source")
    source = checkout / "src/model/tokenrig.py"
    source_hash = sha256(source) if source.is_file() else None
    if source_hash not in (SKINTOKENS_TOKENRIG_SHA256, SKINTOKENS_PATCH_SHA256):
        reasons.append("skintokens_checkout TokenRig source differs from audited source")
    vae = checkout / _SKINTOKENS_VAE
    if not vae.is_file() or vae.stat().st_size == 0:
        reasons.append("SkinTokens FSQ-CVAE checkpoint is missing or empty")
    qwen = checkout / _SKINTOKENS_QWEN
    try:
        qwen_config = json.loads(qwen.read_text())
        if qwen_config.get("model_type") != "qwen3":
            raise ValueError("unexpected model type")
    except (OSError, ValueError, AttributeError):
        reasons.append("SkinTokens Qwen3-0.6B local config is missing or invalid")
    if not checkpoint.is_file() or checkpoint.stat().st_size == 0:
        reasons.append("skintokens_checkpoint is missing or empty")
    if checkout_changes(checkout, checkpoint, source_hash):
        reasons.append("skintokens_checkout has unexpected modified or untracked files")
    if reasons:
        return {"status": "unverified", "reasons": reasons}
    if source_hash == SKINTOKENS_TOKENRIG_SHA256:
        return {"status": "setup_required", "reasons": ["Run character provider-setup skintokens"]}
    return {"status": "ready", "reasons": [], "revision": SKINTOKENS_REVISION,
            "checkpoint_sha256": sha256(checkpoint), "checkpoint_id": checkpoint.name,
            "compatibility_sha256": SKINTOKENS_PATCH_SHA256}


def prepare(checkout):
    """Apply the audited SDPA edit only on explicit setup invocation."""
    checkout = Path(checkout) if checkout else None
    if checkout is None or not (checkout / ".git").exists() or revision(checkout) != SKINTOKENS_REVISION:
        raise ValueError("SkinTokens checkout revision is not the audited revision")
    demo = checkout / "demo.py"
    if not demo.is_file() or sha256(demo) != SKINTOKENS_DEMO_SHA256:
        raise ValueError("SkinTokens demo source differs from audited source")
    source = checkout / "src/model/tokenrig.py"
    if not source.is_file():
        raise ValueError("SkinTokens TokenRig source is missing")
    current = source.read_bytes()
    digest = hashlib.sha256(current).hexdigest()
    if digest == SKINTOKENS_PATCH_SHA256:
        return {"status": "prepared", "revision": SKINTOKENS_REVISION, "compatibility_sha256": digest}
    if digest != SKINTOKENS_TOKENRIG_SHA256 or current.count(_ATTENTION_BEFORE) != 1:
        raise ValueError("SkinTokens TokenRig source differs from audited source")
    patched = current.replace(_ATTENTION_BEFORE, _ATTENTION_AFTER)
    patched_hash = hashlib.sha256(patched).hexdigest()
    if patched_hash != SKINTOKENS_PATCH_SHA256:
        raise ValueError("SkinTokens compatibility patch digest mismatch")
    source.write_bytes(patched)
    return {"status": "prepared", "revision": SKINTOKENS_REVISION, "compatibility_sha256": patched_hash}


def launch(python, checkout, checkpoint, source, output, seed, log):
    """Run seeded SkinTokens inference; returns True when the launcher reported completion."""
    work = Path(output).parent
    request, result = work / f".{Path(output).stem}.request.json", work / f".{Path(output).stem}.result.json"
    request.write_text(json.dumps({"source": str(source), "output": str(output), "checkpoint": str(checkpoint),
                                   "seed": seed, "settings": SKINTOKENS_SETTINGS, "result": str(result)}))
    # Offline run; demo.py posts to a local Blender helper over HTTP, which a host proxy intercepts.
    env = {key: value for key, value in os.environ.items()
           if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
    env.update({"PYTHONHASHSEED": str(seed), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                "HF_DATASETS_OFFLINE": "1"})
    try:
        with open(log, "w") as stream:
            completed = subprocess.run([str(python), "-c", _SKINTOKENS_LAUNCHER, str(request)],
                                       cwd=Path(checkout), env=env, stdout=stream, stderr=subprocess.STDOUT,
                                       check=False)
        if completed.returncode != 0 or not result.is_file():
            return False
        try:
            return json.loads(result.read_text()) == {"status": "complete"}
        except (ValueError, OSError):
            return False
    finally:
        for path in (request, result):
            if path.exists():
                path.unlink()


def main():
    action, payload = sys.argv[1], json.loads(sys.argv[2])
    if action == "preflight":
        result = preflight(payload.get("python"), payload.get("checkout"), payload.get("checkpoint"))
    elif action == "prepare":
        result = prepare(payload.get("checkout"))
    elif action == "launch":
        result = {"complete": launch(payload["python"], payload["checkout"], payload["checkpoint"],
                                     payload["source"], payload["output"], payload["seed"], payload["log"])}
    else:
        raise SystemExit(f"unknown action {action!r}")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
