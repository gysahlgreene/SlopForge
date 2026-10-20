import json
import shutil
import subprocess
import uuid
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter
from .failures import StageFailure


def unity_cli(project_root):
    root = Path(project_root).resolve()
    if not (root / "ProjectSettings/ProjectVersion.txt").is_file():
        raise StageFailure("configuration", f"Not a Unity project: {root}", operation="unity_preflight",
                           remedy="select a Unity project with ProjectSettings/ProjectVersion.txt")
    cli = shutil.which("unity")
    if not cli:
        raise StageFailure("environment", "Unity CLI is required to create and assign the generated PBR material",
                           operation="unity_preflight", remedy="install Unity or configure its CLI")
    return cli


def make_metallic_gloss(metallic_path, roughness_path, destination):
    with Image.open(metallic_path) as image:
        metallic = image.convert("L")
    with Image.open(roughness_path) as image:
        roughness = image.convert("L")
    if metallic.size != roughness.size:
        raise ValueError("Metallic and roughness maps must have matching dimensions")
    Image.merge("RGBA", (metallic, metallic, metallic, ImageChops.invert(roughness))).save(destination)


def derive_emission(basecolor_path, destination, targets=((None, (255, 178, 102)),)):
    """Emission for declared glowing regions, found in the generated base color map.

    Each target is (match_rgb, glow_rgb). match_rgb None means large near-white regions (pale
    emitters such as paper); otherwise texels within a small colour distance of match_rgb.
    A morphological opening drops small flecks. Returns the emissive fraction of the map.
    """
    with Image.open(basecolor_path) as image:
        base = image.convert("RGB")
    size = max(3, round(15 * base.width / 2048) | 1)  # odd kernel, 15 px at 2048
    emission, total = Image.new("RGB", base.size), Image.new("L", base.size)
    for match, glow in targets:
        if match is None:
            r, g, b = base.split()
            low = ImageChops.darker(ImageChops.darker(r, g), b)
            high = ImageChops.lighter(ImageChops.lighter(r, g), b)
            # TRELLIS.2 bakes pale paper as flat near-neutral albedo at ~191-203 or ~253 depending on seed;
            # grey and cream stone stay below 190 (docs/MATERIALS.md, Emission).
            mask = ImageChops.multiply(low.point(lambda v: 255 if v >= 190 else 0),
                                       ImageChops.subtract(high, low).point(lambda v: 255 if v <= 25 else 0))
        else:
            distance = ImageChops.difference(base, Image.new("RGB", base.size, tuple(match)))
            mask = ImageChops.lighter(ImageChops.lighter(*distance.split()[:2]), distance.split()[2])
            mask = mask.point(lambda v: 255 if v <= 48 else 0)
        mask = mask.filter(ImageFilter.MinFilter(size)).filter(ImageFilter.MaxFilter(size))
        total = ImageChops.lighter(total, mask)
        soft = mask.filter(ImageFilter.GaussianBlur(max(1, size // 5)))
        emission = Image.composite(Image.new("RGB", base.size, tuple(glow)), emission, soft)
    emission.save(destination)
    return sum(total.histogram()[128:]) / (base.width * base.height)


def build_unity_material(project_root, fbx, material, maps):
    root = Path(project_root).resolve()
    cli = unity_cli(root)

    fbx = Path(fbx).resolve()
    material = Path(material).resolve()
    try:
        fbx_asset = fbx.relative_to(root).as_posix()
        material_asset = material.relative_to(root).as_posix()
        map_assets = {name: Path(path).resolve().relative_to(root).as_posix() for name, path in maps.items()}
    except ValueError as exc:
        raise ValueError("Unity FBX, material, and maps must be inside the Unity project") from exc

    editor_dir = root / "Assets/Editor"
    editor_dir.mkdir(parents=True, exist_ok=True)
    script = editor_dir / f"SlopForgeMaterialBuilder_{uuid.uuid4().hex}.cs"
    class_name = script.stem
    quote = json.dumps
    script.write_text(f'''using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

public static class {class_name}
{{
    public static void Build()
    {{
        const string fbxPath = {quote(fbx_asset)};
        const string materialPath = {quote(material_asset)};
        AssetDatabase.Refresh();
        var model = AssetDatabase.LoadAssetAtPath<GameObject>(fbxPath);
        var source = model == null ? null : model.GetComponentsInChildren<Renderer>(true)
            .SelectMany(renderer => renderer.sharedMaterials).FirstOrDefault(material => material != null);
        var sourceName = source == null ? Path.GetFileNameWithoutExtension(fbxPath) + "_PBR" : source.name;
        var sourceId = new AssetImporter.SourceAssetIdentifier(typeof(Material), sourceName);
        var pipeline = GraphicsSettings.currentRenderPipeline;
        var pipelineType = pipeline == null ? null : pipeline.GetType();
        var shaderName = pipeline == null ? "Standard" :
            IsUniversalPipeline(pipelineType) ? "Universal Render Pipeline/Lit" : null;
        if (shaderName == null)
            throw new Exception("Unsupported render pipeline '" + pipelineType.FullName +
                "'. SlopForge materials support the Built-in Render Pipeline and URP.");
        var shader = Shader.Find(shaderName);
        if (shader == null)
            throw new Exception("Lit shader '" + shaderName + "' was not found for the active render pipeline");

        SetImport({quote(map_assets["basecolor"])}, TextureImporterType.Default, true);
        SetImport({quote(map_assets["normal"])}, TextureImporterType.NormalMap, false);
        SetImport({quote(map_assets["metallic_gloss"])}, TextureImporterType.Default, false);
        SetImport({quote(map_assets["emission"])}, TextureImporterType.Default, true);
        var mat = AssetDatabase.LoadAssetAtPath<Material>(materialPath);
        if (mat == null)
        {{
            mat = new Material(shader);
            AssetDatabase.CreateAsset(mat, materialPath);
        }}
        mat.shader = shader;
        mat.name = sourceName;
        SetTexture(mat, "_BaseMap", "_MainTex", {quote(map_assets["basecolor"]) });
        SetTexture(mat, "_BumpMap", "_BumpMap", {quote(map_assets["normal"]) });
        SetTexture(mat, "_MetallicGlossMap", "_MetallicGlossMap", {quote(map_assets["metallic_gloss"]) });
        SetTexture(mat, "_EmissionMap", "_EmissionMap", {quote(map_assets["emission"]) });
        SetFloat(mat, "_Metallic", 1f);
        SetFloat(mat, "_Glossiness", 1f);
        SetFloat(mat, "_Smoothness", 1f);
        SetColor(mat, "_Color", Color.white);
        SetColor(mat, "_BaseColor", Color.white);
        SetColor(mat, "_EmissionColor", Color.white);
        mat.EnableKeyword("_NORMALMAP");
        mat.EnableKeyword("_METALLICGLOSSMAP");
        mat.EnableKeyword("_METALLICSPECGLOSSMAP");
        mat.EnableKeyword("_EMISSION");
        EditorUtility.SetDirty(mat);
        AssetDatabase.SaveAssets();

        var importer = (ModelImporter)AssetImporter.GetAtPath(fbxPath);
        importer.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
        importer.materialSearch = ModelImporterMaterialSearch.Everywhere;
        importer.AddRemap(sourceId, mat);
        importer.SaveAndReimport();
        var imported = AssetDatabase.LoadAssetAtPath<GameObject>(fbxPath);
        var assigned = imported == null ? null : imported.GetComponentsInChildren<Renderer>(true)
            .SelectMany(renderer => renderer.sharedMaterials).FirstOrDefault(candidate => candidate == mat);
        if (assigned == null || GetTexture(assigned, "_BaseMap", "_MainTex") == null ||
            GetTexture(assigned, "_BumpMap") == null || GetTexture(assigned, "_MetallicGlossMap") == null)
            throw new Exception("Unity did not import the FBX with the generated PBR material assigned");
        Debug.Log("SLOPFORGE_MATERIAL_ASSIGNED " + materialPath + " -> " + fbxPath);
    }}

    static bool IsUniversalPipeline(Type type)
    {{
        for (var current = type; current != null; current = current.BaseType)
            if (current.FullName == "UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset") return true;
        return false;
    }}
    static void SetImport(string path, TextureImporterType type, bool srgb)
    {{
        var importer = (TextureImporter)AssetImporter.GetAtPath(path);
        if (importer == null) throw new Exception("Texture did not import: " + path);
        importer.textureType = type;
        importer.sRGBTexture = srgb;
        importer.SaveAndReimport();
    }}
    static void SetTexture(Material mat, string urp, string builtin, string path)
    {{
        var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        if (texture == null) throw new Exception("Texture asset missing: " + path);
        string property = mat.HasProperty(urp) ? urp : builtin;
        if (mat.HasProperty(property)) mat.SetTexture(property, texture);
    }}
    static void SetFloat(Material mat, string property, float value)
    {{ if (mat.HasProperty(property)) mat.SetFloat(property, value); }}
    static void SetColor(Material mat, string property, Color value)
    {{ if (mat.HasProperty(property)) mat.SetColor(property, value); }}
    static Texture GetTexture(Material mat, params string[] properties)
    {{
        foreach (var property in properties)
            if (mat.HasProperty(property) && mat.GetTexture(property) != null) return mat.GetTexture(property);
        return null;
    }}
}}
''')
    try:
        subprocess.run([cli, "run", str(root), "--timeout", "600", "--", "-executeMethod",
                        f"{class_name}.Build"], check=True)
    finally:
        script.unlink(missing_ok=True)
        script.with_suffix(".cs.meta").unlink(missing_ok=True)
