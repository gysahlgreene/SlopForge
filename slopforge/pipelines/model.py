import json
import hashlib
import os
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image

from ..backends.blender import inspect_model, process_model
from ..backends.comfyui import generate_image, generate_model, python_executable, workflow_mask_errors
from ..config import select_quality_tier, workflow_node_inputs
from ..candidates import generate_candidates
from ..conditioning import ensure_supported, resolve_conditioning
from ..manifest import (save_manifest, load_manifest, start_execution, start_stage, begin_stage,
                        finish_stage, finish_execution)
from ..paths import resolve_workflow, tool_root
from ..provenance import generator_provenance, file_sha256
from ..style import build_prompt, style_identity
from ..taxonomy import output_path
from ..unity_material import build_unity_material, make_metallic_gloss, unity_cli
from ..validation import summarize_validation, validate_image, validate_model_outputs


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_ref(root, path, artifact_id, kind, stage, attempt, derived_from=()):
    path = Path(path)
    return {"id": artifact_id, "type": kind, "path": path.resolve().relative_to(Path(root).resolve()).as_posix(),
            "sha256": file_sha256(path), "stage": stage, "attempt": attempt,
            "derived_from": [{"artifact_id": item["id"], "sha256": item["sha256"]}
                             for item in derived_from]}


def _persist_reload(root, pipeline, manifest):
    path = Path(root) / pipeline["manifest"]
    from .. import SCHEMA_VERSION
    manifest.setdefault("schema_version", SCHEMA_VERSION)
    save_manifest(path, manifest)
    return _reload_manifest(root, pipeline, manifest)


def _reload_manifest(root, pipeline, manifest):
    latest = load_manifest(Path(root) / pipeline["manifest"])
    assets = manifest.setdefault("assets", {})
    latest_assets = latest.get("assets", {})
    for key in list(assets):
        if key not in latest_assets:
            del assets[key]
    for key, latest_asset in latest_assets.items():
        if key in assets:
            assets[key].clear()
            assets[key].update(latest_asset)
        else:
            assets[key] = latest_asset
    manifest.update({key: value for key, value in latest.items() if key != "assets"})
    manifest["assets"] = assets
    return manifest


def _execution_stage(asset, execution_id, name, attempt):
    execution = next(item for item in asset["executions"] if item["id"] == execution_id)
    return execution, next(item for item in reversed(execution["stages"])
                           if item["name"] == name and item["attempt"] == attempt)


def _lineage_start(context, name, attempt, inputs, settings):
    if not context:
        return None
    asset = context["manifest"]["assets"][context["key"]]
    execution = next(item for item in asset["executions"] if item["id"] == context["execution_id"])
    stage = start_stage(execution, name, attempt, inputs, settings, {})
    begin_stage(stage)
    _persist_reload(context["root"], context["pipeline"], context["manifest"])
    asset = context["manifest"]["assets"][context["key"]]
    return _execution_stage(asset, context["execution_id"], name, attempt)[1]


def _lineage_finish(context, name, attempt, outputs, *, error=None):
    if not context:
        return []
    asset = context["manifest"]["assets"][context["key"]]
    execution, stage = _execution_stage(asset, context["execution_id"], name, attempt)
    refs = []
    if error is None:
        root = context["root"]
        parents = context["upstream"]
        for index, (path, kind) in enumerate(outputs):
            path = Path(path)
            if path.is_file():
                refs.append(_artifact_ref(root, path, f"{execution['id']}:{name}:{attempt}:{index}",
                                          kind, name, attempt, parents))
        finish_stage(stage, "succeeded", refs)
    else:
        finish_stage(stage, "failed", error=str(error) or type(error).__name__)
    _persist_reload(context["root"], context["pipeline"], context["manifest"])
    return refs


_MATERIAL_ARTIFACT_TYPES = {
    "surface": "surface.swatch", "fbx": "mesh.fbx", "blend": "project.blend",
    "basecolor": "texture.basecolor", "normal": "texture.normal", "roughness": "texture.roughness",
    "metallic": "texture.metallic", "metallic_gloss": "texture.metallic_gloss",
    "emission": "texture.emission", "preview_front": "preview.front", "preview_side": "preview.side",
    "preview_rear": "preview.rear", "preview_three_quarter": "preview.three_quarter",
    "validation": "validation.json",
}


def _material_artifact_refs(root, paths, execution_id, attempt, upstream):
    refs = []
    for key, kind in _MATERIAL_ARTIFACT_TYPES.items():
        path = paths[key]
        if path.is_file():
            refs.append(_artifact_ref(root, path, f"{execution_id}:material:{attempt}:{key}", kind,
                                      "material_assembly_export", attempt, upstream))
    return refs


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
            "preview_three_quarter": previews / f"{name}_three_quarter.png",
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
            "preview_three_quarter": previews / f"{name}_three_quarter.png",
            "validation": directory / "validation.json", "generator": directory / "generation.json"}


def _relative_outputs(root, paths, keys):
    return {key: paths[key].relative_to(root).as_posix() for key in keys}


def _generate_material_candidate(root, config, asset_type, asset, number, prompt, stage_mesh, lineage=None, seed=None):
    paths = material_candidate_paths(root, config, asset["name"], number, asset_type)
    paths["directory"].mkdir(parents=True, exist_ok=True)
    paths["basecolor"].parent.mkdir(parents=True, exist_ok=True)
    candidate = {"number": number, "prompt": prompt, "status": "failed", "kind": "surface_swatch",
                 "seed": seed if seed is not None else secrets.randbits(32), "path": paths["surface"].relative_to(root).as_posix(),
                 "validation": {"status": "not_run", "errors": [], "warnings": [], "measured": {}}}
    pipeline = config["asset_pipeline"]
    material_started = assembly_started = False
    candidate["artifacts"] = []
    try:
        workflow = pipeline["workflows"].get("image")
        if not workflow:
            raise ValueError("Configure asset_pipeline.workflows.image in ai/project.yaml")
        metadata_path = paths["generator"]
        _lineage_start(lineage, "material_generation", number, (lineage or {}).get("upstream", []),
                       {"prompt": prompt, "seed": candidate["seed"]})
        material_started = bool(lineage)
        generate_image(root, config, resolve_workflow(root, workflow), prompt, paths["surface"],
                       f"slopforge/prop/{asset['name']}/material_{candidate['seed']}",
                       candidate["seed"], metadata_path)
        material_check = validate_image(paths["surface"], expected_format="PNG",
                                        report_path=paths["surface"].relative_to(root))
        if material_check["status"] == "failed":
            raise ValueError("Surface material validation failed: " + "; ".join(material_check["errors"]))
        info = json.loads(metadata_path.read_text()) if metadata_path.is_file() else {}
        candidate["generator"] = generator_provenance(info.get("workflow"), info)
        if material_started:
            candidate["artifacts"].extend(_lineage_finish(lineage, "material_generation", number,
                [(paths["surface"], "surface.swatch"), (metadata_path, "generation.metadata")]))
            material_started = False

        python = python_executable(root, config)
        _lineage_start(lineage, "material_assembly_export", number, (lineage or {}).get("upstream", []),
                       {"material_scale": float(pipeline.get("material_scale", 3.0))})
        assembly_started = bool(lineage)
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
                        "preview_front", "preview_side", "preview_rear", "preview_three_quarter")}
        candidate["validation"] = validate_model_outputs(check_paths, inspection, face_budget, root,
            max_components=asset_type.get("max_components"),
            max_nonmanifold_edges=asset_type.get("max_nonmanifold_edges"),
            max_boundary_edges=asset_type.get("max_boundary_edges"))
        paths["validation"].write_text(json.dumps(candidate["validation"], indent=2) + "\n")
        candidate["status"] = "candidate" if candidate["validation"]["status"] != "failed" else "failed"
        candidate["outputs"] = _relative_outputs(root, paths, check_paths)
        candidate["generator"].update({"workflow": info.get("workflow") or workflow,
                                        "seed": candidate["seed"]})
        if assembly_started:
            candidate["artifacts"].extend(_lineage_finish(lineage, "material_assembly_export", number,
                [(paths[key], _MATERIAL_ARTIFACT_TYPES[key]) for key in _MATERIAL_ARTIFACT_TYPES]))
            assembly_started = False
    except Exception as exc:
        if material_started:
            _lineage_finish(lineage, "material_generation", number, [], error=exc)
        if assembly_started:
            _lineage_finish(lineage, "material_assembly_export", number, [], error=exc)
        candidate["error"] = str(exc)
        candidate["validation"]["errors"].append(str(exc))
    return candidate


def _native_material_candidate(root, config, asset_type, asset, number, mesh_info, lineage=None):
    paths = material_candidate_paths(root, config, asset["name"], number, asset_type)
    paths["basecolor"].parent.mkdir(parents=True, exist_ok=True)
    mesh_path = root / asset["source"]["glb"]
    artifacts = []
    _lineage_start(lineage, "material_generation", number, (lineage or {}).get("upstream", []),
                   {"workflow": "mesh_pbr", "seed": mesh_info.get("seed")})
    if mesh_info.get("conditioning_image"):
        shutil.copy2(mesh_path.parent / mesh_info["conditioning_image"], paths["directory"] / "conditioning.png")
        mesh_info = {**mesh_info, "conditioning_image": "conditioning.png"}
    for key in ("basecolor", "normal", "roughness", "metallic"):
        shutil.copy2(mesh_path.parent / mesh_info["textures"][key], paths[key])
    make_metallic_gloss(paths["metallic"], paths["roughness"], paths["metallic_gloss"])
    shutil.copy2(paths["basecolor"], paths["surface"])
    with Image.open(paths["basecolor"]) as image:
        Image.new("RGB", image.size, (0, 0, 0)).save(paths["emission"])
    paths["generator"].write_text(json.dumps(mesh_info, indent=2) + "\n")
    artifacts.extend(_lineage_finish(lineage, "material_generation", number,
        [(paths[key], _MATERIAL_ARTIFACT_TYPES[key]) for key in
         ("surface", "basecolor", "normal", "roughness", "metallic", "metallic_gloss", "emission")]
        + [(paths["generator"], "generation.metadata")]))
    budget = int(config["asset_pipeline"]["model_budgets"].get(asset_type.get("face_budget"), 30000))
    textures = [paths[key] for key in ("basecolor", "normal", "roughness", "metallic", "emission")]
    _lineage_start(lineage, "material_assembly_export", number, (lineage or {}).get("upstream", []),
                   {"preserve_uvs": True, "face_budget": budget})
    process_model(root, config, mesh_path, paths["fbx"], paths["blend"], textures, budget,
                  preview_dir=paths["preview_front"].parent, preserve_uvs=True,
                  stage_mesh=root / asset["source"]["processed_mesh"])
    inspection = inspect_model(root, config, paths["blend"], paths["validation"], budget)
    keys = ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss", "emission",
            "preview_front", "preview_side", "preview_rear", "preview_three_quarter")
    validation = validate_model_outputs({key: paths[key] for key in keys}, inspection, budget, root,
        max_components=asset_type.get("max_components"),
        max_nonmanifold_edges=asset_type.get("max_nonmanifold_edges"),
        max_boundary_edges=asset_type.get("max_boundary_edges"))
    paths["validation"].write_text(json.dumps(validation, indent=2) + "\n")
    artifacts.extend(_lineage_finish(lineage, "material_assembly_export", number,
        [(paths[key], _MATERIAL_ARTIFACT_TYPES[key]) for key in _MATERIAL_ARTIFACT_TYPES]))
    return {"number": number, "prompt": asset.get("generation_prompt", asset["description"]),
            "status": "candidate" if validation["status"] != "failed" else "failed",
            "kind": "mesh_pbr", "seed": mesh_info.get("seed"),
            "path": paths["surface"].relative_to(root).as_posix(), "validation": validation,
            "generator": generator_provenance(mesh_info.get("workflow"), mesh_info),
            "outputs": _relative_outputs(root, paths, keys), "artifacts": artifacts}


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
    seeds = [secrets.randbits(32) for _ in range(count)]
    selected_number = asset.get("material_candidates", {}).get("selected")
    selected_candidate = next((item for item in asset.get("material_candidates", {}).get("items", [])
                               if item["number"] == selected_number), None)
    parent_execution = next((execution for execution in asset.get("executions", [])
                             if selected_candidate and execution["id"] == selected_candidate.get("execution_id")), None)
    mesh_ref = next((artifact for stage in reversed(parent_execution.get("stages", []) if parent_execution else [])
                     for artifact in reversed(stage.get("outputs", []))
                     if artifact["type"] in {"mesh.glb", "mesh.raw", "mesh.final"}), None)
    concept_ref = asset.get("source", {}).get("concept_artifact")
    upstream = ([concept_ref] if concept_ref else []) + ([mesh_ref] if mesh_ref else [])
    execution = start_execution(asset, {"asset_type": asset.get("type"), "brief": asset.get("description"),
        "mesh_sha256": mesh_ref.get("sha256") if mesh_ref else file_sha256(paths["glb"]),
        "material_prompt": prompt, "material_scale": config["asset_pipeline"].get("material_scale", 3.0),
        "quality": config["asset_pipeline"].get("quality_settings", {}), "seeds": seeds},
        parent_execution_id=parent_execution.get("id") if parent_execution else None)
    lineage = {"root": root, "pipeline": config["asset_pipeline"], "manifest": manifest, "key": key,
               "execution_id": execution["id"], "upstream": upstream}
    results = []
    for index, number in enumerate(range(start, start + count)):
        candidate = _generate_material_candidate(root, config, asset_type, asset, number, prompt,
            paths["processed_mesh"], lineage=lineage, seed=seeds[index])
        if not candidate.get("artifacts"):
            candidate["artifacts"] = _material_artifact_refs(root,
                material_candidate_paths(root, config, asset["name"], number, asset_type),
                execution["id"], number, upstream)
        candidate.update({"execution_id": execution["id"], "stage_attempt": number,
                          "mesh_source": paths["glb"].relative_to(root).as_posix(),
                          "mesh_attempt": mesh_ref.get("attempt") if mesh_ref else None,
                          "upstream_artifacts": upstream})
        existing.append(candidate)
        results.append(candidate)
    finish_execution(execution, "succeeded" if any(item["status"] == "candidate" for item in results) else "failed")
    from .. import SCHEMA_VERSION
    manifest.setdefault("schema_version", SCHEMA_VERSION)
    save_manifest(root / config["asset_pipeline"]["manifest"], manifest)
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
                  "preview_front", "preview_side", "preview_rear", "preview_three_quarter")
    existing = [paths[name] for name in (*final_keys, "glb", "unity_material") if paths[name].exists()]
    if existing and not (force or config["asset_pipeline"].get("overwrite_existing")):
        raise FileExistsError(f"Approved model outputs exist; pass --force to replace: {existing[0]}")
    sources = {name: root / candidate["outputs"][name] for name in final_keys}
    missing = [str(path) for path in sources.values() if not path.is_file() or not path.stat().st_size]
    if missing:
        raise ValueError("Material candidate output missing or empty: " + missing[0])
    mesh_source = candidate.get("mesh_source") or asset.get("source", {}).get("glb")
    if not isinstance(mesh_source, str) or not (root / mesh_source).is_file():
        raise ValueError("Qualified material candidate has no retained source mesh")
    candidate_artifacts = candidate.get("artifacts", [])
    pipeline = config["asset_pipeline"]
    execution = start_execution(asset, {
        "asset_type": asset.get("type"), "candidate_artifacts": [
            {"id": item["id"], "sha256": item["sha256"]} for item in candidate_artifacts],
        "publication_roles": ["surface", "fbx", "blend", "maps", "previews", "unity_material", "validation"],
    }, parent_execution_id=candidate.get("execution_id"))
    publication_stage = start_stage(execution, "final_publication", 1, candidate_artifacts,
                                    {"approval": "selected material candidate"}, {})
    begin_stage(publication_stage)
    from .. import SCHEMA_VERSION
    manifest.setdefault("schema_version", SCHEMA_VERSION)
    save_manifest(root / pipeline["manifest"], manifest)
    publication_paths = [paths[name] for name in (*final_keys, "glb", "unity_material", "validation")]
    publication_paths += [path.with_suffix(path.suffix + ".meta") for path in publication_paths]
    with tempfile.TemporaryDirectory(prefix="slopforge-texture-backup-") as backup_dir:
        backups = {}
        for index, destination in enumerate(publication_paths):
            if destination.is_file():
                backup = Path(backup_dir) / str(index)
                shutil.copy2(destination, backup)
                backups[destination] = backup
        try:
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
            if (root / mesh_source).resolve() != paths["glb"].resolve():
                paths["glb"].parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / mesh_source, paths["glb"])
            build_unity_material(root, paths["fbx"], paths["directory"] / "Materials" /
                                 f"{asset['name']}_preview_PBR.mat",
                                 {name: paths[name] for name in ("basecolor", "normal", "metallic_gloss", "emission")})
            validation = dict(candidate["validation"])
            validation["measured"] = dict(validation.get("measured", {}))
            validation["measured"].update({name: paths[name].relative_to(root).as_posix() for name in final_keys})
            validation["measured"]["unity_material"] = paths["unity_material"].relative_to(root).as_posix()
            paths["validation"].write_text(json.dumps(validation, indent=2) + "\n")
        except Exception as exc:
            for destination in publication_paths:
                if destination in backups:
                    shutil.copy2(backups[destination], destination)
                else:
                    destination.unlink(missing_ok=True)
            finish_stage(publication_stage, "failed", error=str(exc) or type(exc).__name__)
            finish_execution(execution, "failed")
            save_manifest(root / pipeline["manifest"], manifest)
            raise
    candidate["approval"] = "approved"
    asset["material_candidates"]["selected"] = number
    asset["material_prompt"] = candidate["prompt"]
    asset["generator"]["material"] = candidate.get("generator")
    asset["generator"]["workflow"]["material"] = (candidate.get("generator") or {}).get("workflow")
    asset["generator"]["seed"]["material"] = candidate.get("seed")
    asset["outputs"] = _relative_outputs(root, paths, (*final_keys, "glb", "unity_material", "validation"))
    asset["validation"] = validation
    asset["status"] = "ready"
    asset["updated_at"] = datetime.now(timezone.utc).isoformat()
    candidate_refs = candidate.get("artifacts", [])
    mesh_ref = next((item for item in candidate.get("upstream_artifacts", []) if item["type"].startswith("mesh.")), None)
    by_type = {}
    for item in candidate_refs:
        by_type.setdefault(item["type"], []).append(item)
    published = []
    output_types = {"surface": "surface.swatch", "fbx": "mesh.fbx", "blend": "project.blend",
                    "basecolor": "texture.basecolor", "normal": "texture.normal", "roughness": "texture.roughness",
                    "metallic": "texture.metallic", "metallic_gloss": "texture.metallic_gloss",
                    "emission": "texture.emission", "preview_front": "preview.front", "preview_side": "preview.side",
                    "preview_rear": "preview.rear", "preview_three_quarter": "preview.three_quarter",
                    "unity_material": "material.unity", "validation": "validation.json", "glb": "mesh.glb"}
    for key_name, kind in output_types.items():
        path = paths[key_name]
        parents = by_type.get(kind, [])
        if key_name == "glb" and mesh_ref:
            parents = [mesh_ref]
        if key_name == "unity_material":
            parents = [item for item in candidate_refs if item["type"].startswith("texture.")]
        if key_name == "validation":
            parents = candidate_refs
        if path.is_file():
            published.append(_artifact_ref(root, path, f"{execution['id']}:published:{key_name}", kind,
                                           "final_publication", 1, parents))
    finish_stage(publication_stage, "succeeded", published)
    finish_execution(execution, "succeeded")
    asset["published_artifacts"] = published
    save_manifest(root / pipeline["manifest"], manifest)
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
    workflow = pipeline["workflows"].get("model")
    if workflow:
        problems = workflow_mask_errors(json.loads(resolve_workflow(root, workflow).read_text()))
        if problems:
            raise ValueError("Invalid model workflow mask wiring: " + "; ".join(problems))
    paths = model_paths(root, config, asset["name"], asset_type)
    existing = [path for name, path in paths.items() if name != "directory" and path.exists()]
    if existing and not (force or config["asset_pipeline"].get("overwrite_existing")):
        raise FileExistsError(f"Model outputs exist; pass --force to replace: {existing[0]}")
    prompt = candidate.get("description", asset["description"])
    concept_workflow = pipeline["workflows"].get("image")
    material_prompt = material_prompt or build_prompt(style, asset_type, prompt, mode="material")
    material_count = material_count or int(pipeline["defaults"].get("material_candidates", 2))
    attempts = int(pipeline["defaults"].get("model_candidates", 1))
    if material_count < 1 or attempts < 1:
        raise ValueError("Material and model candidate budgets must be at least 1")
    next_attempt = max((int(item.get("number", 0)) for item in asset.get("model_attempts", [])), default=0) + 1
    mesh_seeds = [secrets.randbits(32) for _ in range(attempts)]
    material_seeds = [] if workflow else [secrets.randbits(32) for _ in range(attempts * material_count)]
    concept_path = root / candidate["path"]
    candidate_artifact = candidate.get("artifact")
    if candidate_artifact is None:
        candidate_artifact = {"id": f"legacy-concept:{number}", "type": "image.concept.legacy",
                              "path": candidate["path"], "sha256": file_sha256(concept_path),
                              "stage": "legacy_concept_selection", "attempt": number, "derived_from": []}
    model_workflow_path = resolve_workflow(root, workflow) if workflow else None
    execution = start_execution(asset, {
        "asset_type": asset_type.get("name"), "brief": candidate.get("description", asset.get("description")),
        "selected_concept": {"sha256": candidate_artifact["sha256"]},
        "workflows": {"concept": concept_workflow,
                      "model": {"identifier": Path(workflow).name if workflow else "hunyuan3d_image_to_model_api",
                                "sha256": file_sha256(model_workflow_path) if model_workflow_path and model_workflow_path.is_file() else None,
                                "configured_inputs": workflow_node_inputs(config, "model", Path(workflow).name) if workflow else {}}},
        "quality": {"tier": pipeline.get("selected_quality_tier", "normal"),
                    "settings": pipeline.get("quality_settings", {})},
        "mesh": {"face_budget": pipeline.get("model_budgets", {}).get(asset_type.get("face_budget")),
                 "voxel_resolution": asset_type.get("voxel_resolution"), "seeds": mesh_seeds},
        "material_prompt": material_prompt, "material_count": material_count,
        "material_seeds": material_seeds,
    }, parent_execution_id=candidate.get("execution_id"))
    paths["concept"].parent.mkdir(parents=True, exist_ok=True)
    paths["basecolor"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(concept_path, paths["concept"])
    selected_artifact = _artifact_ref(root, paths["concept"], f"approved-concept:{execution['id']}",
                                      "image.concept.approved", "conditioning_preparation", 1,
                                      [candidate_artifact])
    candidate["approval"] = "approved"
    asset["candidates"]["selected"] = number
    asset["status"] = "processing"
    asset["description"] = candidate.get("description", asset["description"])
    asset["style"], asset["style_version"] = style["name"], style["version"]
    asset["source"] = {"concept": paths["concept"].relative_to(root).as_posix(),
                       "concept_artifact": selected_artifact,
                       "concept_lineage": {"status": "known" if candidate.get("execution_id") else "unknown",
                           "reason": None if candidate.get("execution_id") else "legacy concept candidate has no execution record"}}
    pipeline = config["asset_pipeline"]
    _persist_reload(root, pipeline, manifest)
    asset = manifest["assets"][key]
    execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
    python = python_executable(root, config)
    try:
        stage = start_stage(execution, "conditioning_preparation", 1, [candidate_artifact],
                            {"strategy": conditioning["strategy"], "tool": "prepare_3d_input.py"},
                            {"concept_lineage": asset["source"]["concept_lineage"]})
        begin_stage(stage)
        _persist_reload(root, pipeline, manifest)
        asset = manifest["assets"][key]
        print("3D stage: background removal and isolated reconstruction input...", flush=True)
        subprocess.run([python, str(tool_root() / "processing/prepare_3d_input.py"), "--input", str(paths["concept"]),
                        "--cutout", str(paths["cutout"]), "--output", str(paths["input_3d"])], check=True)
        cutout_check = validate_image(paths["cutout"], expected_format="PNG", require_alpha=True, report_path=paths["cutout"].relative_to(root))
        input_check = validate_image(paths["input_3d"], expected_format="PNG", report_path=paths["input_3d"].relative_to(root))
        if cutout_check["status"] == "failed" or input_check["status"] == "failed":
            raise ValueError(f"Prepared concept validation failed: {cutout_check['errors'] + input_check['errors']}")
        outputs = [_artifact_ref(root, paths["cutout"], f"cutout:{execution['id']}",
                                 "image.cutout", "conditioning_preparation", 1, [selected_artifact]),
                   _artifact_ref(root, paths["input_3d"], f"3d-input:{execution['id']}",
                                 "image.3d_input", "conditioning_preparation", 1, [selected_artifact])]
        _, conditioning_stage = _execution_stage(asset, execution["id"], "conditioning_preparation", 1)
        finish_stage(conditioning_stage, "succeeded", outputs)
        _persist_reload(root, pipeline, manifest)
        asset = manifest["assets"][key]
        execution, _ = _execution_stage(asset, execution["id"], "conditioning_preparation", 1)

        workflow = pipeline["workflows"].get("model")
        print("3D stage: mesh and PBR generation..." if workflow else "3D stage: Hunyuan3D mesh generation...", flush=True)
        material_candidates = []
        viable = []
        attempt_errors = []
        attempt_reports = asset.setdefault("model_attempts", [])
        next_attempt = max((int(item.get("number", 0)) for item in attempt_reports), default=0) + 1
        next_material = max((int(item["number"]) for item in asset.get("material_candidates", {}).get("items", [])), default=0) + 1
        for offset in range(attempts):
            attempt_number = next_attempt + offset
            attempt_dir = root / pipeline["candidate_root"] / asset_type["name"] / asset["name"] / f"mesh_{attempt_number:02d}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            source_mesh, model_metadata = attempt_dir / f"{asset['name']}.glb", attempt_dir / "generation.json"
            stage_mesh = attempt_dir / "processed_mesh.blend"
            mesh_seed = mesh_seeds[offset]
            conditioning_refs = conditioning_stage["outputs"]
            mesh_stage = start_stage(execution, "mesh_workflow_execution", attempt_number,
                                     [candidate_artifact, *conditioning_refs],
                                     {"seed": mesh_seed, "workflow": workflow or "hunyuan3d_image_to_model_api"},
                                     {"concept_lineage": asset["source"]["concept_lineage"]})
            begin_stage(mesh_stage)
            _persist_reload(root, pipeline, manifest)
            asset = manifest["assets"][key]
            execution, mesh_stage = _execution_stage(asset, execution["id"], "mesh_workflow_execution", attempt_number)
            attempt_reports = asset.setdefault("model_attempts", [])
            journal_context = {"manifest_path": str(root / pipeline["manifest"]), "asset_selector": key,
                               "execution_id": execution["id"], "attempt": attempt_number,
                               "upstream_artifacts": [candidate_artifact, *conditioning_refs]}
            try:
                config["_journal_context"] = journal_context
                if workflow:
                    budget = int(pipeline["model_budgets"].get(asset_type.get("face_budget"), 30000))
                    generate_model(root, config, paths["cutout"], asset["name"], source_mesh, model_metadata,
                                   mesh_seed, budget, voxel_resolution=asset_type.get("voxel_resolution"))
                else:
                    generate_model(root, config, paths["input_3d"], asset["name"], source_mesh, model_metadata, mesh_seed)
                config.pop("_journal_context", None)
                _reload_manifest(root, pipeline, manifest)
                asset = manifest["assets"][key]
                execution, mesh_stage = _execution_stage(asset, execution["id"], "mesh_workflow_execution", attempt_number)
                attempt_reports = asset.setdefault("model_attempts", [])
                mesh_info = json.loads(model_metadata.read_text())
                missing = lambda reason: {"status": "not_recorded", "reason": reason}
                backend = mesh_info.get("backend") or {}
                facts = mesh_info.get("provenance") or {}
                mesh_stage["provenance"].update({
                    "backend": {name: backend.get(name, missing(f"Worker did not record backend {name}"))
                                for name in ("provider", "version", "device")},
                    "model_weights": facts.get("model_weights", missing("Worker did not record exact model weights")),
                    "custom_node_revisions": facts.get("custom_node_revisions",
                        missing("Worker did not record custom-node revisions")),
                    "model_filenames": mesh_info.get("model_filenames", missing("Worker did not record configured model filenames")),
                    "workflow_source": mesh_info.get("workflow_source", missing("Worker did not record source workflow provenance")),
                    "workflow_effective_sha256": ({"status": "known", "value": mesh_info["workflow_effective_sha256"]}
                        if mesh_info.get("workflow_effective_sha256") else
                        missing("Worker did not record the effective workflow hash")),
                    "effective_bindings": mesh_info.get("effective_bindings", missing("Worker did not record effective bindings")),
                })
            except Exception as exc:
                config.pop("_journal_context", None)
                _reload_manifest(root, pipeline, manifest)
                asset = manifest["assets"][key]
                execution, mesh_stage = _execution_stage(asset, execution["id"], "mesh_workflow_execution", attempt_number)
                reason = f"mesh generation failed: {exc}"
                attempt_errors.append(reason)
                if mesh_stage["status"] == "running":
                    partial = []
                    if source_mesh.is_file():
                        partial.append(_artifact_ref(root, source_mesh, f"mesh:{execution['id']}:{attempt_number}",
                            "mesh.glb", "mesh_workflow_execution", attempt_number, conditioning_refs))
                    finish_stage(mesh_stage, "failed", partial, error=reason)
                attempt_reports.append({"number": attempt_number,
                                        "seed": mesh_seed,
                                        "source": source_mesh.relative_to(root).as_posix() if source_mesh.is_file() else None,
                                        "generation": model_metadata.relative_to(root).as_posix(),
                                        "status": "rejected", "error": reason,
                                        "execution_id": execution["id"], "stage_attempt": attempt_number})
                _persist_reload(root, pipeline, manifest)
                asset = manifest["assets"][key]
                execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
                continue
            mesh_outputs = [_artifact_ref(root, source_mesh, f"mesh:{execution['id']}:{attempt_number}",
                "mesh.glb", "mesh_workflow_execution", attempt_number, conditioning_refs)]
            if model_metadata.is_file():
                mesh_outputs.append(_artifact_ref(root, model_metadata, f"mesh-metadata:{execution['id']}:{attempt_number}",
                    "generation.metadata", "mesh_workflow_execution", attempt_number, conditioning_refs))
            if mesh_stage["status"] == "running":
                finish_stage(mesh_stage, "succeeded", mesh_outputs)
            _persist_reload(root, pipeline, manifest)
            asset = manifest["assets"][key]
            execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
            attempt_reports = asset.setdefault("model_attempts", [])
            asset["source"].update({"cutout": paths["cutout"].relative_to(root).as_posix(),
                                    "3d_input": paths["input_3d"].relative_to(root).as_posix(),
                                    "glb": source_mesh.relative_to(root).as_posix(),
                                    "processed_mesh": stage_mesh.relative_to(root).as_posix()})
            execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
            mesh_artifact = next((artifact for stage_record in reversed(execution["stages"])
                                  for artifact in reversed(stage_record.get("outputs", []))
                                  if artifact["type"] in {"mesh.glb", "mesh.raw", "mesh.final"}), mesh_outputs[0])
            lineage = {"root": root, "pipeline": pipeline, "manifest": manifest, "key": key,
                       "execution_id": execution["id"], "attempt": attempt_number,
                       "upstream": [candidate_artifact, mesh_artifact]}
            if mesh_info.get("textured"):
                start = next_material
                generated = [_native_material_candidate(root, config, asset_type, asset, start, mesh_info,
                                                        lineage=lineage)]
            else:
                generated = [_generate_material_candidate(root, config, asset_type, asset, number,
                            material_prompt, stage_mesh, lineage=lineage,
                            seed=material_seeds[offset * material_count + index])
                             for index, number in enumerate(range(next_material, next_material + material_count))]
            asset = manifest["assets"][key]
            execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
            attempt_reports = asset.setdefault("model_attempts", [])
            next_material += len(generated)
            for item in generated:
                item["mesh_source"] = source_mesh.relative_to(root).as_posix()
                item["mesh_attempt"] = attempt_number
                item["execution_id"] = execution["id"]
                item["stage_attempt"] = item["number"]
                item["upstream_artifacts"] = lineage["upstream"]
                if not item.get("artifacts"):
                    candidate_paths = material_candidate_paths(root, config, asset["name"], item["number"], asset_type)
                    item["artifacts"] = _material_artifact_refs(root, candidate_paths, execution["id"],
                                                                  item["number"], lineage["upstream"])
            material_candidates.extend(generated)
            viable = [item for item in generated if item["status"] == "candidate"]
            attempt_reports.append({"number": attempt_number, "source": source_mesh.relative_to(root).as_posix(),
                                    "seed": mesh_seed,
                                    "generation": model_metadata.relative_to(root).as_posix(),
                                    "source_sha256": _sha256(source_mesh),
                                    "input_sha256": _sha256(paths["cutout"] if workflow else paths["input_3d"]),
                                        "status": "qualified" if viable else "rejected",
                                        "execution_id": execution["id"], "stage_attempt": attempt_number,
                                    "materials": [{"number": item["number"], "status": item["status"],
                                                   "validation": item.get("validation")} for item in generated]})
            _persist_reload(root, pipeline, manifest)
            asset = manifest["assets"][key]
            execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
            attempt_reports = asset.setdefault("model_attempts", [])
            if viable:
                break
        previous = asset.get("material_candidates", {}).get("items", [])
        asset["material_candidates"] = {"items": previous + material_candidates, "selected": None}
        if not viable:
            failures = [error for item in material_candidates for error in item.get("validation", {}).get("errors", [])]
            raise ValueError(f"No qualified model after {attempts} attempts: " +
                             ("; ".join(attempt_errors + failures) or "candidate processing failed"))
        first = viable[0]
        asset["conditioning"] = {"strategy": conditioning["strategy"], "references_used": conditioning["references"]}
        asset["generator"] = {"workflow": {"concept": concept_workflow, "mesh": mesh_info.get("workflow"),
                                             "material": (first.get("generator") or {}).get("workflow")},
                               "model": mesh_info.get("model"),
                               "seed": {"concept": candidate.get("seed"), "mesh": mesh_info.get("seed")},
                               "quality": mesh_info.get("quality") or (candidate.get("generator") or {}).get("quality"),
                               "model_attempts": attempt_reports}
        asset["material_prompt"] = first["prompt"]
        asset["validation"] = {"status": "not_run", "errors": [], "warnings": [
            "Choose a material candidate and approve it before using the Unity output."], "measured": {}}
        asset["status"] = "awaiting_texture_approval"
        asset["updated_at"] = datetime.now(timezone.utc).isoformat()
        execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
        finish_execution(execution, "succeeded")
        save_manifest(root / pipeline["manifest"], manifest)
        print("Material candidate previews:")
        for item in material_candidates:
            print(f"  {item['number']}: {item.get('outputs', {}).get('preview_front', item['path'])} ({item['status']})")
        return {"status": asset["status"], "material_candidates": material_candidates}
    except Exception as exc:
        _reload_manifest(root, pipeline, manifest)
        asset = manifest["assets"][key]
        execution = next(item for item in asset["executions"] if item["id"] == execution["id"])
        for stage in execution.get("stages", []):
            if stage["status"] == "running":
                finish_stage(stage, "failed", error=str(exc) or type(exc).__name__)
        if execution.get("status") == "running":
            finish_execution(execution, "failed")
        asset["status"] = "failed"
        validation = asset.setdefault("validation", {})
        validation["status"] = "failed"
        validation.setdefault("errors", []).append(f"Pipeline stopped: {exc}")
        validation.setdefault("warnings", [])
        validation.setdefault("measured", {})
        save_manifest(root / pipeline["manifest"], manifest)
        raise
