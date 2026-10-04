from pathlib import Path


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def resolve_conditioning(project_root, config, style, *, reference_paths=None, reference_categories=None,
                        reference_entries=None):
    root = Path(project_root).resolve()
    settings = config["asset_pipeline"].get("conditioning", {})
    strategy = settings.get("strategy", "text_only")
    max_references = int(settings.get("max_references", 3))
    strength = float(settings.get("strength", 0.65))
    if max_references < 1 or not 0 <= strength <= 1:
        raise ValueError("conditioning.max_references must be positive and strength must be between 0 and 1")
    if strategy != "reference" and (reference_paths or reference_categories or reference_entries is not None):
        raise ValueError("Reference selection was provided while conditioning.strategy is not 'reference'")
    approved = Path(style["_directory"]) / "references/approved"
    references = []
    if strategy == "reference":
        if reference_entries is not None and (reference_paths or reference_categories):
            raise ValueError("Choose a reference library or style reference selectors, not both")
        if reference_entries is not None:
            selected = [(Path(entry["path"]), entry) for entry in reference_entries]
        elif reference_paths:
            selected = [(Path(path).expanduser(), None) for path in reference_paths]
        elif reference_categories:
            selected = []
        else:
            selected = [(path, None) for path in sorted(path for path in approved.glob("*")
                                                        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)]
        for category in reference_categories or ():
            if not category or Path(category).name != category or category in {".", ".."}:
                raise ValueError(f"Invalid reference category: {category!r}")
            selected.extend((path, None) for path in sorted(path for path in (approved / category).glob("*")
                                                            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS))
        paths = []
        for path, entry in selected:
            if entry and entry.get("status") != "ready":
                raise ValueError(f"Reference library entry {entry.get('id')!r} is {entry.get('status')}; review its file/hash")
            path = path if path.is_absolute() else root / path
            path = path.resolve()
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                raise ValueError(f"Reference is not an existing image: {path}")
            if entry is None and not path.is_relative_to(approved.resolve()):
                raise ValueError(f"Reference must be in the selected style's approved reference library: {path}")
            if path not in [item[0] for item in paths]:
                paths.append((path, entry))
        if (reference_paths or reference_entries is not None) and len(paths) > max_references:
            raise ValueError(f"Selected {len(paths)} references, exceeding conditioning.max_references={max_references}")
        for path, entry in paths[:max_references]:
            item = {"path": path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path),
                    "strength": entry.get("strength") if entry and entry.get("strength") is not None else strength}
            if entry:
                item.update({"library_entry_id": entry["id"], "category": entry.get("category"),
                             "sha256": entry.get("sha256"), "expected_sha256": entry.get("expected_sha256"),
                             "source": entry.get("source")})
            references.append(item)
    return {"strategy": strategy, "references": references, "strength": strength,
            "workflow_inputs": settings.get("workflow_inputs", []),
            "backend": {"workflow": config["asset_pipeline"]["workflows"].get("image")}}


def ensure_supported(conditioning, workflow_inputs=None):
    if conditioning["strategy"] == "text_only":
        return
    if conditioning["strategy"] != "reference":
        raise NotImplementedError(f"Conditioning strategy {conditioning['strategy']!r} is not supported")
    if not conditioning.get("references"):
        raise ValueError("Reference conditioning is enabled but no approved reference images were selected")
    slots = workflow_inputs if workflow_inputs is not None else conditioning.get("workflow_inputs", [])
    if not slots:
        raise NotImplementedError("Reference conditioning requires configured conditioning.workflow_inputs for the selected ComfyUI workflow")
    if len(conditioning.get("references", [])) > len(slots):
        raise ValueError(f"Selected {len(conditioning['references'])} references but workflow maps only {len(slots)} reference_inputs")
