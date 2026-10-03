import importlib.util
import importlib
import json
import os
import shutil
import sys
from pathlib import Path
from urllib.request import urlopen

from .config import load_project
from .paths import blender_executable, comfy_home, comfy_url, resolve_workflow, tool_root
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

    config = style = types = None
    root = Path(project_root).expanduser().resolve() if project_root else None
    if root and (root / "ai/project.yaml").is_file():
        try:
            config = load_project(root)
            report("PASS", "Project config", str(root / "ai/project.yaml"))
            style = load_style(root, config)
            report("PASS", "Style pack", f"{style['name']} v{style['version']}")
            types = load_taxonomy(root)
            report("PASS", "Asset taxonomy", f"{len(types)} types")
            workflow = resolve_workflow(root, config["asset_pipeline"]["workflows"]["image"])
            report("PASS", "Workflow", str(workflow))
            model_workflow = config["asset_pipeline"]["workflows"].get("model")
            if model_workflow:
                model_path = resolve_workflow(root, model_workflow)
                report("PASS", "Model workflow", str(model_path))
                loaders = {"UNETLoader": ("diffusion_models", "unet_name"),
                           "VAELoader": ("vae", "vae_name"), "CLIPVisionLoader": ("clip_vision", "clip_name")}
                for node in json.loads(model_path.read_text()).values():
                    loader = loaders.get(node.get("class_type"))
                    if loader:
                        folder, field = loader
                        model = comfy_home(config, root) / "models" / folder / node["inputs"][field]
                        report("PASS" if model.is_file() else "FAIL", "Model weight", str(model))
            generated = root / config["asset_pipeline"]["output_root"]
            report("PASS" if generated.is_dir() else "WARN", "Generated directories",
                   str(generated) if generated.is_dir() else f"not initialized: {generated}")
        except Exception as exc:
            report("FAIL", "Project config/style/workflow", str(exc))
    else:
        report("WARN", "Project config", "pass --project or run inside a project initialized with slopforge init")
        packaged = tool_root() / "workflows/image_text2img_api.json"
        report("PASS" if packaged.is_file() else "FAIL", "Workflow", str(packaged))
        report("WARN", "Style pack", "no target project selected")
        report("WARN", "Generated directories", "no target project selected")

    url = comfy_url(config)
    try:
        with urlopen(url + "/system_stats", timeout=3):
            report("PASS", "ComfyUI", url)
    except Exception as exc:
        report("WARN", "ComfyUI", f"offline or unreachable at {url} ({exc.__class__.__name__})")

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

    if not (config or {}).get("asset_pipeline", {}).get("workflows", {}).get("model"):
        checkpoint_name = (config or {}).get("asset_pipeline", {}).get("tools", {}).get(
            "hunyuan_checkpoint", "hunyuan3d-dit-v2_fp16.safetensors")
        checkpoint = comfy_home(config, root) / "models/checkpoints" / checkpoint_name
        report("PASS" if checkpoint.is_file() else "WARN", "Hunyuan3D checkpoint", str(checkpoint))
    return 1 if failures else 0
