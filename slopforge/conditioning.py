from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def resolve_conditioning(project_root, config, style):
    settings = config["asset_pipeline"].get("conditioning", {})
    strategy = settings.get("strategy", "text_only")
    max_references = int(settings.get("max_references", 3))
    strength = float(settings.get("strength", 0.65))
    approved = Path(style["_directory"]) / "references/approved"
    paths = sorted(
        path
        for path in approved.glob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )[:max_references]
    references = (
        [
            {"path": path.relative_to(project_root).as_posix(), "strength": strength}
            for path in paths
        ]
        if strategy == "reference"
        else []
    )
    return {
        "strategy": strategy,
        "references": references,
        "strength": strength,
        "backend": {"workflow": config["asset_pipeline"]["workflows"].get("image")},
    }


def ensure_supported(conditioning):
    if conditioning["strategy"] != "text_only":
        raise NotImplementedError(
            f"Conditioning strategy {conditioning['strategy']!r} is configured, but the current ComfyUI image workflow does not consume reference or LoRA conditioning. Use text_only until a compatible workflow is configured."
        )
