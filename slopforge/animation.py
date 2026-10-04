"""Validation for reusable, project-local character animation libraries."""
import re
from pathlib import Path, PurePosixPath

import yaml


CLIP_NAMES = {"idle", "walk", "run", "jump", "attack", "hurt", "death", "interact"}
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


def validate_animation_library(project_root, name):
    root = Path(project_root).resolve()
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("Animation library name must be a simple name")
    path = root / "ai/animation_libraries" / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Animation library not found: {path}")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Animation library must be a version 1 mapping")
    if data.get("skeleton_type") not in {"humanoid", "generic"}:
        raise ValueError("Animation library skeleton_type must be humanoid or generic")
    clips = data.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError("Animation library requires at least one clip")
    ids = set()
    resolved = []
    for clip in clips:
        if not isinstance(clip, dict) or not isinstance(clip.get("id"), str) or not _NAME.fullmatch(clip["id"]):
            raise ValueError("Animation clips require simple unique ids")
        if clip["id"] in ids:
            raise ValueError(f"Duplicate animation clip id {clip['id']!r}")
        ids.add(clip["id"])
        if clip.get("name") not in CLIP_NAMES:
            raise ValueError(f"Unsupported prototype animation name: {clip.get('name')!r}")
        relative = clip.get("path")
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError(f"Clip {clip['id']!r} path must be project-relative")
        posix = PurePosixPath(relative)
        if not posix.parts or posix.is_absolute() or ".." in posix.parts or posix.parts[0].endswith(":"):
            raise ValueError(f"Clip {clip['id']!r} path must stay inside the project")
        clip_path = (root / Path(*posix.parts)).resolve()
        if not clip_path.is_relative_to(root) or not clip_path.is_file() or not clip_path.stat().st_size:
            raise ValueError(f"Clip {clip['id']!r} file is missing or outside the project")
        if clip_path.suffix.lower() not in {".fbx", ".glb"}:
            raise ValueError(f"Clip {clip['id']!r} must reference FBX or GLB")
        if type(clip.get("loop")) is not bool or type(clip.get("root_motion")) is not bool:
            raise ValueError(f"Clip {clip['id']!r} requires boolean loop and root_motion settings")
        mapping = clip.get("bone_mapping", {})
        if not isinstance(mapping, dict) or any(not isinstance(source, str) or not source.strip()
                                                or not isinstance(target, str) or not target.strip()
                                                for source, target in mapping.items()):
            raise ValueError(f"Clip {clip['id']!r} bone_mapping must map non-empty bone names")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError(f"Clip {clip['id']!r} bone_mapping target names must be unique")
        resolved.append({**clip, "resolved_path": clip_path})
    return {**data, "clips": resolved, "path": path}
