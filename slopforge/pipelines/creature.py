"""Creatures (M5): rig an approved creature model (package B1; docs/CREATURES.md).

`rig_creature` runs SkinTokens once per seed on the creature's published model, checks each raw rig against the
type's limb declaration (slopforge/creature_rig.py, measured in Blender), keeps every candidate with its verdict, and
finishes the best passing one: generic names, each bone's local X across the body, the source material, FBX and
.blend, and the review poses. Nothing is approved here: `approve_rig` records the human review of the contact sheet,
behind the delivery-rights gate.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..backends import comfyui, video2rig
from ..backends.blender import blender_environment
from ..character_rigging import _project_file, run_skintokens_inference, skintokens_preflight
from .. import creature_gait, creature_rig, creature_views, video_intake
from ..creature_rig import deformation_poses, rig_settings
from ..creature_video import video_prompt, video_settings
from ..creature_views import creature_config, framing, motion_settings, outside_panels
from ..failures import StageFailure, failure_record, should_retry
from ..manifest import (begin_stage, find_asset, finish_execution, finish_stage, register_artifact, save_manifest,
                        set_artifact_approval, start_execution, start_stage)
from ..paths import blender_executable, resolve_workflow, tool_root
from ..provenance import file_sha256, tool_sha256
from ..providers import artifact_rights, require_shippable, rights_of
from ..skintokens_runtime import SKINTOKENS_SETTINGS
from ..taxonomy import load_taxonomy, output_path
from ..workflow_requirements import workflow_output_rights, workflow_requirements_identity
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


# B2: video2rig's start frame, the reader's training set and known motions (docs/CREATURES.md)

FACING = {"-Y": (0, -1, 0), "+Y": (0, 1, 0), "-X": (-1, 0, 0), "+X": (1, 0, 0)}


def _v2r(config, root, step, project, log, **options):
    return video2rig.run(config, root, step, project, log, **options)


def _video2rig_identity(config, root):
    return video2rig.identity(video2rig.preflight(config, root)["local"])


def _synth(config, root, blend, request):
    """blender/synth_motion.py in the creature's rig .blend; its report, or RuntimeError with its error."""
    with tempfile.TemporaryDirectory(prefix="slopforge-synth-") as temporary:
        path = Path(temporary) / "request.json"
        path.write_text(json.dumps(request, default=str))
        subprocess.run([blender_executable(config, root), str(blend), "--background", "--factory-startup",
                        "--python", str(tool_root() / "blender/synth_motion.py"), "--", str(path)], check=False,
                       env=blender_environment())
    report = json.loads(Path(request["report"]).read_text()) if Path(request["report"]).is_file() else None
    if not report or report.get("status") != "complete":
        raise RuntimeError("synthetic motion failed: " + "; ".join((report or {}).get("errors", ["no report"])))
    return report


def _encode(frames, mp4):
    ffmpeg = os.environ.get("V2R_FFMPEG") or shutil.which("ffmpeg")
    if not ffmpeg:
        raise StageFailure("environment", "ffmpeg is not installed", operation="creature synth",
                           remedy="Install ffmpeg, or set V2R_FFMPEG to its path")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", "24", "-i", str(Path(frames) / "%04d.png"),
                    "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(mp4)], check=True)


def _stages(asset):
    """Every stage of the asset's execution records; ValueError when a record is malformed."""
    executions = asset.get("executions")
    stages = [stage for item in executions for stage in item.get("stages", [])] if (
        isinstance(executions, list) and all(isinstance(item, dict) and isinstance(item.get("stages", []), list)
                                             for item in executions)) else None
    if stages is None or not all(isinstance(stage, dict) and isinstance(stage.get("outputs") or [], list)
                                 and all(isinstance(output, dict) for output in stage.get("outputs") or [])
                                 for stage in stages):
        raise ValueError(f"creature {asset['name']}'s execution records are malformed")
    return stages


def _rig_blend(root, asset):
    """The rig .blend B1 finished, and the stage output that produced it as it is now; every execution record is
    checked before one is selected."""
    rigging = asset.get("rigging") or {}
    if rigging.get("status") not in ("review_required", "approved") or "rig_blend" not in asset.get("artifacts", {}):
        raise ValueError(f"creature {asset['name']} has no rig: run `slopforge creature rig {asset['name']}` first")
    stages = _stages(asset)
    path, blend = _project_file(root, asset["artifacts"]["rig_blend"].get("path"), "The rig .blend")
    blend = Path(blend)
    digest = file_sha256(blend) if blend.is_file() else None
    refs = [output for stage in stages if stage.get("name") == "rig_postprocess" and stage.get("status") == "succeeded"
            for output in stage.get("outputs") or [] if output.get("path") == path and output.get("sha256") == digest]
    if not refs:
        raise ValueError(f"creature {asset['name']}'s rig .blend is missing or changed since it was made; rig it again")
    return blend, refs[-1]


def _fail(root, config, manifest, asset, execution, stage, exc, record):
    failure = failure_record(exc, stage=stage["name"], stage_id=stage["id"], attempt=stage["attempt"],
                             operation=stage["name"])
    finish_stage(stage, "failed", error=str(exc) or type(exc).__name__, failure=failure)
    finish_execution(execution, "failed", failure=failure)
    record.update(status="failed", error=str(exc) or type(exc).__name__)
    save_manifest(root / config["asset_pipeline"]["manifest"], manifest)


def calibrate_creature(project_root, config, manifest, name, *, views=None, widths=None, poses=None):
    """Turn a rigged creature into a video2rig project: creature.json from its rig record and type (fit_bones, hinges,
    declared joint ranges), the rig exported, the two-view start frame rendered with its view pair and framing and
    checked to hold the whole creature, then the reader's training pictures (reader.prepare, training skipped)."""
    root = Path(project_root).resolve()
    asset = _creature(manifest, name)
    blend, blend_ref = _rig_blend(root, asset)
    settings = motion_settings(load_taxonomy(root)[asset["type"]])
    settings.update({key: value for key, value in (("views", views), ("widths", widths)) if value is not None})
    framing(settings, length=1.0, width=1.0)   # views, widths and margins refuse here, before anything is made
    count = poses or settings["training_poses"]
    if isinstance(count, bool) or not isinstance(count, int) or not 100 <= count <= 20000:
        raise ValueError(f"training poses must be 100 to 20000, got {count!r}")
    creature = creature_config(asset["name"], asset["rigging"], settings["joint_limits"])
    folder = output_path(root, config, asset["type"], asset["name"]) / "Motion"
    if (folder / "video2rig").exists():
        raise FileExistsError(f"A video2rig project exists; inspect or move it before calibrating again: "
                              f"{folder / 'video2rig'}")
    provider = _video2rig_identity(config, root)
    rights = [{"source": "video2rig", **provider["output_rights"]}] + rights_of(config, "blender")
    manifest_path = root / config["asset_pipeline"]["manifest"]
    request = {key: settings.get(key) for key in ("views", "widths", "margin", "margin_wide", "side")}
    execution = start_execution(asset, {"stage": "creature_calibration", "rig_blend_sha256": blend_ref["sha256"],
                                        "creature": creature, "framing": request, "training_poses": count,
                                        "video2rig": video2rig.runtime.VIDEO2RIG_REVISION,
                                        "checks_sha256": file_sha256(creature_views.__file__)})
    project = video2rig.project_folder(folder, creature)
    log = folder / "video2rig.log"
    record = asset["motion"] = {"status": "calibrating", "project": project.relative_to(root).as_posix(),
                                "creature": creature, "training_poses": count, "rig_status": asset["rigging"]["status"],
                                "clips": {}}
    review = asset["rigging"]["status"]   # a rig awaiting its deformation review may be calibrated; the stages say so
    stage = start_stage(execution, "creature_calibration", 1, [blend_ref], {"creature": creature, "framing": request},
                        {"provider": provider, "output_rights": rights, "rig_review": review})
    begin_stage(stage)
    save_manifest(manifest_path, manifest)
    try:
        _v2r(config, root, "export_rig", project, log, blend=blend)
        mesh, rig = np.load(project / "rig/mesh.npz"), json.loads((project / "rig/rig.json").read_text())
        world = np.asarray(rig["armature_world"], float)
        skin = mesh["verts"] @ world[:3, :3].T + world[:3, 3]
        forward = np.array(FACING[creature["facing"]], float)
        chosen = framing(settings, length=float(np.ptp(skin @ forward)),
                         width=float(np.ptp(skin @ np.cross((0, 0, 1), forward))))
        chosen["facing"] = creature["facing"]   # declared, not guessed by render_start from foot and toe names
        _v2r(config, root, "render_start", project, log, blend=blend, framing=chosen)
        cut = outside_panels(json.loads((project / "start/cameras.json").read_text()), skin)
        if cut:
            raise StageFailure("processing_validation", f"the creature leaves the start frame (points outside, by "
                               f"view: {cut})", operation="creature calibrate",
                               remedy="raise margin_wide or margin, or declare other views or widths")
    except Exception as exc:
        _fail(root, config, manifest, asset, execution, stage, exc, record)
        raise
    record["framing"] = chosen
    start = [_artifact_ref(root, project / path, f"{execution['id']}:{label}", kind, "creature_calibration", 1,
                           [blend_ref]) for label, kind, path in (("mesh", "data.rig_mesh", "rig/mesh.npz"),
                                                                  ("rig", "data.rig", "rig/rig.json"),
                                                                  ("cameras", "data.cameras", "start/cameras.json"),
                                                                  ("start", "image.calibrated_views", "start/start.png"))]
    finish_stage(stage, "succeeded", start)
    stage = start_stage(execution, "detector_training_set", 1, start[:3], {"poses": count, "creature": creature},
                        {"provider": provider, "output_rights": rights, "rig_review": review})
    begin_stage(stage)
    save_manifest(manifest_path, manifest)
    try:
        _v2r(config, root, "prepare", project, log, blend=blend, poses=count)
        if not (project / "reader/poses.npz").is_file():
            raise StageFailure("processing_validation", "reader.prepare wrote no reader/poses.npz",
                               operation="creature calibrate", remedy=f"Read {log}")
    except Exception as exc:
        _fail(root, config, manifest, asset, execution, stage, exc, record)
        raise
    finish_stage(stage, "succeeded", [_artifact_ref(root, project / path, f"{execution['id']}:{label}", kind,
                                                    "detector_training_set", 1, start)
                                      for label, kind, path in (("poses", "data.training_set", "reader/poses.npz"),
                                                                ("visible", "data.training_visibility",
                                                                 "reader/visible.npz"))
                                      if (project / path).is_file()])
    finish_execution(execution, "succeeded")
    record["status"] = "calibrated"
    save_manifest(manifest_path, manifest)
    return {"status": "calibrated", "project": record["project"], "framing": chosen, "training_poses": count}


def synthesize_motion(project_root, config, manifest, name, clip, *, kind, seed=0, frames=96, action=None):
    """Render a known motion (synth_motion.py: random, gait or an authored action) through the creature's start
    cameras as an exam clip, with its truth: video2rig's render_poses at each panel's own size, the panels joined
    as render_start joins them, 24 fps. A motion that leaves a panel is refused (nothing may leave the frame)."""
    root = Path(project_root).resolve()
    asset = _creature(manifest, name)
    record = asset.get("motion") or {}
    if record.get("status") != "calibrated":
        raise ValueError(f"creature {name} is not calibrated: run `slopforge creature calibrate {name}` first")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", clip):
        raise ValueError(f"clip names are lower-case letters, digits and underscores, got {clip!r}")
    if kind not in ("random", "gait", "action"):
        raise ValueError(f"the motion kind must be random, gait or action, got {kind!r}")
    if kind == "action" and not action:
        raise ValueError("--kind action needs --action, the authored action to loop")
    if isinstance(frames, bool) or not isinstance(frames, int) or not 1 <= frames <= 2400:
        raise ValueError(f"frames must be 1 to 2400, got {frames!r}")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError(f"seed must be a whole number of 0 or more, got {seed!r}")
    project = root / record["project"]
    exam, mp4 = project / "exam" / clip, project / "clips" / f"{clip}.mp4"
    if exam.exists() or mp4.exists():
        raise FileExistsError(f"Clip {clip} exists; inspect or move it before rendering it again: {exam}")
    blend, blend_ref = _rig_blend(root, asset)
    creature = json.loads((project / "creature.json").read_text())
    if creature != record["creature"]:
        raise ValueError(f"{project / 'creature.json'} changed since calibration; calibrate {name} again")
    cameras = json.loads((project / "start/cameras.json").read_text())
    settings = {"clip": clip, "kind": kind, "seed": seed, "frames": frames, "action": action}
    tool = tool_sha256(tool_root() / "blender/synth_motion.py")
    execution = start_execution(asset, {"stage": "synthetic_motion", **settings, "creature": creature,
                                        "cameras_sha256": file_sha256(project / "start/cameras.json"),
                                        "tool_sha256": tool, "checks_sha256": file_sha256(creature_views.__file__),
                                        "video2rig": video2rig.runtime.VIDEO2RIG_REVISION})
    provider = _video2rig_identity(config, root)
    rights = [{"source": "video2rig", **provider["output_rights"]}] + rights_of(config, "blender")
    stage = start_stage(execution, "synthetic_motion", 1, [blend_ref], {**settings, "tool_sha256": tool},
                        {"provider": provider, "output_rights": rights, "rig_review": asset["rigging"]["status"]})
    begin_stage(stage)
    manifest_path = root / config["asset_pipeline"]["manifest"]
    save_manifest(manifest_path, manifest)
    log = project.parent / "video2rig.log"
    try:
        exam.mkdir(parents=True)
        _synth(config, root, blend, {"creature": creature, "kind": kind, "seed": seed, "frames": frames,
                                     "action": action, "loops": 4, "out": str(exam / "poses.npz"),
                                     "truth": str(exam / "truth.json"), "report": str(exam / "synth_report.json")})
        panels = {}
        for fit in sorted({max(view["width_px"], view["height_px"]) for view in cameras["views"]}):
            out = exam / f"renders_fit{fit}"
            _v2r(config, root, "render_poses", project, log, blend=blend, motion=exam / "poses.npz", out=out, fit=fit)
            panels.update({view["name"]: out / view["name"] for view in cameras["views"]
                           if max(view["width_px"], view["height_px"]) == fit})
            shutil.copy(out / "labels.npz", exam / "labels.npz")
        labels = np.load(exam / "labels.npz")
        world = np.asarray(labels["armature_world"], float)
        joints = np.concatenate([labels["heads"], labels["tails"]], axis=1).reshape(-1, 3)
        left = outside_panels(cameras, joints @ world[:3, :3].T + world[:3, 3])
        if left:
            raise StageFailure("processing_validation", f"the {kind} motion leaves the frame (joint positions "
                               f"outside, by view: {left})", operation="creature synth",
                               remedy="calibrate with a larger margin_wide, or make a motion that stays nearer")
        count = len(np.load(exam / "poses.npz")["quats"])
        width, height = cameras["frame_px"]
        (exam / "frames").mkdir()
        for index in range(count):
            frame = np.zeros((height, width, 3), np.uint8)
            for view in cameras["views"]:
                with Image.open(panels[view["name"]] / f"{index:04d}.jpg") as panel:
                    frame[:, view["x0_px"]:view["x0_px"] + view["width_px"]] = np.asarray(panel.convert("RGB"))
            for view in cameras["views"][1:]:   # render_start's divider: 4 px at .03
                frame[:, view["x0_px"] - 2:view["x0_px"] + 2] = round(0.03 * 255)
            Image.fromarray(frame).save(exam / "frames" / f"{index:04d}.png")
        mp4.parent.mkdir(exist_ok=True)
        _encode(exam / "frames", mp4)
    except Exception as exc:
        _fail(root, config, manifest, asset, execution, stage, exc, {})
        raise
    finish_stage(stage, "succeeded", [_artifact_ref(root, path, f"{execution['id']}:{label}", kind_, "synthetic_motion",
                                                    1, [blend_ref])
                                      for label, kind_, path in (("poses", "data.known_motion", exam / "poses.npz"),
                                                                 ("truth", "data.motion_truth", exam / "truth.json"),
                                                                 ("labels", "data.motion_labels", exam / "labels.npz"),
                                                                 ("clip", "video.synthetic_clip", mp4))])
    finish_execution(execution, "succeeded")
    record["clips"][clip] = {"kind": kind, "seed": seed, "frames": count, "action": action,
                             "clip": mp4.relative_to(root).as_posix(), "exam": exam.relative_to(root).as_posix()}
    save_manifest(manifest_path, manifest)
    return {"status": "rendered", "clip": record["clips"][clip]["clip"], "frames": count}


# B5: video generation and intake (docs/CREATURES.md, "Video generation")

VIDEO_TIMEOUT = 3600   # seconds for one clip; #149's 121-frame clips took 1,300-1,600 s on an 80 GB H100


def _generate_video(config, root, workflow, prompt, negative, image, destination, seed, metadata, **options):
    return comfyui.generate_video(root, config, workflow, prompt, negative, image, destination, seed, metadata,
                                  **options)


def _read_clip(path):
    return video_intake.read_clip(path)


def _start_frame(root, asset, project):
    """The calibrated start frame as the calibration stage made it; ValueError when it changed since."""
    path = (project / "start/start.png").relative_to(root).as_posix()
    digest = file_sha256(project / "start/start.png") if (project / "start/start.png").is_file() else None
    refs = [output for stage in _stages(asset) if stage.get("name") == "creature_calibration"
            and stage.get("status") == "succeeded" for output in stage.get("outputs") or []
            if output.get("path") == path and output.get("sha256") == digest]
    if not refs:
        raise ValueError(f"creature {asset['name']}'s start frame is missing or changed since calibration; calibrate "
                         "it again")
    return project / "start/start.png", refs[-1]


def _intake(config, root, project, clip, mp4, start, cameras, limits, log):
    """B0's validation of one clip: video_intake's checks first, then, only for a clip that passes them, video2rig's
    check of the two views read with the trained reader (its body and limb disagreement against D7's limits), the
    clip's measured frame times given to video2rig before it reads anything."""
    frames, fps = _read_clip(mp4)
    measured = video_intake.measure(frames, fps, start, cameras)
    validation = video_intake.judge(measured, limits)
    work = project / "work" / clip
    work.mkdir(parents=True, exist_ok=True)
    if validation["status"] == "passed":
        # every decoded frame is one container frame (a clip with repeated frames was refused above)
        video_intake.write_timing(work, measured["video_frames"], fps, container_fps=fps)
        try:
            check = _v2r(config, root, "check", project, log, clip=clip)
        except StageFailure as exc:   # video2rig was ready before generation: a crash on this clip refuses it
            check = {"verdict": "FAIL", "messages": [f"video2rig's check could not read the clip: {exc}"]}
        body, limbs = check.get("body"), check.get("limbs")
        failed = check.get("verdict") == "FAIL" or body is None or limbs is None
        measured.update(video_view_disagreement=body, video_limb_disagreement=limbs,
                        video_check_verdict=check.get("verdict"), video_check_failures=int(failed))
        cross = (("video_views_disagree", "video_view_disagreement", "max_video_view_disagreement",
                  "the views disagree on the body by {:.1%} of its height"),
                 ("video_limbs_disagree", "video_limb_disagreement", "max_video_limb_disagreement",
                  "the views disagree on the limbs by {:.1%} of its height"))
        for code, metric, limit, words in cross:
            if measured[metric] is not None and measured[metric] > limits[limit]:
                validation["errors"].append(words.format(measured[metric]))
                validation["failure_codes"].append(code)
        if failed and not validation["failure_codes"]:
            validation["errors"].append("video2rig's check failed the clip: " + ("; ".join(check.get("messages") or [])
                                                                                  or "no body or limb reading"))
            validation["failure_codes"].append("video_check_failed")
        validation["limits"].update({key: limits[key] for key in ("max_video_view_disagreement",
                                                                    "max_video_limb_disagreement")},
                                    max_video_check_failures=0)
        validation["status"] = "failed" if validation["errors"] else "passed"
        validation["check"] = check
    (work / "intake.json").write_text(json.dumps(validation, indent=1))
    return validation


def video_creature(project_root, config, manifest, name, motion, *, count=1, seed=1):
    """`count` clips of `motion` from the calibrated creature's start frame (B5): seeded candidates on the type's
    image-to-video graph, each through the intake before anything reads it; a refused clip is kept with its reason and
    the next seed is tried while failures.should_retry allows (count + the motion's retries tries in all)."""
    root = Path(project_root).resolve()
    asset = _creature(manifest, name)
    record = asset.get("motion") or {}
    if record.get("status") != "calibrated":
        raise ValueError(f"creature {name} is not calibrated: run `slopforge creature calibrate {name}` first")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
        raise ValueError(f"count must be 1 to 8, got {count!r}")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError(f"seed must be a whole number of 0 or more, got {seed!r}")
    settings = video_settings(load_taxonomy(root)[asset["type"]], motion)
    project = root / record["project"]
    if not (project / "reader/reader.pt").is_file():
        raise ValueError(f"creature {name}'s reader is not trained ({project / 'reader/reader.pt'}): intake reads "
                         "each clip's two views with it; train it with video2rig's reader.train on the GPU provider")
    start, start_ref = _start_frame(root, asset, project)
    cameras = json.loads((project / "start/cameras.json").read_text())
    _video2rig_identity(config, root)   # video2rig's check reads every clip: refuse now, not after the GPU time
    for tool in ("ffprobe", "ffmpeg"):
        if not shutil.which(tool):
            raise ValueError(f"{tool} is not installed: the intake reads each clip with it; install ffmpeg")
    framed = record.get("framing") or {}
    prompt, negative = video_prompt(settings, description=asset.get("description") or name,
                                    name=name.replace("_", " "), views=framed.get("views") or [],
                                    side=framed.get("side", "left"))
    workflow = resolve_workflow(root, settings["workflow"])
    graph = json.loads(workflow.read_text())
    length = [node_id for node_id, node in graph.items() if node.get("class_type") == "WanImageToVideo"]
    loaders = [node_id for node_id, node in graph.items() if node.get("class_type") == "LoadImage"]
    if len(length) != 1 or len(loaders) != 1:
        raise ValueError(f"{workflow.name} needs one WanImageToVideo node (the clip's length) and one LoadImage node "
                         f"(the start frame); it has {len(length)} and {len(loaders)}")
    size = graph[length[0]]["inputs"]
    frame_w, frame_h = cameras["frame_px"]
    if abs(size["width"] / size["height"] - frame_w / frame_h) > 0.01 * frame_w / frame_h:
        raise ValueError(f"{workflow.name} renders {size['width']}x{size['height']}, but the start frame is "
                         f"{frame_w}x{frame_h}: the graph would crop it and every clip would fail intake")
    workflow_inputs = {length[0]: {"length": settings["frames"]}}
    models = sorted({value for node in graph.values() for value in node.get("inputs", {}).values()
                     if isinstance(value, str) and value.endswith(".safetensors")})
    provider = {"name": "comfyui", "workflow": workflow.name, "workflow_sha256": file_sha256(workflow),
                "requirements": workflow_requirements_identity(workflow, graph)}
    rights = workflow_output_rights(workflow, models)
    start_array = np.asarray(Image.open(start).convert("RGB"))
    budget = count + settings["retries"]
    for clip_seed in range(seed, seed + budget):   # every seed this run may use, before any GPU time
        clip = f"{motion}_s{clip_seed}"
        if (project / "clips" / f"{clip}.mp4").exists() or (project / "work" / clip).exists():
            raise FileExistsError(f"Clip {clip} exists from an earlier run; start from a later seed (--seed) or move "
                                  f"it: {project / 'clips' / f'{clip}.mp4'}")
    reader = file_sha256(project / "reader/reader.pt")
    manifest_path = root / config["asset_pipeline"]["manifest"]
    execution = start_execution(asset, {"stage": "video_generation", "motion": motion, "count": count, "seed": seed,
                                        "prompt": prompt, "negative": negative, "frames": settings["frames"],
                                        "workflow_sha256": provider["workflow_sha256"], "limits": settings["limits"],
                                        "intake_sha256": file_sha256(video_intake.__file__),
                                        "start_sha256": start_ref["sha256"], "reader_sha256": reader,
                                        "video2rig": video2rig.runtime.VIDEO2RIG_REVISION})
    candidates = record.setdefault("videos", {}).setdefault(motion, [])
    log = project.parent / "video2rig.log"
    accepted, rejected, attempt = [], [], 0
    while len(accepted) < count and attempt < budget:
        attempt += 1
        clip_seed = seed + attempt - 1
        clip = f"{motion}_s{clip_seed}"
        mp4, meta = project / "clips" / f"{clip}.mp4", project / "clips" / f"{clip}.generation.json"
        mp4.parent.mkdir(parents=True, exist_ok=True)
        parameters = {"motion": motion, "seed": clip_seed, "prompt": prompt, "negative": negative,
                      "frames": settings["frames"], "workflow_inputs": workflow_inputs}
        stage = start_stage(execution, "video_generation", attempt, [start_ref], parameters,
                            {"provider": provider, "output_rights": rights, "models": models,
                             "reader_sha256": reader})
        begin_stage(stage)
        save_manifest(manifest_path, manifest)
        candidate = {"clip": clip, "seed": clip_seed, "prompt": prompt, "frames": settings["frames"]}
        try:
            _generate_video(config, root, workflow, prompt, negative, start, mp4, clip_seed, meta,
                            workflow_inputs=workflow_inputs, timeout=VIDEO_TIMEOUT)
            generation = json.loads(meta.read_text()) if meta.is_file() else {}
            candidate.update(path=mp4.relative_to(root).as_posix(), generation=generation)
            validation = _intake(config, root, project, clip, mp4, start_array, cameras, settings["limits"], log)
        except StageFailure as exc:
            failure = failure_record(exc, stage=stage["name"], stage_id=stage["id"], attempt=attempt,
                                     operation="video_generation")
            if not failure["retryable"]:
                candidates.append({**candidate, "status": "failed", "reasons": [str(exc)]})
                _fail(root, config, manifest, asset, execution, stage, exc, {})
                raise
            validation = exc.evidence["validation"]
        except (Exception, KeyboardInterrupt) as exc:
            candidates.append({**candidate, "status": "failed", "reasons": [str(exc) or type(exc).__name__]})
            _fail(root, config, manifest, asset, execution, stage, exc, {})
            raise
        candidate.update(status=validation["status"] == "passed" and "accepted" or "rejected",
                         codes=list(validation["failure_codes"]), reasons=list(validation["errors"]),
                         intake={key: value for key, value in validation.get("measured", {}).items()
                                 if key != "panels"},
                         panels=validation.get("measured", {}).get("panels"), check=validation.get("check"))
        candidates.append(candidate)
        stage["intake"] = {"status": validation["status"], "codes": candidate["codes"],
                           "measured": validation.get("measured"), "check": validation.get("check")}
        if candidate["status"] == "accepted":
            accepted.append(clip)
            outputs = [_artifact_ref(root, mp4, f"{execution['id']}:{clip}", "video.generated_clip",
                                     "video_generation", attempt, [start_ref]),
                       _artifact_ref(root, project / "work" / clip / "intake.json", f"{execution['id']}:{clip}:intake",
                                     "data.video_intake", "video_generation", attempt, [start_ref])]
            if meta.is_file():
                outputs.append(_artifact_ref(root, meta, f"{execution['id']}:{clip}:generation",
                                             "data.video_generation", "video_generation", attempt, [start_ref]))
            finish_stage(stage, "succeeded", outputs)
            record.setdefault("clips", {})[clip] = {
                "kind": "video", "motion": motion, "seed": clip_seed, "clip": mp4.relative_to(root).as_posix(),
                "frames": validation["measured"]["video_frames"], "fps": validation["measured"]["video_container_fps"]}
            save_manifest(manifest_path, manifest)
            continue
        rejected.append(clip)
        refusal = StageFailure("candidate_quality", "; ".join(validation["errors"]), operation="video_intake",
                               remedy="the clip is kept; the next seed is tried", evidence={"validation": validation})
        failure = failure_record(refusal, stage=stage["name"], stage_id=stage["id"], attempt=attempt,
                                 operation="video_intake")
        finish_stage(stage, "failed", error="; ".join(validation["errors"]), failure=failure)
        save_manifest(manifest_path, manifest)
        if not should_retry(failure, used=attempt, limit=budget) or budget - attempt < count - len(accepted):
            break                                                  # out of tries, or the clips asked for are out of reach
    if len(accepted) < count:
        exhausted = StageFailure("candidate_quality", f"{len(accepted)} of {count} {motion} clips passed intake in "
                                 f"{attempt} tries (seeds {seed}-{seed + attempt - 1})", operation="creature video",
                                 remedy="read the rejected clips' reasons in the manifest and their intake.json; "
                                        "try other seeds with --seed, or change the motion's prompt",
                                 evidence={"rejected": rejected})
        finish_execution(execution, "failed", failure=failure_record(exhausted, stage="video_generation",
                                                                       attempt=attempt, operation="creature video"))
        save_manifest(manifest_path, manifest)
        raise exhausted
    finish_execution(execution, "succeeded")
    save_manifest(manifest_path, manifest)
    return {"status": "accepted", "clips": accepted, "rejected": rejected}


# B6: extraction, bake and review (docs/CREATURES.md, "Extraction and bake")

BAKE = "blender/bake_extracted_motion.py"
REVIEW_SAMPLES = 8   # one cycle's phases in the review sheet


def _bake(config, root, source, request):
    """blender/bake_extracted_motion.py on the .blend import_motion saved; its report (complete, or an error with
    its failure code), RuntimeError when Blender wrote none."""
    with tempfile.TemporaryDirectory(prefix="slopforge-bake-") as temporary:
        path = Path(temporary) / "request.json"
        path.write_text(json.dumps(request, default=str))
        subprocess.run([blender_executable(config, root), str(source), "--background", "--factory-startup",
                        "--python", str(tool_root() / BAKE), "--", str(path)], check=False, env=blender_environment())
    if not Path(request["report"]).is_file():
        raise RuntimeError("Blender's motion bake wrote no report")
    return json.loads(Path(request["report"]).read_text())


def _accepted_clip(root, asset, clip):
    """(the clip's entry in motion.clips, its video_generation output as intake accepted it); ValueError otherwise."""
    entry = ((asset.get("motion") or {}).get("clips") or {}).get(clip)
    if not isinstance(entry, dict) or entry.get("kind") != "video":
        raise ValueError(f"creature {asset['name']} has no accepted clip {clip!r}: extract a clip that passed "
                         f"`slopforge creature video` (see motion.videos for each candidate's verdict)")
    path = root / entry["clip"]
    digest = file_sha256(path) if path.is_file() else None
    refs = [output for stage in _stages(asset) if stage.get("name") == "video_generation"
            and stage.get("status") == "succeeded" for output in stage.get("outputs") or []
            if output.get("path") == entry["clip"] and output.get("sha256") == digest]
    if not refs:
        raise ValueError(f"clip {clip} is missing or changed since intake accepted it: {entry['clip']}")
    rights = next(stage["provenance"].get("output_rights") or [] for stage in _stages(asset)
                  if stage.get("name") == "video_generation" and refs[-1] in (stage.get("outputs") or []))
    return entry, refs[-1], rights


def _legs(root, asset):
    """{front.L: [the leg's last two bones]}: each declared leg's chain from B1's structure report, by final name;
    the bake takes the lower of the two bones' tails as the foot."""
    structure = json.loads((root / asset["rigging"]["structure"]).read_text())
    names = structure["names"]
    return {f"{limb['end']}.{limb['side']}": [names[bone] for bone in limb["chain"][-2:]]
            for limb in structure["limbs"]}


def _check_fit(motion, creature, frames, times):
    """B8's boundary: the fit's bones are the creature's, one fit per clip frame at the clip's measured times (the
    intake's timing.json; video2rig's own cadence read Wan's 16 fps as 24, #149), and every number finite."""
    fit = np.load(motion)
    problems = []
    if set(map(str, fit["bones"])) != set(creature["fit_bones"]) or str(fit["root"]) != creature["root_bone"]:
        problems.append(f"the fit's bones ({len(fit['bones'])}, root {fit['root']}) are not creature.json's "
                        f"({len(creature['fit_bones'])}, root {creature['root_bone']})")
    if len(fit["times"]) != frames or not np.allclose(fit["times"], times, atol=1e-6):
        problems.append(f"the fit's frame times are not the clip's measured ones ({len(fit['times'])} frames, "
                        f"{len(times)} expected): video2rig did not read work/<clip>/timing.json")
    if not all(np.isfinite(fit[key]).all() for key in ("quaternions", "root_location", "times")):
        problems.append("the fit's rotations or root positions are not finite")
    if problems:
        raise StageFailure("processing_validation", "; ".join(problems), operation="creature extract",
                           remedy="read video2rig.log and work/<clip>/report.json; the clip and the fit are kept")


def _review_sheet(root, mp4, cameras, renders, path):
    """Each sampled phase as a row: the clip's two panels at that frame, then the baked Action in the same views."""
    frames, _ = _read_clip(mp4)
    by_index = {}
    for item in renders:
        by_index.setdefault(item["index"], {})[item["view"]] = item
    tiles = []
    for index in sorted(by_index):
        row = by_index[index]
        frame = next(iter(row.values()))["clip_frame"]
        for view in cameras["views"]:
            panel = frames[frame][:, view["x0_px"] * frames.shape[2] // cameras["frame_px"][0]:
                                  (view["x0_px"] + view["width_px"]) * frames.shape[2] // cameras["frame_px"][0]]
            tiles.append((Image.fromarray(panel), f"clip frame {frame}, {view['name'][4:]}"))
        for view in cameras["views"]:
            with Image.open(row[view["name"]]["path"]) as image:
                tiles.append((image.convert("RGB"), f"baked, {view['name'][4:]}"))
    _sheet(tiles, path, columns=2 * len(cameras["views"]))


def extract_creature(project_root, config, manifest, name, clip):
    """One clip that passed intake through video2rig's run (the reader road) and import_motion, then baked in place
    and cut to its loop (B6): the FBX is registered as a candidate animation with its stride, period and review
    sheet; `animation approve` is the human gate. A fit that does not match the clip stops before the bake; a clip
    with no walk cycle is refused (candidate_quality: generate another) and kept with its fit."""
    root = Path(project_root).resolve()
    asset = _creature(manifest, name)
    record = asset.get("motion") or {}
    if record.get("status") != "calibrated":
        raise ValueError(f"creature {name} is not calibrated: run `slopforge creature calibrate {name}` first")
    entry, clip_ref, clip_rights = _accepted_clip(root, asset, clip)
    project = root / record["project"]
    folder = project.parent / clip
    if folder.exists() or (project / "out" / f"{clip}.npz").exists():
        raise FileExistsError(f"Clip {clip} was extracted before; inspect or move {folder} and "
                              f"{project / 'out' / f'{clip}.npz'} before extracting it again")
    if not (project / "reader/reader.pt").is_file():
        raise ValueError(f"creature {name}'s reader is missing ({project / 'reader/reader.pt'}): run reads the clip "
                         "with it")
    blend, blend_ref = _rig_blend(root, asset)
    creature = json.loads((project / "creature.json").read_text())
    if creature != record["creature"]:
        raise ValueError(f"{project / 'creature.json'} changed since calibration; calibrate {name} again")
    times = json.loads((project / "work" / clip / "timing.json").read_text())["times"]
    legs = _legs(root, asset)
    provider = _video2rig_identity(config, root)
    rights = clip_rights + [{"source": "video2rig", **provider["output_rights"]}] + rights_of(config, "blender")
    reader = file_sha256(project / "reader/reader.pt")
    tool = tool_sha256(tool_root() / BAKE)
    execution = start_execution(asset, {"stage": "motion_extraction", "clip": clip, "clip_sha256": clip_ref["sha256"],
                                        "reader_sha256": reader, "rig_blend_sha256": blend_ref["sha256"],
                                        "creature": creature, "legs": legs, "bake_tool_sha256": tool,
                                        "gait_sha256": file_sha256(creature_gait.__file__),
                                        "video2rig": video2rig.runtime.VIDEO2RIG_REVISION})
    manifest_path = root / config["asset_pipeline"]["manifest"]
    log = project.parent / "video2rig.log"
    stage = start_stage(execution, "motion_extraction", 1, [clip_ref], {"clip": clip},
                        {"provider": provider, "output_rights": rights, "reader_sha256": reader})
    begin_stage(stage)
    save_manifest(manifest_path, manifest)
    extraction = entry["extraction"] = {"status": "extracting"}
    try:
        fit = _v2r(config, root, "run", project, log, clip=clip)
        _check_fit(fit["motion"], creature, entry["frames"], times)
    except (Exception, KeyboardInterrupt) as exc:
        _fail(root, config, manifest, asset, execution, stage, exc, extraction)
        raise
    work = project / "work" / clip
    fit_refs = [_artifact_ref(root, path, f"{execution['id']}:{label}", kind, "motion_extraction", 1, [clip_ref])
                for label, kind, path in (("fit", "data.motion_extraction", fit["motion"]),
                                          ("report", "report.motion_extraction", work / "report.json"))
                if path.is_file()]
    finish_stage(stage, "succeeded", fit_refs)
    extraction.update(fit=Path(fit["motion"]).relative_to(root).as_posix(), warnings=fit["report"].get("warnings", []),
                      fit_report={key: value for key, value in fit["report"].items() if key != "warnings"})

    folder.mkdir(parents=True)
    request = {"legs": legs, "root_bone": creature["root_bone"], "fit_bones": creature["fit_bones"],
               "fbx": str(folder / f"{clip}.fbx"), "blend": str(folder / f"{clip}_baked.blend"),
               "renders": str(folder / "renders"), "cameras": str(project / "start/cameras.json"),
               "samples": REVIEW_SAMPLES, "report": str(folder / "bake.json")}
    stage = start_stage(execution, "motion_bake", 1, [fit_refs[0], blend_ref],
                        {"legs": legs, "samples": REVIEW_SAMPLES, "tool_sha256": tool},
                        {"output_rights": rights})
    begin_stage(stage)
    save_manifest(manifest_path, manifest)
    try:
        _v2r(config, root, "import_motion", project, log, blend=blend, clip=clip, save=folder / "source.blend")
        if not (folder / "source.blend").is_file():
            raise RuntimeError("video2rig's import_motion saved no .blend")
        baked = _bake(config, root, folder / "source.blend", request)
        if baked.get("status") == "error" and baked.get("failure_code") in creature_gait.GAIT_LIMITS:
            validation = {"status": "failed", "errors": baked["errors"], "failure_codes": [baked["failure_code"]],
                          "artifact_kind": "motion", "measured": baked.get("measured") or {},
                          "limits": creature_gait.GAIT_LIMITS[baked["failure_code"]]}
            raise StageFailure("candidate_quality", "; ".join(baked["errors"]), operation="creature extract",
                               remedy="the clip and its fit are kept; generate another clip of the motion",
                               evidence={"validation": validation})
        if baked.get("status") != "complete":
            raise RuntimeError("the motion bake failed: " + "; ".join(baked.get("errors") or ["no reason"]))
        cameras = json.loads((project / "start/cameras.json").read_text())
        _review_sheet(root, root / entry["clip"], cameras, baked["renders"], folder / "review.png")
    except StageFailure as exc:
        if exc.category == "candidate_quality":
            failure = failure_record(exc, stage=stage["name"], stage_id=stage["id"], attempt=1,
                                     operation="creature extract")
            finish_stage(stage, "failed", error=str(exc), failure=failure)
            finish_execution(execution, "failed", failure=failure)
            extraction.update(status="rejected", codes=exc.evidence["validation"]["failure_codes"],
                              reasons=exc.evidence["validation"]["errors"])
            save_manifest(manifest_path, manifest)
        else:
            _fail(root, config, manifest, asset, execution, stage, exc, extraction)
        raise
    except (Exception, KeyboardInterrupt) as exc:
        _fail(root, config, manifest, asset, execution, stage, exc, extraction)
        raise
    parents = [fit_refs[0], blend_ref]
    outputs = [_artifact_ref(root, path, f"{execution['id']}:{label}", kind, "motion_bake", 1, parents)
               for label, kind, path in (("fbx", "animation.fbx", folder / f"{clip}.fbx"),
                                         ("bake", "report.motion_bake", folder / "bake.json"),
                                         ("blend", "project.blend", folder / f"{clip}_baked.blend"),
                                         ("review", "image.motion_review", folder / "review.png"))]
    finish_stage(stage, "succeeded", outputs)
    finish_execution(execution, "succeeded")
    gait = {key: baked[key] for key in ("stride_m", "period_s", "speed_mps", "cycles", "residual_travel_m",
                                        "stance_slide_mps")}
    weak = [f"{leg} planted once: its steps barely lift; watch it in the review sheet" for leg in baked["weak_legs"]]
    extraction["warnings"] = extraction["warnings"] + weak
    relative = {output["type"]: output["path"] for output in outputs}
    register_artifact(manifest, asset["id"], f"animation.{clip}", "animation.fbx", relative["animation.fbx"],
                      status="candidate", derived_from=[{"asset_id": asset["id"], "output_id": "rig"}],
                      provenance={"provider": provider, "source_clip": entry["clip"], "loop": True,
                                  "root_motion": False, **gait, "window": baked["window"], "fps": baked["fps"],
                                  "output_rights": rights},
                      approval_status="pending", validation={"measured": {**gait, "plants": baked["plants"]}})
    extraction.update(status="review_required", fbx=relative["animation.fbx"], bake=relative["report.motion_bake"],
                      review_sheet=relative["image.motion_review"], window=baked["window"], **gait,
                      outputs={output["type"]: output["sha256"] for output in outputs})
    save_manifest(manifest_path, manifest)
    return {"status": "review_required", "fbx": relative["animation.fbx"],
            "review_sheet": relative["image.motion_review"], "warnings": extraction["warnings"],
            "window": baked["window"], **gait}


def approve_motion(project_root, manifest, name, clip, *, confirmed=False):
    """Record the human review of a baked creature clip (B6's gate): its rig approved first, its FBX, bake report and
    review sheet unchanged since the bake, and the rights over its whole lineage shippable."""
    if not confirmed:
        raise ValueError("Explicit human confirmation is required: review the clip's review sheet, then pass --confirm")
    root = Path(project_root).resolve()
    asset = _creature(manifest, name)
    entry = ((asset.get("motion") or {}).get("clips") or {}).get(clip) or {}
    extraction = entry.get("extraction") or {}
    if extraction.get("status") not in ("review_required", "approved") or f"animation.{clip}" not in asset["artifacts"]:
        raise ValueError(f"creature {name} has no baked clip {clip!r}: run `slopforge creature extract {name} {clip}`")
    if (asset.get("rigging") or {}).get("status") != "approved":
        raise ValueError(f"creature {name}'s rig is not approved: review its contact sheet and run "
                         f"`slopforge creature approve-rig {name} --confirm` first")
    for kind, digest in extraction["outputs"].items():
        path = root / {"animation.fbx": extraction["fbx"], "report.motion_bake": extraction["bake"],
                       "image.motion_review": extraction["review_sheet"]}.get(kind, "")
        if kind in ("animation.fbx", "report.motion_bake", "image.motion_review") and (
                not path.is_file() or file_sha256(path) != digest):
            raise ValueError(f"clip {clip}'s {kind} is missing or changed since the bake; extract it again")
    rights = require_shippable(artifact_rights(manifest, asset["id"], f"animation.{clip}"), f"{name} {clip}",
                               "animation approve")
    set_artifact_approval(manifest, asset["id"], f"animation.{clip}", "approved")
    extraction.update(status="approved", approved_at=datetime.now(timezone.utc).isoformat(), output_rights=rights)
    return {"status": "approved", "output_rights": rights}
