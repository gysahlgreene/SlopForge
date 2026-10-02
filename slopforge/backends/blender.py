import json
import subprocess
from pathlib import Path

from ..paths import blender_executable, tool_root


def process_model(project_root, config, glb, fbx, blend, textures, face_budget, *,
                  surface_source=None, preview_dir=None, material_scale=3.0,
                  stage_mesh=None, reuse_stage_mesh=False):
    root = Path(project_root).resolve()
    script = tool_root() / "blender/prepare_model.py"
    command = [blender_executable(config, root), "--background", "--python", str(script), "--",
               str(glb), str(fbx), str(blend), *(str(path) for path in textures),
               "--face-budget", str(face_budget)]
    if surface_source:
        command.extend(("--surface-source", str(surface_source)))
    if preview_dir:
        command.extend(("--preview-dir", str(preview_dir)))
    command.extend(("--material-scale", str(material_scale)))
    if stage_mesh:
        if reuse_stage_mesh:
            command[command.index("--") + 1] = str(stage_mesh)
            command.append("--reuse-stage-mesh")
        else:
            command.extend(("--stage-mesh-output", str(stage_mesh)))
    return subprocess.run(command, check=True)


def inspect_model(project_root, config, blend, output_json, face_budget):
    root = Path(project_root).resolve()
    script = tool_root() / "blender/inspect_model.py"
    command = [blender_executable(config, root), "--background", "--python", str(script), "--",
               str(blend), str(output_json), str(face_budget)]
    subprocess.run(command, check=True)
    return json.loads(Path(output_json).read_text())
