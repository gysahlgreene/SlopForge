import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .config import load_project
from .manifest import asset_key, find_asset, load_manifest, new_record, save_manifest
from .paths import discover_project_root, resolve_project_root
from .pipelines import image, model
from .pipelines.primitive import register_primitive
from .style import build_prompt, load_style
from .taxonomy import canonical_type, load_taxonomy


COMMANDS = {"init", "generate", "candidates", "approve", "inspect", "doctor", "styles", "assets", "prompt"}


def parser():
    root = argparse.ArgumentParser(prog="slopforge", description="Generate and approve local AI game-asset slop.")
    root.add_argument("--version", action="version", version=f"slopforge {__version__}")
    root.add_argument("--project", help="Target Unity project; otherwise discovered from the current directory")
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize SlopForge configuration in a Unity project")
    init.add_argument("target", type=Path)
    init.add_argument("--force", action="store_true", help="Replace managed configuration files; preserve existing asset manifest")

    generate = sub.add_parser("generate", help="Generate candidates for an asset")
    generate.add_argument("asset_type")
    generate.add_argument("name")
    generate.add_argument("description")
    generate.add_argument("--count", type=int)
    generate.add_argument("--auto-approve", action="store_true")
    generate.add_argument("--force", action="store_true")
    generate.add_argument("--dry-run", action="store_true", help="Print the style-injected prompt without inference")

    candidates = sub.add_parser("candidates", help="List candidates for an asset")
    candidates.add_argument("name")
    approve = sub.add_parser("approve", help="Approve a candidate and continue the pipeline")
    approve.add_argument("name")
    approve.add_argument("candidate", type=int)
    approve.add_argument("--force", action="store_true")
    inspect = sub.add_parser("inspect", help="Show manifest and validation details for an asset")
    inspect.add_argument("name")
    sub.add_parser("doctor", help="Diagnose local dependencies and the selected project")
    sub.add_parser("styles", help="List project style packs")
    sub.add_parser("assets", help="List tracked project assets")
    prompt = sub.add_parser("prompt", help="Print a style-injected prompt without inference")
    prompt.add_argument("asset_type")
    prompt.add_argument("description")
    return root


def parse_args(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] in (["-h"], ["--help"], ["--version"]) or argv[:1] in (["init"], ["generate"], ["candidates"], ["approve"], ["inspect"], ["doctor"], ["styles"], ["assets"], ["prompt"]):
        return parser().parse_args(argv)
    if argv[:1] == ["--project"] and len(argv) > 2 and argv[2] in COMMANDS:
        return parser().parse_args(argv)
    legacy = argparse.ArgumentParser(prog="slopforge", description="Automatic candidate generation.")
    legacy.add_argument("asset_type")
    legacy.add_argument("name")
    legacy.add_argument("description")
    legacy.add_argument("--project")
    legacy.add_argument("--force", action="store_true")
    args = legacy.parse_args(argv)
    args.command, args.count, args.auto_approve, args.dry_run = "generate", None, True, False
    return args


def _project(args):
    selected = args.project or os.environ.get("SLOPFORGE_PROJECT_ROOT")
    return resolve_project_root(selected) if selected else discover_project_root()


def _active_style(style):
    return {"key": style["_key"], "name": style["name"], "version": style["version"]}


def _asset_key(manifest, asset_type, name):
    key = asset_key(asset_type, name)
    if key in manifest["assets"]:
        return key
    for old_key, item in manifest["assets"].items():
        old_type = "prop" if item.get("type") == "model" else item.get("type")
        if item.get("name", old_key) == name and old_type == asset_type:
            return old_key
    return key


def _list_candidates(manifest, name):
    record = find_asset(manifest, name)
    print(f"{record['name']} ({record['type']}) — {record['status']}")
    for item in record.get("candidates", {}).get("items", []):
        marker = " [selected]" if record["candidates"].get("selected") == item["number"] else ""
        print(f"{item['number']}: {item['path']} — {item['status']}{marker}")


def _run(args):
    if args.command == "init":
        from .initializer import init_project
        print(f"Initialized: {init_project(args.target, args.force)}")
        return 0
    if args.command == "doctor":
        from .doctor import run_doctor
        project = None
        if args.project:
            project = Path(args.project).expanduser().resolve()
        else:
            try:
                project = discover_project_root()
            except FileNotFoundError:
                pass
        return run_doctor(project)

    root = _project(args)
    config = load_project(root)
    types = load_taxonomy(root)
    style = load_style(root, config)
    pipeline = config["asset_pipeline"]
    manifest_path = root / pipeline["manifest"]
    manifest = load_manifest(manifest_path)

    if args.command == "prompt":
        asset_type = canonical_type(args.asset_type, types)
        print(build_prompt(style, types[asset_type], args.description,
                           types[asset_type].get("prompt_mode", "asset")))
        return 0
    if args.command == "styles":
        directory = root / "ai/styles"
        for path in sorted(directory.glob("*/style.yaml")):
            active = " *" if path.parent.name == pipeline["active_style"] else ""
            print(f"{path.parent.name}{active}")
        return 0
    if args.command == "assets":
        for record in manifest["assets"].values():
            print(f"{record.get('type')}\t{record.get('name')}\t{record.get('status')}")
        return 0
    if args.command == "inspect":
        print(json.dumps(find_asset(manifest, args.name), indent=2))
        return 0
    if args.command == "candidates":
        _list_candidates(manifest, args.name)
        return 0

    manifest["active_style"] = _active_style(style)
    if args.command == "approve":
        record = find_asset(manifest, args.name)
        asset_type = "prop" if record.get("type") == "model" else record["type"]
        recipe = types[canonical_type(asset_type, types)]
        key = next(key for key, item in manifest["assets"].items() if item is record)
        if recipe["pipeline"] == "image":
            result = image.approve(root, config, recipe, manifest, key, args.candidate, args.force)
            print(json.dumps(result, indent=2))
        elif recipe["pipeline"] == "model":
            model.approve(root, config, recipe, style, manifest, key, args.candidate, args.force)
        else:
            raise ValueError("Unity-native geometry does not have generated candidates")
        save_manifest(manifest_path, manifest)
        return 0

    asset_type = canonical_type(args.asset_type, types)
    recipe = types[asset_type]
    if recipe["pipeline"] == "native":
        record = register_primitive(manifest, config, style, args.name, args.description)
        save_manifest(manifest_path, manifest)
        print(f"Registered {record['name']} for Unity-native geometry; no AI inference was run.")
        return 0
    if args.count is not None and args.count < 1:
        raise ValueError("--count must be at least 1")
    prompt_text = build_prompt(style, recipe, args.description, recipe.get("prompt_mode", "asset"))
    if args.dry_run:
        print(prompt_text)
        return 0

    count_key = "image_candidates" if recipe["pipeline"] == "image" else "model_candidates"
    count = args.count or pipeline["defaults"][count_key]
    key = _asset_key(manifest, asset_type, args.name)
    if key in manifest["assets"]:
        record = manifest["assets"][key]
        if record.get("status") == "ready" and not (args.force or pipeline.get("overwrite_existing")):
            raise FileExistsError(f"Asset is already ready; pass --force to regenerate: {args.name}")
        record.update({"description": args.description, "style": style["name"],
                       "style_version": style["version"], "status": "generating"})
    else:
        record = new_record(asset_type, args.name, args.description, style, pipeline["conditioning"])
        record["status"] = "generating"
        manifest["assets"][key] = record
    save_manifest(manifest_path, manifest)

    try:
        generated = (image.generate(root, config, recipe, style, args.name, args.description,
                                    count, manifest, key) if recipe["pipeline"] == "image" else
                     model.generate(root, config, recipe, style, args.name, args.description,
                                    count, manifest, key))
        save_manifest(manifest_path, manifest)
    except Exception as exc:
        record["status"] = "failed"
        record.setdefault("validation", {"status": "not_run", "warnings": [], "measured": {}})
        record["validation"].setdefault("warnings", []).append(str(exc))
        save_manifest(manifest_path, manifest)
        raise
    if not args.auto_approve:
        print(f"Generated {len(generated)} candidate(s). Review with: slopforge --project {root} candidates {args.name}")
        return 0
    selected = next((candidate for candidate in generated if candidate.get("status") == "candidate"), None)
    if selected is None:
        raise RuntimeError(f"No valid candidate exists for {args.name}")
    if recipe["pipeline"] == "image":
        result = image.approve(root, config, recipe, manifest, key, selected["number"], args.force)
        print(json.dumps(result, indent=2))
    else:
        model.approve(root, config, recipe, style, manifest, key, selected["number"], args.force)
    save_manifest(manifest_path, manifest)
    return 0


def main(argv=None):
    args = parse_args(argv)
    try:
        return _run(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
