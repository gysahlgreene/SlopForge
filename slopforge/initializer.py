import json
import shutil
from pathlib import Path

import yaml

from .paths import tool_root


def init_project(target, force=False):
    target = Path(target).expanduser().resolve()
    if not (target / "Assets").is_dir():
        raise ValueError(f"Target must be an existing Unity project with Assets/: {target}")
    source = tool_root() / "templates"
    managed = [Path("ai/project.yaml"), Path("ai/assets/manifest.json"), Path("ai/styles/default/style.yaml")]
    managed.extend(Path("ai/asset_types") / path.name for path in (source / "asset_types").glob("*.yaml"))
    managed.extend(Path("ai/recipes") / path.name for path in (source / "recipes").glob("*.yaml"))
    conflicts = [target / path for path in managed if (target / path).exists()]
    if conflicts and not force:
        raise FileExistsError("Refusing to overwrite existing project files; pass --force: " + str(conflicts[0]))

    project_dirs = [
        "ai/assets", "ai/assets/candidates", "ai/workflows", "ai/asset_types", "ai/recipes",
        "ai/libraries", "ai/animation_libraries", "ai/prototypes",
        "ai/styles/default/references/approved", "ai/styles/default/references/candidates",
        ".continue/rules",
        "Assets/Art/Generated/Icons", "Assets/Art/Generated/UI", "Assets/Art/Generated/Props",
        "Assets/Art/Generated/Portraits", "Assets/Art/Generated/Models", "Assets/Art/Generated/Decals",
        "Assets/Art/Generated/Concepts", "Assets/Art/Generated/Textures",
        "Assets/Art/Generated/Characters", "Assets/Art/Generated/Characters/Spritesheets",
    ]
    for directory in project_dirs:
        (target / directory).mkdir(parents=True, exist_ok=True)

    config = yaml.safe_load((source / "project.yaml").read_text())
    config["project"]["name"] = target.name
    if force or not (target / "ai/project.yaml").exists():
        (target / "ai/project.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    manifest = json.loads((source / "manifest.json").read_text())
    if not (target / "ai/assets/manifest.json").exists():
        (target / "ai/assets/manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    style_source = source / "style/style.yaml"
    style_target = target / "ai/styles/default/style.yaml"
    if force or not style_target.exists():
        shutil.copy2(style_source, style_target)
    for path in (source / "asset_types").glob("*.yaml"):
        destination = target / "ai/asset_types" / path.name
        if force or not destination.exists():
            shutil.copy2(path, destination)
    for path in (source / "recipes").glob("*.yaml"):
        destination = target / "ai/recipes" / path.name
        if force or not destination.exists():
            shutil.copy2(path, destination)
    agent_files = [(source / name, target / name) for name in ("AGENTS.md", "CLAUDE.md")]
    agent_files.extend((path, target / ".continue/rules" / path.name)
                       for path in (source / "continue").glob("*.md"))
    for source_file, destination in agent_files:
        if not destination.exists():
            shutil.copy2(source_file, destination)
    return target
