import copy
import shutil
import tempfile
from pathlib import Path

from ..backends.comfyui import generate_image
from ..candidates import approve_image_candidate, generate_candidates
from ..conditioning import ensure_supported, resolve_conditioning
from ..paths import resolve_workflow
from ..provenance import file_sha256
from ..providers import NOTICES_FILE, combine_rights, require_shippable, rights_of, write_notices
from ..config import workflow_node_inputs
from ..style import build_prompt, style_identity
from ..surface import make_cutout, make_tiling_material
from ..validation import validate_image


def generate(project_root, config, asset_type, style, name, description, count, manifest, key, *, generation_prompt=None,
             reference_paths=None, reference_categories=None, reference_entries=None, variations=None):
    conditioning = resolve_conditioning(project_root, config, style, reference_paths=reference_paths,
                                        reference_categories=reference_categories, reference_entries=reference_entries)
    ensure_supported(conditioning)
    prompt = generation_prompt or build_prompt(style, asset_type, description, asset_type.get("prompt_mode", "asset"))
    workflow = config["asset_pipeline"]["workflows"].get("image")
    if not workflow:
        raise ValueError("Configure asset_pipeline.workflows.image in ai/project.yaml")
    workflow_path = resolve_workflow(project_root, workflow)
    conditioning_args = {"conditioning": conditioning} if conditioning["strategy"] == "reference" else {}

    def backend(prompt_text, destination, seed, metadata):
        return generate_image(project_root, config, workflow_path, prompt_text, destination,
                              f"slopforge/{asset_type['name']}/{name}/candidate_{seed}", seed, metadata,
                              **conditioning_args)

    identity_inputs = None
    if asset_type.get("name") == "prop":
        identity_inputs = {"asset_type": "prop", "brief": description, "generation_prompt": prompt,
                           "style": style_identity(style),
                           "workflow": {"identifier": Path(workflow_path).name,
                                        "sha256": file_sha256(workflow_path) if Path(workflow_path).is_file() else None,
                                        "configured_inputs": workflow_node_inputs(config, "image", Path(workflow_path).name)},
                           "quality": {"tier": config["asset_pipeline"].get("selected_quality_tier", "normal"),
                                       "settings": config["asset_pipeline"].get("quality_settings", {})},
                           "conditioning": {"strategy": conditioning["strategy"],
                               "references": [{"sha256": item.get("sha256"), "strength": item.get("strength")}
                                              for item in conditioning.get("references", [])]}}
    candidates = generate_candidates(project_root, config, asset_type, style, name, prompt, count, manifest, key, backend,
                                    semantic_description=description, variations=variations,
                                    identity_inputs=identity_inputs)
    record = manifest["assets"][key]
    record["description"] = description
    record["generation_prompt"] = prompt
    record["conditioning"] = {"strategy": conditioning["strategy"], "references_used": conditioning["references"]}
    record["generator"]["workflow"] = workflow
    return candidates


def _candidate_rights(asset, number):
    """What the candidate's ComfyUI worker recorded about its models' terms; nothing recorded is unknown."""
    candidate = next((item for item in (asset.get("candidates") or {}).get("items", [])
                      if item.get("number") == number), None)
    recorded = ((candidate or {}).get("generator") or {}).get("output_rights")
    return recorded if isinstance(recorded, list) else [
        {"source": f"candidate {number}", "status": "unknown",
         "reason": "its worker recorded no output rights (made before they were recorded: generate it again)"}]


def _deliver(root, asset, entries):
    """The image pipeline publishes into the Unity project: its rights decide whether it may (docs/COMFYUI.md)."""
    rights = require_shippable(combine_rights(entries), asset.get("name", "the image"), "approve")
    asset["output_rights"] = rights
    published = root / asset["outputs"]["image"]
    write_notices(published.parent, asset.get("name", published.stem), rights, f"{published.stem}.{NOTICES_FILE}")
    return rights


def approve(project_root, config, asset_type, manifest, key, number, force=False):
    processing = asset_type.get("processing")
    entries = _candidate_rights(manifest["assets"][key], number)
    # Refused before anything is published; the processing's own rights are checked after it runs, below.
    require_shippable(combine_rights(entries), manifest["assets"][key].get("name", key), "approve")
    if not processing:
        result = approve_image_candidate(project_root, config, asset_type, manifest, key, number, force)
        if result["status"] != "failed":
            _deliver(Path(project_root).resolve(), manifest["assets"][key], entries)
        return result
    root = Path(project_root).resolve()
    snapshot = copy.deepcopy(manifest["assets"][key])
    # Processing runs after the published image is replaced, so a failure puts back the files and the record the
    # saved manifest still describes (2026-10-23 audit: a failed cut-out left an uncut image under the old record).
    name = snapshot.get("outputs", {}).get("image")
    published = [root / name, (root / name).with_suffix("")] if name else []  # the image and its tiling maps
    with tempfile.TemporaryDirectory(prefix="slopforge-approve-") as backup:
        saved = {}
        for index, path in enumerate(published):
            if path.exists():
                saved[path] = Path(backup) / str(index)
                (shutil.copytree if path.is_dir() else shutil.copy2)(path, saved[path])
        try:
            result = approve_image_candidate(project_root, config, asset_type, manifest, key, number, force)
            if result["status"] == "failed":
                return result
            result = _process(root, config, asset_type, manifest["assets"][key], processing)
            asset = manifest["assets"][key]
            _deliver(root, asset, entries + _processing_rights(config, asset.get("processing") or {}))
            return result
        except BaseException:
            image = manifest["assets"][key].get("outputs", {}).get("image")
            for path in {*published, *((root / image, (root / image).with_suffix("")) if image else ())}:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            for path, kept in saved.items():
                (shutil.copytree if kept.is_dir() else shutil.copy2)(kept, path)
            manifest["assets"][key] = snapshot
            raise


def _processing_rights(config, record):
    """A cut-out is BiRefNet's; a tiling material's inpaint and upscale are what their workers recorded."""
    if record.get("kind") == "cutout":
        return rights_of(config, "background_removal")
    entries = []
    for step in ("seamless", "upscale"):
        if step in record:
            recorded = record[step].get("output_rights") if isinstance(record[step], dict) else None
            entries += recorded if isinstance(recorded, list) else [
                {"source": f"tiling {step}", "status": "unknown", "reason": "its run recorded no output rights"}]
    return entries


def _process(root, config, asset_type, asset, processing):
    image = root / asset["outputs"]["image"]
    if processing == "cutout":
        size = make_cutout(root, config, image, image)
        asset["processing"] = {"kind": "cutout", "size": list(size), "sha256": file_sha256(image)}
    elif processing == "tiling_material":
        paths, provenance = make_tiling_material(root, config, image, asset.get("generation_prompt") or asset["description"],
                                                 image.with_suffix(""), seams=asset_type.get("seams", "cut"))
        asset["outputs"].update({f"tiling_{name}": path.relative_to(root).as_posix() for name, path in paths.items()})
        asset["processing"] = {"kind": "tiling_material", **provenance}
    else:
        raise ValueError(f"Asset type {asset_type['name']} declares unknown processing {processing!r}")
    # Measure what is published now, not the image before processing.
    asset["validation"] = validate_image(image, expected_format=asset_type.get("format", "PNG"),
                                         require_alpha=bool(asset_type.get("alpha_required", False)),
                                         report_path=image.relative_to(root))
    asset["status"] = "ready" if asset["validation"]["status"] != "failed" else "failed"
    return asset["validation"]
