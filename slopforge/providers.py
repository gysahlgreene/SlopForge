"""Providers and the rights in their outputs (docs/ARCHITECTURE.md, Providers).

A provider is anything SlopForge is pointed at to make an asset: a ComfyUI service, a hosted API, a GPU host over SSH
or a local tool. Each carries an `output_rights` record saying whether what it makes may ship in a commercial game:
`cleared` (terms read, outputs free to use), `attribution_required` (cleared with a notice that must ship),
`restricted` (terms read, commercial use forbidden or conditioned) or `unknown` (not read). An artifact's rights are
the weakest across its lineage; delivery refuses `restricted` and `unknown`, experiments never do.
"""
import json
import os
import re
from pathlib import Path

from .failures import StageFailure

RIGHTS = ("restricted", "unknown", "attribution_required", "cleared")  # weakest first
SHIPPABLE = ("attribution_required", "cleared")
_REQUIRED = {"cleared": ("terms", "terms_version", "read_on"),
             "attribution_required": ("terms", "terms_version", "read_on", "notice"),
             "restricted": ("terms", "terms_version", "read_on", "reason"),
             "unknown": ("reason",)}
_FIELDS = {"status", "terms", "terms_version", "read_on", "notice", "reason"}


def validate_output_rights(record, where="output_rights"):
    """A checked copy of an output-rights record; ValueError naming the field otherwise."""
    if not isinstance(record, dict):
        raise ValueError(f"{where} must be a mapping")
    status = record.get("status")
    if status not in _REQUIRED:
        raise ValueError(f"{where}.status must be one of {', '.join(RIGHTS)}, not {status!r}")
    extra = sorted(set(record) - _FIELDS)
    if extra:
        raise ValueError(f"{where} has unknown fields: {', '.join(map(str, extra))}")
    for field in _FIELDS - {"status"}:
        if field in record and (not isinstance(record[field], str) or not record[field].strip()):
            raise ValueError(f"{where}.{field} must be non-empty text")
    for field in _REQUIRED[status]:
        if field not in record:
            raise ValueError(f"{where}.{field} is required when status is {status}")
    if "read_on" in record and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["read_on"]):
        raise ValueError(f"{where}.read_on must be a date, YYYY-MM-DD")
    return dict(record)


def combine_rights(entries):
    """The weakest status over `entries` ({source, **record}), with every notice to ship and every reason a
    status is not shippable. An invalid entry counts as unknown; it never raises."""
    status, notices, reasons, sources = "cleared", [], [], []
    for index, entry in enumerate(entries):
        named = isinstance(entry, dict) and isinstance(entry.get("source"), str) and entry["source"].strip()
        source = entry["source"] if named else f"entry {index + 1}"
        try:
            if not named:
                raise ValueError("no source names the provider or model")
            record = validate_output_rights({key: value for key, value in entry.items() if key != "source"}, source)
        except ValueError as exc:
            record = {"status": "unknown", "reason": f"invalid output rights ({exc})"}
        if RIGHTS.index(record["status"]) < RIGHTS.index(status):
            status = record["status"]
        if record.get("notice") and record["notice"] not in notices:
            notices.append(record["notice"])
        if record["status"] not in SHIPPABLE:
            reasons.append(f"{source}: {record['reason']}")
        sources.append({"source": source, "status": record["status"]})
    return {"status": status, "notices": notices, "reasons": reasons, "sources": sources}


PROVIDER_TYPES = ("comfyui", "hosted_api", "ssh_gpu", "local_tool")
_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
_CREDENTIAL_FIELDS = {"api_key", "key", "token", "secret", "password", "credentials"}
# Terms of the providers SlopForge configures through tools.* keys, and of its own local tools: read on 2026-10-27 from
# the publishers' licence files and cards (docs/COMFYUI.md, Output rights).
BUILTIN_RIGHTS = {
    "skintokens": {"status": "cleared", "terms": "MIT (SkinTokens code and weights; Qwen3-0.6B, Apache-2.0, is used "
                   "for its architecture only)", "terms_version": "SkinTokens LICENSE at 273b691; weights card",
                   "read_on": "2026-10-27"},
    "part_masks": {"status": "cleared", "terms": "MIT (Florence-2 large); Apache-2.0 (SAM 2.1 Hiera large)",
                   "terms_version": "microsoft/Florence-2-large LICENSE; facebook/sam2.1-hiera-large card",
                   "read_on": "2026-10-27"},
    # OmniPart is MIT, but the part synthesis SlopForge runs decodes meshes with NVIDIA FlexiCubes and writes GLBs with
    # nvdiffrast, both under the NVIDIA Source Code License: "only may be used or intended for use non-commercially".
    "omnipart": {"status": "restricted", "terms": "MIT (OmniPart); NVIDIA Source Code License, section 3.3 "
                 "(FlexiCubes, nvdiffrast)", "terms_version": "OmniPart ceb1a4ff: flexicubes/LICENSE.txt, nvdiffrast "
                 "LICENSE.txt", "read_on": "2026-10-27",
                 "reason": "its mesh decoder (FlexiCubes) and GLB export (nvdiffrast) are licensed for non-commercial "
                           "research or evaluation only"},
    "background_removal": {"status": "cleared", "terms": "MIT (BiRefNet general, through rembg)",
                           "terms_version": "ZhengPeng7/BiRefNet LICENSE; rembg's BiRefNet-general-epoch_244.onnx",
                           "read_on": "2026-10-27"},
    "blender": {"status": "cleared", "terms": "GPL-2.0-or-later covers Blender; what you make with it is yours",
                "terms_version": "blender.org/about/license", "read_on": "2026-10-27"},
}


def _legacy(tools, name, keys, rights):
    """A provider configured through tools.<prefix>_* keys before the map existed."""
    values = {key: tools.get(f"{name}_{key}") for key in keys}
    if not any(values.values()):
        return None
    return {"type": "ssh_gpu" if values.get("host") else "local_tool", "configured_by": f"tools.{name}_*",
            **{key: value for key, value in values.items() if value}, "output_rights": dict(rights)}


def load_providers(config):
    """Every provider the project is pointed at, by name: the `providers:` map, plus the tools.* keys read into it
    so existing projects keep working. A declared block overrides what the old keys say."""
    from .backends import video2rig
    from .paths import comfy_url
    pipeline = config.get("asset_pipeline", {})
    tools, declared = pipeline.get("tools") or {}, pipeline.get("providers")
    if declared is None:
        declared = {}
    if not isinstance(declared, dict):
        raise ValueError("asset_pipeline.providers must be a mapping of names to provider blocks")
    # ComfyUI's models carry their own terms in each workflow's requirements sidecar.
    found = {"comfyui": {"type": "comfyui", "url": comfy_url({"asset_pipeline": {"tools": tools}}),
                         "configured_by": "COMFYUI_URL or tools.comfy_url"}}
    for name, keys in (("skintokens", ("host", "python", "checkout", "checkpoint")),
                       ("omnipart", ("python", "checkout"))):
        entry = _legacy(tools, name, keys, BUILTIN_RIGHTS[name])
        if entry:
            found[name] = entry
    masks = _legacy(tools, "parts", ("host", "python", "models"), BUILTIN_RIGHTS["part_masks"])
    if masks:
        found["part_masks"] = masks
    if "omnipart" in found and tools.get("parts_host"):  # OmniPart runs on the part-mask host
        found["omnipart"].update(type="ssh_gpu", host=tools["parts_host"])
    settings = video2rig.settings(config)
    if any(settings.values()):
        found["video2rig"] = {"type": "local_tool", **{key: value for key, value in settings.items() if value},
                              "output_rights": dict(video2rig.OUTPUT_RIGHTS)}
    for name, block in declared.items():
        found[name] = _checked(name, block, found.get(name))
    return found


def _checked(name, block, builtin):
    where = f"providers.{name}"
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError(f"{where}: provider names are lower-case words")
    if not isinstance(block, dict):
        raise ValueError(f"{where} must be a mapping")
    kind = block.get("type")
    if kind not in PROVIDER_TYPES:
        raise ValueError(f"{where}.type must be one of {', '.join(PROVIDER_TYPES)}, not {kind!r}")
    credentials = sorted(_CREDENTIAL_FIELDS & set(block))
    if credentials:
        raise ValueError(f"{where}.{credentials[0]}: credentials never go in the project file; name the environment "
                         "variable that holds them with key_env")
    if kind == "hosted_api" and not (isinstance(block.get("key_env"), str) and _ENV_NAME.fullmatch(block["key_env"])):
        raise ValueError(f"{where}.key_env must name the environment variable holding the API key (e.g. "
                         "REPLICATE_API_TOKEN), never the key itself")
    if kind == "ssh_gpu" and not all(isinstance(block.get(key), str) and block[key].startswith("/")
                                     for key in ("python", "checkout")):
        raise ValueError(f"{where}.python and .checkout must be absolute paths on its host")
    entry = {**(builtin or {}), **block}
    if "output_rights" in block:
        entry["output_rights"] = validate_output_rights(block["output_rights"], f"{where}.output_rights")
    elif not builtin:
        entry["output_rights"] = {"status": "unknown", "reason": f"{where}.output_rights is not set"}
    return entry


def preflight(name, provider, config, project_root):
    """Whether a provider can run now: {status: ready | unavailable | unverified | not_checked, reasons, ...}."""
    if provider["type"] == "hosted_api":
        variable = provider["key_env"]
        if not os.environ.get(variable):
            return {"status": "unavailable", "category": "configuration",
                    "reasons": [f"Set the environment variable {variable} (providers.{name}.key_env)"]}
        return {"status": "ready", "reasons": [], "vendor": provider.get("vendor"),
                "models": provider.get("models", {})}
    if name == "video2rig":
        from .backends import video2rig
        machines = video2rig.preflight(config, project_root)
        worst = next((report for report in machines.values() if report["status"] != "ready"), None)
        return {**(worst or {"status": "ready", "reasons": []}), "machines": machines}
    if name == "skintokens":
        from .character_rigging import skintokens_preflight
        return skintokens_preflight(config, project_root)
    return {"status": "not_checked", "reasons": [f"no preflight for {provider['type']} provider {name} yet"]}


def require_ready(name, report):
    if report.get("status") != "ready":
        raise StageFailure(report.get("category", "configuration"),
                           f"provider {name} is not ready: " + "; ".join(report.get("reasons", [])),
                           operation=f"provider {name} preflight", remedy="Run slopforge doctor and fix what it reports")


def _unknown(reason):
    return {"status": "unknown", "notices": [], "reasons": [reason], "sources": []}


def merge_rights(*parts):
    """Combined rights of several lineages: the weakest status, every notice once, every reason."""
    status, notices, reasons, sources = "cleared", [], [], []
    for part in parts:
        if RIGHTS.index(part["status"]) < RIGHTS.index(status):
            status = part["status"]
        notices += [notice for notice in part["notices"] if notice not in notices]
        reasons += part["reasons"]
        sources += part["sources"]
    return {"status": status, "notices": notices, "reasons": reasons, "sources": sources}


def lineage_rights(asset, refs):
    """The rights in `refs` (artifact references of an asset's execution records), over their complete lineage:
    every producing stage's recorded output_rights, through every input. A stage that recorded none, a reference no
    stage produced, copies that disagree and malformed records are unknown with a reason; nothing raises."""
    executions = asset.get("executions") if isinstance(asset, dict) else None
    if not isinstance(executions, list):
        return _unknown("the asset's execution records are malformed")
    producers = {}  # every member is checked before any is selected (provenance skill)
    for execution in executions:
        stages = execution.get("stages") if isinstance(execution, dict) else None
        if not isinstance(stages, list) or not all(isinstance(item, dict) for item in stages):
            return _unknown(f"execution {execution.get('id') if isinstance(execution, dict) else '?'} is malformed")
        for item in stages:
            outputs = item.get("outputs")
            if not isinstance(outputs, list) or not all(isinstance(output, dict) and isinstance(output.get("id"), str)
                                                        for output in outputs):
                return _unknown(f"stage {item.get('name')} attempt {item.get('attempt')} has malformed outputs")
            for output in outputs:  # identity is the id with the content: concept candidates reuse ids
                producers.setdefault((output["id"], output.get("sha256")), []).append(item)
    if not isinstance(refs, list) or not refs:
        return _unknown("no lineage recorded for the delivered artifact")
    parts, queue, seen = [], list(refs), set()
    while queue:
        item = queue.pop()
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("sha256"), str):
            parts.append(_unknown("a lineage reference is malformed"))
            continue
        if (item["id"], item["sha256"]) in seen:
            continue
        seen.add((item["id"], item["sha256"]))
        found = producers.get((item["id"], item["sha256"]), [])
        parents = item.get("derived_from")
        if not found and isinstance(parents, list) and len(parents) == 1 and isinstance(parents[0], dict) and \
                parents[0].get("sha256") == item["sha256"] and isinstance(parents[0].get("artifact_id"), str):
            # a byte copy (approve's approved-concept:<execution>): the same content, so the same rights as its source
            queue.append({"id": parents[0]["artifact_id"], "sha256": parents[0]["sha256"]})
            continue
        if not found:
            parts.append(_unknown(f"no stage records producing {item['id']} with this content"))
            continue
        recorded = {json.dumps((producer.get("provenance") or {}).get("output_rights") if
                               isinstance(producer.get("provenance"), dict) else "malformed", sort_keys=True)
                    for producer in found}
        if len(recorded) != 1:  # adopted copies of one stage must agree
            parts.append(_unknown(f"the stages recording {item['id']} disagree about its rights"))
            continue
        producer = found[0]
        label = f"{producer.get('name')} attempt {producer.get('attempt')}"
        entries = (producer.get("provenance") or {}).get("output_rights") if isinstance(
            producer.get("provenance"), dict) else "malformed"
        if producer.get("status") != "succeeded":
            parts.append(_unknown(f"{label} did not succeed"))
        elif entries is None:
            parts.append(_unknown(f"{label} recorded no output rights (made before they were recorded: regenerate it)"))
        elif not isinstance(entries, list):
            parts.append(_unknown(f"{label} has malformed output rights"))
        else:
            parts.append(combine_rights(entries))
        if "delivered_rights" in (producer.get("provenance") or {}):
            # final_publication: what it published carries what delivery decided, the delivered mesh's rights included
            parts.append(_combined(producer["provenance"]["delivered_rights"]) or
                         _unknown(f"{label} has malformed delivered rights"))
        inputs = producer.get("inputs")
        if isinstance(inputs, list):
            queue.extend(inputs)
        else:
            parts.append(_unknown(f"{label} has malformed inputs"))
    return merge_rights(*parts)


def _combined(record):
    """A checked copy of a combined rights record (what delivery decided), or None."""
    if (not isinstance(record, dict) or record.get("status") not in RIGHTS or
            not all(isinstance(record.get(key), list) for key in ("notices", "reasons", "sources")) or
            not all(isinstance(item, str) for item in record["notices"] + record["reasons"])):
        return None
    return {key: list(record[key]) if isinstance(record[key], list) else record[key]
            for key in ("status", "notices", "reasons", "sources")}


def published_rights(asset):
    """The rights recorded on an asset when it was delivered (a combined record), or unknown."""
    record = asset.get("output_rights") if isinstance(asset, dict) else None
    name = asset.get("name", "an asset") if isinstance(asset, dict) else "an asset"
    if record is None:
        return _unknown(f"{name} was delivered before output rights were recorded: deliver it again")
    return _combined(record) or _unknown(f"{name}'s recorded output rights are malformed")


def artifact_rights(manifest, selector, artifact_id):
    """The rights in a registered artifact (characters, rigs, animations): its own recorded output_rights and those
    of everything it derives from; an asset's delivered output reads the asset's delivery record."""
    from .manifest import find_asset
    assets = manifest.get("assets") if isinstance(manifest, dict) else None
    if not isinstance(assets, dict) or not all(isinstance(item, dict) for item in assets.values()):
        return _unknown("the manifest's assets are malformed")
    by_id = {}
    for item in assets.values():
        by_id.setdefault(item.get("id"), []).append(item)
    try:
        start = find_asset(manifest, selector)
    except (KeyError, ValueError) as exc:
        return _unknown(f"asset {selector}: {exc}")
    seen = set()

    def walk(asset, name):
        if (id(asset), name) in seen:
            return merge_rights()
        seen.add((id(asset), name))
        artifact = (asset.get("artifacts") or {}).get(name)
        if not isinstance(artifact, dict):
            return _unknown(f"{asset.get('name')} has no artifact {name}")
        entries = (artifact.get("provenance") or {}).get("output_rights")
        # A file the asset delivered (approve-texture's published_artifacts) carries the delivery record, the rights
        # over its whole lineage. (`outputs` is no test: it maps every registered artifact's path.)
        delivered = artifact.get("path") in {item.get("path") for item in asset.get("published_artifacts") or []
                                             if isinstance(item, dict)}
        parts = [combine_rights(entries)] if isinstance(entries, list) else [] if delivered else [
            _unknown(f"{asset.get('name')} {name} recorded no output rights")]
        if delivered:
            parts.append(published_rights(asset))
        for source in artifact.get("derived_from") or []:
            parents = by_id.get(source.get("asset_id")) if isinstance(source, dict) else None
            if not parents or len(parents) != 1:
                parts.append(_unknown(f"source asset {source.get('asset_id') if isinstance(source, dict) else '?'} "
                                      "is missing or ambiguous"))
            elif source.get("output_id") in (parents[0].get("artifacts") or {}):
                parts.append(walk(parents[0], source["output_id"]))
            else:
                parts.append(published_rights(parents[0]))
        return merge_rights(*parts)
    return walk(start, artifact_id)


def require_shippable(rights, what, operation):
    """Delivery's gate: `attribution_required` and `cleared` pass; `unknown` and `restricted` stop it."""
    if rights["status"] in SHIPPABLE:
        return rights
    raise StageFailure("configuration", f"{what} cannot be delivered by {operation}: the rights in its outputs are "
                       f"{rights['status']} ({'; '.join(rights['reasons']) or 'no reason recorded'})",
                       operation=operation,
                       remedy="Read the terms of each source named and record them (providers.<name>.output_rights, "
                              "or the model's output_rights in its workflow's requirements sidecar), or regenerate "
                              "on providers whose outputs are cleared; generating and reviewing still work")


def rights_of(config, name):
    """[{source, **record}] for a stage that used provider `name` (or one of SlopForge's own local tools): the
    project's providers map first, so a user's own reading of the terms wins, else the terms read for SlopForge."""
    try:
        entry = load_providers(config).get(name) or {}
    except ValueError as exc:
        return [{"source": name, "status": "unknown", "reason": f"the providers configuration is invalid ({exc})"}]
    record = entry.get("output_rights") or BUILTIN_RIGHTS.get(name)
    if not record:
        return [{"source": name, "status": "unknown", "reason": f"provider {name} states no output rights"}]
    return [{"source": name, **record}]


NOTICES_FILE = "SlopForge-NOTICES.txt"


def write_notices(directory, what, rights, filename=NOTICES_FILE):
    """The notices a delivered asset owes, in a file beside it so they ship with it; a stale one is removed."""
    path = Path(directory) / filename
    if not rights["notices"]:
        path.unlink(missing_ok=True)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{what}: notices owed under the terms of the models and tools that made it (recorded by "
                    "SlopForge). Ship them with it.\n\n" + "\n".join(rights["notices"]) + "\n")
    return path
