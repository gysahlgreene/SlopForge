"""Validation for reusable, project-local character animation libraries."""
import re
import json
import math
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

import yaml
from .character_rigging import _character_asset
from .manifest import register_artifact
from .paths import blender_executable, tool_root


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


def retarget_animation(project_root, config, manifest, character_selector, library_name, clip_id):
    """Retarget one library clip onto an explicitly approved character rig."""
    root = Path(project_root).resolve()
    library = validate_animation_library(root, library_name)
    clips = [clip for clip in library["clips"] if clip["id"] == clip_id]
    if len(clips) != 1:
        raise KeyError(f"Animation clip {clip_id!r} is not in library {library_name!r}")
    clip = clips[0]
    mapping = clip.get("bone_mapping", {})
    if not mapping:
        raise ValueError(f"Animation clip {clip_id!r} requires an explicit bone_mapping for retargeting")

    character = _character_asset(manifest, character_selector)
    rig = character.get("artifacts", {}).get("rig")
    if not rig or rig.get("status") != "ready" or rig.get("approval", {}).get("status") != "approved":
        raise ValueError("Animation retargeting requires a ready, approved character rig")
    if rig.get("type") not in {"model.rigged", "model.fbx"}:
        raise ValueError("Animation retargeting requires an FBX character rig")
    rig_path = _contained_file(root, rig.get("path"), "Character rig", {".fbx"})

    output_root = Path(config["asset_pipeline"]["output_root"])
    destination = (root / output_root / "Characters" / character["name"] / "Animations" /
                   f"{clip_id}.fbx").resolve()
    if not destination.is_relative_to(root):
        raise ValueError("Animation output directory must stay inside the project")
    if destination.exists():
        raise FileExistsError(f"Animation output already exists: {destination}")

    script = tool_root() / "blender/retarget_character_animation.py"
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="slopforge-retarget-") as temporary:
            request = Path(temporary) / "request.json"
            report = Path(temporary) / "result.json"
            request.write_text(json.dumps({"rig": str(rig_path), "animation": str(clip["resolved_path"]),
                "output": str(destination), "report": str(report), "bone_mapping": mapping,
                "loop": clip["loop"], "root_motion": clip["root_motion"]}))
            try:
                subprocess.run([blender_executable(config, root), "--background", "--factory-startup",
                                "--python", str(script), "--", str(request)], check=True)
            except subprocess.CalledProcessError:
                pass
            if not report.is_file():
                raise RuntimeError("Blender animation retargeting failed without a result report")
            result = json.loads(report.read_text())
            if result.get("status") != "complete":
                raise RuntimeError("Blender animation retargeting failed: " +
                                   str(result.get("error", "provider did not complete")))
            if not destination.is_file() or not destination.stat().st_size:
                raise RuntimeError("Blender animation retargeting produced no FBX output")
            displacement = result.get("max_vertex_displacement")
            frames = result.get("frames")
            if (not isinstance(displacement, (int, float)) or isinstance(displacement, bool)
                    or not math.isfinite(displacement) or displacement < 0
                    or not isinstance(frames, int) or frames < 1):
                raise RuntimeError("Blender animation report has invalid frame or deformation metrics")

        relative = destination.relative_to(root).as_posix()
        provenance = {"provider": "Blender action retarget", "source_library": library_name,
                      "source_clip": clip_id, "source_path": clip["path"],
                      "source_rig": rig["path"], "bone_mapping": mapping,
                      "loop": clip["loop"], "root_motion": clip["root_motion"]}
        artifact = register_artifact(manifest, character["id"], f"animation.{clip_id}", "animation.fbx",
                                     relative, status="candidate",
                                     derived_from=[{"asset_id": character["id"], "output_id": "rig"}],
                                     provenance=provenance, approval_status="pending",
                                     validation={"status": "not_run", "errors": [], "warnings": [
                                         "Retargeted motion and skin deformation require human review."],
                                         "measured": {"frames": frames,
                                                      "max_vertex_displacement": displacement}})
        character.setdefault("animations", {})[clip_id] = {
            "name": clip["name"], "artifact_id": f"animation.{clip_id}", "status": "review_required",
            "library": library_name, "source_clip": clip["path"], "loop": clip["loop"],
            "root_motion": clip["root_motion"], "frames": frames,
            "max_vertex_displacement": displacement, "bone_mapping": mapping}
        return {"status": "review_required", "artifact": artifact, "frames": frames,
                "max_vertex_displacement": displacement}
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _contained_file(root, relative, label, suffixes):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError(f"{label} path must be project-relative")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or not posix.parts or posix.parts[0].endswith(":"):
        raise ValueError(f"{label} path must stay inside the project")
    path = (root / Path(*posix.parts)).resolve()
    if not path.is_relative_to(root) or not path.is_file() or not path.stat().st_size:
        raise ValueError(f"{label} is missing or outside the project")
    if path.suffix.lower() not in suffixes:
        raise ValueError(f"{label} must be one of: {', '.join(sorted(suffixes))}")
    return path
