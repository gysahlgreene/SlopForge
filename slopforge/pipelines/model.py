import json
import os
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image

from ..backends.blender import inspect_model, process_model
from ..backends.comfyui import generate_image, generate_model, python_executable
from ..config import select_quality_tier
from ..candidates import generate_candidates
from ..conditioning import ensure_supported, resolve_conditioning
from ..manifest import save_manifest
from ..paths import resolve_workflow, tool_root
from ..provenance import generator_provenance
from ..style import build_prompt, style_identity
from ..taxonomy import output_path
from ..unity_material import build_unity_material, make_metallic_gloss, unity_cli
from ..validation import summarize_validation, validate_image, validate_model_outputs


def model_paths(project_root, config, name, asset_type="prop"):
    directory = output_path(project_root, config, asset_type, name)
    source, materials, previews = directory / "Source", directory / "Materials", directory / "Previews"
    return {"directory": directory, "concept": source / "concept.png", "cutout": source / "concept_cutout.png",
            "input_3d": source / "concept_3d_input.png", "glb": source / f"{name}.glb",
            "surface": materials / f"{name}_surface_source.png",
            "fbx": directory / f"{name}.fbx", "blend": directory / f"{name}_preview.blend",
            "basecolor": materials / f"{name}_basecolor.png", "normal": materials / f"{name}_normal.png",
            "roughness": materials / f"{name}_roughness.png", "metallic": materials / f"{name}_metallic.png",
            "metallic_gloss": materials / f"{name}_metallic_gloss.png",
            "unity_material": materials / f"{name}_preview_PBR.mat",
            "emission": materials / f"{name}_emission.png", "preview_front": previews / f"{name}_front.png",
            "preview_side": previews / f"{name}_side.png", "preview_rear": previews / f"{name}_rear.png",
            "processed_mesh": source / "processed_mesh.blend",
            "validation": directory / "validation.json"}


def material_candidate_paths(project_root, config, name, number, asset_type="prop"):
    asset_type_name = asset_type if isinstance(asset_type, str) else asset_type.get("name", "prop")
    directory = Path(project_root) / config["asset_pipeline"]["candidate_root"] / asset_type_name / name / f"material_{number:02d}"
    materials, previews = directory / "Materials", directory / "Previews"
    return {"directory": directory, "surface": directory / "surface_source.png",
            "fbx": directory / f"{name}.fbx", "blend": directory / f"{name}_preview.blend",
            "basecolor": materials / f"{name}_basecolor.png", "normal": materials / f"{name}_normal.png",
            "roughness": materials / f"{name}_roughness.png", "metallic": materials / f"{name}_metallic.png",
            "metallic_gloss": materials / f"{name}_metallic_gloss.png",
            "emission": materials / f"{name}_emission.png", "preview_front": previews / f"{name}_front.png",
            "preview_side": previews / f"{name}_side.png", "preview_rear": previews / f"{name}_rear.png",
            "validation": directory / "validation.json", "generator": directory / "generation.json"}


def _relative_outputs(root, paths, keys):
    return {key: paths[key].relative_to(root).as_posix() for key in keys}


def _generate_material_candidate(root, config, asset_type, asset, number, prompt, stage_mesh):
    paths = material_candidate_paths(root, config, asset["name"], number, asset_type)
    paths["directory"].mkdir(parents=True, exist_ok=True)
    paths["basecolor"].parent.mkdir(parents=True, exist_ok=True)
    candidate = {"number": number, "prompt": prompt, "status": "failed", "kind": "surface_swatch",
                 "seed": secrets.randbits(32), "path": paths["surface"].relative_to(root).as_posix(),
                 "validation": {"status": "not_run", "errors": [], "warnings": [], "measured": {}}}
    pipeline = config["asset_pipeline"]
    try:
        workflow = pipeline["workflows"].get("image")
        if not workflow:
            raise ValueError("Configure asset_pipeline.workflows.image in ai/project.yaml")
        metadata_path = paths["generator"]
        generate_image(root, config, resolve_workflow(root, workflow), prompt, paths["surface"],
                       f"slopforge/prop/{asset['name']}/material_{candidate['seed']}",
                       candidate["seed"], metadata_path)
        material_check = validate_image(paths["surface"], expected_format="PNG",
                                        report_path=paths["surface"].relative_to(root))
        if material_check["status"] == "failed":
            raise ValueError("Surface material validation failed: " + "; ".join(material_check["errors"]))
        info = json.loads(metadata_path.read_text()) if metadata_path.is_file() else {}
        candidate["generator"] = generator_provenance(info.get("workflow"), info)

        python = python_executable(root, config)
        subprocess.run([python, str(tool_root() / "processing/make_pbr_maps.py"), "--basecolor", str(paths["surface"]),
                        "--prompt", prompt,
                        "--normal", str(paths["normal"]), "--roughness", str(paths["roughness"]),
                        "--metallic", str(paths["metallic"]), "--emission", str(paths["emission"])], check=True)
        make_metallic_gloss(paths["metallic"], paths["roughness"], paths["metallic_gloss"])
        face_budget = int(pipeline["model_budgets"].get(asset_type.get("face_budget"), 30000))
        textures = [paths[key] for key in ("basecolor", "normal", "roughness", "metallic", "emission")]
        mesh_path = root / asset["source"]["processed_mesh"]
        process_model(root, config, root / asset["source"]["glb"], paths["fbx"], paths["blend"], textures,
                      face_budget, surface_source=paths["surface"],
                      preview_dir=paths["preview_front"].parent,
                      material_scale=float(pipeline.get("material_scale", 3.0)),
                      stage_mesh=mesh_path, reuse_stage_mesh=mesh_path.is_file())
        inspection = inspect_model(root, config, paths["blend"], paths["validation"], face_budget)
        check_paths = {key: paths[key] for key in
                        ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss", "emission",
                        "preview_front", "preview_side", "preview_rear")}
        candidate["validation"] = validate_model_outputs(check_paths, inspection, face_budget, root,
            max_components=asset_type.get("max_components"),
            max_nonmanifold_edges=asset_type.get("max_nonmanifold_edges"))
        paths["validation"].write_text(json.dumps(candidate["validation"], indent=2) + "\n")
        candidate["status"] = "candidate" if candidate["validation"]["status"] != "failed" else "failed"
        candidate["outputs"] = _relative_outputs(root, paths, check_paths)
        candidate["generator"].update({"workflow": info.get("workflow") or workflow,
                                        "seed": candidate["seed"]})
    except Exception as exc:
        candidate["error"] = str(exc)
        candidate["validation"]["errors"].append(str(exc))
    return candidate


def _native_material_candidate(root, config, asset_type, asset, number, mesh_info):
    paths = material_candidate_paths(root, config, asset["name"], number, asset_type)
    paths["basecolor"].parent.mkdir(parents=True, exist_ok=True)
    mesh_path = root / asset["source"]["glb"]
    for key in ("basecolor", "normal", "roughness", "metallic"):
        shutil.copy2(mesh_path.parent / mesh_info["textures"][key], paths[key])
    make_metallic_gloss(paths["metallic"], paths["roughness"], paths["metallic_gloss"])
    shutil.copy2(paths["basecolor"], paths["surface"])
    with Image.open(paths["basecolor"]) as image:
        Image.new("RGB", image.size, (0, 0, 0)).save(paths["emission"])
    paths["generator"].write_text(json.dumps(mesh_info, indent=2) + "\n")
    budget = int(config["asset_pipeline"]["model_budgets"].get(asset_type.get("face_budget"), 30000))
    textures = [paths[key] for key in ("basecolor", "normal", "roughness", "metallic", "emission")]
    process_model(root, config, mesh_path, paths["fbx"], paths["blend"], textures, budget,
                  preview_dir=paths["preview_front"].parent, preserve_uvs=True,
                  stage_mesh=root / asset["source"]["processed_mesh"])
    inspection = inspect_model(root, config, paths["blend"], paths["validation"], budget)
    keys = ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss", "emission",
            "preview_front", "preview_side", "preview_rear")
    validation = validate_model_outputs({key: paths[key] for key in keys}, inspection, budget, root,
        max_components=asset_type.get("max_components"),
        max_nonmanifold_edges=asset_type.get("max_nonmanifold_edges"))
    paths["validation"].write_text(json.dumps(validation, indent=2) + "\n")
    return {"number": number, "prompt": asset.get("generation_prompt", asset["description"]),
            "status": "candidate" if validation["status"] != "failed" else "failed",
            "kind": "mesh_pbr", "seed": mesh_info.get("seed"),
            "path": paths["surface"].relative_to(root).as_posix(), "validation": validation,
            "generator": generator_provenance(mesh_info.get("workflow"), mesh_info),
            "outputs": _relative_outputs(root, paths, keys)}


def generate(project_root, config, asset_type, style, name, description, count, manifest, key, *, generation_prompt=None,
             reference_paths=None, reference_categories=None, reference_entries=None, variations=None):
    root = Path(project_root).resolve()
    conditioning = resolve_conditioning(root, config, style, reference_paths=reference_paths,
                                        reference_categories=reference_categories, reference_entries=reference_entries)
    ensure_supported(conditioning)
    pipeline = config["asset_pipeline"]
    workflow = pipeline["workflows"].get("image")
    if not workflow:
        raise ValueError("Configure asset_pipeline.workflows.image in ai/project.yaml")
    workflow_path = resolve_workflow(root, workflow)
    prompt = generation_prompt or build_prompt(style, asset_type, description)
    conditioning_args = {"conditioning": conditioning} if conditioning["strategy"] == "reference" else {}

    def backend(prompt_text, destination, seed, metadata):
        return generate_image(root, config, workflow_path, prompt_text, destination,
                              f"slopforge/{asset_type['name']}/{name}/concept_{seed}", seed, metadata,
                              **conditioning_args)

    result = generate_candidates(root, config, asset_type, style, name, prompt, count, manifest, key, backend,
                                 semantic_description=description, variations=variations)
    record = manifest["assets"][key]
    record["description"] = description
    record["generation_prompt"] = prompt
    record["conditioning"] = {"strategy": conditioning["strategy"], "references_used": conditioning["references"]}
    record["generator"]["workflow"] = str(workflow)
    return result


def _style_matches_selected_concept(asset, style):
    number = asset.get("candidates", {}).get("selected")
    candidate = next((item for item in asset.get("candidates", {}).get("items", []) if item["number"] == number), None)
    expected = candidate.get("style") if candidate else None
    return (expected == style_identity(style) if expected else
            (asset.get("style"), asset.get("style_version")) == (style["name"], style["version"]))


def retexture(project_root, config, asset_type, style, manifest, key, *, material_prompt=None, count=1):
    root = Path(project_root).resolve()
    asset = manifest["assets"][key]
    items = asset.get("material_candidates", {}).get("items", [])
    if items and items[-1].get("kind") == "mesh_pbr":
        raise ValueError("This model has mesh-generated PBR regions. Surface-swatch retexturing would replace them; generate a revised concept to change its material design.")
    if not _style_matches_selected_concept(asset, style):
        raise ValueError("Concept style has changed; restore the original style or generate a new concept")
    paths = model_paths(root, config, asset["name"], asset_type)
    if not paths["glb"].is_file():
        raise ValueError("No generated mesh exists; approve a concept candidate first")
    asset.setdefault("source", {})["processed_mesh"] = paths["processed_mesh"].relative_to(root).as_posix()
    if count < 1:
        raise ValueError("Texture candidate count must be at least 1")
    prompt = material_prompt or build_prompt(style, asset_type, asset["description"], mode="material")
    existing = asset.setdefault("material_candidates", {"items": [], "selected": None})["items"]
    start = max((int(item["number"]) for item in existing), default=0) + 1
    results = []
    for number in range(start, start + count):
        candidate = _generate_material_candidate(root, config, asset_type, asset, number, prompt, paths["processed_mesh"])
        existing.append(candidate)
        results.append(candidate)
    return results


def approve_texture(project_root, config, manifest, key, number, force=False, *, asset_type="prop"):
    root = Path(project_root).resolve()
    asset = manifest["assets"][key]
    candidate = next((item for item in asset.get("material_candidates", {}).get("items", [])
                      if item["number"] == number), None)
    if candidate is None or candidate.get("status") != "candidate":
        raise ValueError(f"Material candidate {number} is not valid for {asset['name']}")
    unity_cli(root)
    paths = model_paths(root, config, asset["name"], asset_type)
    candidate_paths = material_candidate_paths(root, config, asset["name"], number, asset_type)
    candidate.setdefault("outputs", {})
    if not candidate_paths["metallic_gloss"].is_file():
        make_metallic_gloss(candidate_paths["metallic"], candidate_paths["roughness"],
                            candidate_paths["metallic_gloss"])
    candidate["outputs"]["metallic_gloss"] = candidate_paths["metallic_gloss"].relative_to(root).as_posix()
    final_keys = ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss", "emission",
                  "preview_front", "preview_side", "preview_rear")
    existing = [paths[name] for name in (*final_keys, "unity_material") if paths[name].exists()]
    if existing and not (force or config["asset_pipeline"].get("overwrite_existing")):
        raise FileExistsError(f"Approved model outputs exist; pass --force to replace: {existing[0]}")
    sources = {name: root / candidate["outputs"][name] for name in final_keys}
    missing = [str(path) for path in sources.values() if not path.is_file() or not path.stat().st_size]
    if missing:
        raise ValueError("Material candidate output missing or empty: " + missing[0])
    for name in final_keys:
        destination = paths[name]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            shutil.copy2(sources[name], temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    build_unity_material(root, paths["fbx"], paths["directory"] / "Materials" /
                         f"{asset['name']}_preview_PBR.mat",
                         {name: paths[name] for name in ("basecolor", "normal", "metallic_gloss", "emission")})
    validation = dict(candidate["validation"])
    validation["measured"] = dict(validation.get("measured", {}))
    validation["measured"].update({name: paths[name].relative_to(root).as_posix() for name in final_keys})
    validation["measured"]["unity_material"] = paths["unity_material"].relative_to(root).as_posix()
    paths["validation"].write_text(json.dumps(validation, indent=2) + "\n")
    candidate["approval"] = "approved"
    asset["material_candidates"]["selected"] = number
    asset["material_prompt"] = candidate["prompt"]
    asset["generator"]["material"] = candidate.get("generator")
    asset["generator"]["workflow"]["material"] = (candidate.get("generator") or {}).get("workflow")
    asset["generator"]["seed"]["material"] = candidate.get("seed")
    asset["outputs"] = _relative_outputs(root, paths, (*final_keys, "unity_material", "validation"))
    asset["validation"] = validation
    asset["status"] = "ready"
    asset["updated_at"] = datetime.now(timezone.utc).isoformat()
    return validation


def approve(project_root, config, asset_type, style, manifest, key, number, force=False, *,
            material_prompt=None, material_count=None, quality_tier=None):
    root = Path(project_root).resolve()
    asset = manifest["assets"][key]
    candidate = next((item for item in asset.get("candidates", {}).get("items", []) if item["number"] == number), None)
    if candidate is None or candidate.get("status") != "candidate":
        raise ValueError(f"Candidate {number} is not valid for {asset['name']}")
    candidate_quality = (candidate.get("generator") or {}).get("quality", {}).get("tier")
    config = select_quality_tier(config, quality_tier or candidate_quality or
                                 config["asset_pipeline"].get("selected_quality_tier", "normal"))
    pipeline = config["asset_pipeline"]
    if pipeline["workflows"].get("model") and material_prompt:
        raise ValueError("The mesh-texturing workflow uses the selected concept's material design. Put the intended materials in --image-prompt; --material-prompt is for surface swatches.")
    expected_style = candidate.get("style")
    if ((expected_style and expected_style != style_identity(style)) or
            (not expected_style and (asset.get("style"), asset.get("style_version")) != (style["name"], style["version"]))):
        raise ValueError("Candidate style has changed; activate the original unchanged style pack or generate new candidates before 3D approval")
    conditioning = resolve_conditioning(root, config, style)
    ensure_supported(conditioning)
    paths = model_paths(root, config, asset["name"], asset_type)
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
    concept_workflow = pipeline["workflows"].get("image")
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
        workflow = pipeline["workflows"].get("model")
        print("3D stage: mesh and PBR generation..." if workflow else "3D stage: Hunyuan3D mesh generation...", flush=True)
        if workflow:
            budget = int(pipeline["model_budgets"].get(asset_type.get("face_budget"), 30000))
            generate_model(root, config, paths["cutout"], asset["name"], paths["glb"], model_metadata, mesh_seed, budget)
        else:
            generate_model(root, config, paths["input_3d"], asset["name"], paths["glb"], model_metadata, mesh_seed)
        mesh_info = json.loads(model_metadata.read_text())
        asset["source"].update({"cutout": paths["cutout"].relative_to(root).as_posix(),
                                "3d_input": paths["input_3d"].relative_to(root).as_posix(),
                                "glb": paths["glb"].relative_to(root).as_posix(),
                                "processed_mesh": paths["processed_mesh"].relative_to(root).as_posix()})
        material_prompt = material_prompt or build_prompt(style, asset_type, prompt, mode="material")
        count = material_count or int(pipeline["defaults"].get("material_candidates", 2))
        if count < 1:
            raise ValueError("Material candidate count must be at least 1")
        if mesh_info.get("textured"):
            print("3D stage: preserving generated UVs and PBR maps for mesh previews...", flush=True)
            start = max((item["number"] for item in asset.get("material_candidates", {}).get("items", [])), default=0) + 1
            material_candidates = [_native_material_candidate(root, config, asset_type, asset, start, mesh_info)]
        else:
            print(f"3D stage: generating {count} material candidates on the saved mesh...", flush=True)
            material_candidates = []
            start = max((item["number"] for item in asset.get("material_candidates", {}).get("items", [])), default=0) + 1
            for material_number in range(start, start + count):
                material_candidates.append(_generate_material_candidate(root, config, asset_type, asset,
                                                                          material_number, material_prompt,
                                                                          paths["processed_mesh"]))
        previous = asset.get("material_candidates", {}).get("items", [])
        for item in previous:
            item["approval"] = "superseded"
            if item.get("status") == "candidate":
                item["status"] = "superseded"
        asset["material_candidates"] = {"items": previous + material_candidates, "selected": None}
        viable = [item for item in material_candidates if item["status"] == "candidate"]
        if not viable:
            reasons = "; ".join(item.get("error", "validation failed") for item in material_candidates)
            raise ValueError(f"No valid material candidates generated for {asset['name']}: {reasons}")
        first = viable[0]
        asset["conditioning"] = {"strategy": conditioning["strategy"], "references_used": conditioning["references"]}
        asset["generator"] = {"workflow": {"concept": concept_workflow, "mesh": mesh_info.get("workflow"),
                                             "material": (first.get("generator") or {}).get("workflow")},
                               "model": mesh_info.get("model"),
                               "seed": {"concept": candidate.get("seed"), "mesh": mesh_info.get("seed")},
                               "quality": mesh_info.get("quality") or (candidate.get("generator") or {}).get("quality")}
        asset["material_prompt"] = first["prompt"]
        asset["validation"] = {"status": "not_run", "errors": [], "warnings": [
            "Choose a material candidate and approve it before using the Unity output."], "measured": {}}
        asset["status"] = "awaiting_texture_approval"
        asset["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_manifest(root / pipeline["manifest"], manifest)
        print("Material candidate previews:")
        for item in material_candidates:
            print(f"  {item['number']}: {item['outputs'].get('preview_front', item['path'])} ({item['status']})")
        return {"status": asset["status"], "material_candidates": material_candidates}
    except Exception as exc:
        asset["status"] = "failed"
        asset.setdefault("validation", {"status": "not_run", "warnings": [], "measured": {}})
        asset["validation"].setdefault("warnings", []).append(f"Pipeline stopped: {exc}")
        save_manifest(root / pipeline["manifest"], manifest)
        raise
