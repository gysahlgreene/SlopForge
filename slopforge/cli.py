import argparse
import json
import math
import os
import sys
import textwrap
from pathlib import Path

from . import __version__
from .config import load_project, select_quality_tier
from .backends.comfyui import ComfyUIClient
from .manifest import asset_key, find_asset, load_manifest, new_record, register_artifact, save_manifest
from .paths import comfy_url, discover_project_root, resolve_project_root
from .pipelines import image, model
from .pipelines.primitive import register_primitive
from . import recipes, prototypes
from .exploration import parse_variations, promote_candidate
from .spritepack import package_sprite_sheet
from .ui import make_sprite_import_metadata
from .unity_ui import apply_sprite_settings
from .unity_vfx import create_particle_prefab
from .environment import validate_environment_kit
from .character_rigging import rigify_character
from .tileset import package_tileset
from .unity_tiles import create_tile_assets
from .style import build_prompt, load_style
from .taxonomy import canonical_type, load_taxonomy, output_path, validate_asset_name


COMMANDS = {"init", "make", "generate", "explore", "promote", "spritepack", "tilepack", "tile-unity", "ui-meta", "candidates", "approve", "reject", "review", "retexture", "approve-texture", "inspect", "doctor", "styles", "assets", "prompt", "recipe", "library", "animation", "character", "prototype", "environment-check"}


def parser():
    root = argparse.ArgumentParser(prog="slopforge", description="Generate and approve local AI game-asset slop.")
    root.add_argument("--version", action="version", version=f"slopforge {__version__}")
    root.add_argument("--project", help="Target Unity project; otherwise discovered from the current directory")
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize SlopForge configuration in a Unity project")
    init.add_argument("target", type=Path)
    init.add_argument("--force", action="store_true", help="Replace managed configuration files; preserve existing asset manifest")

    sub.add_parser("make", help="Guided asset creation from description to Unity",
                   description="Walk through style, asset type, generation, visual review, and Unity approval.")

    generate = sub.add_parser("generate", help="Generate candidates for an asset")
    generate.add_argument("asset_type")
    generate.add_argument("name")
    generate.add_argument("description")
    generate.add_argument("--image-prompt", help="Send this agent-authored prompt unchanged to the image workflow")
    generate.add_argument("--count", type=int)
    generate.add_argument("--auto-approve", action="store_true")
    generate.add_argument("--force", action="store_true")
    generate.add_argument("--dry-run", action="store_true", help="Print the style-injected prompt without inference")
    generate.add_argument("--quality-tier", help="Use a configured quality tier: draft, normal, or final")
    generate.add_argument("--reference", action="append", dest="reference_paths", help="Approved style reference image (repeatable)")
    generate.add_argument("--reference-category", action="append", dest="reference_categories",
                          help="Select approved references from a category folder (repeatable)")
    generate.add_argument("--reference-library", help="Use ordered references from a project library such as character/alice")

    explore = sub.add_parser("explore", help="Generate deliberate, disposable concept variations")
    explore.add_argument("asset_type")
    explore.add_argument("name", help="Unique exploration name, such as relay_ideas")
    explore.add_argument("description")
    explore.add_argument("--variation", action="append", required=True,
                         help="Design variation as dimension=value; repeat dimensions across candidates")
    explore.add_argument("--quality-tier", help="Quality tier (defaults to draft)")
    explore.add_argument("--reference", action="append", dest="reference_paths")
    explore.add_argument("--reference-category", action="append", dest="reference_categories")
    explore.add_argument("--reference-library")

    promote = sub.add_parser("promote", help="Move an exploration candidate into a tracked production asset")
    promote.add_argument("exploration")
    promote.add_argument("candidate", type=int)
    promote.add_argument("--name", required=True, help="Name for the new tracked asset")

    spritepack = sub.add_parser("spritepack", help="Slice an approved character or VFX sheet into deterministic frames")
    spritepack.add_argument("name", help="Approved sprite_sheet or vfx_sheet asset name")
    spritepack.add_argument("--animation", required=True, help="Animation name such as idle or walk")
    spritepack.add_argument("--grid", nargs=2, type=int, metavar=("COLUMNS", "ROWS"), required=True)
    spritepack.add_argument("--fps", type=float, required=True)
    spritepack.add_argument("--pivot", nargs=2, type=float, metavar=("X", "Y"), default=(0.5, 0.0))
    spritepack.add_argument("--loop", action=argparse.BooleanOptionalAction, default=None)
    spritepack.add_argument("--particle-prefab", action="store_true",
                            help="Create a Unity texture-sheet ParticleSystem prefab (vfx_sheet only)")

    tilepack = sub.add_parser("tilepack", help="Slice and validate an approved terrain tile sheet")
    tilepack.add_argument("name", help="Approved tile_sheet asset name")
    tilepack.add_argument("--grid", nargs=2, type=int, metavar=("COLUMNS", "ROWS"), required=True)
    tilepack.add_argument("--tile-size", nargs=2, type=int, metavar=("WIDTH", "HEIGHT"), required=True)
    tilepack.add_argument("--margin", type=int, default=0)
    tilepack.add_argument("--padding", type=int, default=0)
    tilepack.add_argument("--layout", choices=("orthogonal", "isometric"), default="orthogonal")
    tilepack.add_argument("--collider", choices=("none", "grid", "sprite"), default="none")
    tilepack.add_argument("--pixels-per-unit", type=float, default=100)
    tilepack.add_argument("--transition-mask", type=int, action="append",
                          help="N/E/S/W edge mask (0-15), repeat once per tile")
    tilepack.add_argument("--unity-assets", action="store_true",
                          help="Create native Unity Tile assets through the installed Editor")
    tile_unity = sub.add_parser("tile-unity", help="Create Unity Tile assets for an already packaged tileset")
    tile_unity.add_argument("name", help="Packaged tile_sheet asset name")

    ui_meta = sub.add_parser("ui-meta", help="Write Unity Sprite and 9-slice import settings for an approved UI asset")
    ui_meta.add_argument("name", help="Approved ui asset name")
    ui_meta.add_argument("--border", nargs=4, type=int, metavar=("LEFT", "BOTTOM", "RIGHT", "TOP"),
                         default=(0, 0, 0, 0))
    ui_meta.add_argument("--pivot", nargs=2, type=float, metavar=("X", "Y"), default=(0.5, 0.5))
    ui_meta.add_argument("--pixels-per-unit", type=float, default=100)
    ui_meta.add_argument("--apply", action="store_true", help="Apply settings through the installed Unity Editor")
    ui_meta.add_argument("--prefab", action="store_true", help="Create a simple UGUI Image prefab (requires --apply)")

    candidates = sub.add_parser("candidates", help="List candidates for an asset")
    candidates.add_argument("name")
    approve = sub.add_parser("approve", help="Approve a candidate and continue the pipeline")
    approve.add_argument("name")
    approve.add_argument("candidate", type=int)
    approve.add_argument("--material-prompt", help="Use this agent-authored surface-material prompt for 3D assets")
    approve.add_argument("--material-count", type=int, help="Number of material candidates to bake onto the saved mesh")
    approve.add_argument("--force", action="store_true")
    approve.add_argument("--quality-tier", help="Override the selected candidate's tier for 3D processing")
    reject = sub.add_parser("reject", help="Reject an unapproved candidate and record the reason")
    reject.add_argument("name")
    reject.add_argument("candidate", type=int)
    reject.add_argument("--reason")
    review = sub.add_parser("review", help="Generate a local HTML review board for candidates and packs")
    review.add_argument("--output", default="slopforge-review.html", help="Project-relative HTML output path")
    retexture = sub.add_parser("retexture", help="Generate more material candidates for an approved model")
    retexture.add_argument("name")
    retexture.add_argument("--material-prompt", help="Send this agent-authored material prompt unchanged")
    retexture.add_argument("--count", type=int)
    retexture.add_argument("--quality-tier", help="Use a configured tier for material generation")
    approve_texture = sub.add_parser("approve-texture", help="Approve a material candidate for a model")
    approve_texture.add_argument("name")
    approve_texture.add_argument("candidate", type=int)
    approve_texture.add_argument("--force", action="store_true")
    inspect = sub.add_parser("inspect", help="Show manifest and validation details for an asset")
    inspect.add_argument("name")
    sub.add_parser("doctor", help="Diagnose local dependencies and the selected project")
    sub.add_parser("styles", help="List project style packs")
    sub.add_parser("assets", help="List tracked project assets")
    library = sub.add_parser("library", help="Inspect reusable project reference libraries")
    library_commands = library.add_subparsers(dest="library_action", required=True)
    library_commands.add_parser("list", help="List reference libraries")
    show_library = library_commands.add_parser("show", help="Show resolved library membership and file status")
    show_library.add_argument("selector", help="Library kind/name, such as character/alice")
    animation = sub.add_parser("animation", help="Validate reusable character animation libraries")
    animation_commands = animation.add_subparsers(dest="animation_action", required=True)
    check_animation_library = animation_commands.add_parser("validate", help="Validate clip files and retarget metadata")
    check_animation_library.add_argument("name", help="Library name under ai/animation_libraries/")
    retarget_animation_clip = animation_commands.add_parser("retarget", help="Retarget one library clip to an approved rig")
    retarget_animation_clip.add_argument("name", help="Animation library name")
    retarget_animation_clip.add_argument("clip", help="Clip id in the animation library")
    retarget_animation_clip.add_argument("--character", required=True, help="Tracked character with an approved rig")
    unity_animation_setup = animation_commands.add_parser("unity-setup", help="Create a Unity controller and character prefab")
    unity_animation_setup.add_argument("character", help="Tracked character name")
    unity_animation_setup.add_argument("--rig-type", choices=("generic", "humanoid"), default="generic")
    character = sub.add_parser("character", help="Prepare reviewable 3D character rigs")
    character_commands = character.add_subparsers(dest="character_action", required=True)
    rig_character = character_commands.add_parser("rig", help="Rig an approved character model with Blender Rigify")
    rig_character.add_argument("name", help="Tracked character asset name")
    rig_character.add_argument("--source-output", default="model", help="Approved model artifact id (default: model)")
    prototype = sub.add_parser("prototype", help="Plan and run approval-gated content recipes")
    prototype_commands = prototype.add_subparsers(dest="prototype_action", required=True)
    propose_prototype = prototype_commands.add_parser("propose", help="Write an editable, unapproved content plan")
    propose_prototype.add_argument("name")
    propose_prototype.add_argument("description")
    propose_prototype.add_argument("--recipe", action="append", dest="recipe_names",
                                   help="Recipe to include (repeatable; defaults to all project recipes)")
    propose_prototype.add_argument("--quality-tier", choices=("draft", "normal", "final"), default="draft")
    propose_prototype.add_argument("--candidate-budget", type=int, default=100)
    approve_prototype = prototype_commands.add_parser("approve", help="Approve the current on-disk plan")
    approve_prototype.add_argument("name")
    for action, help_text in (("run", "Run approved stages until a review gate"),
                              ("resume", "Resume after approving recipe outputs")):
        command = prototype_commands.add_parser(action, help=help_text)
        command.add_argument("name")
    regenerate_prototype = prototype_commands.add_parser("regenerate", help="Regenerate one recipe child")
    regenerate_prototype.add_argument("name")
    regenerate_prototype.add_argument("stage")
    regenerate_prototype.add_argument("child_id")
    prompt = sub.add_parser("prompt", help="Print a style-injected prompt without inference")
    prompt.add_argument("asset_type")
    prompt.add_argument("description")

    environment_check = sub.add_parser("environment-check", help="Validate approved environment kit modules against their grid constraints")
    environment_check.add_argument("name", help="Completed environment recipe instance")

    recipe = sub.add_parser("recipe", help="Run or resume a project asset recipe")
    recipe_commands = recipe.add_subparsers(dest="recipe_action", required=True)
    recipe_commands.add_parser("list", help="List recipe definitions and tracked runs")
    run_recipe = recipe_commands.add_parser("run", help="Create a recipe run and generate its children")
    run_recipe.add_argument("recipe_name")
    run_recipe.add_argument("--name", help="Unique name for this pack instance")
    run_recipe.add_argument("--quality-tier", help="Override the recipe's configured quality tier")
    run_recipe.add_argument("--reference-library", help="Use this approved reference library for every recipe child")
    resume_recipe = recipe_commands.add_parser("resume", help="Continue incomplete recipe stages")
    resume_recipe.add_argument("name", help="Recipe instance name")
    regenerate = recipe_commands.add_parser("regenerate", help="Generate new candidates for one recipe child")
    regenerate.add_argument("name", help="Recipe instance name")
    regenerate.add_argument("child_id", help="Child id from the recipe definition")
    return root


def parse_args(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] in (["-h"], ["--help"], ["--version"]) or argv[:1] in (["init"], ["make"], ["generate"], ["explore"], ["promote"], ["spritepack"], ["tilepack"], ["tile-unity"], ["ui-meta"], ["candidates"], ["approve"], ["reject"], ["review"], ["retexture"], ["approve-texture"], ["inspect"], ["doctor"], ["styles"], ["assets"], ["prompt"], ["recipe"], ["library"], ["animation"], ["character"], ["prototype"], ["environment-check"]):
        return parser().parse_args(argv)
    if argv[:1] == ["--project"] and len(argv) > 2 and argv[2] in COMMANDS:
        return parser().parse_args(argv)
    legacy = argparse.ArgumentParser(prog="slopforge", description="Automatic candidate generation.")
    legacy.add_argument("asset_type")
    legacy.add_argument("name")
    legacy.add_argument("description")
    legacy.add_argument("--project")
    legacy.add_argument("--force", action="store_true")
    legacy.add_argument("--image-prompt")
    args = legacy.parse_args(argv)
    args.command, args.count, args.auto_approve, args.dry_run = "generate", None, True, False
    return args


def _project(args):
    selected = args.project or os.environ.get("SLOPFORGE_PROJECT_ROOT")
    return resolve_project_root(selected) if selected else discover_project_root()


def _active_style(style):
    return {"key": style["_key"], "name": style["name"], "version": style["version"]}


def _create_unity_tiles(root, manifest_path, manifest, asset, settings):
    tile_artifacts = [(artifact_id, artifact) for artifact_id, artifact in asset.get("artifacts", {}).items()
                      if artifact_id.startswith("tiles.") and artifact_id[6:].isdigit()]
    tile_artifacts.sort(key=lambda item: item[0])
    if not tile_artifacts:
        raise ValueError("No packaged tile images were found; run tilepack first")
    assets_exist = [artifact_id.replace("tiles.", "tiles.unity_", 1) in asset.get("artifacts", {})
                    for artifact_id, _ in tile_artifacts]
    if all(assets_exist):
        paths = [root / asset["artifacts"][artifact_id.replace("tiles.", "tiles.unity_", 1)]["path"]
                 for artifact_id, _ in tile_artifacts]
        if all(path.is_file() for path in paths):
            return paths
        raise FileNotFoundError("Unity Tile artifact is registered but its file is missing")
    if any(assets_exist):
        raise FileExistsError("Tileset has a partial Unity Tile import; inspect UnityTiles before retrying")
    tile_paths = [(root / artifact["path"]).resolve() for _, artifact in tile_artifacts]
    if any(not path.is_relative_to(root) or not path.is_file() for path in tile_paths):
        raise ValueError("Packaged tile path is missing or outside the project")
    source = asset.get("outputs", {}).get("image")
    if not source:
        raise ValueError("Approved tile sheet source is missing")
    source_path = (root / source).resolve()
    if not source_path.is_relative_to(root) or not source_path.is_file():
        raise ValueError("Approved tile sheet is missing or outside the project")
    tileset_path = asset.get("tileset", {}).get("directory")
    if not isinstance(tileset_path, str) or not tileset_path:
        raise ValueError("Packaged tileset directory is not recorded")
    tileset_dir = (root / tileset_path).resolve()
    if not tileset_dir.is_relative_to(root) or not tileset_dir.is_dir():
        raise ValueError("Packaged tileset directory is missing or outside the project")
    unity_directory = tileset_dir.parent / "UnityTiles"
    settings = settings or asset.get("tileset", {})
    unity_paths = create_tile_assets(root, tile_paths, unity_directory, collider=settings.get("collider", "none"),
                                     pixels_per_unit=settings.get("pixels_per_unit", 100))
    for index, path in enumerate(unity_paths):
        register_artifact(manifest, asset["id"], f"tiles.unity_{index:03d}", "unity.tile",
                          path.relative_to(root).as_posix(),
                          derived_from=[{"asset_id": asset["id"], "output_id": "image"}],
                          provenance={"processor": "slopforge.unity_tiles", **settings, "index": index},
                          approval_status="approved")
    save_manifest(manifest_path, manifest)
    return unity_paths


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
    for item in record.get("material_candidates", {}).get("items", []):
        marker = " [selected]" if record["material_candidates"].get("selected") == item["number"] else ""
        preview = item.get("outputs", {}).get("preview_front", item.get("path", ""))
        print(f"material {item['number']}: {preview} — {item['status']}{marker}")


def _make_style_options(root, config):
    options = []
    for path in sorted((root / "ai/styles").glob("*/style.yaml")):
        selected = dict(config)
        selected["asset_pipeline"] = {**config["asset_pipeline"], "active_style": path.parent.name}
        options.append((path.parent.name, load_style(root, selected)))
    return options


def _open_candidates(root, candidates):
    from PIL import Image

    for item in candidates:
        path = Path(item["path"])
        path = path if path.is_absolute() else root / path
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        try:
            with Image.open(path) as preview:
                preview.show(title=f"SlopForge candidate {item['number']}")
        except Exception:
            print(f"Couldn't open candidate {item['number']}: {path}")


def _open_material_candidates(root, candidates):
    from PIL import Image

    for item in candidates:
        for view in ("preview_front", "preview_side", "preview_rear"):
            relative = item.get("outputs", {}).get(view)
            if not relative:
                continue
            path = root / relative
            try:
                with Image.open(path) as preview:
                    preview.show(title=f"Material {item['number']} {view.removeprefix('preview_')}")
            except Exception:
                print(f"Couldn't open material preview: {path}")


def _make_project(args):
    selected = args.project or os.environ.get("SLOPFORGE_PROJECT_ROOT")
    if selected:
        root = Path(selected).expanduser().resolve()
    else:
        try:
            root = discover_project_root()
        except FileNotFoundError:
            current = Path.cwd()
            root = current if (current / "Assets").is_dir() else Path(input("Unity project path (folder with Assets/, e.g. ~/UnityProjects/MyGame; Ctrl-C cancels): ")).expanduser().resolve()
    if not (root / "Assets").is_dir():
        raise ValueError(f"That folder doesn't look like a Unity project (missing Assets/): {root}")
    if not (root / "ai/project.yaml").is_file():
        from .initializer import init_project
        init_project(root)
        print(f"Set up SlopForge in {root.name}.")
    return root


def _check_comfy(config, root):
    url = comfy_url(config)
    try:
        ComfyUIClient(url, timeout=3).health()
    except Exception as exc:
        raise RuntimeError(f"ComfyUI isn't responding at {url}. Start it, then check with `slopforge --project {root} doctor`.") from exc


def _make_operation(command, root, style_key, **values):
    return argparse.Namespace(command=command, project=str(root), _style_key=style_key, _guided=True, **values)


def _run_make(args):
    root = _make_project(args)
    config = load_project(root)
    types = load_taxonomy(root)
    style_options = _make_style_options(root, config)
    if not style_options:
        raise ValueError("No style packs found. Run `slopforge init` for this Unity project first.")

    active_key = config["asset_pipeline"]["active_style"]
    active_index = next((i for i, (key, _) in enumerate(style_options) if key == active_key), None)
    if active_index is None:
        raise ValueError(f"Active style '{active_key}' is missing. Check ai/project.yaml and ai/styles/.")
    if len(style_options) == 1:
        style_key, style = style_options[0]
        print(f"\nUsing your only art style: {style['name']}.")
    else:
        current_style = style_options[active_index][1]
        print(f"\nStep 1 of 4: choose an art style. Press Enter to keep {current_style['name']}.")
        for key, option in style_options:
            marker = " (current)" if key == active_key else ""
            identity = option["identity"]
            description = "; ".join(value for value in (identity.get("genre"), identity.get("rendering")) if value)
            print(f"  • {option['name']}{marker}")
            if description:
                print(textwrap.fill(description, width=72, initial_indent="    ", subsequent_indent="    "))
        while True:
            choice = input(f"Which style should this asset use? Type a name, or press Enter to keep {current_style['name']}: ").strip()
            if not choice:
                style_key = active_key
                break
            selected = next(((key, option) for key, option in style_options
                             if choice.casefold() in {key.casefold(), option["name"].casefold()}), None)
            if selected:
                style_key, style = selected
                break
            print("Type one of the style names shown above, or press Enter to keep the current style.")
    style = next(style for key, style in style_options if key == style_key)
    if len(style_options) > 1:
        print(f"Using {style['name']} for this asset.\n")

    sorted_types = sorted(types.values(), key=lambda item: item["name"])
    print("Step 2 of 4: what are you making?")
    for number, recipe in enumerate(sorted_types, 1):
        route = {"image": "2D image", "model": "3D model", "native": "Unity geometry"}[recipe["pipeline"]]
        print(f"  {number}. {recipe['name']} ({route})")
    while True:
        choice = input("Type number or name: ").strip()
        try:
            if choice.isdigit():
                number = int(choice)
                if not 1 <= number <= len(sorted_types):
                    raise ValueError
                recipe = sorted_types[number - 1]
            else:
                recipe = types[canonical_type(choice, types)]
            asset_type = recipe["name"]
            break
        except (ValueError, IndexError, KeyError):
            print("Enter one of the listed numbers or type names.")

    manifest_path = root / config["asset_pipeline"]["manifest"]
    manifest = load_manifest(manifest_path)

    while True:
        name = input("Short name for this asset (letters, numbers, _ or -): ").strip()
        try:
            validate_asset_name(name)
            existing_key = _asset_key(manifest, asset_type, name)
            existing = manifest["assets"].get(existing_key)
            if existing and existing.get("status") == "ready":
                print("That name already has an approved asset. Choose another name to keep the current one safe.")
                continue
            break
        except ValueError as exc:
            print(exc)
    while True:
        description = input('Describe what it should look like (for example, "A small red healing potion"): ').strip()
        if description:
            break
        print("Add a short description so SlopForge knows what to create.")

    if recipe["pipeline"] != "native":
        print("\nChecking ComfyUI...")
        _check_comfy(config, root)
    print(f"\nStep 3 of 4: creating {asset_type} '{name}' in {style['name']} style.")
    generate_args = _make_operation("generate", root, style_key, asset_type=asset_type, name=name,
                                    description=description, image_prompt=None, count=None,
                                    auto_approve=False, force=False, dry_run=False)
    try:
        _run(generate_args)
    except Exception as exc:
        print(f"Couldn't create candidates: {exc}")
        print(f"Next: run `slopforge --project {root} doctor` for setup help.")
        return 1

    if recipe["pipeline"] == "native":
        print("\nDone. This is a Unity geometry task; create the simple shape in the Unity Editor.")
        return 0

    config = load_project(root)
    manifest = load_manifest(root / config["asset_pipeline"]["manifest"])
    key = _asset_key(manifest, asset_type, name)
    print("\nStep 4 of 4: review the candidates that opened, then choose one to send to Unity.")
    while True:
        record = manifest["assets"][key]
        candidates = [item for item in record.get("candidates", {}).get("items", []) if item.get("status") == "candidate"]
        for item in candidates:
            print(f"  {item['number']}. {item['path']}")
        _open_candidates(root, candidates)
        selection = input("Candidate number to approve, r to make more, or q to stop: ").strip().lower()
        if selection == "q":
            print(f"Candidates are saved. Review them later with: slopforge --project {root} candidates {name}")
            return 0
        if selection == "r":
            try:
                _run(generate_args)
            except Exception as exc:
                print(f"Couldn't create more candidates: {exc}")
                print(f"Next: run `slopforge --project {root} doctor` for setup help.")
                return 1
            manifest = load_manifest(root / config["asset_pipeline"]["manifest"])
            continue
        try:
            candidate_number = int(selection)
            if not any(item["number"] == candidate_number for item in candidates):
                raise ValueError
        except ValueError:
            print("Enter a listed candidate number, r, or q.")
            continue
        output = output_path(root, config, recipe, name)
        confirm = input(f"Approve candidate {candidate_number} to {output.relative_to(root)}? [y/N]: ").strip().lower()
        if confirm not in {"y", "yes"}:
            print("Nothing was copied into Unity. Your candidates are still saved.")
            return 0
        approve_args = _make_operation("approve", root, style_key, name=name, candidate=candidate_number, force=False)
        try:
            _run(approve_args)
        except Exception as exc:
            print(f"Couldn't approve that candidate: {exc}")
            print(f"Next: run `slopforge --project {root} doctor` for setup help.")
            return 1
        manifest = load_manifest(manifest_path)
        record = find_asset(manifest, name)
        if recipe["pipeline"] == "model" and record.get("status") == "awaiting_texture_approval":
            print("\nReview the material candidates on the same mesh from the front, side, and rear.")
            while True:
                record = find_asset(manifest, name)
                material_candidates = [item for item in record.get("material_candidates", {}).get("items", [])
                                       if item.get("status") == "candidate"]
                for item in material_candidates:
                    print(f"  material {item['number']}: {item['outputs'].get('preview_front')}")
                _open_material_candidates(root, material_candidates)
                native = any(item.get("kind") == "mesh_pbr" for item in material_candidates)
                choices = "Material number to approve, or q to stop: " if native else "Material number to approve, r to make more, or q to stop: "
                selection = input(choices).strip().lower()
                if selection == "q":
                    print(f"Model and material candidates are saved. Review with: slopforge --project {root} candidates {name}")
                    return 0
                if selection == "r" and not native:
                    count = input("How many more material candidates? [2]: ").strip()
                    try:
                        count = int(count or "2")
                        _run(_make_operation("retexture", root, style_key, name=name,
                                             material_prompt=None, count=count))
                    except Exception as exc:
                        print(f"Couldn't create material candidates: {exc}")
                        return 1
                    manifest = load_manifest(manifest_path)
                    continue
                try:
                    material_number = int(selection)
                    if not any(item["number"] == material_number for item in material_candidates):
                        raise ValueError
                except ValueError:
                    print("Enter a listed material number or q." if native else "Enter a listed material number, r, or q.")
                    continue
                confirm = input(f"Approve material {material_number} and export it to Unity? [y/N]: ").strip().lower()
                if confirm not in {"y", "yes"}:
                    return 0
                try:
                    _run(_make_operation("approve-texture", root, style_key, name=name,
                                         candidate=material_number, force=False))
                except Exception as exc:
                    print(f"Couldn't approve that material: {exc}")
                    return 1
                manifest = load_manifest(manifest_path)
                record = find_asset(manifest, name)
                break
        validation = record.get("validation", {})
        if validation.get("status") in {"passed", "passed_with_warnings"} and record.get("status") == "ready":
            relative_output = record.get("outputs", {}).get("fbx") if recipe["pipeline"] == "model" else validation.get("measured", {}).get("path")
            relative_output = relative_output or output.relative_to(root).as_posix()
            print(f"\nExported to {relative_output}. Unity will import it automatically.")
            if validation["status"] == "passed_with_warnings":
                print("Export completed with warnings; review these before using it:")
                for warning in validation.get("warnings", []):
                    print(f"  - {warning}")
            else:
                print("File checks passed. They check file health, so review the art itself in Unity too.")
            if recipe["pipeline"] == "model":
                print(f"Next: open the imported model at {relative_output} in Unity and check that the parts look attached.")
            elif asset_type in {"icon", "ui", "portrait"}:
                print(f"Next: in Unity, select {relative_output}, set Texture Type to Sprite (2D and UI), click Apply, then assign it to an Image component.")
            else:
                print(f"Next: review {relative_output} in Unity and assign it to the object or material that needs it.")
        else:
            print(f"\nThe asset didn't pass its file checks. Don't use it yet; run `slopforge --project {root} inspect {name}` for details.")
        return 0


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
    if args.command == "make":
        return _run_make(args)

    root = _project(args)
    config = load_project(root)
    if getattr(args, "_style_key", None):
        config["asset_pipeline"]["active_style"] = args._style_key
    if getattr(args, "quality_tier", None):
        config = select_quality_tier(config, args.quality_tier)
    elif args.command == "explore" and not os.environ.get("SLOPFORGE_QUALITY_TIER"):
        config = select_quality_tier(config, "draft")
    pipeline = config["asset_pipeline"]
    manifest_path = root / pipeline["manifest"]
    manifest = load_manifest(manifest_path)

    if args.command == "library":
        from .libraries import list_libraries, resolve_library
        if args.library_action == "list":
            for selector in list_libraries(root):
                print(selector)
        else:
            print(json.dumps(resolve_library(root, args.selector, manifest), indent=2))
        return 0

    if args.command == "animation":
        from .animation import retarget_animation, validate_animation_library
        if args.animation_action == "validate":
            library = validate_animation_library(root, args.name)
            print(f"Animation library {args.name}: {len(library['clips'])} valid clip(s), {library['skeleton_type']} skeleton")
            for clip in library["clips"]:
                print(f"  {clip['name']}\t{clip['resolved_path'].relative_to(root).as_posix()}\tloop={clip['loop']}\troot_motion={clip['root_motion']}")
            return 0
        if args.animation_action == "unity-setup":
            from .unity_animation import build_character_animator
            result = build_character_animator(root, config, manifest, args.character, rig_type=args.rig_type)
            save_manifest(manifest_path, manifest)
            print(f"Unity character setup: {result['status']}")
            print(f"Controller: {result['controller']['path']}")
            print(f"Prefab: {result['prefab']['path']}")
            return 0
        result = retarget_animation(root, config, manifest, args.character, args.name, args.clip)
        save_manifest(manifest_path, manifest)
        print(f"Animation {args.clip}: {result['status']} ({result['frames']} frames)")
        print(f"Candidate: {result['artifact']['path']}")
        return 0

    if args.command == "character":
        result = rigify_character(root, config, manifest, args.name, source_output=args.source_output)
        save_manifest(manifest_path, manifest)
        print(f"Character {args.name}: {result['status']}")
        print(f"Rig candidate: {result['rig_artifact']['path']}")
        print("Review the rig and six pose images before approving it.")
        return 0

    if args.command == "prototype":
        types = load_taxonomy(root)
        style = load_style(root, config)
        if args.prototype_action == "propose":
            plan = prototypes.propose(root, args.name, args.description, style, types, config,
                                      recipe_names=args.recipe_names, quality_tier=args.quality_tier,
                                      candidate_budget=args.candidate_budget)
            path = prototypes.plan_path(root, args.name)
            print(f"Proposed {len(plan['stages'])} stage(s), {len(plan['content_plan'])} content item(s), "
                  f"about {plan['estimated_candidates']} estimated candidate(s) against budget {plan['candidate_budget']}: "
                  f"{path.relative_to(root)}")
            print("Review/edit the plan, then run `slopforge prototype approve", args.name + "`.")
            return 0
        if args.prototype_action == "approve":
            plan = prototypes.approve(root, args.name)
            print(f"Approved prototype plan {args.name} ({len(plan['stages'])} stages)")
            return 0
        if args.prototype_action == "regenerate":
            plan = prototypes.load_plan(root, args.name)
            if plan.get("approval", {}).get("status") != "approved":
                raise ValueError("Prototype plan must be explicitly approved before regeneration")
            key = asset_key("prototype", args.name)
            prototype = manifest["assets"].get(key)
            if not prototype:
                raise KeyError(f"No prototype run named {args.name!r}")
            stage = prototype["prototype"]["stages"].get(args.stage)
            if not stage:
                raise KeyError(f"Prototype has no stage {args.stage!r}")
            if any(prototype["prototype"]["stages"][dependency]["status"] != "approved"
                   for dependency in stage["depends_on"]):
                raise ValueError("Prototype stage dependencies require approved outputs before regeneration")
            recipes.regenerate_child(root, config, style, types, manifest, stage["instance"], args.child_id,
                                     save=lambda current: save_manifest(manifest_path, current))
            stage["status"] = "awaiting_approval"
        result = prototypes.run(root, config, style, types, manifest, args.name,
                                save=lambda current: save_manifest(manifest_path, current))
        print(f"Prototype {args.name}: {result['status']}")
        for stage_id, stage in result["prototype"]["stages"].items():
            detail = f" ({'; '.join(stage['errors'])})" if stage.get("errors") else ""
            print(f"  {stage_id}: {stage['status']}{detail}")
        return 2 if result["status"] == "partial" else 0

    if args.command == "review":
        from .review import generate_review_board
        page = generate_review_board(root, manifest, args.output)
        print(page)
        return 0

    if args.command == "environment-check":
        selector = asset_key("recipe", args.name)
        recipe_asset = manifest["assets"].get(selector)
        if not recipe_asset or "recipe_instance" not in recipe_asset:
            raise KeyError(f"No recipe run named {args.name!r}")
        if "kit_constraints" not in recipe_asset["recipe_instance"].get("definition", {}):
            raise ValueError(f"Recipe {args.name!r} has no environment kit constraints")
        report = validate_environment_kit(recipe_asset, manifest)
        output = root / "ai/assets/environment_checks" / f"{args.name}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
        derived_from = []
        for stage in recipe_asset["recipe_instance"]["stages"].values():
            child = manifest["assets"].get(stage.get("asset_key"), {})
            for output_id in ("blend", "fbx"):
                if output_id in child.get("outputs", {}):
                    derived_from.append({"asset_id": child["id"], "output_id": output_id})
                    break
        register_artifact(manifest, selector, "kit.validation", "data.environment_validation",
                          output.relative_to(root).as_posix(), status="ready" if report["status"] == "passed" else "failed",
                          derived_from=derived_from,
                          provenance={"processor": "slopforge.environment", "constraints": report["constraints"]},
                          approval_status="not_required", validation=report)
        recipe_asset["environment_validation"] = {"status": report["status"],
                                                  "path": output.relative_to(root).as_posix()}
        save_manifest(manifest_path, manifest)
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "passed" else 1

    if args.command == "tilepack":
        asset = find_asset(manifest, args.name)
        if asset.get("type") != "tile_sheet" or asset.get("status") != "ready":
            raise ValueError("tilepack requires an approved tile_sheet asset")
        selected = asset.get("candidates", {}).get("selected")
        if not any(candidate.get("number") == selected and candidate.get("approval") == "approved"
                   for candidate in asset.get("candidates", {}).get("items", [])):
            raise ValueError("tilepack requires an explicitly approved sheet candidate")
        source = asset.get("outputs", {}).get("image")
        if not source:
            raise ValueError("Approved tile sheet has no image output")
        source_path = (root / source).resolve()
        if not source_path.is_relative_to(root) or not source_path.is_file():
            raise ValueError("Approved tile sheet is missing or outside the project")
        if not math.isfinite(args.pixels_per_unit) or args.pixels_per_unit <= 0:
            raise ValueError("--pixels-per-unit must be positive and finite")
        output_root = (root / pipeline["output_root"] / "Tilesets" / asset["name"]).resolve()
        if not output_root.is_relative_to(root):
            raise ValueError("Tileset output must stay within the project")
        result = package_tileset(source_path, output_root / "Tiles", asset["name"],
                                 columns=args.grid[0], rows=args.grid[1], tile_size=args.tile_size,
                                 margin=args.margin, padding=args.padding, layout=args.layout,
                                 collider=args.collider, transition_masks=args.transition_mask)
        derived_from = [{"asset_id": asset["id"], "output_id": "image"}]
        settings = {"columns": args.grid[0], "rows": args.grid[1], "tile_size": args.tile_size,
                    "margin": args.margin, "padding": args.padding, "layout": args.layout,
                    "collider": args.collider, "pixels_per_unit": args.pixels_per_unit,
                    "transition_masks": args.transition_mask}
        for tile in result["tiles"]:
            register_artifact(manifest, asset["id"], f"tiles.{tile['index']:03d}", "image.tile",
                              (result["directory"] / tile["path"]).relative_to(root).as_posix(),
                              derived_from=derived_from,
                              provenance={"processor": "slopforge.tileset", **settings, **tile},
                              approval_status="approved")
        for artifact_id, artifact_type, path in (("tiles.atlas", "image.tile_atlas", result["atlas"]),
                                                  ("tiles.metadata", "data.tileset", result["metadata"])):
            register_artifact(manifest, asset["id"], artifact_id, artifact_type,
                              path.relative_to(root).as_posix(), derived_from=derived_from,
                              provenance={"processor": "slopforge.tileset", **settings},
                              approval_status="approved")
        asset["tileset"] = {"directory": result["directory"].relative_to(root).as_posix(), **settings}
        save_manifest(manifest_path, manifest)
        if args.unity_assets:
            _create_unity_tiles(root, manifest_path, manifest, asset, settings)
        print(result["directory"])
        return 0

    if args.command == "tile-unity":
        asset = find_asset(manifest, args.name)
        if asset.get("type") != "tile_sheet" or asset.get("status") != "ready" or not asset.get("tileset"):
            raise ValueError("tile-unity requires a tile_sheet asset already processed with tilepack")
        paths = _create_unity_tiles(root, manifest_path, manifest, asset, asset["tileset"])
        print("\n".join(path.relative_to(root).as_posix() for path in paths))
        return 0

    types = load_taxonomy(root)
    style = load_style(root, config)

    if args.command == "explore":
        variations = parse_variations(args.variation)
        asset_type = canonical_type(args.asset_type, types)
        recipe = types[asset_type]
        if recipe["pipeline"] == "native":
            raise ValueError("Unity-native assets do not have image concept candidates to explore")
        validate_asset_name(args.name)
        key = asset_key(asset_type, args.name)
        if key in manifest["assets"]:
            raise FileExistsError(f"Exploration {args.name!r} already exists")
        if getattr(args, "reference_library", None) and (args.reference_paths or args.reference_categories):
            raise ValueError("Choose --reference-library or --reference/--reference-category, not both")
        reference_entries = None
        if args.reference_library:
            from .libraries import resolve_library
            reference_entries = resolve_library(root, args.reference_library, manifest)["entries"]
        record = new_record(asset_type, args.name, args.description, style, pipeline["conditioning"])
        record.update({"generation_mode": "explore", "quality_tier": pipeline["selected_quality_tier"]})
        manifest["active_style"] = _active_style(style)
        manifest["assets"][key] = record
        save_manifest(manifest_path, manifest)
        prompt_text = build_prompt(style, recipe, args.description, recipe.get("prompt_mode", "asset"))
        generator = image.generate if recipe["pipeline"] == "image" else model.generate
        try:
            generated = generator(root, config, recipe, style, args.name, args.description, len(variations),
                                  manifest, key, generation_prompt=prompt_text, variations=variations,
                                  reference_paths=args.reference_paths,
                                  reference_categories=args.reference_categories,
                                  reference_entries=reference_entries)
            save_manifest(manifest_path, manifest)
        except Exception as exc:
            record["status"] = "failed"
            record.setdefault("validation", {"status": "not_run", "warnings": [], "measured": {}})
            record["validation"].setdefault("warnings", []).append(str(exc))
            save_manifest(manifest_path, manifest)
            raise
        print(f"Explored {len(generated)} deliberate variation(s). Review with: slopforge --project {root} review")
        return 0

    if args.command == "promote":
        source = find_asset(manifest, args.exploration)
        asset_type = canonical_type(source.get("type"), types)
        recipe = types[asset_type]
        if recipe["pipeline"] == "native":
            raise ValueError("Unity-native assets cannot receive generated candidates")
        record = promote_candidate(root, pipeline["candidate_root"], manifest, args.exploration,
                                   args.candidate, args.name, recipe, style)
        save_manifest(manifest_path, manifest)
        print(f"Promoted to {record['name']}. Review, then approve with: slopforge --project {root} approve {record['name']} 1")
        return 0

    if args.command == "spritepack":
        asset = find_asset(manifest, args.name)
        asset_type = asset.get("type")
        if asset_type not in {"sprite_sheet", "vfx_sheet"} or asset.get("status") != "ready":
            raise ValueError("spritepack requires an approved sprite_sheet or vfx_sheet asset")
        if args.particle_prefab and asset_type != "vfx_sheet":
            raise ValueError("--particle-prefab requires a vfx_sheet asset")
        selected = asset.get("candidates", {}).get("selected")
        if not any(candidate.get("number") == selected and candidate.get("approval") == "approved"
                   for candidate in asset.get("candidates", {}).get("items", [])):
            raise ValueError("spritepack requires an explicitly approved sheet candidate")
        source = asset.get("outputs", {}).get("image")
        if not source:
            raise ValueError("Approved sprite sheet has no image output")
        source_path = (root / source).resolve()
        if not source_path.is_relative_to(root) or not source_path.is_file():
            raise ValueError("Approved sprite sheet is missing or outside the project")
        loop = args.loop if args.loop is not None else args.animation in {"idle", "walk", "run"}
        asset_folder = "VisualEffects" if asset_type == "vfx_sheet" else "Characters"
        destination = (root / pipeline["output_root"] / asset_folder / asset["name"] / args.animation).resolve()
        if not destination.is_relative_to(root):
            raise ValueError("Sprite pack output must stay within the project")
        result = package_sprite_sheet(source_path, destination, args.animation, columns=args.grid[0],
                                      rows=args.grid[1], fps=args.fps, pivot=args.pivot, loop=loop)
        derived_from = [{"asset_id": asset["id"], "output_id": "image"}]
        prefix = f"{'vfx' if asset_type == 'vfx_sheet' else 'sprites'}.{args.animation}"
        settings = {"fps": args.fps, "pivot": result["pivot"], "loop": loop,
                    "columns": args.grid[0], "rows": args.grid[1], "frame_size": result["frame_size"]}
        for index, frame in enumerate(result["frame_paths"]):
            register_artifact(manifest, asset["id"], f"{prefix}.frame_{index:03d}", "image.sprite_frame",
                              frame.relative_to(root).as_posix(), derived_from=derived_from,
                              provenance={"processor": "slopforge.spritepack", **settings, "frame": index},
                              approval_status="approved")
        register_artifact(manifest, asset["id"], f"{prefix}.atlas", "image.sprite_atlas",
                          result["atlas"].relative_to(root).as_posix(), derived_from=derived_from,
                          provenance={"processor": "slopforge.spritepack", **settings}, approval_status="approved")
        register_artifact(manifest, asset["id"], f"{prefix}.metadata", "data.unity_animation",
                          result["metadata"].relative_to(root).as_posix(), derived_from=derived_from,
                          provenance={"processor": "slopforge.spritepack", **settings}, approval_status="approved")
        if args.particle_prefab:
            prefab = destination / "particle_system.prefab"
            material = destination / "particle_system.mat"
            create_particle_prefab(root, result["atlas"], prefab, material,
                                   columns=args.grid[0], rows=args.grid[1], loop=loop)
            for artifact_id, artifact_type, path in ((f"{prefix}.prefab", "unity.particle_prefab", prefab),
                                                      (f"{prefix}.material", "unity.material", material)):
                register_artifact(manifest, asset["id"], artifact_id, artifact_type,
                                  path.relative_to(root).as_posix(), derived_from=derived_from,
                                  provenance={"processor": "slopforge.unity_vfx", **settings},
                                  approval_status="approved")
        asset.setdefault("sprite_animations", {})[args.animation] = {
            "frame_count": result["frame_count"], "frame_size": result["frame_size"],
            "fps": args.fps, "loop": loop, "pivot": result["pivot"],
            "atlas": result["atlas"].relative_to(root).as_posix(),
            "metadata": result["metadata"].relative_to(root).as_posix()}
        save_manifest(manifest_path, manifest)
        print(f"Sprite pack created: {destination}")
        return 0

    if args.command == "ui-meta":
        if args.prefab and not args.apply:
            raise ValueError("--prefab requires --apply")
        asset = find_asset(manifest, args.name)
        if asset.get("type") != "ui" or asset.get("status") != "ready":
            raise ValueError("ui-meta requires an approved ui asset")
        selected = asset.get("candidates", {}).get("selected")
        if not any(candidate.get("number") == selected and candidate.get("approval") == "approved"
                   for candidate in asset.get("candidates", {}).get("items", [])):
            raise ValueError("ui-meta requires an explicitly approved candidate")
        image_relative = asset.get("outputs", {}).get("image")
        if not image_relative:
            raise ValueError("Approved UI asset has no image output")
        image_path = (root / image_relative).resolve()
        if not image_path.is_relative_to(root) or not image_path.is_file():
            raise ValueError("Approved UI image is missing or outside the project")
        from PIL import Image
        with Image.open(image_path) as image_file:
            dimensions = image_file.size
        metadata = make_sprite_import_metadata(image_relative, dimensions, border=args.border, pivot=args.pivot,
                                              pixels_per_unit=args.pixels_per_unit)
        output = image_path.with_name(image_path.stem + "_sprite_settings.json")
        if output.exists():
            raise FileExistsError(f"UI import metadata already exists: {output}")
        output.write_text(json.dumps(metadata, indent=2) + "\n")
        if args.apply:
            try:
                apply_sprite_settings(root, image_path, output, border=args.border, pivot=args.pivot,
                                      pixels_per_unit=args.pixels_per_unit, prefab=args.prefab)
            except Exception:
                output.unlink(missing_ok=True)
                raise
        register_artifact(manifest, asset["id"], "unity.sprite_settings", "data.unity_sprite_settings",
                          output.relative_to(root).as_posix(),
                          derived_from=[{"asset_id": asset["id"], "output_id": "image"}],
                          provenance={"processor": "slopforge.ui", "border": metadata["border"],
                                      "pivot": metadata["pivot"], "pixels_per_unit": args.pixels_per_unit},
                          approval_status="approved")
        if args.prefab:
            register_artifact(manifest, asset["id"], "unity.prefab", "unity.prefab",
                              image_path.with_suffix(".prefab").relative_to(root).as_posix(),
                              derived_from=[{"asset_id": asset["id"], "output_id": "image"}],
                              provenance={"processor": "slopforge.unity_ui", "sprite_settings": "unity.sprite_settings"},
                              approval_status="approved")
        save_manifest(manifest_path, manifest)
        print(output)
        return 0

    if args.command == "recipe":
        if args.recipe_action == "list":
            for name in recipes.list_recipes(root):
                print(f"definition\t{name}")
            for record in manifest["assets"].values():
                if record.get("type") == "recipe" and "recipe_instance" in record:
                    print(f"run\t{record['name']}\t{record.get('status')}")
            return 0
        persist = lambda current: save_manifest(manifest_path, current)
        if args.recipe_action == "run":
            record = recipes.run_recipe(root, config, style, types, manifest, args.recipe_name,
                                        instance_name=args.name, quality_tier=args.quality_tier,
                                        reference_library=args.reference_library, save=persist)
        elif args.recipe_action == "resume":
            record = recipes.resume_recipe(root, config, style, types, manifest, args.name, save=persist)
        else:
            record = recipes.regenerate_child(root, config, style, types, manifest,
                                              args.name, args.child_id, save=persist)
        stages = record["recipe_instance"]["stages"]
        print(f"Recipe {record['name']}: {record['status']}")
        for child_id, stage in stages.items():
            detail = f" ({'; '.join(stage['errors'])})" if stage.get("errors") else ""
            print(f"  {child_id}: {stage['status']}{detail}")
        return 2 if record["status"] == "partial" else 0

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
    if args.command == "reject":
        from .candidates import reject_candidate
        reject_candidate(manifest, args.name, args.candidate, args.reason)
        save_manifest(manifest_path, manifest)
        print(f"Rejected {args.name} candidate {args.candidate}.")
        return 0

    if args.command in {"retexture", "approve-texture"}:
        record = find_asset(manifest, args.name)
        asset_type = "prop" if record.get("type") == "model" else record.get("type")
        recipe = types[canonical_type(asset_type, types)]
        if recipe["pipeline"] != "model":
            raise ValueError(f"{args.name} is not a generated model")
        key = next(key for key, item in manifest["assets"].items() if item is record)
        if args.command == "retexture":
            count = args.count if args.count is not None else pipeline.get("quality_settings", {}).get(
                "defaults", {}).get("material_candidates", 1)
            if count < 1:
                raise ValueError("--count must be at least 1")
            generated = model.retexture(root, config, recipe, style, manifest, key,
                                        material_prompt=args.material_prompt, count=count)
            save_manifest(manifest_path, manifest)
            print(f"Generated {len(generated)} material candidate(s).")
            for item in generated:
                print(f"  {item['number']}: {item.get('outputs', {}).get('preview_front', item.get('path'))} ({item['status']})")
            if not any(item["status"] == "candidate" for item in generated):
                raise RuntimeError(f"No valid material candidates generated for {record['name']}; failures are saved in the manifest")
        else:
            result = model.approve_texture(root, config, manifest, key, args.candidate, args.force)
            save_manifest(manifest_path, manifest)
            print(json.dumps(result, indent=2))
        return 0

    manifest["active_style"] = _active_style(style)
    if args.command == "approve":
        record = find_asset(manifest, args.name)
        asset_type = "prop" if record.get("type") == "model" else record["type"]
        recipe = types[canonical_type(asset_type, types)]
        key = next(key for key, item in manifest["assets"].items() if item is record)
        if recipe["pipeline"] == "image":
            result = image.approve(root, config, recipe, manifest, key, args.candidate, args.force)
            if not getattr(args, "_guided", False):
                print(json.dumps(result, indent=2))
        elif recipe["pipeline"] == "model":
            model.approve(root, config, recipe, style, manifest, key, args.candidate, args.force,
                          material_prompt=getattr(args, "material_prompt", None),
                          material_count=getattr(args, "material_count", None),
                          quality_tier=getattr(args, "quality_tier", None))
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
    prompt_text = args.image_prompt or build_prompt(style, recipe, args.description, recipe.get("prompt_mode", "asset"))
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
        if getattr(args, "reference_library", None) and (getattr(args, "reference_paths", None) or
                                                          getattr(args, "reference_categories", None)):
            raise ValueError("Choose --reference-library or --reference/--reference-category, not both")
        reference_entries = None
        if getattr(args, "reference_library", None):
            from .libraries import resolve_library
            reference_entries = resolve_library(root, args.reference_library, manifest)["entries"]
        generated = (image.generate(root, config, recipe, style, args.name, args.description,
                                    count, manifest, key, generation_prompt=prompt_text,
                                    reference_paths=getattr(args, "reference_paths", None),
                                    reference_categories=getattr(args, "reference_categories", None),
                                    reference_entries=reference_entries) if recipe["pipeline"] == "image" else
                     model.generate(root, config, recipe, style, args.name, args.description,
                                    count, manifest, key, generation_prompt=prompt_text,
                                    reference_paths=getattr(args, "reference_paths", None),
                                    reference_categories=getattr(args, "reference_categories", None),
                                    reference_entries=reference_entries))
        save_manifest(manifest_path, manifest)
    except Exception as exc:
        record["status"] = "failed"
        record.setdefault("validation", {"status": "not_run", "warnings": [], "measured": {}})
        record["validation"].setdefault("warnings", []).append(str(exc))
        save_manifest(manifest_path, manifest)
        raise
    if not args.auto_approve:
        message = f"Generated {len(generated)} candidate(s)."
        if not getattr(args, "_guided", False):
            message += f" Review with: slopforge --project {root} candidates {args.name}"
        print(message)
        return 0
    selected = next((candidate for candidate in generated if candidate.get("status") == "candidate"), None)
    if selected is None:
        raise RuntimeError(f"No valid candidate exists for {args.name}")
    if recipe["pipeline"] == "image":
        result = image.approve(root, config, recipe, manifest, key, selected["number"], args.force)
        print(json.dumps(result, indent=2))
    else:
        model.approve(root, config, recipe, style, manifest, key, selected["number"], args.force,
                      quality_tier=getattr(args, "quality_tier", None))
    save_manifest(manifest_path, manifest)
    return 0


def main(argv=None):
    args = parse_args(argv)
    try:
        return _run(args)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
