"""Licence gate for MakeHuman/MPFB assets (no Blender dependency, so it is unit-tested directly).

MakeHuman community packs mix licences inside one zip: packs named `_cc0` contain AGPL-3.0 items, and
many system assets carry no licence header at all. An asset's own `# license` header wins; without one,
the licence of the pack it was downloaded from must be declared explicitly. Only CC0 and CC-BY are
allowed (owner decision 2026-10-20); CC-BY assets are returned with their attribution.
"""
from pathlib import Path

ALLOWED = {"CC0", "CC-BY"}


def normalise(text):
    """Map the many spellings in MakeHuman headers (CC_by, CC  BY 3.0, CC-0, AGPL3 (...)) to one name."""
    if not text:
        return None
    key = text.lower().replace(" ", "").replace("_", "").replace("-", "")
    if "agpl" in key:
        return "AGPL-3.0"
    if key.startswith("cc0"):
        return "CC0"
    if key.startswith("ccby"):
        return "CC-BY"
    return text.strip()


def header(path):
    """Licence, author and homepage from the comment header of an .mhclo file."""
    found = {"license": None, "author": None, "homepage": None}
    for line in Path(path).read_text(errors="ignore").splitlines():
        if not line.startswith("#"):
            if line.startswith("verts"):
                break
            continue
        for key in found:
            prefix = f"# {key} "
            if line.startswith(prefix):
                found[key] = line[len(prefix):].strip()
    return found


def check(path, declared_pack_license=None, declared_author=None):
    """Return {"license", "author", "homepage", "asset"} or raise ValueError for a disallowed asset.

    CC-BY needs an author to credit: from the header, or declared (e.g. from the pack's download page).
    """
    info = header(path)
    info["author"] = info["author"] or declared_author
    license_name = normalise(info["license"]) or normalise(declared_pack_license)
    asset = Path(path).parent.name
    if license_name is None:
        raise ValueError(f"{asset}: no licence header and no declared pack licence")
    if license_name not in ALLOWED:
        raise ValueError(f"{asset}: licence {license_name} is not allowed (CC0 or CC-BY only)")
    if license_name == "CC-BY" and not info["author"]:
        raise ValueError(f"{asset}: CC-BY without an author to credit; declare one")
    return {"asset": asset, "license": license_name, "author": info["author"], "homepage": info["homepage"]}
