"""Providers and the rights in their outputs (docs/ARCHITECTURE.md, Providers).

A provider is anything SlopForge is pointed at to make an asset: a ComfyUI service, a hosted API, a GPU host over SSH
or a local tool. Each carries an `output_rights` record saying whether what it makes may ship in a commercial game:
`cleared` (terms read, outputs free to use), `attribution_required` (cleared with a notice that must ship),
`restricted` (terms read, commercial use forbidden or conditioned) or `unknown` (not read). An artifact's rights are
the weakest across its lineage; delivery refuses `restricted` and `unknown`, experiments never do.
"""
import os
import re

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
# Terms of the providers SlopForge configures through tools.* keys, and of its own local tools (plan section 7).
BUILTIN_RIGHTS = {
    "skintokens": {"status": "cleared", "terms": "MIT (SkinTokens code and weights); Apache-2.0 (Qwen3-0.6B)",
                   "terms_version": "SkinTokens 273b691", "read_on": "2026-10-27"},
    "part_masks": {"status": "cleared", "terms": "MIT (Florence-2 large); Apache-2.0 (SAM 2.1 Hiera large)",
                   "terms_version": "model cards", "read_on": "2026-10-27"},
    "omnipart": {"status": "cleared", "terms": "MIT (OmniPart code and weights)",
                 "terms_version": "OmniPart ceb1a4ff, weights dfc4b4c7", "read_on": "2026-10-27"},
    "background_removal": {"status": "cleared", "terms": "MIT (BiRefNet general, through rembg)",
                           "terms_version": "BiRefNet LICENSE", "read_on": "2026-10-27"},
    "blender": {"status": "cleared", "terms": "GPL-2.0-or-later covers Blender, not what it makes",
                "terms_version": "blender.org licence FAQ", "read_on": "2026-10-27"},
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
    found = {"comfyui": {"type": "comfyui", "url": comfy_url(config), "configured_by": "COMFYUI_URL or tools.comfy_url"}}
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
