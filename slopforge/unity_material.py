import json
import shutil
import subprocess
import tempfile
import uuid
from itertools import accumulate
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageFilter
from .failures import StageFailure
from .provenance import file_sha256


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


def emitter_colour_mask(base, match):
    """One target's colour-rule mask ("L") on an RGB image, opened so small flecks drop out.

    match None means large pale near-neutral regions clearly paler than most of the map (paper); otherwise
    texels within a small colour distance of match.
    """
    size = max(3, round(15 * base.width / 2048) | 1)  # odd kernel, 15 px at 2048
    if match is None:
        r, g, b = base.split()
        low = ImageChops.darker(ImageChops.darker(r, g), b)
        high = ImageChops.lighter(ImageChops.lighter(r, g), b)
        # TRELLIS.2 bakes pale paper anywhere from ~157 to ~254 depending on the seed; 1.3x the map's
        # median keeps a body as pale as the paper from glowing with it (docs/MATERIALS.md, Known limits).
        counts = list(accumulate(low.histogram()))
        # Capped at 225: when paper is most of the map the median is the paper itself (a lampshade).
        cut = min(225, max(150, 1.3 * next(v for v, count in enumerate(counts) if 2 * count >= counts[-1])))
        mask = ImageChops.multiply(low.point(lambda v: 255 if v >= cut else 0),
                                   ImageChops.subtract(high, low).point(lambda v: 255 if v <= 25 else 0))
    else:
        distance = ImageChops.difference(base, Image.new("RGB", base.size, tuple(match)))
        mask = ImageChops.lighter(ImageChops.lighter(*distance.split()[:2]), distance.split()[2])
        mask = mask.point(lambda v: 255 if v <= 48 else 0)
    return mask.filter(ImageFilter.MinFilter(size)).filter(ImageFilter.MaxFilter(size))


def derive_emission(basecolor_path, destination, targets=((None, (255, 178, 102)),), extra_masks=None):
    """Emission for declared glowing regions, found in the generated base color map.

    Each target is (match_rgb, glow_rgb), found by emitter_colour_mask. extra_masks, one per target or None,
    adds texels found another way (the concept's emitter carried onto the texture, slopforge/emitters.py).
    Returns the smallest target's fraction of the map, so one emitter that was found cannot hide another
    declared one that is missing.
    """
    with Image.open(basecolor_path) as image:
        base = image.convert("RGB")
    size = max(3, round(15 * base.width / 2048) | 1)
    emission, fractions = Image.new("RGB", base.size), []
    for index, (match, glow) in enumerate(targets):
        mask = emitter_colour_mask(base, match)
        if extra_masks and extra_masks[index] is not None:
            mask = ImageChops.lighter(mask, extra_masks[index].convert("L").resize(base.size))
        fractions.append(sum(mask.histogram()[128:]) / (base.width * base.height))
        soft = mask.filter(ImageFilter.GaussianBlur(max(1, size // 5)))
        emission = Image.composite(Image.new("RGB", base.size, tuple(glow)), emission, soft)
    emission.save(destination)
    return min(fractions)


GLASS_ALPHA = 0.35  # see-through, yet still reads as a surface
GLASS_ROUGHNESS = 0.05


def glass_mask(base, match):
    """Texels of one declared glass region ("L" mask): its tint's hue at any lightness, or the pale region.

    Tinted glass bakes with dark shading: on the 2026-10-22 bottle the colour-distance rule found 44% of its
    texels and left the body blotchy, while the tint's hue (emitters.HUE_TOLERANCE, MIN_SATURATION) found 84%.
    """
    if match is None:
        return emitter_colour_mask(base, None)
    from .emitters import HUE_TOLERANCE, MIN_SATURATION
    hsv = np.asarray(base.convert("HSV"), dtype=float)
    tint = Image.new("RGB", (1, 1), tuple(match)).convert("HSV").getpixel((0, 0))
    hue = np.abs((hsv[..., 0] - tint[0] + 128) % 256 - 128) * 360 / 256
    return Image.fromarray(((hue <= HUE_TOLERANCE) & (hsv[..., 1] >= MIN_SATURATION * 255)).astype(np.uint8) * 255)


def apply_glass(basecolor_path, roughness_path, metallic_path, matches):
    """Make declared glass regions see-through, smooth and non-metallic in the maps; returns the share found.

    TRELLIS.2 reconstructs glass drawn as a solid tinted surface as an opaque surface (2026-10-22 bottle and
    lantern globe). Each match is the glass's concept colour, or None for clear glass (glass_mask). Glass texels
    get alpha GLASS_ALPHA in the base colour.
    """
    with Image.open(basecolor_path) as image:
        base = image.convert("RGB")
    mask = Image.new("L", base.size, 0)
    for match in matches:
        mask = ImageChops.lighter(mask, glass_mask(base, match))
    base.putalpha(mask.point(lambda value: 255 - round(value * (1 - GLASS_ALPHA))))
    base.save(basecolor_path)
    for path, value in ((roughness_path, round(255 * GLASS_ROUGHNESS)), (metallic_path, 0)):
        with Image.open(path) as image:
            mode, channel = image.mode, image.convert("L")
        channel.paste(value, mask=mask)
        channel.convert(mode).save(path)
    return sum(mask.histogram()[128:]) / (base.width * base.height)


def zero_metallic(basecolor_path, metallic_path, matches):
    """Zero the metallic map where the base colour matches a declared non-metal's colour; returns the share found.

    A brief that declares metal keeps the generator's metallic map, and TRELLIS.2 decodes glossy non-metals as partly
    metallic (docs/MATERIALS.md, Glossy non-metals): a weapon's leather grip or walnut stock would shine like steel.
    """
    with Image.open(basecolor_path) as image:
        base = image.convert("RGB")
    mask = Image.new("L", base.size, 0)
    for match in matches:
        mask = ImageChops.lighter(mask, emitter_colour_mask(base, match))
    with Image.open(metallic_path) as image:
        mode, channel = image.mode, image.convert("L")
    channel.paste(0, mask=mask)
    channel.convert(mode).save(metallic_path)
    return sum(mask.histogram()[128:]) / (base.width * base.height)


def glass_material_path(material):
    """The Unity material for a prop's declared glass faces, next to its main material."""
    material = Path(material)
    return material.with_name(material.stem + "_Glass.mat")


def build_unity_material(project_root, fbx, material, maps, render=None):
    """Import the FBX with a generated Lit material; with render, also save four URP views to that PNG.

    Returns Unity's import record: per role (fbx, material, each map) its path, GUID, importer type, a hash
    of the importer settings and the file hash, plus the GUID of each texture the material references.
    """
    root = Path(project_root).resolve()
    cli = unity_cli(root)
    with Image.open(maps["basecolor"]) as image:
        # Declared glass is the only source of base colour alpha (apply_glass).
        transparent = "A" in image.getbands() and image.getchannel("A").getextrema()[0] < 255

    fbx = Path(fbx).resolve()
    material = Path(material).resolve()
    try:
        fbx_asset = fbx.relative_to(root).as_posix()
        material_asset = material.relative_to(root).as_posix()
        glass_asset = glass_material_path(material).relative_to(root).as_posix()
        map_assets = {name: Path(path).resolve().relative_to(root).as_posix() for name, path in maps.items()}
    except ValueError as exc:
        raise ValueError("Unity FBX, material, and maps must be inside the Unity project") from exc

    editor_dir = root / "Assets/Editor"
    editor_dir.mkdir(parents=True, exist_ok=True)
    script = editor_dir / f"SlopForgeMaterialBuilder_{uuid.uuid4().hex}.cs"
    class_name = script.stem
    scratch = tempfile.TemporaryDirectory(prefix="slopforge-unity-")
    report_path = Path(scratch.name) / "import.json"
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
        const string reportPath = {quote(str(report_path))};
        const string glassPath = {quote(glass_asset)};
        AssetDatabase.Refresh();
        var model = AssetDatabase.LoadAssetAtPath<GameObject>(fbxPath);
        var sources = model == null ? new Material[0] : model.GetComponentsInChildren<Renderer>(true)
            .SelectMany(renderer => renderer.sharedMaterials).Where(material => material != null).ToArray();
        var source = sources.FirstOrDefault(material => !material.name.EndsWith("_Glass"));
        var glassSource = sources.FirstOrDefault(material => material.name.EndsWith("_Glass"));
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

        SetImport({quote(map_assets["basecolor"])}, TextureImporterType.Default, true, {str(transparent).lower()});
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
        // URP's material validation sets _EMISSION from these flags; a new material starts EmissiveIsBlack.
        mat.globalIlluminationFlags = MaterialGlobalIlluminationFlags.BakedEmissive;
        mat.EnableKeyword("_EMISSION");
        EditorUtility.SetDirty(mat);
        Material glass = null;
        if ({str(transparent).lower()})
        {{
            // Declared glass: its faces carry their own FBX material; it shares the maps and draws transparent.
            if (glassSource == null)
                throw new Exception("The base colour marks glass, but the FBX has no _Glass material for it");
            glass = AssetDatabase.LoadAssetAtPath<Material>(glassPath);
            if (glass == null)
            {{
                glass = new Material(shader);
                AssetDatabase.CreateAsset(glass, glassPath);
            }}
            glass.shader = shader;
            glass.CopyPropertiesFromMaterial(mat);
            glass.name = glassSource.name;
            SetTransparent(glass);
            EditorUtility.SetDirty(glass);
        }}
        AssetDatabase.SaveAssets();

        var importer = (ModelImporter)AssetImporter.GetAtPath(fbxPath);
        importer.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
        importer.materialSearch = ModelImporterMaterialSearch.Everywhere;
        importer.AddRemap(sourceId, mat);
        if (glass != null)
            importer.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), glassSource.name), glass);
        importer.SaveAndReimport();
        var imported = AssetDatabase.LoadAssetAtPath<GameObject>(fbxPath);
        var assigned = imported == null ? null : imported.GetComponentsInChildren<Renderer>(true)
            .SelectMany(renderer => renderer.sharedMaterials).FirstOrDefault(candidate => candidate == mat);
        if (assigned == null || GetTexture(assigned, "_BaseMap", "_MainTex") == null ||
            GetTexture(assigned, "_BumpMap") == null || GetTexture(assigned, "_MetallicGlossMap") == null)
            throw new Exception("Unity did not import the FBX with the generated PBR material assigned");
        if (!assigned.IsKeywordEnabled("_EMISSION"))
            throw new Exception("Unity disabled emission on the generated material; its emission map would not render");
        if (glass != null && !imported.GetComponentsInChildren<Renderer>(true).SelectMany(renderer => renderer.sharedMaterials)
                .Any(candidate => candidate == glass && candidate.renderQueue >= (int)RenderQueue.Transparent))
            throw new Exception("Unity did not assign the transparent glass material; the glass would render opaque");
        Debug.Log("SLOPFORGE_MATERIAL_ASSIGNED " + materialPath + " -> " + fbxPath);
        File.WriteAllText(reportPath, JsonUtility.ToJson(new Report {{
            unity_version = Application.unityVersion,
            assets = new[] {{ Describe("fbx", fbxPath), Describe("material", materialPath),{' Describe("glass_material", glassPath),' if transparent else ''}
                {", ".join(f'Describe("{name}", {quote(map_assets[name])})' for name in ("basecolor", "normal", "metallic_gloss", "emission"))} }},
            material_textures = new[] {{ Reference(mat, "basecolor", "_BaseMap", "_MainTex"),
                Reference(mat, "normal", "_BumpMap"), Reference(mat, "metallic_gloss", "_MetallicGlossMap"),
                Reference(mat, "emission", "_EmissionMap") }} }}));
        {f"RenderViews(imported, {quote(str(Path(render).resolve()))});" if render else ""}
    }}

    static void RenderViews(GameObject model, string path)
    {{
        UnityEditor.SceneManagement.EditorSceneManager.NewScene(
            UnityEditor.SceneManagement.NewSceneSetup.DefaultGameObjects, UnityEditor.SceneManagement.NewSceneMode.Single);
        DynamicGI.UpdateEnvironment();
        var instance = (GameObject)PrefabUtility.InstantiatePrefab(model);
        var renderers = instance.GetComponentsInChildren<Renderer>();
        var bounds = renderers[0].bounds;
        foreach (var renderer in renderers) bounds.Encapsulate(renderer.bounds);
        var camera = Camera.main;
        var light = UnityEngine.Object.FindAnyObjectByType<Light>();
        camera.clearFlags = CameraClearFlags.SolidColor;
        camera.backgroundColor = new Color(0.32f, 0.33f, 0.35f);
        camera.fieldOfView = 30f;
        var distance = bounds.extents.magnitude / Mathf.Sin(camera.fieldOfView * 0.5f * Mathf.Deg2Rad) * 1.05f;
        camera.nearClipPlane = distance * 0.01f;
        camera.farClipPlane = distance * 4f;
        const int size = 768;
        var target = new RenderTexture(size, size, 24);
        camera.targetTexture = target;
        var strip = new Texture2D(size * 4, size, TextureFormat.RGB24, false);
        for (var view = 0; view < 4; view++)
        {{
            var rotation = Quaternion.Euler(20f, 35f + 90f * view, 0f);
            camera.transform.SetPositionAndRotation(bounds.center - rotation * Vector3.forward * distance, rotation);
            light.transform.rotation = rotation * Quaternion.Euler(25f, -35f, 0f);
            camera.Render();
            RenderTexture.active = target;
            strip.ReadPixels(new Rect(0, 0, size, size), size * view, 0);
            RenderTexture.active = null;
        }}
        strip.Apply();
        File.WriteAllBytes(path, strip.EncodeToPNG());
        Debug.Log("SLOPFORGE_UNITY_RENDER " + path);
    }}

    [Serializable] public class Entry {{ public string role, path, guid, importer, settings_sha256; }}
    [Serializable] public class Report {{ public string unity_version; public Entry[] assets, material_textures; }}

    static Entry Describe(string role, string path)
    {{
        var importer = AssetImporter.GetAtPath(path);
        if (importer == null) throw new Exception("Unity has no importer for " + path);
        using (var sha = System.Security.Cryptography.SHA256.Create())
        {{
            var settings = sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(EditorJsonUtility.ToJson(importer)));
            return new Entry {{ role = role, path = path, guid = AssetDatabase.AssetPathToGUID(path),
                importer = importer.GetType().Name,
                settings_sha256 = BitConverter.ToString(settings).Replace("-", "").ToLowerInvariant() }};
        }}
    }}
    static Entry Reference(Material mat, string role, params string[] properties)
    {{
        var texture = GetTexture(mat, properties);
        var path = texture == null ? "" : AssetDatabase.GetAssetPath(texture);
        return new Entry {{ role = role, path = path, guid = path == "" ? "" : AssetDatabase.AssetPathToGUID(path) }};
    }}

    static bool IsUniversalPipeline(Type type)
    {{
        for (var current = type; current != null; current = current.BaseType)
            if (current.FullName == "UnityEngine.Rendering.Universal.UniversalRenderPipelineAsset") return true;
        return false;
    }}
    static void SetImport(string path, TextureImporterType type, bool srgb, bool alpha = false)
    {{
        var importer = (TextureImporter)AssetImporter.GetAtPath(path);
        if (importer == null) throw new Exception("Texture did not import: " + path);
        importer.textureType = type;
        importer.sRGBTexture = srgb;
        importer.alphaIsTransparency = alpha;
        importer.SaveAndReimport();
    }}
    static void SetTransparent(Material mat)
    {{
        // Only glass faces use this material, so the usual transparent setup (no depth writes) sorts correctly.
        SetFloat(mat, "_Surface", 1f);
        SetFloat(mat, "_Blend", 0f);
        SetFloat(mat, "_ZWrite", 0f);
        SetFloat(mat, "_SrcBlend", (float)BlendMode.SrcAlpha);
        SetFloat(mat, "_DstBlend", (float)BlendMode.OneMinusSrcAlpha);
        SetFloat(mat, "_SrcBlendAlpha", (float)BlendMode.One);
        SetFloat(mat, "_DstBlendAlpha", (float)BlendMode.OneMinusSrcAlpha);
        SetFloat(mat, "_Mode", 3f);  // Built-in Standard: Transparent
        mat.SetOverrideTag("RenderType", "Transparent");
        mat.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
        mat.renderQueue = (int)RenderQueue.Transparent;
        // URP's own keyword setup, when its editor assembly is present; reflection keeps Built-in projects compiling.
        var gui = Type.GetType("UnityEditor.Rendering.Universal.ShaderGUI.BaseShaderGUI, Unity.RenderPipelines.Universal.Editor");
        var setup = gui == null ? null : gui.GetMethod("SetMaterialKeywords",
            new[] {{ typeof(Material), typeof(Action<Material>), typeof(Action<Material>) }});
        if (setup != null) setup.Invoke(null, new object[] {{ mat, null, null }});
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
    with scratch:
        try:
            subprocess.run([cli, "run", str(root), "--timeout", "600", "--", "-executeMethod",
                            f"{class_name}.Build"], check=True)
        finally:
            script.unlink(missing_ok=True)
            script.with_suffix(".cs.meta").unlink(missing_ok=True)
        report = json.loads(report_path.read_text())
    return _import_record(root, report)


def _import_record(root, report):
    assets = {item["role"]: {"path": item["path"], "guid": item["guid"], "importer": item["importer"],
                             "settings_sha256": item["settings_sha256"], "sha256": file_sha256(root / item["path"])}
              for item in report["assets"]}
    textures = {item["role"]: item["guid"] for item in report["material_textures"]}
    wrong = sorted(role for role, guid in textures.items() if not guid or guid != assets[role]["guid"])
    if wrong or not all(entry["guid"] for entry in assets.values()):
        raise StageFailure("processing_validation",
                           f"Unity import is inconsistent: the material does not reference the published "
                           f"{', '.join(wrong) or 'assets'} or an asset has no GUID", operation="unity_import",
                           remedy="open the project in Unity, check the Console for import errors, and approve again")
    return {"unity_version": report["unity_version"], "assets": assets, "material_textures": textures}
