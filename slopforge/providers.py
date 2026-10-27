"""Providers and the rights in their outputs (docs/ARCHITECTURE.md, Providers).

A provider is anything SlopForge is pointed at to make an asset: a ComfyUI service, a hosted API, a GPU host over SSH
or a local tool. Each carries an `output_rights` record saying whether what it makes may ship in a commercial game:
`cleared` (terms read, outputs free to use), `attribution_required` (cleared with a notice that must ship),
`restricted` (terms read, commercial use forbidden or conditioned) or `unknown` (not read). An artifact's rights are
the weakest across its lineage; delivery refuses `restricted` and `unknown`, experiments never do.
"""
import re

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
