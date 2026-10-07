"""Validate and record outputs from an external character-rigging provider."""
import json
import hashlib
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from .manifest import register_artifact
from .paths import blender_executable, tool_root
from .character_readiness import readiness_allows_rigging
from .validation import validate_image

SKINTOKENS_REVISION = "273b691d35989d71cd17ff2895fdc735097b92d1"
SKINTOKENS_DEMO_SHA256 = "8e6d058225c39caad0fccf7c4d6942f8e7e32e3f57c5b14cdc60cf2d6cb5d316"
SKINTOKENS_TOKENRIG_SHA256 = "bf27b72201c5fb23028a9f8a8e63b568462abfa2b4e4b15e50529cdbfc15a222"
SKINTOKENS_PATCH_SHA256 = "e9bb33fd067461aa3f12621bfa32d66a8fc6489e6bfafbd4a2866bef9c29f796"
_SKINTOKENS_VAE = "experiments/skin_vae_2_10_32768/last.ckpt"
_SKINTOKENS_QWEN = "models/Qwen3-0.6B/config.json"
_ATTENTION_BEFORE = b'attn_implementation="flash_attention_2"'
_ATTENTION_AFTER = b'attn_implementation="sdpa"'
_SKINTOKENS_SETTINGS = {"top_k": 5, "top_p": 0.95, "temperature": 1.0,
                        "repetition_penalty": 2.0, "num_beams": 10, "use_transfer": True}
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


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skintokens_paths(config, project_root):
    tools = config.get("asset_pipeline", {}).get("tools", {})
    root = Path(project_root).resolve()
    def path(key):
        value = tools.get(key)
        if not isinstance(value, str) or not value:
            return None
        value = Path(value).expanduser()
        return (root / value).resolve()
    return tuple(path(key) for key in ("skintokens_python", "skintokens_checkout", "skintokens_checkpoint"))


def _skintokens_revision(checkout):
    result = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _skintokens_checkout_changes(checkout, checkpoint, source_hash):
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


def skintokens_preflight(config, project_root):
    """Inspect configured runtime without importing or changing upstream code."""
    python, checkout, checkpoint = _skintokens_paths(config, project_root)
    reasons = []
    for key, path in zip(("skintokens_python", "skintokens_checkout", "skintokens_checkpoint"),
                         (python, checkout, checkpoint)):
        if path is None:
            reasons.append(f"Set tools.{key}")
    if reasons:
        return {"status": "unavailable", "reasons": reasons}
    if not python.is_file() or not os.access(python, os.X_OK):
        reasons.append("skintokens_python must be an executable file")
    if not checkout.is_dir() or not (checkout / ".git").exists():
        reasons.append("skintokens_checkout must be a Git checkout")
    if reasons:
        return {"status": "unavailable", "reasons": reasons}
    if _skintokens_revision(checkout) != SKINTOKENS_REVISION:
        reasons.append("skintokens_checkout revision differs from audited revision")
    demo = checkout / "demo.py"
    if not demo.is_file() or _sha256(demo) != SKINTOKENS_DEMO_SHA256:
        reasons.append("skintokens_checkout demo.py differs from audited source")
    source = checkout / "src/model/tokenrig.py"
    source_hash = _sha256(source) if source.is_file() else None
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
    if _skintokens_checkout_changes(checkout, checkpoint, source_hash):
        reasons.append("skintokens_checkout has unexpected modified or untracked files")
    if reasons:
        return {"status": "unverified", "reasons": reasons}
    if source_hash == SKINTOKENS_TOKENRIG_SHA256:
        return {"status": "setup_required", "reasons": ["Run character provider-setup skintokens"]}
    return {"status": "ready", "reasons": [], "revision": SKINTOKENS_REVISION,
            "checkpoint_sha256": _sha256(checkpoint), "checkpoint_id": checkpoint.name,
            "compatibility_sha256": SKINTOKENS_PATCH_SHA256}


def prepare_skintokens_runtime(config, project_root):
    """Apply the audited SDPA edit only on explicit setup invocation."""
    _, checkout, _ = _skintokens_paths(config, project_root)
    if checkout is None or not (checkout / ".git").exists() or _skintokens_revision(checkout) != SKINTOKENS_REVISION:
        raise ValueError("SkinTokens checkout revision is not the audited revision")
    demo = checkout / "demo.py"
    if not demo.is_file() or _sha256(demo) != SKINTOKENS_DEMO_SHA256:
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


def run_skintokens_inference(config, source_model, output_model, *, seed):
    """Run raw SkinTokens inference; postprocessing is a separate pipeline task."""
    output = Path(output_model).resolve()
    root = config.get("_project_root", output.parent)
    report = skintokens_preflight(config, root)
    if report["status"] != "ready":
        raise ValueError("SkinTokens preflight: " + "; ".join(report["reasons"]))
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("SkinTokens seed must be a nonnegative integer")
    source = Path(source_model).resolve()
    if not source.is_file() or source.suffix.lower() not in (".obj", ".fbx", ".glb"):
        raise ValueError("SkinTokens source must be an existing OBJ, FBX, or GLB")
    if output.suffix.lower() != ".glb":
        raise ValueError("SkinTokens output must be GLB")
    if output.exists():
        raise ValueError("SkinTokens output already exists")
    python, checkout, checkpoint = _skintokens_paths(config, root)
    output.parent.mkdir(parents=True, exist_ok=True)
    log = Path(root).resolve() / "ai/logs/skintokens" / (output.stem + ".log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="slopforge-skintokens-") as directory:
        request = Path(directory) / "request.json"
        result = Path(directory) / "result.json"
        request.write_text(json.dumps({"source": str(source), "output": str(output),
                                       "checkpoint": str(checkpoint), "seed": seed,
                                       "settings": _SKINTOKENS_SETTINGS, "result": str(result)}))
        env = {**os.environ, "PYTHONHASHSEED": str(seed), "HF_HUB_OFFLINE": "1",
               "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"}
        with log.open("w") as stream:
            completed = subprocess.run([str(python), "-c", _SKINTOKENS_LAUNCHER, str(request)],
                                       cwd=checkout, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                       check=False)
        if completed.returncode != 0 or not result.is_file():
            raise RuntimeError("SkinTokens inference failed; inspect the project log")
        try:
            if json.loads(result.read_text()) != {"status": "complete"}:
                raise ValueError("invalid result")
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("SkinTokens returned a malformed result") from exc
    if not output.is_file() or output.stat().st_size < 20:
        raise RuntimeError("SkinTokens output is missing or empty")
    try:
        with output.open("rb") as stream:
            header = stream.read(12)
            size = output.stat().st_size
            if (header[:4] != b"glTF" or int.from_bytes(header[4:8], "little") != 2
                    or int.from_bytes(header[8:12], "little") != size):
                raise ValueError("header")
            position = 12
            for expected_type in (b"JSON", b"BIN\0"):
                if position == size and expected_type == b"BIN\0":
                    break
                chunk = stream.read(8)
                if len(chunk) != 8 or chunk[4:] != expected_type:
                    raise ValueError("chunk")
                length = int.from_bytes(chunk[:4], "little")
                position += 8 + length
                if length % 4 or position > size:
                    raise ValueError("chunk length")
                if expected_type == b"JSON":
                    model = json.loads(stream.read(length))
                    if not isinstance(model, dict) or model.get("asset", {}).get("version") != "2.0":
                        raise ValueError("GLB asset")
                else:
                    stream.seek(length, 1)
            if position != size:
                raise ValueError("trailing data")
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
        raise RuntimeError("SkinTokens output is malformed GLB") from exc
    return {"status": "complete", "output_sha256": _sha256(output), "revision": report["revision"],
            "checkpoint_id": report["checkpoint_id"], "checkpoint_sha256": report["checkpoint_sha256"],
            "compatibility_sha256": report["compatibility_sha256"], "seed": seed,
            "settings": dict(_SKINTOKENS_SETTINGS)}


RECOMMENDED_POSES = ("t_pose", "raised_arms", "crouch", "leg_lift", "elbow_bend", "shoulder_rotation")
SKINTOKENS_POSES = ("neutral",) + RECOMMENDED_POSES
_POSE_ID = re.compile(r"[a-z][a-z0-9_]*\Z")
WELD_RELATIVE_TOLERANCE = 1e-5


def welding_tolerance(low, high):
    spans = [float(high[axis]) - float(low[axis]) for axis in range(3)]
    if any(not math.isfinite(span) or span <= 0 for span in spans):
        raise ValueError("Character model bounds must be finite and non-degenerate")
    return max(spans) * WELD_RELATIVE_TOLERANCE


def _project_file(root, relative, label):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError(f"{label} must be a project-relative path")
    path = PurePosixPath(relative)
    if not path.parts or path.is_absolute() or ".." in path.parts or path.parts[0].endswith(":"):
        raise ValueError(f"{label} must be a project-relative path")
    resolved = (root / Path(*path.parts)).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} must stay inside the project")
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise ValueError(f"{label} is missing or empty: {relative}")
    return path.as_posix(), resolved


def _character_asset(manifest, selector):
    character = manifest["assets"].get(selector)
    if character is None:
        matches = [item for item in manifest["assets"].values()
                   if item.get("id") == selector or item.get("name") == selector]
        if len(matches) != 1:
            raise KeyError(f"No unique character asset named {selector!r}")
        character = matches[0]
    if character.get("type") != "character":
        raise ValueError("Rigging results can only be recorded on a character asset")
    return character


def resolve_rigging_source(project_root, manifest, character_selector, source_output):
    """Resolve an approved model with separately accepted animation readiness."""
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)
    artifact = character.get("artifacts", {}).get(source_output)
    if (not artifact or artifact.get("status") != "ready"
            or artifact.get("approval", {}).get("status") != "approved"):
        raise ValueError(f"Rigging source output {source_output!r} must be a ready approved artifact")
    if artifact.get("type") not in {"model.glb", "model.fbx"}:
        raise ValueError(f"Rigging source output {source_output!r} must be a GLB or FBX model")
    readiness = character.get("animation_readiness")
    if readiness and readiness.get("status") == "fail":
        raise ValueError("Character mesh failed animation-readiness checks: " + "; ".join(readiness.get("reasons", [])))
    if not readiness_allows_rigging(readiness):
        raise ValueError("Rigging requires an accepted animation-readiness report; run character readiness and approve it")
    _, path = _project_file(root, artifact.get("path"), "Rigging source model")
    if path.suffix.lower() not in {".glb", ".fbx"}:
        raise ValueError("Rigging source artifact extension must be .glb or .fbx")
    expected_source = {"artifact_id": artifact.get("id"), "path": artifact["path"],
                       "sha256": _sha256(path)}
    if readiness.get("source_output") != source_output or readiness.get("source") != expected_source:
        raise ValueError("Approved animation-readiness report does not match the selected source model")
    return path


def rigify_character(project_root, config, manifest, character_selector, *, source_output="model"):
    """Run Blender's bundled Rigify provider and record its exports for review."""
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)
    source = resolve_rigging_source(root, manifest, character_selector, source_output)
    output_root = Path(config["asset_pipeline"]["output_root"])
    output = (root / output_root / "Characters" / character["name"] / "Rigging").resolve()
    if not output.is_relative_to(root):
        raise ValueError("Rigging output directory must stay inside the project")
    rigged_model = output / f"{character['name']}_rigged.fbx"
    evidence = {pose: (output / "Review" / f"{pose}.png") for pose in RECOMMENDED_POSES}
    if rigged_model.exists() or any(path.exists() for path in evidence.values()):
        raise FileExistsError(f"Rigging outputs already exist; inspect or move them before retrying: {output}")
    output.mkdir(parents=True, exist_ok=True)
    script = tool_root() / "blender/rigify_character.py"
    try:
        with tempfile.TemporaryDirectory(prefix="slopforge-rigify-") as temporary:
            request_path = Path(temporary) / "request.json"
            report_path = Path(temporary) / "result.json"
            request_path.write_text(json.dumps({"source": str(source), "rigged_model": str(rigged_model),
                "evidence": {pose: str(path) for pose, path in evidence.items()}, "report": str(report_path),
                "weld_relative_tolerance": WELD_RELATIVE_TOLERANCE}))
            command = [blender_executable(config, root), "--background", "--factory-startup",
                       "--python", str(script), "--", str(request_path)]
            try:
                subprocess.run(command, check=True)
            except subprocess.CalledProcessError:
                pass
            if not report_path.is_file():
                raise RuntimeError("Blender Rigify failed without a provider result report")
            result = json.loads(report_path.read_text())
            if result.get("status") != "complete":
                raise RuntimeError("Blender Rigify failed: " + str(result.get("error", "provider did not complete")))
            result["rigged_model"] = rigged_model.relative_to(root).as_posix()
            result["source_output"] = source_output
            result["evidence"] = {pose: path.relative_to(root).as_posix() for pose, path in evidence.items()
                                  if path.is_file()}
            if len(result["evidence"]) != len(RECOMMENDED_POSES):
                raise RuntimeError("Blender Rigify did not render all recommended review poses")
            return record_rigging_result(root, manifest, character["id"], result)
    except Exception:
        rigged_model.unlink(missing_ok=True)
        for path in evidence.values():
            path.unlink(missing_ok=True)
        raise


def run_character_rigging(project_root, config, manifest, character_selector, *, source_output="model"):
    """Select the configured character-rigging provider without changing the result contract."""
    provider = config["asset_pipeline"].get("character_rigging_provider", "blender_rigify")
    if provider == "blender_rigify":
        return rigify_character(project_root, config, manifest, character_selector, source_output=source_output)
    if provider == "skintokens":
        return skintokens_character(project_root, config, manifest, character_selector, source_output=source_output)
    raise ValueError(f"Unsupported character_rigging_provider {provider!r}; available provider: blender_rigify, skintokens")


def classify_skintokens_structure(report):
    """Fail closed on missing or invalid structural measurements."""
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    check(report.get("armature_count") == 1, "Expected one armature")
    check(isinstance(report.get("skinned_component_count"), int) and report["skinned_component_count"] > 0,
          "No skinned character components")
    check(report.get("unclassified_objects") == [], "Unclassified geometry remains")
    check(report.get("unweighted_vertices") == 0, "Unweighted vertices")
    low, high = report.get("weight_sum_min"), report.get("weight_sum_max")
    check(isinstance(low, (int, float)) and isinstance(high, (int, float))
          and math.isfinite(low) and math.isfinite(high) and low >= 0.99 and high <= 1.01,
          "Weight sums outside tolerance")
    check(isinstance(report.get("max_influences"), int) and 0 < report["max_influences"] <= 4,
          "More than four influences or missing influence count")
    check(isinstance(report.get("bind_pose_count"), int) and report["bind_pose_count"] > 0,
          "Missing bind pose")
    coverage = report.get("material_coverage", {})
    check(isinstance(coverage, dict) and coverage.get("base_color", 0) >= 0.99,
          "Base color was not transferred")
    return {"status": "fail" if errors else "pass", "errors": errors}


def skintokens_character(project_root, config, manifest, character_selector, *, source_output="model"):
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)
    if source_output != "normalized_model":
        raise ValueError("SkinTokens requires the approved 'normalized_model' source output")
    source = resolve_rigging_source(root, manifest, character_selector, source_output)
    output = (root / config["asset_pipeline"]["output_root"] / "Characters" / character["name"] / "Rigging").resolve()
    if not output.is_relative_to(root):
        raise ValueError("Rigging output directory must stay inside the project")
    raw = output / "skintokens_raw.glb"
    rigged = output / f"{character['name']}_skintokens.fbx"
    report_path = output / "skintokens_report.json"
    contact = output / "Review" / "contact_sheet.png"
    evidence = {pose: output / "Review" / f"{pose}.png" for pose in SKINTOKENS_POSES}
    if any(path.exists() for path in (raw, rigged, report_path, contact, *evidence.values())):
        raise FileExistsError(f"SkinTokens outputs already exist; inspect or move them before retrying: {output}")
    output.mkdir(parents=True, exist_ok=True)
    inference = run_skintokens_inference(config, source, raw, seed=0)
    with tempfile.TemporaryDirectory(prefix="slopforge-skintokens-blender-") as temporary:
        request_path = Path(temporary) / "request.json"
        request_path.write_text(json.dumps({"source": str(source), "raw": str(raw),
            "rigged_model": str(rigged), "report": str(report_path), "contact_sheet": str(contact),
            "checkpoint_sha256": inference["checkpoint_sha256"], "skintokens_revision": inference["revision"],
            "evidence": {pose: str(path) for pose, path in evidence.items()}}))
        command = [blender_executable(config, root), "--background", "--factory-startup", "--python",
                   str(tool_root() / "blender/skintokens_character.py"), "--", str(request_path)]
        subprocess.run(command, check=True)
    if not report_path.is_file():
        raise RuntimeError("SkinTokens Blender postprocessing produced no report")
    report = json.loads(report_path.read_text())
    structural = classify_skintokens_structure(report)
    if report.get("status") != "complete" or structural["status"] != "pass":
        raise RuntimeError("SkinTokens postprocessing failed: " + "; ".join(structural["errors"] + report.get("errors", [])))
    if not rigged.is_file() or not rigged.stat().st_size:
        raise RuntimeError("SkinTokens postprocessing produced no FBX")
    if not contact.is_file() or any(not path.is_file() for path in evidence.values()):
        raise RuntimeError("SkinTokens postprocessing omitted canonical evidence")
    result = {"provider": {"name": "SkinTokens", "version": inference["revision"],
              "source": "https://github.com/VAST-AI-Research/SkinTokens", "license": "MIT",
              "source_revision": inference["revision"], "checkpoint_sha256": inference["checkpoint_sha256"]},
              "source_output": source_output, "rigged_model": rigged.relative_to(root).as_posix(),
              "evidence": {pose: path.relative_to(root).as_posix() for pose, path in evidence.items()},
              "skeleton_mapping": report.get("semantic_mapping", {}),
              "deformation_evidence": report.get("deformation_evidence", {}),
              "structural_report": structural, "postprocess_report": report_path.relative_to(root).as_posix(),
              "contact_sheet": contact.relative_to(root).as_posix()}
    return record_rigging_result(root, manifest, character["id"], result)


def approve_deformation(project_root, manifest, character_selector, *, confirmed=False):
    if not confirmed:
        raise ValueError("Explicit human confirmation is required")
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)
    rigging = character.get("rigging", {})
    if rigging.get("structural_report", {}).get("status") != "pass":
        raise ValueError("Passing structural report required")
    artifacts = character.get("artifacts", {})
    if any(f"rig_pose.{pose}" not in artifacts for pose in SKINTOKENS_POSES):
        raise ValueError("All canonical pose images are required")
    if "rig_contact_sheet" not in artifacts:
        raise ValueError("Canonical contact sheet is required")
    for key in ("rig_contact_sheet", *(f"rig_pose.{pose}" for pose in SKINTOKENS_POSES)):
        _project_file(root, artifacts[key]["path"], key)
    character.setdefault("pipeline_status", {})["deformation_status"] = "approved"
    rigging["deformation_approval"] = {"status": "approved"}
    return {"status": "approved"}


def record_rigging_result(project_root, manifest, character_selector, result):
    """Record provider exports as pending typed artifacts; never auto-approve a rig."""
    if not isinstance(result, dict):
        raise ValueError("Rigging provider result must be an object")
    root = Path(project_root).resolve()
    character = _character_asset(manifest, character_selector)

    provider = result.get("provider")
    required_provider = ("name", "version", "source", "license")
    if not isinstance(provider, dict) or any(not isinstance(provider.get(key), str) or not provider[key].strip()
                                              for key in required_provider):
        raise ValueError("Rigging provider provenance requires name, version, source, and license")
    source_output = result.get("source_output")
    if (not isinstance(source_output, str)
            or source_output not in character.get("artifacts", {})
            and source_output not in character.get("outputs", {})):
        raise ValueError("Rigging result must name an existing source output")
    if source_output in character.get("artifacts", {}):
        artifact = character["artifacts"][source_output]
        if artifact.get("status") != "ready" or artifact.get("approval", {}).get("status") != "approved":
            raise ValueError("Rigging source output must be ready and approved")

    rig_path, rig_file = _project_file(root, result.get("rigged_model"), "Rigged model")
    if rig_file.suffix.lower() not in {".fbx", ".glb"}:
        raise ValueError("Rigged model must be an FBX or GLB export")
    evidence = result.get("evidence", {})
    mapping = result.get("skeleton_mapping", {})
    unity_mapping = result.get("unity_humanoid_mapping")
    deformation = result.get("deformation_evidence", {})
    mesh_repair = result.get("mesh_repair", {})
    if (not isinstance(evidence, dict) or not isinstance(mapping, dict) or not isinstance(deformation, dict)
            or not isinstance(mesh_repair, dict)):
        raise ValueError("Rig evidence, deformation evidence, skeleton mapping, and mesh repair must be mappings")
    if unity_mapping is not None and (not isinstance(unity_mapping, dict)
            or any(not isinstance(name, str) or not name.strip() or not isinstance(bone, str) or not bone.strip()
                   for name, bone in unity_mapping.items())
            or len(set(unity_mapping.values())) != len(unity_mapping)):
        raise ValueError("Unity Humanoid mapping must map human bone names to unique non-empty rig bones")
    if any(not isinstance(source, str) or not source.strip() or not isinstance(target, str) or not target.strip()
           for source, target in mapping.items()):
        raise ValueError("Skeleton mapping entries must map non-empty bone names")
    for pose, metrics in deformation.items():
        value = metrics.get("max_vertex_displacement") if isinstance(metrics, dict) else None
        if (not isinstance(pose, str) or not isinstance(metrics, dict) or not isinstance(value, (int, float))
                or isinstance(value, bool) or not math.isfinite(value) or value < 0):
            raise ValueError("Deformation evidence requires finite non-negative max_vertex_displacement metrics")

    evidence_files = []
    for pose, relative in evidence.items():
        if not isinstance(pose, str) or not _POSE_ID.fullmatch(pose):
            raise ValueError(f"Invalid rig evidence pose id: {pose!r}")
        relative, path = _project_file(root, relative, f"Rig evidence {pose}")
        check = validate_image(path, expected_format="PNG")
        if check["status"] == "failed":
            raise ValueError(f"Rig evidence {pose} is not a valid PNG: " + "; ".join(check["errors"]))
        evidence_files.append((pose, relative, check))

    provenance = {key: provider[key] for key in required_provider}
    for key in ("model", "model_license", "source_revision", "checkpoint_sha256"):
        if key in provider:
            provenance[key] = provider[key]
    derived = [{"asset_id": character["id"], "output_id": source_output}]
    validation = {"status": "not_run", "errors": [],
                  "warnings": ["Structural export checks passed; deformation quality requires manual review."],
                  "measured": {"skeleton_mapping_count": len(mapping), "evidence_pose_count": len(evidence_files)}}
    if "structural_report" in result:
        structural = result["structural_report"]
        if structural.get("status") != "pass":
            raise ValueError("Rig structural report must pass before registration")
        validation["status"] = "pass"
        validation["measured"]["structural_status"] = "pass"
    registered = register_artifact(manifest, character["id"], "rig", "model.rigged", rig_path,
                                   status="candidate", derived_from=derived, provenance=provenance,
                                   approval_status="pending", validation=validation)
    for pose, relative, check in evidence_files:
        register_artifact(manifest, character["id"], f"rig_pose.{pose}", "image.rig_evidence", relative,
                          status="candidate", derived_from=derived, provenance=provenance,
                          approval_status="pending", validation=check)
    if result.get("contact_sheet"):
        relative, path = _project_file(root, result["contact_sheet"], "Rig contact sheet")
        check = validate_image(path, expected_format="PNG")
        if check["status"] == "failed":
            raise ValueError("Rig contact sheet is not a valid PNG")
        register_artifact(manifest, character["id"], "rig_contact_sheet", "image.rig_evidence", relative,
                          status="candidate", derived_from=derived, provenance=provenance,
                          approval_status="pending", validation=check)
    missing = [pose for pose in RECOMMENDED_POSES if pose not in evidence]
    character["rigging"] = {"status": "review_required", "source_output": source_output,
                            "provider": provenance, "skeleton_mapping": dict(mapping),
                            "deformation_evidence": deformation,
                            "mesh_repair": mesh_repair,
                            "validation": validation, "missing_recommended_poses": missing}
    if "structural_report" in result:
        character["rigging"]["structural_report"] = result["structural_report"]
    if "postprocess_report" in result:
        character["rigging"]["postprocess_report"] = result["postprocess_report"]
    if unity_mapping is not None:
        character["rigging"]["unity_humanoid_mapping"] = dict(unity_mapping)
    statuses = character.setdefault("pipeline_status", {})
    statuses.update({"rigging_status": "review_required", "deformation_status": "needs_review"})
    character["status"] = "candidate"
    return {"status": "review_required", "rig_artifact": registered, "missing_recommended_poses": missing}
