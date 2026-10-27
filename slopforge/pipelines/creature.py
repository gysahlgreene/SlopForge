"""Creatures (M5): rig an approved creature model (package B1; docs/CREATURES.md).

`rig_creature` runs SkinTokens once per seed on the creature's published model, checks each raw rig against the
type's limb declaration (slopforge/creature_rig.py, measured in Blender), keeps every candidate with its verdict, and
finishes the best passing one: generic names, each bone's local X across the body, the source material, FBX and
.blend, and the review poses. Nothing is approved here: `approve_rig` records the human review of the contact sheet,
behind the delivery-rights gate.
"""
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from ..backends.blender import blender_environment
from ..character_rigging import run_skintokens_inference, skintokens_preflight
from .. import creature_rig
from ..creature_rig import deformation_poses, rig_settings
from ..failures import StageFailure, failure_record
from ..manifest import (begin_stage, find_asset, finish_execution, finish_stage, register_artifact, save_manifest,
                        set_artifact_approval, start_execution, start_stage)
from ..paths import blender_executable, tool_root
from ..provenance import file_sha256, tool_sha256
from ..providers import artifact_rights, require_shippable, rights_of
from ..skintokens_runtime import SKINTOKENS_SETTINGS
from ..taxonomy import load_taxonomy, output_path
from .model import _artifact_ref

SCRIPT = "blender/creature_rig.py"


def _provider(config, root):
    """SkinTokens' identity, after its preflight (every seed's inference repeats it)."""
    report = skintokens_preflight(config, root)
    if report["status"] != "ready":
        raise ValueError("SkinTokens preflight: " + "; ".join(report["reasons"]))
    return {"name": "SkinTokens", "version": report["revision"], "license": "MIT",
            "source": "https://github.com/VAST-AI-Research/SkinTokens", "source_revision": report["revision"],
            "checkpoint_sha256": report["checkpoint_sha256"]}


def _infer(config, source, raw, seed, log):
    return run_skintokens_inference(config, source, raw, seed=seed, log=log)


def _blender(config, root, request):
    with tempfile.TemporaryDirectory(prefix="slopforge-creature-") as temporary:
        path = Path(temporary) / "request.json"
        path.write_text(json.dumps(request))
        subprocess.run([blender_executable(config, root), "--background", "--factory-startup", "--python",
                        str(tool_root() / SCRIPT), "--", str(path)], check=False, env=blender_environment())
    if not Path(request["report"]).is_file():
        raise RuntimeError(f"Blender's creature rig {request['action']} wrote no report")
    report = json.loads(Path(request["report"]).read_text())
    if report.get("status") == "error":
        raise RuntimeError(f"Blender's creature rig {request['action']} failed: " + "; ".join(report["errors"]))
    return report


def _creature(manifest, name):
    asset = find_asset(manifest, name)
    if asset.get("type") != "creature":
        raise ValueError(f"{name} is a {asset.get('type')}, not a creature")
    if asset.get("status") != "ready" or not asset.get("outputs", {}).get("fbx"):
        raise ValueError(f"creature {name} has no published model yet: approve its material first (approve-texture)")
    return asset


def _published_model(root, asset):
    """The creature's published FBX and its one publication record; every member is checked before one is selected."""
    source = root / asset["outputs"]["fbx"]
    published = asset.get("published_artifacts")
    matches = ([item for item in published if item.get("path") == asset["outputs"]["fbx"]]
               if isinstance(published, list) and all(isinstance(item, dict) for item in published) else [])
    if len(matches) != 1 or not source.is_file() or file_sha256(source) != matches[0].get("sha256"):
        raise ValueError(f"creature {asset['name']}'s published model is missing, ambiguous or changed since it was "
                         "published; approve its material again")
    return source, matches[0]


def _sheet(tiles, path, columns):
    """Labelled images in a grid, each scaled to one height."""
    height = 300
    scaled = [(image.convert("RGB").resize((max(1, round(image.width * height / image.height)), height)), label)
              for image, label in tiles]
    width = max(image.width for image, _ in scaled)
    rows = -(-len(scaled) // columns)
    sheet = Image.new("RGB", (width * columns, (height + 34) * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (image, label) in enumerate(scaled):
        x, y = (index % columns) * width, (index // columns) * (height + 34)
        sheet.paste(image, (x, y))
        draw.text((x + 6, y + height + 6), label[:110], fill="black")
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def _seed_tile(root, candidate):
    if candidate["status"] == "error":
        return Image.new("RGB", (600, 270), (120, 120, 120))
    views = [Image.open(root / candidate["views"][view]).convert("RGB") for view in ("front", "side")]
    tile = Image.new("RGB", (sum(view.width for view in views), max(view.height for view in views)), "white")
    tile.paste(views[0], (0, 0))
    tile.paste(views[1], (views[0].width, 0))
    return tile


def rig_creature(project_root, config, manifest, name, *, seeds=None):
    """Rig a creature's published model with SkinTokens, one retained candidate per seed (1..seeds), and finish the
    best passing one for review. Raises StageFailure when no seed passes; every candidate is kept either way."""
    root = Path(project_root).resolve()
    asset = _creature(manifest, name)
    settings = rig_settings(load_taxonomy(root)[asset["type"]])
    default = settings.pop("seeds")
    count = default if seeds is None else seeds
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
        raise ValueError(f"seeds must be 1 to 8, got {count!r}")
    source, source_ref = _published_model(root, asset)
    directory = output_path(root, config, asset["type"], asset["name"]) / "Rigging"
    if directory.exists():
        raise FileExistsError(f"Rigging outputs exist; inspect or move them before retrying: {directory}")
    provider = _provider(config, root)
    rights = rights_of(config, "skintokens") + rights_of(config, "blender")
    # the Blender script and its helpers, and the checks module it imports from the package (tool_sha256 follows
    # only sibling imports)
    tool, checks = tool_sha256(tool_root() / SCRIPT), file_sha256(creature_rig.__file__)
    manifest_path = root / config["asset_pipeline"]["manifest"]
    execution = start_execution(asset, {"stage": "creature_rigging", "source_sha256": source_ref["sha256"],
                                        **settings, "seeds": count, "provider": provider,
                                        "skintokens_settings": dict(SKINTOKENS_SETTINGS), "tool_sha256": tool,
                                        "checks_sha256": checks})
    derived = [{"asset_id": asset["id"], "output_id": "fbx"}]

    def relative(path):
        return Path(path).relative_to(root).as_posix()

    candidates, raw_refs = [], {}
    for seed in range(1, count + 1):
        folder = directory / "candidates" / f"seed_{seed}"
        raw, report_path = folder / "raw.glb", folder / "structure.json"
        views = {view: str(folder / f"{view}.png") for view in ("front", "side")}
        stage = start_stage(execution, "rig_candidate", seed, [source_ref], {"seed": seed, **settings,
                            "tool_sha256": tool, "checks_sha256": checks}, {"provider": provider, "output_rights": rights})
        begin_stage(stage)
        save_manifest(manifest_path, manifest)
        try:
            _infer(config, source, raw, seed, folder / "skintokens.log")
            report = _blender(config, root, {"action": "check", "raw": str(raw), "limbs": settings["limbs"],
                                             "limits": settings["limits"], "views": views, "report": str(report_path)})
        except Exception as exc:   # a seed that crashes is recorded; the other seeds still run
            failure = failure_record(exc, stage="rig_candidate", stage_id=stage["id"], attempt=seed,
                                     operation="creature_rig")
            finish_stage(stage, "failed", error=str(exc) or type(exc).__name__, failure=failure)
            candidates.append({"seed": seed, "status": "error", "errors": [str(exc) or type(exc).__name__]})
            continue
        prefix = f"{execution['id']}:seed_{seed}"
        raw_refs[seed] = _artifact_ref(root, raw, f"{prefix}:raw", "rig.raw", "rig_candidate", seed, [source_ref])
        finish_stage(stage, "succeeded", [raw_refs[seed], *(
            _artifact_ref(root, path, f"{prefix}:{label}", kind, "rig_candidate", seed, [raw_refs[seed]])
            for label, kind, path in (("structure", "report.rig_structure", report_path),
                                      ("front", "image.rig_view", views["front"]),
                                      ("side", "image.rig_view", views["side"])))])
        validation = {key: report[key] for key in ("status", "errors", "failure_codes", "warnings", "artifact_kind",
                                                   "measured", "limits")}
        register_artifact(manifest, asset["id"], f"rig_candidate.seed_{seed}", "rig.candidate", relative(raw),
                          status="candidate" if report["status"] == "passed" else "failed", derived_from=derived,
                          provenance={**provider, "seed": seed, "output_rights": rights},
                          approval_status="not_required", validation=validation)
        candidates.append({"seed": seed, "status": report["status"], "errors": report["errors"],
                           "asymmetry": report["measured"]["rig_asymmetry"], "raw": relative(raw),
                           "structure": relative(report_path),
                           "views": {view: relative(path) for view, path in views.items()},
                           **({"names": report["names"], "fit_bones": report["fit_bones"], "facing": report["facing"]}
                              if report["status"] == "passed" else {})})

    review = directory / "Review"
    seed_sheet = review / "seed_sheet.png"
    _sheet([(_seed_tile(root, item), f"seed {item['seed']}: {item['status']}"
             + (f" - {item['errors'][0]}" if item["errors"] else "")) for item in candidates],
           seed_sheet, columns=min(4, len(candidates)))
    register_artifact(manifest, asset["id"], "rig_seed_sheet", "image.rig_evidence", relative(seed_sheet),
                      status="candidate", derived_from=derived, provenance={"output_rights": rights},
                      approval_status="not_required")
    summaries = [{key: value for key, value in item.items() if key not in ("names", "fit_bones")} for item in candidates]
    record = {"provider": provider, **settings, "candidates": summaries, "seed_sheet": relative(seed_sheet)}
    passing = [item for item in candidates if item["status"] == "passed"]

    def fail(exc, stage=None):
        failure = failure_record(exc, stage=stage["name"] if stage else "creature_rigging",
                                 stage_id=stage["id"] if stage else None, attempt=stage["attempt"] if stage else None,
                                 operation="creature_rig")
        if stage:
            finish_stage(stage, "failed", error=str(exc) or type(exc).__name__, failure=failure)
        finish_execution(execution, "failed", failure=failure)
        asset["rigging"] = {"status": "failed", **record, "error": str(exc)}
        asset.setdefault("pipeline_status", {})["rigging_status"] = "failed"
        save_manifest(manifest_path, manifest)

    if not passing:
        exc = StageFailure("candidate_quality", f"no SkinTokens seed of {count} passed the rig checks",
                           operation="creature_rig",
                           remedy="look at the seed sheet; try more seeds (--seeds, up to 8), or regenerate the "
                                  "creature with its four legs clear of the body and each other")
        fail(exc)
        raise exc
    chosen = min(passing, key=lambda item: (item["asymmetry"], item["seed"]))
    poses = deformation_poses(set(chosen["names"].values()))
    rigged, blend = directory / f"{asset['name']}_rig.fbx", directory / f"{asset['name']}_rig.blend"
    images = [review / f"pose_{index}.png" for index in range(len(poses))]
    contact = review / "contact_sheet.png"
    stage = start_stage(execution, "rig_postprocess", 1, [raw_refs[chosen["seed"]], source_ref],
                        {"seed": chosen["seed"], "names": chosen["names"], "poses": poses, "tool_sha256": tool,
                         "checks_sha256": checks},
                        {"output_rights": rights})
    begin_stage(stage)
    save_manifest(manifest_path, manifest)
    try:
        finished = _blender(config, root, {
            "action": "finish", "source": str(source), "raw": str(root / chosen["raw"]), "names": chosen["names"],
            "facing": chosen["facing"],
            "rigged_model": str(rigged), "blend": str(blend), "poses": poses,
            "pose_images": [str(image) for image in images], "report": str(directory / "finish.json")})
        _sheet([(Image.open(image), pose["label"]) for image, pose in zip(images, poses)], contact, columns=3)
    except Exception as exc:
        fail(exc, stage)
        raise
    parents = [raw_refs[chosen["seed"]], source_ref]
    finish_stage(stage, "succeeded", [_artifact_ref(root, path, f"{execution['id']}:{label}", kind, "rig_postprocess",
                                                    1, parents)
                                      for label, kind, path in (("rig", "model.rigged", rigged),
                                                                ("blend", "project.blend", blend),
                                                                ("contact_sheet", "image.rig_evidence", contact))])
    finish_execution(execution, "succeeded")
    provenance = {**provider, "seed": chosen["seed"], "output_rights": rights}
    validation = asset["artifacts"][f"rig_candidate.seed_{chosen['seed']}"]["validation"]
    rig = register_artifact(manifest, asset["id"], "rig", "model.rigged", relative(rigged), status="candidate",
                            derived_from=derived, provenance=provenance, approval_status="pending",
                            validation=validation)
    register_artifact(manifest, asset["id"], "rig_blend", "project.blend", relative(blend), status="candidate",
                      derived_from=derived, provenance=provenance, approval_status="not_required",
                      validation=validation)
    register_artifact(manifest, asset["id"], "rig_contact_sheet", "image.rig_evidence", relative(contact),
                      status="candidate", derived_from=derived, provenance={"output_rights": rights},
                      approval_status="not_required")
    asset["rigging"] = {"status": "review_required", "seed": chosen["seed"], **record, "facing": chosen["facing"],
                        "names": chosen["names"], "fit_bones": chosen["fit_bones"], "rig_sha256": file_sha256(rigged),
                        "source_sha256": source_ref["sha256"],
                        "contact_sheet": relative(contact), "structure": chosen["structure"],
                        "material_transfer": finished.get("material_transfer")}
    asset.setdefault("pipeline_status", {})["rigging_status"] = "review_required"
    save_manifest(manifest_path, manifest)
    return {"status": "review_required", "seed": chosen["seed"], "rig": rig, "contact_sheet": relative(contact),
            "seed_sheet": relative(seed_sheet), "candidates": summaries}


def approve_rig(project_root, manifest, name, *, confirmed=False):
    """Record the human review of a creature rig's contact sheet. The rig must be unchanged since it was made, and
    the rights over its whole lineage shippable."""
    if not confirmed:
        raise ValueError("Explicit human confirmation is required: review the contact sheet, then pass --confirm")
    root = Path(project_root).resolve()
    asset = _creature(manifest, name)
    rigging = asset.get("rigging") or {}
    if rigging.get("status") not in ("review_required", "approved") or "rig" not in asset.get("artifacts", {}):
        raise ValueError(f"creature {name} has no rig to approve: run `slopforge creature rig {name}`")
    if _published_model(root, asset)[1]["sha256"] != rigging.get("source_sha256"):
        raise ValueError(f"creature {name}'s model was republished since its rig was made; rig it again")
    rig = root / asset["artifacts"]["rig"]["path"]
    if not rig.is_file() or file_sha256(rig) != rigging.get("rig_sha256"):
        raise ValueError(f"creature {name}'s rig is missing or changed since it was made; rig it again")
    if not (root / rigging["contact_sheet"]).is_file():
        raise ValueError(f"creature {name}'s contact sheet is missing: {rigging['contact_sheet']}")
    rights = require_shippable(artifact_rights(manifest, asset["id"], "rig"), name, "creature approve-rig")
    set_artifact_approval(manifest, asset["id"], "rig", "approved")
    rigging["status"] = "approved"
    rigging["review"] = {"status": "approved", "approved_at": datetime.now(timezone.utc).isoformat(),
                         "output_rights": rights}
    asset.setdefault("pipeline_status", {})["rigging_status"] = "approved"
    return {"status": "approved", "output_rights": rights}
