from ..manifest import asset_key, new_record
from ..taxonomy import validate_asset_name


def register_primitive(manifest, config, style, name, description):
    validate_asset_name(name)
    key = asset_key("primitive", name)
    existing = manifest.get("assets", {}).get(key)
    if existing is not None:
        existing.update(
            {
                "description": description,
                "style": style["name"],
                "style_version": style["version"],
                "route": "unity_native_geometry",
            }
        )
        return existing
    record = new_record(
        "primitive", name, description, style, {"strategy": "text_only"}
    )
    record.update(
        {
            "status": "planned",
            "route": "unity_native_geometry",
            "validation": {
                "status": "not_run",
                "warnings": [
                    "Create this with Unity-native/basic geometry; this command writes no Unity scene or prefab."
                ],
                "measured": {},
            },
        }
    )
    manifest["assets"][key] = record
    return record
