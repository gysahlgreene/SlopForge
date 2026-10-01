import json
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..backends.blender import inspect_model, process_model
from ..backends.comfyui import generate_image, generate_model, python_executable
from ..candidates import generate_candidates
from ..conditioning import ensure_supported, resolve_conditioning
from ..manifest import save_manifest
from ..paths import resolve_workflow, tool_root
from ..style import build_prompt, style_identity
from ..taxonomy import output_path
from ..validation import summarize_validation, validate_image, validate_model_outputs


def model_paths(project_root, config, name):
    directory = output_path(project_root, config, "prop", name)
    source, materials = directory / "Source", directory / "Materials"
    return {"directory": directory, "concept": source / "concept.png", "cutout": source / "concept_cutout.png",
            "input_3d": source / "concept_3d_input.png", "glb": source / f"{name}.glb",
            "fbx": directory / f"{name}.fbx", "blend": directory / f"{name}_preview.blend",
            "basecolor": materials / f"{name}_basecolor.png", "normal": materials / f"{name}_normal.png",
            "roughness": materials / f"{name}_roughness.png", "metallic": materials / f"{name}_metallic.png",
            "emission": materials / f"{name}_emission.png", "validation": directory / "validation.json"}


def generate(project_root, config, asset_type, style, name, description, count, manifest, key):
    root = Path(project_root).resolve()
    conditioning = resolve_conditioning(root, config, style)
    ensure_supported(conditioning)
    pipeline = config["asset_pipeline"]
    workflow = pipeline["workflows"].get("image")
    if not workflow:
        raise ValueError("Configure asset_pipeline.workflows.image in ai/project.yaml")
    workflow_path = resolve_workflow(root, workflow)
    prompt = build_prompt(style, asset_type, description)

    def backend(prompt_text, destination, seed, metadata):
        return generate_image(root, config, workflow_path, prompt_text, destination,
                              f"slopforge/{asset_type['name']}/{name}/concept_{seed}", seed, metadata)

    result = generate_candidates(root, config, asset_type, style, name, prompt, count, manifest, key, backend,
                                 semantic_description=description)
    record = manifest["assets"][key]
    record["description"] = description
    record["conditioning"] = {"strategy": conditioning["strategy"], "references_used": conditioning["references"]}
    record["generator"]["workflow"] = str(workflow)
    return result


def approve(project_root, config, asset_type, style, manifest, key, number, force=False):
    root = Path(project_root).resolve()
    asset = manifest["assets"][key]
    candidate = next((item for item in asset.get("candidates", {}).get("items", []) if item["number"] == number), None)
    if candidate is None or candidate.get("status") != "candidate":
        raise ValueError(f"Candidate {number} is not valid for {asset['name']}")
    expected_style = candidate.get("style")
    if ((expected_style and expected_style != style_identity(style)) or
            (not expected_style and (asset.get("style"), asset.get("style_version")) != (style["name"], style["version"]))):
        raise ValueError("Candidate style has changed; activate the original unchanged style pack or generate new candidates before 3D approval")
    conditioning = resolve_conditioning(root, config, style)
    ensure_supported(conditioning)
    paths = model_paths(root, config, asset["name"])
    existing = [path for name, path in paths.items() if name != "directory" and path.exists()]
    if existing and not (force or config["asset_pipeline"].get("overwrite_existing")):
        raise FileExistsError(f"Model outputs exist; pass --force to replace: {existing[0]}")
    paths["concept"].parent.mkdir(parents=True, exist_ok=True)
    paths["basecolor"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / candidate["path"], paths["concept"])
    candidate["approval"] = "approved"
    asset["candidates"]["selected"] = number
    asset["status"] = "processing"
    asset["description"] = candidate.get("description", asset["description"])
    asset["style"], asset["style_version"] = style["name"], style["version"]
    asset["source"] = {"concept": paths["concept"].relative_to(root).as_posix()}
    pipeline = config["asset_pipeline"]
    save_manifest(root / pipeline["manifest"], manifest)
    prompt = asset["description"]
    workflow = pipeline["workflows"].get("image")
    if not workflow:
        raise ValueError("Configure asset_pipeline.workflows.image in ai/project.yaml")
    workflow_path = resolve_workflow(root, workflow)
    python = python_executable(root, config)
    try:
        print("3D stage: background removal and isolated reconstruction input...", flush=True)
        subprocess.run([python, str(tool_root() / "processing/prepare_3d_input.py"), "--input", str(paths["concept"]),
                        "--cutout", str(paths["cutout"]), "--output", str(paths["input_3d"])], check=True)
        cutout_check = validate_image(paths["cutout"], expected_format="PNG", require_alpha=True, report_path=paths["cutout"].relative_to(root))
        input_check = validate_image(paths["input_3d"], expected_format="PNG", report_path=paths["input_3d"].relative_to(root))
        if cutout_check["status"] == "failed" or input_check["status"] == "failed":
            raise ValueError(f"Prepared concept validation failed: {cutout_check['errors'] + input_check['errors']}")

        model_metadata = paths["directory"] / "model_generation.json"
        mesh_seed = secrets.randbits(32)
        print("3D stage: Hunyuan3D mesh generation...", flush=True)
        generate_model(root, config, paths["input_3d"], asset["name"], paths["glb"], model_metadata, mesh_seed)
        mesh_info = json.loads(model_metadata.read_text())

        material_prompt = build_prompt(style, asset_type, prompt, mode="material")
        material_metadata = paths["directory"] / "material_generation.json"
        material_seed = secrets.randbits(32)
        print("3D stage: material base-colour generation...", flush=True)
        generate_image(root, config, workflow_path, material_prompt, paths["basecolor"],
                       f"slopforge/{asset_type['name']}/{asset['name']}/material", material_seed, material_metadata)
        base_check = validate_image(paths["basecolor"], expected_format="PNG", report_path=paths["basecolor"].relative_to(root))
        if base_check["status"] == "failed":
            raise ValueError(f"Base colour validation failed: {base_check['errors']}")

        print("3D stage: v1 heuristic PBR maps...", flush=True)
        subprocess.run([python, str(tool_root() / "processing/make_pbr_maps.py"), "--basecolor", str(paths["basecolor"]),
                        "--prompt", prompt, "--normal", str(paths["normal"]), "--roughness", str(paths["roughness"]),
                        "--metallic", str(paths["metallic"]), "--emission", str(paths["emission"])], check=True)
        face_budget = int(pipeline["model_budgets"].get(asset_type.get("face_budget"), 30000))
        textures = [paths[name] for name in ("basecolor", "normal", "roughness", "metallic", "emission")]
        print("3D stage: Blender cleanup, UVs, materials, BLEND and FBX export...", flush=True)
        process_model(root, config, paths["glb"], paths["fbx"], paths["blend"], textures, face_budget)
        print("3D stage: mesh and output validation...", flush=True)
        inspection = inspect_model(root, config, paths["blend"], paths["validation"], face_budget)
        output_validation = validate_model_outputs({name: paths[name] for name in
            ("glb", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "emission")}, inspection, face_budget, root)
        paths["validation"].write_text(json.dumps(output_validation, indent=2) + "\n")
        asset["validation"] = output_validation
        if output_validation["status"] == "failed":
            raise ValueError(summarize_validation(output_validation))

        asset["status"] = "ready"
        asset["conditioning"] = {"strategy": conditioning["strategy"], "references_used": conditioning["references"]}
        asset["generator"] = {"workflow": {"concept": workflow, "mesh": mesh_info.get("workflow"), "material": workflow},
                               "model": mesh_info.get("model"),
                               "seed": {"concept": candidate.get("seed"), "mesh": mesh_info.get("seed"), "material": material_seed}}
        asset["source"].update({"cutout": paths["cutout"].relative_to(root).as_posix(),
                                "3d_input": paths["input_3d"].relative_to(root).as_posix(),
                                "glb": paths["glb"].relative_to(root).as_posix()})
        asset["outputs"] = {name: paths[name].relative_to(root).as_posix() for name in
                             ("fbx", "blend", "basecolor", "normal", "roughness", "metallic", "emission", "validation")}
        asset["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_manifest(root / pipeline["manifest"], manifest)
        print(summarize_validation(output_validation))
        return output_validation
    except Exception as exc:
        asset["status"] = "failed"
        asset.setdefault("validation", {"status": "not_run", "warnings": [], "measured": {}})
        asset["validation"].setdefault("warnings", []).append(f"Pipeline stopped: {exc}")
        save_manifest(root / pipeline["manifest"], manifest)
        raise
