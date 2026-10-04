import importlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

from .backends.comfyui import ComfyUIClient
from .config import load_project
from .paths import blender_executable, comfy_backend, comfy_home, comfy_url, resolve_workflow, tool_root
from .style import load_style
from .taxonomy import load_taxonomy


def run_doctor(project_root=None):
    failures = []

    def report(status, label, detail=""):
        print(f"{status:4} {label}" + (f" — {detail}" if detail else ""))
        if status == "FAIL":
            failures.append(label)

    print("SlopForge Doctor")
    version = sys.version_info
    supported = (3, 10) <= version[:2] < (3, 15)
    report("PASS" if supported else "FAIL", "Python", f"{version.major}.{version.minor}.{version.micro} (supported: 3.10–3.14)")
    missing = []
    for module in ("numpy", "PIL", "yaml", "rembg"):
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(module)
        except (ImportError, ValueError):
            missing.append(module)
    report("PASS" if not missing else "FAIL", "Python packages", "available" if not missing else ", ".join(missing))
    try:
        importlib.import_module("onnxruntime")
    except Exception:
        report("FAIL", "Background removal backend", 'onnxruntime unavailable; install "rembg[cpu]"')
    else:
        report("PASS", "Background removal backend", "onnxruntime available")

    root = Path(project_root).expanduser().resolve() if project_root else None
    config = None
    workflow_paths = []
    if root and (root / "ai/project.yaml").is_file():
        try:
            config = load_project(root)
            report("PASS", "Project config", str(root / "ai/project.yaml"))
            style = load_style(root, config)
            report("PASS", "Style pack", f"{style['name']} v{style['version']}")
            types = load_taxonomy(root)
            report("PASS", "Asset taxonomy", f"{len(types)} types")
            for role, key in (("Workflow", "image"), ("Model workflow", "model")):
                configured = config["asset_pipeline"]["workflows"].get(key)
                if configured:
                    path = resolve_workflow(root, configured)
                    workflow_paths.append((role, path))
                    report("PASS", role, str(path))
            generated = root / config["asset_pipeline"]["output_root"]
            report("PASS" if generated.is_dir() else "WARN", "Generated directories",
                   str(generated) if generated.is_dir() else f"not initialized: {generated}")
        except Exception as exc:
            report("FAIL", "Project config/style/workflow", str(exc))
    else:
        report("WARN", "Project config", "pass --project or run inside a project initialized with slopforge init")
        packaged = tool_root() / "workflows/image_text2img_api.json"
        report("PASS" if packaged.is_file() else "FAIL", "Workflow", str(packaged))
        if packaged.is_file():
            workflow_paths.append(("Workflow", packaged))

    url = comfy_url(config)
    backend = comfy_backend(config)
    profile = (config or {}).get("asset_pipeline", {}).get("selected_compute_profile", "default")
    report("PASS", "ComfyUI configuration", f"{url} ({backend}; profile: {profile})")
    home = comfy_home(config, root) if backend == "local" else None
    if home:
        report("PASS" if home.is_dir() else "WARN", "ComfyUI local home", str(home))
    elif backend == "remote":
        report("PASS", "ComfyUI file transfer", "HTTP upload and output download; no local COMFYUI_HOME needed")
    else:
        report("PASS", "ComfyUI file transfer", "HTTP upload and output download")

    client = ComfyUIClient(url, timeout=5)
    try:
        stats = client.health()
        system = stats.get("system", {})
        devices = ", ".join(device.get("name", "unknown") for device in stats.get("devices", [])) or "device not reported"
        report("PASS", "ComfyUI reachable", f"{url}; {system.get('comfyui_version', 'version unknown')}; {devices}")
        try:
            node_info = client.node_types()
            required = set()
            for _, workflow_path in workflow_paths:
                required.update(node.get("class_type") for node in json.loads(workflow_path.read_text()).values()
                                if node.get("class_type"))
            if config and not config["asset_pipeline"]["workflows"].get("model"):
                required.update({"LoadImage", "ImageOnlyCheckpointLoader", "CLIPVisionEncode", "Hunyuan3Dv2Conditioning",
                                 "EmptyLatentHunyuan3Dv2", "KSampler", "VAEDecodeHunyuan3D", "VoxelToMesh", "SaveGLB"})
            missing_nodes = sorted(required - node_info.keys())
            report("FAIL" if missing_nodes else "PASS", "Workflow node capabilities",
                   "missing: " + ", ".join(missing_nodes) if missing_nodes else f"all {len(required)} required node classes available")
            for role, workflow_path in workflow_paths:
                try:
                    client.validate_workflow(json.loads(workflow_path.read_text()), node_info)
                except Exception as exc:
                    report("FAIL", f"{role} model choices", str(exc))
                else:
                    report("PASS", f"{role} model choices", "required model names are available")
            report("PASS", "ComfyUI HTTP API", "health and workflow node discovery available; file transfer and generation are not exercised by doctor")
        except Exception as exc:
            report("WARN", "Workflow node capabilities", str(exc))
    except Exception as exc:
        report("WARN", "ComfyUI reachable", f"offline or unreachable at {url}: {exc}")

    try:
        blender = blender_executable(config, root)
        if not Path(blender).is_file():
            blender = shutil.which(blender)
        if not blender:
            raise FileNotFoundError("Blender executable not found")
        if not os.access(blender, os.X_OK):
            raise FileNotFoundError(f"Blender is not executable: {blender}")
        report("PASS", "Blender", blender)
    except FileNotFoundError as exc:
        report("WARN", "Blender", str(exc))
    return 1 if failures else 0
