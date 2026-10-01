from pathlib import Path

from ..backends.comfyui import generate_image
from ..candidates import approve_image_candidate, generate_candidates
from ..conditioning import ensure_supported, resolve_conditioning
from ..paths import resolve_workflow
from ..style import build_prompt


def generate(project_root, config, asset_type, style, name, description, count, manifest, key):
    conditioning = resolve_conditioning(project_root, config, style)
    ensure_supported(conditioning)
    prompt = build_prompt(style, asset_type, description, asset_type.get("prompt_mode", "asset"))
    workflow = config["asset_pipeline"]["workflows"].get("image")
    if not workflow:
        raise ValueError("Configure asset_pipeline.workflows.image in ai/project.yaml")
    workflow_path = resolve_workflow(project_root, workflow)

    def backend(prompt_text, destination, seed, metadata):
        return generate_image(project_root, config, workflow_path, prompt_text, destination,
                              f"slopforge/{asset_type['name']}/{name}/candidate_{seed}", seed, metadata)

    candidates = generate_candidates(project_root, config, asset_type, style, name, prompt, count, manifest, key, backend)
    record = manifest["assets"][key]
    record["description"] = description
    record["conditioning"] = {"strategy": conditioning["strategy"], "references_used": conditioning["references"]}
    record["generator"]["workflow"] = workflow
    return candidates


def approve(project_root, config, asset_type, manifest, key, number, force=False):
    return approve_image_candidate(project_root, config, asset_type, manifest, key, number, force)
