"""Props generated open: edits of a concept candidate with its hinged part open, so the inside comes from a picture.

A chest generated closed has no inside to copy and its lid's cut wanders (HC5, HC6). The owner approves an open
picture as a second concept (2026-10-26); docs/superpowers/specs/2026-10-26-open-state-hinged-parts-design.md.
"""
import copy
import json
import subprocess
from pathlib import Path

from .backends.comfyui import generate_image
from .candidates import generate_candidates
from .parts import check_part_masks, make_part_masks
from .paths import resolve_workflow, tool_root
from .provenance import file_sha256
from .style import style_identity
from .validation import validate_image


def hinged_part(asset):
    """The one hinged part an open picture shows open."""
    hinges = [part for part in asset.get("parts") or [] if part["kind"] == "hinge"]
    if len(hinges) != 1:
        raise ValueError(f"An open picture shows one hinged part open; {asset['name']} declares {len(hinges)} "
                         "(for example --part 'lid=hinge:x:-100..0@back-bottom: the lid')")
    return hinges[0]


def open_prompt(asset, part, inside=None):
    """The edit instruction: the part swung open as far as it turns, the rest of the concept kept."""
    angle = round(max(abs(part["min"]), abs(part["max"])))
    edge = (part.get("anchor") or ["back"])[0]
    text = part.get("text") or f"the {part['name']}"
    lean = " so that it leans back behind the object" if edge == "back" else ""
    return (f"Open {text}: swing it open about {angle} degrees on its hinges along its {edge} edge{lean}. The same "
            f"{asset['description']} from the same viewpoint, keeping every detail, material and colour. The inside "
            f"is visible: {inside or 'plain inner walls and floor in the same material as the outside'}, and the "
            f"inner face of {text}. Same lighting, plain white background.")


def open_parent(asset, number):
    """The closed concept candidate an open picture may be made from or approved with."""
    parent = next((item for item in asset.get("candidates", {}).get("items", []) if item["number"] == number), None)
    if parent is None or parent.get("status") != "candidate" or not parent.get("artifact"):
        raise ValueError(f"Candidate {number} of {asset['name']} is not a concept candidate with a recorded image")
    if parent.get("open_of") is not None:
        raise ValueError(f"Candidate {number} is an open picture of candidate {parent['open_of']}; "
                         "name the closed concept it opens")
    return parent


def generate_open_candidates(project_root, config, asset_type, style, manifest, key, number, count, *,
                             inside=None, prompt=None):
    """Open pictures of concept candidate `number`, recorded as candidates with open_of; returns their records."""
    root = Path(project_root).resolve()
    asset = manifest["assets"][key]
    part = hinged_part(asset)
    workflow = config["asset_pipeline"]["workflows"].get("edit")
    if not workflow:
        raise ValueError("Open pictures are edits of the concept: set asset_pipeline.workflows.edit to "
                         "image_edit_qwen_api.json (Qwen-Image-Edit-2511; docs/WORKFLOWS.md)")
    parent = open_parent(asset, number)
    workflow_path = resolve_workflow(root, workflow)
    text = prompt or open_prompt(asset, part, inside)

    def backend(prompt_text, destination, seed, metadata):
        return generate_image(root, config, workflow_path, prompt_text, destination,
                              f"slopforge/{asset_type['name']}/{asset['name']}/open_{seed}", seed, metadata,
                              conditioning={"references": [{"path": parent["path"], "strength": 1.0}],
                                            "workflow_inputs": [{"image": {"node": "image", "input": "image"}}]})

    identity = {"asset_type": asset_type["name"], "brief": asset["description"], "generation_prompt": text,
                "open_of": {"number": number, "sha256": parent["artifact"]["sha256"]}, "part": part,
                "style": style_identity(style),
                "workflow": {"identifier": workflow_path.name, "sha256": file_sha256(workflow_path)}}
    generator = copy.deepcopy(asset.get("generator"))  # the asset's concept generator, not the edit's
    try:
        return generate_candidates(root, config, asset_type, style, asset["name"], text, count, manifest, key, backend,
                                   semantic_description=asset["description"], identity_inputs=identity,
                                   stage_inputs=[parent["artifact"]], record_fields={"open_of": number})
    finally:
        manifest["assets"][key]["generator"] = generator


def open_choice(asset, number, open_number):
    """The open picture approved with concept candidate `number`."""
    hinged_part(asset)
    chosen = next((item for item in asset.get("candidates", {}).get("items", []) if item["number"] == open_number), None)
    if (chosen is None or chosen.get("status") != "candidate" or chosen.get("open_of") != number
            or not chosen.get("artifact")):
        raise ValueError(f"Candidate {open_number} is not an open picture of candidate {number}")
    return chosen


def prepare_open_conditioning(root, config, python, picture, folder, parts, execution_id, picture_ref, artifact_ref):
    """The approved open picture's cut-out, reconstruction input and part masks, as conditioning artifacts:
    the mesh is generated and split from these. `artifact_ref` is the pipeline's artifact record factory."""
    cutout, input_3d, masks_dir = folder / "open_cutout.png", folder / "open_3d_input.png", folder / f"parts_open_{execution_id}"
    subprocess.run([python, str(tool_root() / "processing/prepare_3d_input.py"), "--input", str(picture),
                    "--cutout", str(cutout), "--output", str(input_3d)], check=True)
    checks = [validate_image(cutout, expected_format="PNG", require_alpha=True, report_path=cutout.relative_to(root)),
              validate_image(input_3d, expected_format="PNG", report_path=input_3d.relative_to(root))]
    if any(check["status"] == "failed" for check in checks):
        raise ValueError(f"Prepared open picture validation failed: {checks[0]['errors'] + checks[1]['errors']}")
    # the part lies elsewhere on the open picture: its own box (approve --open-part-box), else the text alone
    make_part_masks(config, cutout, [{**{k: v for k, v in part.items() if k not in ("box", "open_box")},
                                      **({"box": part["open_box"]} if part.get("open_box") else {})}
                                     for part in parts], masks_dir)
    stage = ("conditioning_preparation", 1)
    cutout_ref = artifact_ref(root, cutout, f"open-cutout:{execution_id}", "image.cutout.open", *stage, [picture_ref])
    refs = [cutout_ref,
            artifact_ref(root, input_3d, f"open-3d-input:{execution_id}", "image.3d_input.open", *stage, [picture_ref])]
    refs += [artifact_ref(root, masks_dir / f"{part['name']}.png", f"open-part-mask-{part['name']}:{execution_id}",
                          "image.part_mask.open", *stage, [cutout_ref])
             for part in parts if (masks_dir / f"{part['name']}.png").is_file()]
    refs += [artifact_ref(root, masks_dir / "masks.json", f"open-part-masks:{execution_id}", "data.part_masks.open",
                          *stage, [cutout_ref])]
    if (masks_dir / "parts_overlay.png").is_file():
        refs.append(artifact_ref(root, masks_dir / "parts_overlay.png", f"open-part-overlay:{execution_id}",
                                 "image.part_overlay.open", *stage, [cutout_ref]))
    return refs


def open_paths(root, refs, parts):
    """The open picture's cut-out, reconstruction input and masks folder from the conditioning stage's outputs;
    stops before mesh inference when a declared part is missing from the open picture."""
    by_type = {item["type"]: Path(root) / item["path"] for item in refs}
    masks = by_type["data.part_masks.open"]
    check_part_masks(json.loads(masks.read_text()), parts)
    return {"cutout": by_type["image.cutout.open"], "input_3d": by_type["image.3d_input.open"],
            "part_masks": masks.parent}
