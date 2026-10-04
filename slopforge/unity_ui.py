import json
import subprocess
import uuid
from pathlib import Path

from .unity_material import unity_cli


def apply_sprite_settings(project_root, image_path, metadata_path, *, border, pivot, pixels_per_unit, prefab=False):
    root = Path(project_root).resolve()
    image_path = Path(image_path).resolve()
    metadata_path = Path(metadata_path).resolve()
    try:
        image_asset = image_path.relative_to(root).as_posix()
        metadata_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Unity UI images and metadata must be inside the Unity project") from exc
    if not image_path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError("Unity UI image and sprite settings metadata must both exist")
    prefab_path = image_path.with_suffix(".prefab")
    if prefab and prefab_path.exists():
        raise FileExistsError(f"UI prefab already exists: {prefab_path}")

    class_name = "SlopForgeSpriteImporter_" + uuid.uuid4().hex
    source = json.dumps(image_asset)
    pivot_x, pivot_y = (repr(float(value)) for value in pivot)
    left, bottom, right, top = border
    prefab_asset = json.dumps(prefab_path.relative_to(root).as_posix())
    create_prefab = "true" if prefab else "false"
    script = root / "Assets/Editor" / f"{class_name}.cs"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f'''using System;
using UnityEditor;
using UnityEngine;

public static class {class_name}
{{
    public static void Apply()
    {{
        const string imagePath = {source};
        AssetDatabase.Refresh();
        var importer = AssetImporter.GetAtPath(imagePath) as TextureImporter;
        if (importer == null) throw new Exception("Texture importer not found: " + imagePath);
        importer.textureType = TextureImporterType.Sprite;
        importer.spriteImportMode = SpriteImportMode.Single;
        var settings = new TextureImporterSettings();
        importer.ReadTextureSettings(settings);
        settings.spriteMeshType = SpriteMeshType.FullRect;
        importer.SetTextureSettings(settings);
        importer.spritePixelsPerUnit = {float(pixels_per_unit)}f;
        importer.spritePivot = new Vector2({pivot_x}f, {pivot_y}f);
        importer.spriteBorder = new Vector4({left}, {bottom}, {right}, {top});
        importer.alphaIsTransparency = true;
        importer.SaveAndReimport();
        if ({create_prefab})
        {{
            var sprite = AssetDatabase.LoadAssetAtPath<Sprite>(imagePath);
            if (sprite == null) throw new Exception("Imported Sprite not found: " + imagePath);
            var imageType = Type.GetType("UnityEngine.UI.Image, UnityEngine.UI");
            if (imageType == null) throw new Exception("The Unity UGUI package is required to create an Image prefab.");
            var image = new GameObject(sprite.name, typeof(RectTransform), typeof(CanvasRenderer));
            var component = image.AddComponent(imageType);
            imageType.GetProperty("sprite").SetValue(component, sprite);
            imageType.GetProperty("raycastTarget").SetValue(component, false);
            if ({left} + {bottom} + {right} + {top} > 0)
                imageType.GetProperty("type").SetValue(component, Enum.Parse(imageType.GetNestedType("Type"), "Sliced"));
            PrefabUtility.SaveAsPrefabAsset(image, {prefab_asset});
            UnityEngine.Object.DestroyImmediate(image);
        }}
        AssetDatabase.SaveAssets();
        Debug.Log("SLOPFORGE_UI_SPRITE_APPLIED " + imagePath);
    }}
}}
''')
    try:
        subprocess.run([unity_cli(root), "run", str(root), "--timeout", "600", "--", "-executeMethod",
                        f"{class_name}.Apply"], check=True)
    finally:
        script.unlink(missing_ok=True)
        script.with_suffix(".cs.meta").unlink(missing_ok=True)
    return prefab_path if prefab else None
