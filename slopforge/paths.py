import os
import shutil
import sys
from pathlib import Path


def package_root():
    return Path(__file__).resolve().parents[1]


def tool_root():
    root = package_root()
    if (root / "processing").is_dir() and (root / "templates").is_dir():
        return root
    installed = Path(sys.prefix) / "share" / "slopforge"
    if installed.is_dir():
        return installed
    return root


def discover_project_root(start=None):
    current = Path(start or Path.cwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "ai/project.yaml").is_file():
            return candidate
    raise FileNotFoundError(f"No ai/project.yaml found from {current}; pass --project or run slopforge init.")


def resolve_project_root(value=None, start=None):
    root = Path(value).expanduser().resolve() if value else discover_project_root(start)
    if not (root / "ai/project.yaml").is_file():
        raise FileNotFoundError(f"Not an initialized asset project: {root} (missing ai/project.yaml)")
    return root


def resolve_workflow(project_root, workflow):
    workflow = Path(workflow).expanduser()
    if workflow.is_absolute():
        if workflow.is_file():
            return workflow.resolve()
        raise FileNotFoundError(f"Configured workflow not found: {workflow}")
    root = Path(project_root).resolve()
    candidates = [root / workflow]
    if workflow.parts[:2] != ("ai", "workflows"):
        candidates.append(root / "ai/workflows" / workflow.name)
    candidates.append(tool_root() / "workflows" / workflow.name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"Workflow not found in project overrides or toolkit: {workflow}")


def comfy_url(config=None):
    configured = os.environ.get("COMFYUI_URL")
    if configured:
        return configured.rstrip("/")
    if config:
        return config["asset_pipeline"]["tools"].get("comfy_url", "http://127.0.0.1:8188").rstrip("/")
    return "http://127.0.0.1:8188"


def comfy_home(config=None, project_root=None):
    configured = os.environ.get("COMFYUI_HOME")
    if not configured and config:
        configured = config["asset_pipeline"]["tools"].get("comfy_home")
    path = Path(configured).expanduser() if configured else Path.home() / "ComfyUI"
    if not path.is_absolute() and project_root:
        path = Path(project_root) / path
    return path.resolve()


def blender_executable(config=None, project_root=None):
    configured = os.environ.get("BLENDER_BIN")
    if not configured and config:
        configured = config["asset_pipeline"]["tools"].get("blender")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute() and project_root:
            path = Path(project_root) / path
        return str(path.resolve()) if path.is_file() else str(configured)
    found = shutil.which("blender")
    if found:
        return found
    for candidate in ("/Applications/Blender.app/Contents/MacOS/Blender",
                      "/Applications/Blender.app/Contents/MacOS/blender"):
        if Path(candidate).is_file():
            return candidate
    raise FileNotFoundError("Blender not found; configure project tools.blender or set BLENDER_BIN.")
