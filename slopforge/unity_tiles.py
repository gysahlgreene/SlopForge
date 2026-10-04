import json
import subprocess
import uuid
from pathlib import Path

from .unity_material import unity_cli


def create_tile_assets(project_root, tile_paths, output_directory, *, collider, pixels_per_unit):
    root = Path(project_root).resolve()
    output_directory = Path(output_directory).resolve()
    try:
        output_asset = output_directory.relative_to(root).as_posix()
        source_assets = [Path(path).resolve().relative_to(root).as_posix() for path in tile_paths]
    except ValueError as exc:
        raise ValueError("Tile images and Unity tile assets must be inside the Unity project") from exc
    if any(not (root / path).is_file() for path in source_assets):
        raise FileNotFoundError("One or more sliced tile images are missing")
    if collider not in {"none", "grid", "sprite"}:
        raise ValueError("Tile collider must be none, grid, or sprite")
    if not isinstance(pixels_per_unit, (int, float)) or isinstance(pixels_per_unit, bool) or pixels_per_unit <= 0:
        raise ValueError("pixels_per_unit must be positive")
    output_directory.mkdir(parents=True, exist_ok=True)
    outputs = [output_directory / f"{Path(path).stem}.asset" for path in source_assets]
    existing = next((path for path in outputs if path.exists()), None)
    if existing:
        raise FileExistsError(f"Unity tile asset already exists: {existing}")

    collider_value = {"none": "None", "grid": "Grid", "sprite": "Sprite"}[collider]
    statements = "\n".join(
        f'''        CreateTile({json.dumps(source)}, {json.dumps(destination.relative_to(root).as_posix())});'''
        for source, destination in zip(source_assets, outputs))
    class_name = "SlopForgeTileBuilder_" + uuid.uuid4().hex
    script = root / "Assets/Editor" / f"{class_name}.cs"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f'''using System;
using UnityEditor;
using UnityEngine;
using UnityEngine.Tilemaps;

public static class {class_name}
{{
    public static void Build()
    {{
        AssetDatabase.Refresh();
{statements}
        AssetDatabase.SaveAssets();
        Debug.Log("SLOPFORGE_TILE_ASSETS_CREATED {output_asset}");
    }}

    static void CreateTile(string imagePath, string tilePath)
    {{
        var importer = AssetImporter.GetAtPath(imagePath) as TextureImporter;
        if (importer == null) throw new Exception("Tile texture importer not found: " + imagePath);
        importer.textureType = TextureImporterType.Sprite;
        importer.spriteImportMode = SpriteImportMode.Single;
        importer.spritePixelsPerUnit = {float(pixels_per_unit)}f;
        importer.alphaIsTransparency = true;
        var settings = new TextureImporterSettings();
        importer.ReadTextureSettings(settings);
        settings.spriteMeshType = SpriteMeshType.FullRect;
        importer.SetTextureSettings(settings);
        importer.SaveAndReimport();
        var sprite = AssetDatabase.LoadAssetAtPath<Sprite>(imagePath);
        if (sprite == null) throw new Exception("Tile Sprite did not import: " + imagePath);
        var tile = ScriptableObject.CreateInstance<Tile>();
        tile.sprite = sprite;
        tile.colliderType = Tile.ColliderType.{collider_value};
        AssetDatabase.CreateAsset(tile, tilePath);
    }}
}}
''')
    try:
        subprocess.run([unity_cli(root), "run", str(root), "--timeout", "600", "--", "-executeMethod",
                        f"{class_name}.Build"], check=True)
    finally:
        script.unlink(missing_ok=True)
        script.with_suffix(".cs.meta").unlink(missing_ok=True)
    missing = [path for path in outputs if not path.is_file()]
    if missing:
        raise RuntimeError("Unity completed without creating every Tile asset: " + ", ".join(map(str, missing)))
    return outputs
