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

from ..paths import blender_executable, comfy_backend, comfy_url, resolve_workflow, tool_root
from ..config import workflow_node_inputs


class ComfyUIError(RuntimeError):
    pass


class ComfyUIClient:
    """HTTP boundary for local and remote ComfyUI instances."""

    MODEL_INPUTS = {"ckpt_name", "unet_name", "vae_name", "clip_name", "clip_vision", "model_name",
                    "bg_removal_name"}

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
            raise ComfyUIError(f"ComfyUI {method} {path} returned HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ComfyUIError(f"ComfyUI {method} {path} failed at {self.base_url}: {exc}") from exc

    def json(self, method, path, payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        raw = self._request(method, path, body, "application/json" if body is not None else None)
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ComfyUIError(f"ComfyUI {method} {path} returned invalid JSON") from exc

    def health(self):
        return self.json("GET", "/system_stats")

    def node_types(self):
        return self.json("GET", "/object_info")

    def upload_file(self, path, subfolder="slopforge"):
        path = Path(path)
        if not path.is_file():
            raise ComfyUIError(f"Input file does not exist: {path}")
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
            raise ComfyUIError("ComfyUI input upload returned invalid JSON") from exc
        if not result.get("name"):
            raise ComfyUIError(f"ComfyUI input upload did not return a filename: {result}")
        return result

    upload_input = upload_file

    def validate_workflow(self, workflow, node_info=None):
        node_info = node_info or self.node_types()
        missing = sorted({node.get("class_type") for node in workflow.values() if node.get("class_type")} - node_info.keys())
        if missing:
            raise ComfyUIError("ComfyUI is missing workflow node classes: " + ", ".join(missing))
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
            raise ComfyUIError("ComfyUI does not expose these workflow model choices: " + "; ".join(unavailable_models))
        return node_info

    def queue_workflow(self, workflow, client_id=None):
        self.validate_workflow(workflow)
        result = self.json("POST", "/prompt", {"prompt": workflow, "client_id": client_id or str(uuid.uuid4())})
        if result.get("node_errors"):
            details = json.dumps(result["node_errors"], sort_keys=True)
            raise ComfyUIError(f"ComfyUI rejected workflow (missing node, model, or invalid input): {details}")
        if not result.get("prompt_id"):
            raise ComfyUIError(f"ComfyUI rejected workflow without a prompt id: {result}")
        return result["prompt_id"]

    def history(self, prompt_id):
        result = self.json("GET", f"/history/{prompt_id}")
        return result.get(prompt_id)

    def wait_for_completion(self, prompt_id, timeout=3600, poll_interval=1):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            entry = self.history(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyUIError(f"ComfyUI generation {prompt_id} failed: {status.get('messages', status)}")
                if status.get("completed") and entry.get("outputs"):
                    return entry
            time.sleep(poll_interval)
        raise ComfyUIError(f"Timed out waiting for ComfyUI history for prompt {prompt_id}")

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
            raise ComfyUIError(f"Could not download ComfyUI output {filename}: {exc}") from exc
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
            raise ComfyUIError(f"ComfyUI returned an empty output for {filename}")
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


def generate_image(project_root, config, workflow, prompt, destination, prefix, seed, metadata, *,
                   conditioning=None):
    root = Path(project_root).resolve()
    resolved = resolve_workflow(root, workflow)
    script = tool_root() / "processing/comfy_generate.py"
    command = [python_executable(root, config), str(script), "--workflow", str(resolved),
               "--prompt", prompt, "--dest", str(destination), "--prefix", prefix,
               "--seed", str(seed), "--metadata", str(metadata)]
    quality = config["asset_pipeline"].get("quality_settings", {})
    quality_info = {"tier": config["asset_pipeline"].get("selected_quality_tier", "normal"),
                    "settings": quality}
    command.extend(["--quality", json.dumps(quality_info)])
    node_inputs = workflow_node_inputs(config, "image", resolved.name)
    if node_inputs:
        command.extend(["--workflow-inputs", json.dumps(node_inputs)])
    if conditioning and conditioning.get("strategy") == "reference":
        references = [{**item, "path": str(root / item["path"]), "provenance_path": item["path"]}
                      for item in conditioning["references"]]
        command.extend(["--references", json.dumps(references),
                        "--reference-inputs", json.dumps(conditioning["workflow_inputs"])])
    return subprocess.run(command, check=True, env=comfy_environment(config, root))


def generate_model(project_root, config, image, name, destination, metadata, seed, face_budget=30000,
                  voxel_resolution=None):
    root = Path(project_root).resolve()
    script = tool_root() / "processing/comfy_generate_3d.py"
    command = [python_executable(root, config), str(script), "--image", str(image),
               "--name", name, "--dest", str(destination),
               "--checkpoint", config["asset_pipeline"]["tools"]["hunyuan_checkpoint"],
               "--seed", str(seed), "--metadata", str(metadata)]
    workflow = config["asset_pipeline"]["workflows"].get("model")
    if workflow:
        command.extend(["--workflow", str(resolve_workflow(root, workflow)), "--face-budget", str(face_budget),
                        "--blender", blender_executable(config, root)])
        if voxel_resolution is not None:
            command.extend(["--voxel-resolution", str(voxel_resolution)])
    quality = config["asset_pipeline"].get("quality_settings", {})
    command.extend(["--quality", json.dumps({"tier": config["asset_pipeline"].get("selected_quality_tier", "normal"),
                                               "settings": quality})])
    workflow_name = Path(workflow).name if workflow else "hunyuan3d_image_to_model_api.json"
    node_inputs = workflow_node_inputs(config, "model", workflow_name)
    if node_inputs:
        command.extend(["--workflow-inputs", json.dumps(node_inputs)])
    return subprocess.run(command, check=True, env=comfy_environment(config, root))
