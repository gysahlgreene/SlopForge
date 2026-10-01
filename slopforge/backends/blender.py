import json
import subprocess
from pathlib import Path

from ..paths import blender_executable, tool_root


def process_model(project_root, config, glb, fbx, blend, textures, face_budget):
    root = Path(project_root).resolve()
    script = tool_root() / "blender/prepare_model.py"
    command = [blender_executable(config, root), "--background", "--python", str(script), "--",
               str(glb), str(fbx), str(blend), *(str(path) for path in textures),
               "--face-budget", str(face_budget)]
    return subprocess.run(command, check=True)


def inspect_model(project_root, config, blend, output_json, face_budget):
    root = Path(project_root).resolve()
    script = tool_root() / "blender/inspect_model.py"
    command = [blender_executable(config, root), "--background", "--python", str(script), "--",
               str(blend), str(output_json), str(face_budget)]
    subprocess.run(command, check=True)
    return json.loads(Path(output_json).read_text())
