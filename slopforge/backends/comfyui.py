import os
import json
import mimetypes
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pathlib import Path
from ..provenance import provenance_fact

from ..paths import blender_executable, comfy_backend, comfy_url, resolve_workflow, tool_root
from ..failures import StageFailure
from ..config import workflow_node_inputs


class ComfyUIError(RuntimeError):
    """Structured failure that crosses the ComfyUI backend boundary.

    Extends RuntimeError with optional structured fields while preserving
    the original constructor signature and __str__ behaviour so existing
    callers that only check for RuntimeError or str(exc) continue to work.
    """

    def __init__(self, message, /, *, category=None, operation=None, evidence=None):
        super().__init__(message)
        self.category = category
        self.operation = operation
        self.evidence = evidence

    # Maintain positional-lookup compatibility for callers that do
    # ``e.args[1]`` or similar: never change ``args``.  All extra
    # attributes are keyword-only and therefore backwards-compatible.


# ── Worker failure report (protocol-v1) ───────────────────────────────
_FAILURE_REPORT_VERSION = "v1"
_FAILURE_REQUIRED_FIELDS = frozenset(
    {"version", "category", "operation", "message", "exception_type"},
)


def _safe_serialisable_evidence(evidence):
    """Return a JSON-serialisable copy of ``evidence`` or {} on failure."""
    if not isinstance(evidence, dict):
        return {}
    try:
        json.dumps(evidence, allow_nan=False)
        return evidence
    except (TypeError, ValueError):
        return {}


def _classify_failure_report(report):
    """Classify a worker failure report's readiness for structured handling.

    Returns one of:
    - ``'structured'`` when the report is complete, fresh, and self-consistent
      and ``category`` maps to one of the known failure classes.
    - ``'unknown'`` when the report is missing/stale/malformed/contradictory
      or the version is not ``'v1'``.
    """
    if not isinstance(report, dict):
        return "unknown"

    # Version gate
    version = report.get("version")
    if version != _FAILURE_REPORT_VERSION:
        return "unknown"

    # Presence gate
    for key in _FAILURE_REQUIRED_FIELDS:
        if key not in report:
            return "unknown"

    # Type gates
    if not isinstance(report["category"], str) or not report["category"]:
        return "unknown"
    if not isinstance(report["operation"], str) or not report["operation"]:
        return "unknown"
    if not isinstance(report["message"], str) or not report["message"]:
        return "unknown"
    if not isinstance(report["exception_type"], str) or not report["exception_type"]:
        return "unknown"

    # Self-consistency gate: ``evidence`` (when present) must not contain
    # contradictions that break structured handling — e.g. ``True`` where
    # a structured report already says ``"configuration"`` but the message
    # and operation imply a processing step).
    evidence = report.get("evidence")
    if evidence is not None and not isinstance(evidence, dict):
        return "unknown"

    # Category gate — only recognised structured classes from
    # Package 3 plan are allowed; everything else falls back to ``unknown``
    # for safety.
    _VALID_CATEGORIES = frozenset({
        "configuration",
        "environment",
        "inference",
        "candidate_quality",
        "processing_validation",
        "interruption",
        "unknown",
    })
    if report["category"] not in _VALID_CATEGORIES:
        return "unknown"
    if ("stage" in report and (not isinstance(report["stage"], str) or not report["stage"])):
        return "unknown"
    if ("stage_id" in report and
            (not isinstance(report["stage_id"], str) or not report["stage_id"])):
        return "unknown"

    return "structured"


def workflow_mask_errors(workflow):
    problems = []
    for name, node in workflow.items():
        if node.get("class_type") != "ImageCropToMask":
            continue
        link = node.get("inputs", {}).get("masks")
        if not isinstance(link, list) or len(link) != 2:
            continue
        source = workflow.get(link[0], {})
        if source.get("class_type") == "LoadImage" and link[1] == 1:
            problems.append(f"{name}: LoadImage MASK is transparency, but ImageCropToMask needs "
                            "foreground. Connect an InvertMask node between them; automatic "
                            "polarity guessing can erase narrow subjects.")
    return problems


def backend_provenance(health=None, *, queried=False):
    health = health if isinstance(health, dict) else {}
    system = health.get("system") if isinstance(health.get("system"), dict) else {}
    devices = health.get("devices") if isinstance(health.get("devices"), list) else []
    facts = {"provider": provenance_fact("known", value="ComfyUI")}
    version = system.get("comfyui_version")
    facts["version"] = (provenance_fact("known", value=version) if version else
                         provenance_fact("unavailable" if queried else "not_recorded",
                                         reason="ComfyUI did not expose a version" if queried else
                                                "Backend health was not queried"))
    names = []
    for _item in devices:
        if isinstance(_item, dict):
            _name = _item.get("name")
            if _name:
                names.append(_name)
    names = sorted(names)
    facts["device"] = (provenance_fact("known", value=names) if names else
                        provenance_fact("unavailable" if queried else "not_recorded",
                                        reason="ComfyUI did not expose device identity" if queried else
                                               "Backend health was not queried"))
    facts["model_weights"] = provenance_fact("unavailable",
        reason="ComfyUI health does not expose exact model weight identity")
    facts["custom_node_revisions"] = provenance_fact("unavailable",
        reason="ComfyUI object metadata does not expose custom-node revisions")
    return facts


class ComfyUIClient:
    """HTTP boundary for local and remote ComfyUI instances."""

    # "name" is ModelPatchLoader's model file (Z-Image Fun ControlNet patches).
    MODEL_INPUTS = {"ckpt_name", "unet_name", "vae_name", "clip_name", "clip_vision", "model_name",
                    "bg_removal_name", "name"}

    def __init__(self, base_url, timeout=60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method, path, data=None, content_type=None):
        headers = {"Content-Type": content_type} if content_type else {}
        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            category = ("environment" if path == "/object_info" else
                        "configuration" if path == "/prompt" and 400 <= exc.code < 500 else
                        "inference")
            raise ComfyUIError(f"ComfyUI {method} {path} returned HTTP {exc.code}: {detail}",
                               category=category, operation=f"http_{method.lower()}",
                               evidence={"endpoint": path, "status": exc.code}) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ComfyUIError(
                f"ComfyUI {method} {path} failed: {exc}",
                category="environment",
                operation=f"http_{method.lower()}",
                evidence={"endpoint": path, "method": method},
            ) from exc

    def json(self, method, path, payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        raw = self._request(method, path, body, "application/json" if body is not None else None)
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ComfyUIError(f"ComfyUI {method} {path} returned invalid JSON",
                               category="inference", operation=f"http_{method.lower()}",
                               evidence={"endpoint": path}) from exc

    def health(self):
        return self.json("GET", "/system_stats")

    def node_types(self):
        return self.json("GET", "/object_info")

    def upload_file(self, path, subfolder="slopforge"):
        path = Path(path)
        if not path.is_file():
            raise ComfyUIError(f"Input file does not exist: {path}", category="configuration",
                               operation="upload_input", evidence={"input": path.name})
        if ".." in Path(subfolder).parts or Path(subfolder).is_absolute():
            raise ValueError("ComfyUI upload subfolder must be a relative path without '..'")
        boundary = "----SlopForge" + uuid.uuid4().hex
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = b"".join((
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode(),
            path.read_bytes(),
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\n{subfolder}\r\n--{boundary}--\r\n".encode(),
        ))
        raw = self._request("POST", "/upload/image", data, f"multipart/form-data; boundary={boundary}")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ComfyUIError("ComfyUI input upload returned invalid JSON", category="inference",
                               operation="upload_input", evidence={"endpoint": "/upload/image"}) from exc
        if not result.get("name"):
            raise ComfyUIError("ComfyUI input upload did not return a filename", category="inference",
                               operation="upload_input", evidence={"endpoint": "/upload/image"})
        return result

    upload_input = upload_file

    def validate_workflow(self, workflow, node_info=None):
        problems = workflow_mask_errors(workflow)
        if problems:
            raise ComfyUIError(
                "Invalid workflow mask wiring: " + "; ".join(problems),
                category="configuration",
                operation="validate_workflow",
                evidence={"problems": problems},
            )
        # Preserve transport failures; only workflow/node-choice defects are configuration errors.
        try:
            node_info = node_info or self.node_types()
        except ComfyUIError as exc:
            raise ComfyUIError(
                str(exc),
                category=exc.category or "unknown",
                operation=exc.operation or "validate_workflow",
                evidence={"node_info_fetch_error": str(exc)},
            ) from exc
        missing = sorted({node.get("class_type") for node in workflow.values() if node.get("class_type")} - node_info.keys())
        if missing:
            raise ComfyUIError(
                "ComfyUI is missing workflow node classes: " + ", ".join(missing),
                category="configuration",
                operation="validate_workflow",
                evidence={"missing": missing},
            )
        unavailable_models = []
        for node in workflow.values():
            info = node_info.get(node.get("class_type"), {})
            required = info.get("input", {}).get("required", {})
            for key, value in node.get("inputs", {}).items():
                options = required.get(key)
                if key in self.MODEL_INPUTS and isinstance(options, list) and options and isinstance(options[0], list) and isinstance(value, str):
                    if value not in options[0]:
                        unavailable_models.append(f"{node.get('class_type')}.{key}: {value}")
        if unavailable_models:
            raise ComfyUIError(
                "ComfyUI does not expose these workflow model choices: " + "; ".join(unavailable_models),
                category="configuration",
                operation="validate_workflow",
                evidence={"unavailable_models": unavailable_models},
            )
        return node_info

    def queue_workflow(self, workflow, client_id=None):
        self.validate_workflow(workflow)
        try:
            result = self.json("POST", "/prompt", {
                "prompt": workflow, "client_id": client_id or str(uuid.uuid4())})
        except KeyboardInterrupt as exc:
            raise ComfyUIError(
                "ComfyUI queue submission interrupted; remote outcome is unknown",
                category="interruption", operation="queue_workflow",
                evidence={"endpoint": "/prompt", "outcome_unknown": True}) from exc
        except ComfyUIError as exc:
            # A transport/server failure may arrive after ComfyUI accepted the job.
            if exc.category != "configuration":
                evidence = exc.evidence if isinstance(exc.evidence, dict) else {}
                exc.evidence = {**evidence, "outcome_unknown": True}
            raise
        if not isinstance(result, dict):
            raise ComfyUIError(
                "ComfyUI queue submission returned a malformed response; remote outcome is unknown",
                category="inference", operation="queue_workflow",
                evidence={"endpoint": "/prompt", "response_type": type(result).__name__,
                          "outcome_unknown": True},
            )
        if result.get("node_errors"):
            details = json.dumps(result["node_errors"], sort_keys=True)
            raise ComfyUIError(
                f"ComfyUI rejected workflow (missing node, model, or invalid input): {details}",
                category="configuration",
                operation="queue_workflow",
                evidence={"node_errors": result["node_errors"]},
            )
        if not result.get("prompt_id"):
            raise ComfyUIError(
                f"ComfyUI rejected workflow without a prompt id: {result}",
                category="inference",
                operation="queue_workflow",
                evidence={"result": result, "outcome_unknown": True},
            )
        return result["prompt_id"]

    def history(self, prompt_id):
        result = self.json("GET", f"/history/{prompt_id}")
        return result.get(prompt_id)

    def wait_for_completion(self, prompt_id, timeout=3600, poll_interval=1):
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                try:
                    entry = self.history(prompt_id)
                except ComfyUIError as exc:
                    evidence = exc.evidence if isinstance(exc.evidence, dict) else {}
                    raise ComfyUIError(
                        str(exc), category=exc.category or "inference",
                        operation=exc.operation or "wait_for_completion",
                        evidence={**evidence, "prompt_id": prompt_id, "outcome_unknown": True}) from exc
                if entry:
                    status = entry.get("status", {})
                    if status.get("status_str") == "error":
                        raise ComfyUIError(f"ComfyUI generation {prompt_id} failed: {status.get('messages', status)}",
                                           category="inference", operation="wait_for_completion",
                                           evidence={"prompt_id": prompt_id, "remote_terminal": True})
                    if status.get("completed") and entry.get("outputs"):
                        return entry
                time.sleep(poll_interval)
        except KeyboardInterrupt as exc:
            raise ComfyUIError(
                f"Waiting for ComfyUI generation {prompt_id} was interrupted; remote outcome is unknown",
                category="interruption", operation="wait_for_completion",
                evidence={"prompt_id": prompt_id, "outcome_unknown": True}) from exc
        raise ComfyUIError(
            f"Timed out waiting for ComfyUI history for prompt {prompt_id}",
            category="inference",
            operation="wait_for_completion",
            evidence={"prompt_id": prompt_id, "timeout": timeout, "outcome_unknown": True},
        )

    def list_outputs(self, history):
        found = []

        def visit(value):
            if isinstance(value, dict):
                if isinstance(value.get("filename"), str):
                    found.append({"filename": value["filename"], "subfolder": value.get("subfolder", ""),
                                  "type": value.get("type", "output")})
                else:
                    for item in value.values():
                        visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(history.get("outputs", history))
        return found

    def download_output(self, output, destination):
        filename = output.get("filename")
        if not filename or Path(filename).name != filename:
            raise ValueError(f"Invalid ComfyUI output filename: {filename!r}")
        subfolder = output.get("subfolder", "")
        if Path(subfolder).is_absolute() or ".." in Path(subfolder).parts:
            raise ValueError(f"Invalid ComfyUI output subfolder: {subfolder!r}")
        query = urlencode({"filename": filename, "subfolder": subfolder, "type": output.get("type", "output")})
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = self._request("GET", f"/view?{query}")
        except ComfyUIError as exc:
            raise ComfyUIError(f"Could not download ComfyUI output {filename}: {exc}",
                               category=exc.category or "inference", operation="download_output",
                               evidence={"filename": filename, "output_type": output.get("type", "output")}) from exc
        fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}.")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if not destination.stat().st_size:
            destination.unlink()
            raise ComfyUIError(f"ComfyUI returned an empty output for {filename}", category="inference",
                               operation="download_output", evidence={"filename": filename})
        return destination


def python_executable(project_root, config):
    configured = config["asset_pipeline"]["tools"].get("asset_python")
    if not configured:
        return sys.executable
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path(project_root) / path
    return str(path) if path.is_file() else sys.executable


def comfy_environment(config, project_root=None):
    env = os.environ.copy()
    env["COMFYUI_URL"] = comfy_url(config)
    env["SLOPFORGE_COMFYUI_BACKEND"] = comfy_backend(config)
    env["SLOPFORGE_COMPUTE_PROFILE"] = config["asset_pipeline"].get("selected_compute_profile", "default")
    env.pop("COMFYUI_HOME", None)
    import_path = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (import_path, env.get("PYTHONPATH"))))
    return env


def _write_failure_report(path, *, error):
    """Atomically write a protocol-v1 failure report for the given error.

    Called by workers when they handle a ComfyUIError.  The report is
    written to a temporary file first and ``os.replace`` is used so that
    wrappers never see a half-written report.

    If writing fails the function silently returns ``False`` so that the
    subprocess exit code is never changed by a failed write.
    """
    report = {
        "version": _FAILURE_REPORT_VERSION,
        "category": error.category or "unknown",
        "operation": error.operation or "worker",
        "message": str(error),
        "exception_type": type(error).__name__,
        "evidence": _safe_serialisable_evidence(error.evidence),
    }
    if getattr(error, "stage", None):
        report["stage"] = error.stage
    if getattr(error, "stage_id", None):
        report["stage_id"] = error.stage_id
    try:
        report_path = Path(path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(report_path.parent),
            prefix=f".{report_path.name}.",
        )
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(report, handle, allow_nan=False)
                handle.write("\n")
            os.replace(tmp, str(report_path))
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return True
    except Exception:
        # Never crash the worker on a failed report write.
        return False


def generate_image(project_root, config, workflow, prompt, destination, prefix, seed, metadata, *,
                   conditioning=None):
    root = Path(project_root).resolve()
    resolved = resolve_workflow(root, workflow)
    script = tool_root() / "processing/comfy_generate.py"
    # Create fresh report path for this invocation.
    report_path = str(Path(destination).parent / f".comfy_failure_{uuid.uuid4().hex}.json")
    command = [python_executable(root, config), str(script), "--workflow", str(resolved),
               "--prompt", prompt, "--dest", str(destination), "--prefix", prefix,
               "--seed", str(seed), "--metadata", str(metadata),
               "--failure-report", report_path]
    quality = config["asset_pipeline"].get("quality_settings", {})
    quality_info = {"tier": config["asset_pipeline"].get("selected_quality_tier", "normal"),
                    "settings": quality}
    command.extend(["--quality", json.dumps(quality_info)])
    node_inputs = workflow_node_inputs(config, "image", resolved.name)
    if node_inputs:
        command.extend(["--workflow-inputs", json.dumps(node_inputs)])
    if conditioning and conditioning.get("references"):
        references = [{**item, "path": str(root / item["path"]), "provenance_path": item["path"]}
                      for item in conditioning["references"]]
        command.extend(["--references", json.dumps(references),
                        "--reference-inputs", json.dumps(conditioning["workflow_inputs"])])
    result = subprocess.run(command, check=False, env=comfy_environment(config, root))
    if result.returncode == 0:
        return result
    # Subprocess failed — validate the invocation's report and raise.
    failed = _build_failure_from_report(report_path)
    raise failed


def _build_failure_from_report(report_path, default_category="unknown"):
    """Read and validate an invocation failure report, returning StageFailure.

    Returns a ``StageFailure`` with category, operation, message, remedy,
    and safe evidence when the report is valid structured data.
    Missing, stale, malformed, or contradictory reports return a
    StageFailure with category ``default_category`` (default "unknown").
    """
    report_path_obj = Path(report_path)
    if not report_path_obj.exists():
        return StageFailure(
            default_category,
            "failure report missing or unreadable",
            operation="read_failure_report",
            remedy="inspect the worker and remote service state before starting another inference",
            evidence={"report_path": str(report_path), "outcome_unknown": True},
        )
    try:
        data = json.loads(report_path_obj.read_text())
    except (json.JSONDecodeError, OSError):
        return StageFailure(
            default_category,
            "failure report could not be parsed",
            operation="read_failure_report",
            remedy="inspect the worker and remote service state before starting another inference",
            evidence={"report_path": str(report_path), "outcome_unknown": True},
        )
    if _classify_failure_report(data) != "structured":
        return StageFailure(
            default_category,
            f"failure report rejected classification: {data!r}",
            operation="read_failure_report",
            remedy="inspect the worker and remote service state before starting another inference",
            evidence={"report_path": str(report_path), "report": data, "outcome_unknown": True},
        )
    return StageFailure(
        data["category"],
        data["message"],
        operation=data["operation"],
        remedy="inspect the stage boundary and retry after a confirmed fix",
        stage=data.get("stage"),
        stage_id=data.get("stage_id"),
        evidence=data.get("evidence", {}),
    )


def generate_model(project_root, config, image, name, destination, metadata, seed, face_budget=30000,
                  voxel_resolution=None, journal_context=None, require_manifold=False, project_concept=False):
    root = Path(project_root).resolve()
    script = tool_root() / "processing/comfy_generate_3d.py"
    report_path = str(Path(destination).parent / f".comfy_failure_{uuid.uuid4().hex}.json")
    command = [python_executable(root, config), str(script), "--image", str(image),
               "--name", name, "--dest", str(destination),
               "--checkpoint", config["asset_pipeline"]["tools"]["hunyuan_checkpoint"],
               "--seed", str(seed), "--metadata", str(metadata),
               "--failure-report", report_path]
    journal_context = journal_context or config.get("_journal_context")
    if journal_context:
        command.extend(["--journal-context", json.dumps({**journal_context,
                                                          "project_root": str(root),
                                                          "failure_report": report_path})])
    workflow = config["asset_pipeline"]["workflows"].get("model")
    if workflow:
        command.extend(["--workflow", str(resolve_workflow(root, workflow)), "--face-budget", str(face_budget),
                        "--blender", blender_executable(config, root)])
        if voxel_resolution is not None:
            command.extend(["--voxel-resolution", str(voxel_resolution)])
        if require_manifold:
            command.append("--require-manifold")
        if project_concept:
            command.append("--project-concept")
    quality = config["asset_pipeline"].get("quality_settings", {})
    command.extend(["--quality", json.dumps({"tier": config["asset_pipeline"].get("selected_quality_tier", "normal"),
                                               "settings": quality})])
    workflow_name = Path(workflow).name if workflow else "hunyuan3d_image_to_model_api.json"
    node_inputs = workflow_node_inputs(config, "model", workflow_name)
    if node_inputs:
        command.extend(["--workflow-inputs", json.dumps(node_inputs)])
    result = subprocess.run(command, check=False, env=comfy_environment(config, root))
    if result.returncode == 0:
        return result
    # Subprocess failed — validate the invocation's report and raise.
    failed = _build_failure_from_report(report_path)
    raise failed
