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
from .validation import DARKENED_LIT, MIN_CONCEPT_CHROMA, _lab, _lab_cells, _lightness_cells


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


METAL_LIGHTNESS_GRID = 16  # cells across the object, as one of the dark-texture check's grids
MIN_LIT_METAL_CELLS = 6  # fewer lit metal cells than this is too little metal to judge from the concept's side
MAX_METAL_GAIN = 8.0


def match_metal_lightness(basecolor_path, metallic_path, cutout, base_view, metal_view):
    """Brighten metal whose base colour is darker than the concept shows it; returns the gain applied (1.0: none).

    TRELLIS.2 decoded a pistol's blued steel near-black (0.13 sRGB, about 2% reflectance, less than any metal)
    where the concept showed dark grey, so the slide rendered as a black mirror and three seeds failed the dark-texture
    check (2026-10-24). cutout, base_view and metal_view are RGBA arrays of the concept and of the base colour and
    metallic maps rendered from the concept's fitted view. Each metal cell lit in the concept gives the ratio of the
    concept's luminance to the base colour's; every metal texel is scaled by their median in linear RGB, keeping its
    hue. Metal is never darkened, and iron drawn dark stays dark.
    """
    concept, concept_cover = _lightness_cells(cutout, METAL_LIGHTNESS_GRID)
    texture, texture_cover = _lightness_cells(base_view, METAL_LIGHTNESS_GRID)
    metal, _ = _lightness_cells(metal_view, METAL_LIGHTNESS_GRID)
    lit = concept_cover & texture_cover & (metal > 53.4) & (concept > DARKENED_LIT)  # L* 53.4 is metallic 0.5
    if lit.sum() < MIN_LIT_METAL_CELLS:
        return 1.0
    luminance = lambda lightness: ((lightness + 16) / 116) ** 3
    gain = float(np.clip(np.median(luminance(concept[lit]) / np.maximum(luminance(texture[lit]), 1e-4)),
                         1.0, MAX_METAL_GAIN))
    if gain == 1.0:
        return gain
    with Image.open(basecolor_path) as image:
        mode, pixels = image.mode, np.asarray(image.convert("RGBA"), dtype=float) / 255
    with Image.open(metallic_path) as image:
        metallic = np.asarray(image.convert("L").resize((pixels.shape[1], pixels.shape[0])), dtype=float) / 255
    rgb = pixels[..., :3]
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    linear[metallic > 0.5] = np.clip(linear[metallic > 0.5] * gain, 0, 1)
    pixels[..., :3] = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
    # Brightening reveals tints the decoder left in dark metal (a pistol's serrations came up pink, 2026-10-25):
    # metal keeps no more chroma than the concept's lit metal shows
    concept_lab, _cover, _box = _lab_cells(cutout, METAL_LIGHTNESS_GRID)
    chroma_limit = float(np.median(np.hypot(concept_lab[lit][:, 1], concept_lab[lit][:, 2]))) + 2.0
    metal_texels = metallic > 0.5
    lab = _lab(pixels[..., :3][metal_texels] * 255)
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    over = chroma > chroma_limit
    if over.any():
        lab[over, 1:] *= (chroma_limit / chroma[over])[:, None]
        pixels[..., :3][metal_texels] = _srgb_from_lab(lab) / 255
    Image.fromarray((pixels * 255).round().astype(np.uint8), "RGBA").convert(mode).save(basecolor_path)
    return gain


COLOUR_CLUSTERS = 3  # non-metal colours told apart in a map: a pistol's grips came out as three wood tones
MIN_CLUSTER_CELLS = 4  # concept-side cells a colour needs before its shift is measured
MAX_CHROMA_SHIFT = 25.0  # CIELAB a*b* units; a larger drift is not a tint
BORROW_DISTANCE = 20.0  # a colour too small to measure takes a measured colour's shift only if this close in CIELAB
LIGHTNESS_SHARE = 0.5  # a lit concept is brighter than albedo, so lightness moves half way to it, and never down
MAX_LIGHTNESS_RATIO = 3.0  # a texture decoded darker than a third of the concept's lightness is not a tint


def _srgb_from_lab(lab):
    """sRGB 0-255 of an (..., 3) CIELAB (D65) array, clipped to the gamut."""
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * np.array([0.95047, 1.0, 1.08883])
    linear = np.clip(xyz @ np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415],
                                     [0.0557, -0.2040, 1.0570]]).T, 0, 1)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055) * 255


def match_concept_colours(basecolor_path, metallic_path, cutout, base_view, metal_view, lightness_share=LIGHTNESS_SHARE):
    """Shift each non-metal colour of the base colour map towards the concept's; returns a report per colour.
    lightness_share: how far lightness moves to the concept's (the parts route, whose textures are dark all over,
    moves the whole way).

    TRELLIS.2 decoded a pistol's rosewood grips more orange and darker than drawn on every seed (CIELAB hue angle 43
    against 37, 2026-10-24), and the whole-object colour checks, dominated by the black steel, passed them. Non-metal
    texels are grouped into COLOUR_CLUSTERS colours. Each colour's cells seen from the concept's side (cutout,
    base_view and metal_view are RGBA arrays, as for match_metal_lightness), where it covers most of the cell and the
    concept is chromatic, give the median CIELAB a*b* offset to the concept and lightness ratio. A colour with too
    few cells borrows the nearest measured colour's shift within BORROW_DISTANCE.
    """
    with Image.open(basecolor_path) as image:
        mode, pixels = image.mode, np.asarray(image.convert("RGBA"), dtype=np.float32)
    with Image.open(metallic_path) as image:
        metallic = np.asarray(image.convert("L").resize((pixels.shape[1], pixels.shape[0])), dtype=np.float32) / 255
    nonmetal = (metallic < 0.5) & (pixels[..., :3].max(-1) > 5)
    if nonmetal.sum() < 100:
        return {}
    lab = _lab(pixels[..., :3][nonmetal]).astype(np.float32)
    rng = np.random.default_rng(0)
    centres = lab[rng.choice(len(lab), COLOUR_CLUSTERS, replace=False)] if len(lab) >= COLOUR_CLUSTERS else lab
    sample = lab[rng.choice(len(lab), min(60000, len(lab)), replace=False)]
    for _ in range(20):  # k-means on a sample of the texels
        labels = np.argmin(((sample[:, None] - centres[None]) ** 2).sum(-1), 1)
        centres = np.array([sample[labels == k].mean(0) if (labels == k).any() else centres[k]
                            for k in range(len(centres))])
    nearest = lambda colours: np.argmin(((colours[..., None, :] - centres) ** 2).sum(-1), -1)
    concept, concept_cover, _ = _lab_cells(cutout, METAL_LIGHTNESS_GRID)
    texture, texture_cover, (x0, y0, x1, y1) = _lab_cells(base_view, METAL_LIGHTNESS_GRID)
    seen = (base_view[..., 3] > 200) & (metal_view[..., 0] < 128)
    view_labels = nearest(_lab(base_view[..., :3].reshape(-1, 3)).reshape(*base_view.shape[:2], 3))
    cell_share = lambda mask: np.asarray(Image.fromarray(mask[y0:y1, x0:x1].astype(np.uint8) * 255).resize(
        (METAL_LIGHTNESS_GRID,) * 2, Image.BOX), dtype=float) / 255
    shares = np.stack([cell_share((view_labels == k) & seen) for k in range(len(centres))])
    # A cell counts for its most common colour when it is mostly non-metal: one wood's grain tones each rarely cover
    # most of a cell alone (2026-10-24 pistol: 3, 0 and 2 cells by single-colour majority).
    measurable = (concept_cover & texture_cover & (shares.sum(0) > 0.6)
                  & (np.hypot(concept[..., 1], concept[..., 2]) > MIN_CONCEPT_CHROMA))
    plurality = shares.argmax(0)
    report, shifts = {}, {}
    for k in range(len(centres)):
        cells = measurable & (plurality == k)
        report[k] = {"colour": [round(float(value), 1) for value in centres[k]], "cells": int(cells.sum())}
        if cells.sum() >= MIN_CLUSTER_CELLS:
            shift = np.median(concept[cells][:, 1:] - texture[cells][:, 1:], 0)
            shift *= min(1.0, MAX_CHROMA_SHIFT / max(float(np.hypot(*shift)), 1e-6))
            ratio = float(np.clip(np.median(concept[cells][:, 0] / np.maximum(texture[cells][:, 0], 1)), 1, MAX_LIGHTNESS_RATIO))
            shifts[k] = (shift, ratio)
    labels = nearest(lab)
    for k in report:
        source = k if k in shifts else min(
            (j for j in shifts if np.linalg.norm(centres[j] - centres[k]) <= BORROW_DISTANCE),
            key=lambda j: np.linalg.norm(centres[j] - centres[k]), default=None)
        if source is None:
            continue
        shift, ratio = shifts[source]
        lab[labels == k, 1:] += shift
        lab[labels == k, 0] = np.clip(lab[labels == k, 0] * (1 + lightness_share * (ratio - 1)), 0, 100)
        report[k].update({"shift_ab": [round(float(value), 1) for value in shift],
                          "lightness": round(1 + lightness_share * (ratio - 1), 3), "from": source})
    if any("shift_ab" in entry for entry in report.values()):
        pixels[..., :3][nonmetal] = _srgb_from_lab(lab)
        Image.fromarray(pixels.round().clip(0, 255).astype(np.uint8), "RGBA").convert(mode).save(basecolor_path)
    return report


def glass_material_path(material):
    """The Unity material for a prop's declared glass faces, next to its main material."""
    material = Path(material)
    return material.with_name(material.stem + "_Glass.mat")


def build_unity_material(project_root, fbx, material, maps, render=None, lightmap_uvs=False):
    """Import the FBX with a generated Lit material; with render, also save four URP views to that PNG.

    lightmap_uvs asks Unity to generate the lightmap UV set (uv2): static props are lightmapped, held weapons never.

    Returns Unity's import record: per role (fbx, material, each map) its path, GUID, importer type, a hash
    of the importer settings and the file hash, plus the GUID of each texture the material references.
    """
    root = Path(project_root).resolve()
    cli = unity_cli(root)
    with Image.open(maps["basecolor"]) as image:
        # Declared glass is the only source of base colour alpha (apply_glass).
        transparent = "A" in image.getbands() and image.getchannel("A").getextrema()[0] < 255
        max_size = max(32, *image.size)  # the importer's ceiling: Unity's default of 2048 would halve a 4096 map

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

        SetImport({quote(map_assets["basecolor"])}, TextureImporterType.Default, true, {max_size}, {str(transparent).lower()});
        SetImport({quote(map_assets["normal"])}, TextureImporterType.NormalMap, false, {max_size});
        SetImport({quote(map_assets["metallic_gloss"])}, TextureImporterType.Default, false, {max_size});
        SetImport({quote(map_assets["emission"])}, TextureImporterType.Default, true, {max_size});
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
        importer.generateSecondaryUV = {'true' if lightmap_uvs else 'false'};
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
    static void SetImport(string path, TextureImporterType type, bool srgb, int maxSize, bool alpha = false)
    {{
        var importer = (TextureImporter)AssetImporter.GetAtPath(path);
        if (importer == null) throw new Exception("Texture did not import: " + path);
        importer.textureType = type;
        importer.sRGBTexture = srgb;
        importer.alphaIsTransparency = alpha;
        importer.maxTextureSize = maxSize;  // Unity's default of 2048 would halve a 4096 map
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


# ---------------------------------------------------------------------------
# Maps for a weapon generated as parts (OmniPart gives base colour only)
# ---------------------------------------------------------------------------

FINISH_ROUGHNESS = {"matte": 0.7, "satin": 0.55, "polished": 0.25}  # a brief's finish word; satin is blued steel


def finish_word(materials):
    """The first finish word (polished, satin, matte) in a declared metal's description; satin when none."""
    import re
    for item in materials or []:
        if item.get("class") == "metal":
            found = re.search(r"\b(polished|satin|matte)\b", (item.get("description") or "").lower())
            if found:
                return found.group(1)
    return "satin"


def _words(text):
    import re
    return [word for word in re.findall(r"[a-z]+", (text or "").lower()) if len(word) >= 3]


def _names_part(region_words, part):
    """Whether a declared region's words name a part: its "grips" for a "grip", or "stock" in "the pistol grip of the
    stock"."""
    own = {part["name"].lower(), *_words(part.get("text"))}
    return any(word.startswith(part["name"].lower()) or part["name"].lower().startswith(word) or word in own
               for word in region_words)


def concept_part_colours(materials, parts, masks_dir, cutout):
    """The declared materials, a non-metal without a colour given the median colour of the concept's coloured pixels
    under the mask of the part its region names. Declared non-metals are kept off metal by their colour
    (zero_metallic); a pistol's grips declared as plain "walnut wood" had none, the generated metallic map called the
    whole pistol metal, and the metal steps greyed the grips (2026-10-25)."""
    if not masks_dir or not cutout or not Path(cutout).is_file():
        return list(materials or [])
    with Image.open(cutout) as image:
        concept = np.asarray(image.convert("RGBA"), dtype=float)
    coloured = []
    for item in materials or []:
        item = dict(item)
        if item.get("class") == "nonmetal" and not item.get("color"):
            for part in parts or []:
                mask_path = Path(masks_dir) / f"{part['name']}.png"
                if not _names_part(_words(item.get("region")), part) or not mask_path.is_file():
                    continue
                with Image.open(mask_path) as image:
                    mask = np.asarray(image.convert("L").resize(concept.shape[1::-1]), dtype=float) > 127
                pixels = concept[mask & (concept[..., 3] > 200)][:, :3]
                pixels = pixels[(pixels.max(1) - pixels.min(1)) > 40]  # its colour, not the steel under the mask
                if len(pixels):
                    item["color"] = "#%02x%02x%02x" % tuple(int(v) for v in np.median(pixels, 0))
                    item["color_source"] = f"concept under the {part['name']} mask"
                    break
        coloured.append(item)
    return coloured


def part_metal(parts, materials):
    """Each part's metallic value: 0 when a declared non-metal's region names it (its "grips" for a "grip", or
    "stock" in "the pistol grip of the stock"), else 1 when the brief declares any metal, else 0."""
    nonmetal = [word for item in materials or [] if item.get("class") == "nonmetal" for word in _words(item.get("region"))]
    default = 1 if any(item.get("class") == "metal" for item in materials or []) else 0
    return {part["name"]: 0 if _names_part(nonmetal, part) else default for part in parts}


def derive_part_maps(atlas, metal, finish, out_dir, normal=None):
    """basecolor (the atlas), the baked tangent normal (flat when none), a constant roughness from the finish
    word, and metallic from the metallic atlas thresholded at 0.5; returns the four paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {key: out_dir / f"{key}.png" for key in ("basecolor", "normal", "roughness", "metallic")}
    with Image.open(atlas) as image:
        size = image.size
        pixels = np.asarray(image.convert("RGB")).copy()
    # Unused atlas texels are exact black and darken every island's edge at the smaller mips: the median used
    # colour instead (a generated texel is never exactly black)
    unused = pixels.sum(-1) == 0
    if unused.any() and not unused.all():
        pixels[unused] = np.median(pixels[~unused], axis=0).astype(np.uint8)
    Image.fromarray(pixels).save(paths["basecolor"])
    if normal is not None:
        shutil.copy2(normal, paths["normal"])
    else:
        Image.new("RGB", size, (128, 128, 255)).save(paths["normal"])
    Image.new("RGB", size, (round(FINISH_ROUGHNESS.get(finish, FINISH_ROUGHNESS["satin"]) * 255),) * 3).save(paths["roughness"])
    with Image.open(metal) as image:
        image.convert("L").point(lambda value: 255 if value >= 128 else 0).convert("RGB").save(paths["metallic"])
    return paths
