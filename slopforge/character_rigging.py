"""Validate and record outputs from an external character-rigging provider."""
import json
import hashlib
import math
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from .manifest import register_artifact
from .paths import blender_executable, tool_root
from .character_readiness import readiness_allows_rigging
from .validation import validate_image

from . import skintokens_runtime as runtime
from .skintokens_runtime import SKINTOKENS_REVISION, SKINTOKENS_SETTINGS as _SKINTOKENS_SETTINGS


def _sha256(path):
    return runtime.sha256(path)


def _skintokens_host(config):
    host = config.get("asset_pipeline", {}).get("tools", {}).get("skintokens_host")
    return host if isinstance(host, str) and host else None


def _skintokens_paths(config, project_root):
    tools = config.get("asset_pipeline", {}).get("tools", {})
    root = Path(project_root).resolve()
    remote = _skintokens_host(config) is not None
    def path(key):
        value = tools.get(key)
        if not isinstance(value, str) or not value:
            return None
        # Remote paths are the host's own absolute paths; never resolve them locally.
        if remote and not value.startswith("/"):
            raise ValueError(f"tools.{key} must be an absolute path on tools.skintokens_host")
        return PurePosixPath(value) if remote else (root / Path(value).expanduser()).resolve()
    return tuple(path(key) for key in ("skintokens_python", "skintokens_checkout", "skintokens_checkpoint"))


def _remote(config, action, payload):
    """Run one skintokens_runtime action with the remote SkinTokens Python; returns its JSON."""
    python = config["asset_pipeline"]["tools"].get("skintokens_python")
    if not python:
        return None
    completed = subprocess.run(["ssh", "-o", "BatchMode=yes", _skintokens_host(config),
                                shlex.join([python, "-", action, json.dumps(payload)])],
                               input=Path(runtime.__file__).read_text(), capture_output=True, text=True,
                               check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"SkinTokens {action} on {_skintokens_host(config)} failed: "
                           + (completed.stderr.strip().splitlines() or ["no output"])[-1])
    return json.loads(completed.stdout.strip().splitlines()[-1])


def skintokens_preflight(config, project_root):
    """Inspect the configured runtime (local, or on tools.skintokens_host) without changing it."""
    python, checkout, checkpoint = _skintokens_paths(config, project_root)
    if _skintokens_host(config):
        if python is None:
            return runtime.preflight(None, checkout, checkpoint)
        return _remote(config, "preflight", {"python": str(python), "checkout": str(checkout) if checkout else None,
                                             "checkpoint": str(checkpoint) if checkpoint else None})
    return runtime.preflight(python, checkout, checkpoint)


def prepare_skintokens_runtime(config, project_root):
    """Apply the audited SDPA edit only on explicit setup invocation."""
    _, checkout, _ = _skintokens_paths(config, project_root)
    if _skintokens_host(config):
        return _remote(config, "prepare", {"checkout": str(checkout) if checkout else None})
    return runtime.prepare(checkout)


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
    host = _skintokens_host(config)
    if host:
        complete = _remote_inference(config, host, python, checkout, checkpoint, source, output, seed, log)
    else:
        complete = runtime.launch(python, checkout, checkpoint, source, output, seed, log)
    if not complete:
        raise RuntimeError("SkinTokens inference failed; inspect the project log")
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


def _remote_inference(config, host, python, checkout, checkpoint, source, output, seed, log):
    """Upload the source, run the shared launcher on the host, and fetch the output and log back."""
    ssh = ["ssh", "-o", "BatchMode=yes", host]
    made = subprocess.run(ssh + ["mktemp", "-d", "/tmp/slopforge-skintokens-XXXXXX"],
                          capture_output=True, text=True, check=False)
    if made.returncode != 0 or not made.stdout.strip():
        raise RuntimeError(f"Could not create a SkinTokens work directory on {host}")
    work = PurePosixPath(made.stdout.strip())
    remote_source, remote_output, remote_log = (work / ("source" + source.suffix.lower()),
                                                work / "output.glb", work / "skintokens.log")
    try:
        if subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(source), f"{host}:{remote_source}"],
                          check=False).returncode != 0:
            raise RuntimeError(f"Could not upload the SkinTokens source to {host}")
        complete = _remote(config, "launch", {"python": str(python), "checkout": str(checkout),
                                              "checkpoint": str(checkpoint), "source": str(remote_source),
                                              "output": str(remote_output), "seed": seed,
                                              "log": str(remote_log)})["complete"]
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", f"{host}:{remote_log}", str(log)], check=False)
        if complete and subprocess.run(["scp", "-q", "-o", "BatchMode=yes", f"{host}:{remote_output}",
                                        str(output)], check=False).returncode != 0:
            raise RuntimeError(f"Could not download the SkinTokens output from {host}")
        return complete
    finally:
        subprocess.run(ssh + ["rm", "-rf", "--", str(work)], check=False)


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
    from .character_quality import require_current_character_source_approval
    require_current_character_source_approval(root, character, source_output)
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
    from .character_quality import require_current_character_source_approval
    require_current_character_source_approval(root, character, source_output)
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
