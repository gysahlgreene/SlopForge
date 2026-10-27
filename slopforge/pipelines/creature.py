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

from ..backends import video2rig
from ..backends.blender import blender_environment
from ..character_rigging import run_skintokens_inference, skintokens_preflight
from .. import creature_rig, creature_views
from ..creature_rig import deformation_poses, rig_settings
from ..creature_views import creature_config, framing, motion_settings, outside_panels
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


def _rig_blend(root, asset):
    """The rig .blend B1 finished, and the stage output that produced it as it is now; every execution record is
    checked before one is selected."""
    rigging = asset.get("rigging") or {}
    if rigging.get("status") not in ("review_required", "approved") or "rig_blend" not in asset.get("artifacts", {}):
        raise ValueError(f"creature {asset['name']} has no rig: run `slopforge creature rig {asset['name']}` first")
    executions = asset.get("executions")
    if (not isinstance(executions, list) or not all(isinstance(item, dict) and isinstance(item.get("stages", []), list)
                                                     and all(isinstance(stage, dict) for stage in item.get("stages", []))
                                                     for item in executions)):
        raise ValueError(f"creature {asset['name']}'s execution records are malformed")
    path = asset["artifacts"]["rig_blend"]["path"]
    blend = root / path
    digest = file_sha256(blend) if blend.is_file() else None
    refs = [output for item in executions for stage in item.get("stages", [])
            if stage.get("name") == "rig_postprocess" and stage.get("status") == "succeeded"
            for output in stage.get("outputs") or [] if isinstance(output, dict) and output.get("path") == path
            and output.get("sha256") == digest]
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
    count = poses or settings["training_poses"]
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
    stage = start_stage(execution, "creature_calibration", 1, [blend_ref], {"creature": creature, "framing": request},
                        {"provider": provider, "output_rights": rights})
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
                        {"provider": provider, "output_rights": rights})
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
                        {"provider": provider, "output_rights": rights})
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
