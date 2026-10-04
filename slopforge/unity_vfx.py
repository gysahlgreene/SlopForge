import json
import subprocess
import uuid
from pathlib import Path

from .unity_material import unity_cli


def create_particle_prefab(project_root, atlas, prefab, material, *, columns, rows, loop):
    root = Path(project_root).resolve()
    atlas, prefab, material = (Path(path).resolve() for path in (atlas, prefab, material))
    try:
        atlas_asset, prefab_asset, material_asset = (
            path.relative_to(root).as_posix() for path in (atlas, prefab, material))
    except ValueError as exc:
        raise ValueError("VFX atlas, prefab, and material must be inside the Unity project") from exc
    if not atlas.is_file():
        raise FileNotFoundError(f"VFX atlas does not exist: {atlas}")
    if prefab.exists() or material.exists():
        raise FileExistsError(f"VFX Unity output already exists: {prefab if prefab.exists() else material}")

    class_name = "SlopForgeVFXBuilder_" + uuid.uuid4().hex
    script = root / "Assets/Editor" / f"{class_name}.cs"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f'''using System;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

public static class {class_name}
{{
    public static void Build()
    {{
        const string atlasPath = {json.dumps(atlas_asset)};
        const string prefabPath = {json.dumps(prefab_asset)};
        const string materialPath = {json.dumps(material_asset)};
        AssetDatabase.Refresh();
        var importer = AssetImporter.GetAtPath(atlasPath) as TextureImporter;
        if (importer == null) throw new Exception("VFX atlas importer not found: " + atlasPath);
        importer.textureType = TextureImporterType.Default;
        importer.alphaIsTransparency = true;
        importer.mipmapEnabled = false;
        importer.SaveAndReimport();
        var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(atlasPath);
        if (texture == null) throw new Exception("VFX atlas did not load: " + atlasPath);
        var pipeline = GraphicsSettings.currentRenderPipeline;
        var shaderName = pipeline == null ? "Particles/Standard Unlit" :
            "Universal Render Pipeline/Particles/Unlit";
        var shader = Shader.Find(shaderName);
        if (shader == null) throw new Exception("Particle shader not found: " + shaderName);
        var material = new Material(shader);
        material.name = "particle_system";
        if (material.HasProperty("_BaseMap")) material.SetTexture("_BaseMap", texture);
        if (material.HasProperty("_MainTex")) material.SetTexture("_MainTex", texture);
        AssetDatabase.CreateAsset(material, materialPath);

        var gameObject = new GameObject("VFX Particle System", typeof(ParticleSystem));
        var system = gameObject.GetComponent<ParticleSystem>();
        var main = system.main;
        main.loop = {str(bool(loop)).lower()};
        main.playOnAwake = false;
        main.startLifetime = 1f;
        main.startSpeed = 0f;
        main.startSize = 1f;
        main.startColor = Color.white;
        var emission = system.emission;
        if (!main.loop)
        {{
            emission.rateOverTime = 0f;
            emission.SetBursts(new[] {{ new ParticleSystem.Burst(0f, 12) }});
        }}
        var shape = system.shape;
        shape.enabled = false;
        var sheet = system.textureSheetAnimation;
        sheet.enabled = true;
        sheet.numTilesX = {columns};
        sheet.numTilesY = {rows};
        sheet.animation = ParticleSystemAnimationType.WholeSheet;
        sheet.frameOverTime = new ParticleSystem.MinMaxCurve(1f);
        var renderer = gameObject.GetComponent<ParticleSystemRenderer>();
        renderer.renderMode = ParticleSystemRenderMode.Billboard;
        renderer.material = material;
        PrefabUtility.SaveAsPrefabAsset(gameObject, prefabPath);
        UnityEngine.Object.DestroyImmediate(gameObject);
        AssetDatabase.SaveAssets();
        Debug.Log("SLOPFORGE_VFX_PREFAB_CREATED " + prefabPath);
    }}
}}
''')
    try:
        subprocess.run([unity_cli(root), "run", str(root), "--timeout", "600", "--", "-executeMethod",
                        f"{class_name}.Build"], check=True)
    finally:
        script.unlink(missing_ok=True)
        script.with_suffix(".cs.meta").unlink(missing_ok=True)
    if not prefab.is_file() or not material.is_file():
        raise RuntimeError("Unity completed without producing the VFX prefab and material")
    return prefab, material
