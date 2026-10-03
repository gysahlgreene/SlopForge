import os
import subprocess
import sys
from pathlib import Path

from ..paths import blender_executable, comfy_home, comfy_url, resolve_workflow, tool_root


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
    env["COMFYUI_HOME"] = str(comfy_home(config, project_root))
    return env


def generate_image(project_root, config, workflow, prompt, destination, prefix, seed, metadata):
    root = Path(project_root).resolve()
    resolved = resolve_workflow(root, workflow)
    script = tool_root() / "processing/comfy_generate.py"
    command = [python_executable(root, config), str(script), "--workflow", str(resolved),
               "--prompt", prompt, "--dest", str(destination), "--prefix", prefix,
               "--seed", str(seed), "--metadata", str(metadata)]
    return subprocess.run(command, check=True, env=comfy_environment(config, root))


def generate_model(project_root, config, image, name, destination, metadata, seed, face_budget=30000):
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
    return subprocess.run(command, check=True, env=comfy_environment(config, root))
