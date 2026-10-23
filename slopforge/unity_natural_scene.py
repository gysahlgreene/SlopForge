"""Render a recipe's scene in Unity: plan it (``scene``), build the plants it names, then build, light, bake and render
it with a generated editor script. Writes stills, flythrough frames and, with ffmpeg, an MP4 and a GIF."""
import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from . import scene as planner
from .manifest import asset_key
from .unity_material import unity_cli
from .unity_scene import OPEN_SIDE_YAW
from .vegetation import is_current, make_vegetation


def _child(manifest, recipe_asset, child_id):
    stage = recipe_asset["recipe_instance"]["stages"].get(child_id)
    asset = manifest["assets"].get((stage or {}).get("asset_key"))
    if not asset or asset.get("status") != "ready":
        raise ValueError(f"Scene child {child_id!r} is not approved; approve it (and publish 3D children with "
                         "approve-texture) before scene-render")
    return asset


def _model_fbx(manifest, recipe_asset, child_id):
    asset = _child(manifest, recipe_asset, child_id)
    fbx = asset.get("unity_import", {}).get("assets", {}).get("fbx", {}).get("path")
    if not fbx:
        raise ValueError(f"Scene model {child_id!r} is not published to Unity; run approve-texture first")
    return fbx


def blade_palette(basecolor, destination, columns=16, seed=3):
    """Blade colours from the base layer's texture: each column fades from a darker base to a lighter tip, and every
    fifth column is a dry blade."""
    with Image.open(basecolor) as image:
        pixels = np.asarray(image.convert("RGB").resize((256, 256))).reshape(-1, 3).astype(np.float64)
    luminance = pixels @ [0.2126, 0.7152, 0.0722]
    green = pixels[(pixels[:, 1] > pixels[:, 0] * 1.05) & (luminance > np.percentile(luminance, 30))]
    if not len(green):
        green = pixels
    picks = green[np.random.default_rng(seed).choice(len(green), columns)]
    palette = np.zeros((64, columns, 3))
    for c in range(columns):
        base, tip = picks[c] * 0.45, np.minimum(picks[c] * 1.35 + [12, 10, 0], 255)
        if c % 5 == 4:
            base, tip = np.array([80, 75, 45]), np.array([190, 170, 110])
        for row in range(64):
            palette[row, c] = base + (tip - base) * row / 63
    Image.fromarray(palette[::-1].round().astype(np.uint8)).resize((64, 256), Image.NEAREST).save(destination)


def render_scene(root, config, manifest, run, *, frames=True):
    """Plan and render the scene of recipe run ``run``; returns Unity's report with the written files.

    The render is built in ``scenes/<run>.partial`` and replaces ``scenes/<run>`` only when Unity finishes with no
    errors; the render it replaces moves to ``scenes/<run>.previous``. A failed render stays in ``.partial``."""
    root = Path(root).resolve()
    recipe_asset = manifest["assets"].get(asset_key("recipe", run))
    if not recipe_asset or "recipe_instance" not in recipe_asset:
        raise KeyError(f"No recipe run named {run!r}")
    instance = recipe_asset["recipe_instance"]
    # Layout, cameras and light come from the project's recipe file, so they can change after the children exist
    # (2026-10-23: the arch's turn was wrong for its regenerated mesh); the run's own copy if the file is gone.
    recipe_file = root / instance.get("definition_path", "")
    from_file = bool(instance.get("definition_path")) and recipe_file.is_file()
    definition = yaml.safe_load(recipe_file.read_text()) if from_file else instance["definition"]
    if "scene" not in definition:
        raise ValueError(f"Recipe {definition.get('id')!r} has no scene block")
    scene = copy.deepcopy(definition["scene"])
    planner.validate_scene(scene, instance["stages"].keys())
    output_root = config["asset_pipeline"]["output_root"]
    generated = root / output_root / "Scenes" / run
    generated.mkdir(parents=True, exist_ok=True)
    final_dir = root / "ai/assets/scenes" / run
    out_dir = final_dir.with_name(f"{run}.partial")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "stills").mkdir(parents=True)

    plants = {}
    for plant, spec in scene.get("plants", {}).items():
        name = f"{run}_{plant}"
        record = manifest["assets"].get(asset_key("vegetation", name))
        bark = _child(manifest, recipe_asset, spec["bark"])["name"]
        foliage = [_child(manifest, recipe_asset, f)["name"] for f in spec["foliage"]]
        if not record or not is_current(root, manifest, record, spec["species"], spec["height"], spec["seed"], bark,
                                        foliage):
            record = make_vegetation(root, config, manifest, name, spec["species"], spec["height"], spec["seed"], bark,
                                     foliage)
        plants[plant] = record

    terrain = planner.Terrain(scene)
    weights = planner.layer_weights(scene, terrain, size=terrain.res - 1)
    rng = np.random.default_rng(scene.get("seed", 1))
    placements = planner.scatter(scene, terrain, rng)
    for item in placements:
        item["fbx"] = plants[item["asset"]]["outputs"]["fbx"] if item["asset"] in plants else \
            _model_fbx(manifest, recipe_asset, item["asset"])
    cover = planner.cover(scene, terrain, weights, rng)
    grass = planner.grass_density(scene, terrain, weights)
    structures = planner.structures(scene, terrain, rng)
    for structure in structures:
        for group in ("pieces", "rubble", "props"):
            for item in structure[group]:
                item["fbx"] = _model_fbx(manifest, recipe_asset, item["model"])
    layers = []
    for layer in scene["terrain"]["layers"]:
        surface = _child(manifest, recipe_asset, layer["surface"])["outputs"]
        with Image.open(root / surface["tiling_roughness"]) as image:
            roughness = np.asarray(image.convert("L")).mean() / 255
        layers.append({"albedo": surface["tiling_basecolor"], "normal": surface["tiling_normal"],
                       "tile": layer["tile"], "smoothness": float(1 - roughness)})
    if grass:
        surfaces = [layer["surface"] for layer in scene["terrain"]["layers"]]
        source = layers[surfaces.index(scene["grass"].get("layer", surfaces[0]))]["albedo"]
        blade_palette(root / source, generated / "blade_palette.png")
    lighting = scene.get("lighting", {})
    sun, sky, fog = lighting.get("sun", {}), lighting.get("sky", {}), lighting.get("fog", {})
    grade, ao, gi = lighting.get("grade", {}), lighting.get("ambient_occlusion", {}), lighting.get("gi", {})
    flight = planner.flythrough(scene, terrain) if frames else []

    with tempfile.TemporaryDirectory(prefix="slopforge-scene-") as scratch:
        scratch = Path(scratch)
        terrain.heights.astype(np.float32).tofile(scratch / "heights.raw")
        weights.astype(np.float32).tofile(scratch / "weights.raw")
        if grass:
            grass["density"].tofile(scratch / "grass.raw")
        request = {
            "size": terrain.size, "height": terrain.height, "res": terrain.res, "splat_res": weights.shape[0],
            "layer_count": len(layers), "heights_path": str(scratch / "heights.raw"),
            "weights_path": str(scratch / "weights.raw"), "layers": layers,
            "plants": [{"name": name, "fbx": record["outputs"]["fbx"], "bark": record["outputs"]["bark_basecolor"],
                        "bark_normal": record["outputs"]["bark_normal"], "leaves": record["outputs"]["leaves"],
                        "shrub": scene["plants"][name]["species"] == "shrub"} for name, record in plants.items()],
            "placements": placements,
            "structures": structures,
            "cover": [{"texture": _child(manifest, recipe_asset, group["foliage"])["outputs"]["image"],
                       "aspect": group["aspect"], "items": [value for item in group["items"] for value in item]}
                      for group in cover],
            "grass": bool(grass), "grass_path": str(scratch / "grass.raw") if grass else "",
            "grass_origin": grass["origin"] if grass else [0, 0], "grass_cell": grass["cell"] if grass else 0,
            "grass_size": grass["size"] if grass else 0,
            "palette": (generated / "blade_palette.png").relative_to(root).as_posix() if grass else "",
            "generated": (generated).relative_to(root).as_posix(),
            "scene_path": f"{output_root}/Scenes/{run}.unity",
            "stills": planner.stills(scene, terrain), "frames": flight,
            "out_dir": str(out_dir), "still_size": list(planner.STILL_SIZE), "frame_size": list(planner.FRAME_SIZE),
            "sun_pitch": sun.get("pitch", 35), "sun_yaw": sun.get("yaw", 35), "sun_colour": sun.get("colour", [1, 1, 1]),
            "sun_intensity": sun.get("intensity", 1.5), "sky_tint": sky.get("tint", [0.5, 0.5, 0.5]),
            "sky_ground": sky.get("ground", [0.37, 0.35, 0.34]), "sky_thickness": sky.get("thickness", 1.0),
            "sky_exposure": sky.get("exposure", 1.3), "fog": bool(fog), "fog_start": fog.get("start", 50),
            "fog_end": fog.get("end", 300), "fog_colour": fog.get("colour", [0.7, 0.75, 0.8]),
            "grade_exposure": grade.get("exposure", 0), "grade_contrast": grade.get("contrast", 0),
            "grade_saturation": grade.get("saturation", 0), "grade_temperature": grade.get("temperature", 0),
            "grade_tint": grade.get("tint", 0), "bloom": grade.get("bloom", 0), "vignette": grade.get("vignette", 0),
            "ao": bool(ao), "ao_intensity": ao.get("intensity", 0.4), "ao_radius": ao.get("radius", 0.3),
            "ao_direct": ao.get("direct", 0.25), "gi": bool(gi), "probe_spacing": gi.get("probe_spacing", 3.0),
            "sky_occlusion": bool(gi.get("sky_occlusion", False)),
        }
        (scratch / "request.json").write_text(json.dumps(request))
        editor = root / "Assets/Editor"
        editor.mkdir(parents=True, exist_ok=True)
        class_name = f"SlopForgeNaturalScene_{uuid.uuid4().hex}"
        script = editor / f"{class_name}.cs"
        script.write_text(_SCRIPT.replace("CLASS_NAME", class_name).replace("OPEN_SIDE_YAW\n", OPEN_SIDE_YAW)
                          .replace("REQUEST_PATH", json.dumps(str(scratch / "request.json"))))
        started = time.monotonic()
        try:
            subprocess.run([unity_cli(root), "run", str(root), "--timeout", "3600", "--", "-executeMethod",
                            f"{class_name}.Build"], check=True)
        finally:
            script.unlink(missing_ok=True)
            script.with_suffix(".cs.meta").unlink(missing_ok=True)
        report = json.loads((out_dir / "report.json").read_text())
    report["seconds"] = round(time.monotonic() - started)
    if flight and shutil.which("ffmpeg"):
        fps = scene["cameras"]["flythrough"]["fps"]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i",
                        str(out_dir / "frames/frame_%04d.png"), "-c:v", "libx264", "-preset", "slow", "-pix_fmt",
                        "yuv420p", "-crf", "26", "-movflags", "+faststart", str(out_dir / "flythrough.mp4")], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i",
                        str(out_dir / "frames/frame_%04d.png"), "-vf",
                        "fps=10,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];"
                        "[b][p]paletteuse=dither=bayer:bayer_scale=3", str(out_dir / "flythrough.gif")], check=True)
        report["video"] = (out_dir / "flythrough.mp4").relative_to(root).as_posix()
    elif flight:
        report.setdefault("warnings", []).append("ffmpeg is not installed: frames were written but not encoded")
    report["scene_source"] = instance["definition_path"] if from_file else "recipe run"
    report["scene_sha256"] = hashlib.sha256(json.dumps(scene, sort_keys=True).encode()).hexdigest()
    report["planned"] = {"placements": len(placements), "cover": sum(len(g["items"]) for g in cover),
                         "structures": len(structures), "plants": sorted(plants)}
    if not report["errors"]:
        previous = final_dir.with_name(f"{run}.previous")
        if final_dir.exists():
            if previous.exists():
                shutil.rmtree(previous)
            final_dir.rename(previous)
        out_dir.rename(final_dir)
        out_dir = final_dir
    report["stills"] = [(out_dir / "stills" / Path(path).name).relative_to(root).as_posix() for path in report["stills"]]
    if report.get("video"):
        report["video"] = (out_dir / "flythrough.mp4").relative_to(root).as_posix()
    report["report"] = (out_dir / "report.json").relative_to(root).as_posix()
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


_SCRIPT = r'''using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

public static class CLASS_NAME
{
    [Serializable] public class Layer { public string albedo, normal; public float tile, smoothness; }
    [Serializable] public class Plant { public string name, fbx, bark, bark_normal, leaves; public bool shrub; }
    [Serializable] public class Placement { public string fbx; public float x, z, yaw, scale, sink; }
    [Serializable] public class Piece { public string fbx, align; public float x, z, yaw, align_value, scale, y, height; public bool auto, floor; }
    [Serializable] public class Structure { public string id; public float floor_y, x, z; public Piece[] pieces, rubble, props; }
    [Serializable] public class Cover { public string texture; public float aspect; public float[] items; }
    [Serializable] public class Shot { public string name; public float fov; public float[] from, to; }
    [Serializable] public class Request
    {
        public float size, height, grass_cell, sun_pitch, sun_yaw, sun_intensity, sky_thickness, sky_exposure, fog_start, fog_end;
        public float grade_exposure, grade_contrast, grade_saturation, grade_temperature, grade_tint, bloom, vignette;
        public float ao_intensity, ao_radius, ao_direct, probe_spacing;
        public int res, splat_res, layer_count, grass_size;
        public bool grass, fog, ao, gi, sky_occlusion;
        public string heights_path, weights_path, grass_path, palette, generated, scene_path, out_dir;
        public float[] grass_origin, sun_colour, sky_tint, sky_ground, fog_colour;
        public int[] still_size, frame_size;
        public Layer[] layers; public Plant[] plants; public Placement[] placements; public Structure[] structures;
        public Cover[] cover; public Shot[] stills, frames;
    }
    [Serializable] public class Report { public string scene; public string[] stills; public int frames, objects, blades, cover; public float bake_seconds; public string[] errors; }

OPEN_SIDE_YAW
    static Color C(float[] v) { return new Color(v[0], v[1], v[2]); }
    static float[] Floats(string path, int count)
    {
        var bytes = File.ReadAllBytes(path);
        var values = new float[count];
        Buffer.BlockCopy(bytes, 0, values, 0, count * 4);
        return values;
    }
    static Bounds Bounds(GameObject g) => g.GetComponentsInChildren<Renderer>().Select(r => r.bounds).Aggregate((a, b) => { a.Encapsulate(b); return a; });
    static GameObject Wrap(string fbx, Vector3 position, float yaw, float scale)
    {
        var model = AssetDatabase.LoadAssetAtPath<GameObject>(fbx);
        if (model == null) throw new Exception("Scene model is missing: " + fbx);
        // An identity root, as kit prefabs use: turning the model itself dropped its FBX axis rotation.
        var root = new GameObject(Path.GetFileNameWithoutExtension(fbx));
        var child = (GameObject)PrefabUtility.InstantiatePrefab(model);
        child.transform.SetParent(root.transform, false); child.transform.localPosition = Vector3.zero;
        root.transform.localScale = Vector3.one * scale; root.transform.rotation = Quaternion.Euler(0f, yaw, 0f);
        root.transform.position = position;
        return root;
    }
    static void Cutout(string path, float cutoff)
    {
        var importer = (TextureImporter)AssetImporter.GetAtPath(path);
        importer.alphaIsTransparency = true; importer.wrapMode = TextureWrapMode.Clamp;
        // Thin blades and leaves averaged below the cutoff in smaller mips and vanished.
        importer.mipMapsPreserveCoverage = true; importer.alphaTestReferenceValue = cutoff;
        importer.SaveAndReimport();
    }
    static void NormalMap(string path)
    {
        var importer = (TextureImporter)AssetImporter.GetAtPath(path);
        importer.textureType = TextureImporterType.NormalMap; importer.SaveAndReimport();
    }
    static Material CutoutMaterial(Shader lit, string texture, float cutoff, bool bothSides, string asset, float glow)
    {
        var m = new Material(lit);
        m.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(texture));
        m.SetFloat("_AlphaClip", 1f); m.SetFloat("_Cutoff", cutoff); m.EnableKeyword("_ALPHATEST_ON");
        m.SetFloat("_Cull", bothSides ? 0f : 2f); m.SetFloat("_Smoothness", 0.18f);
        m.renderQueue = (int)RenderQueue.AlphaTest;
        if (glow > 0f)  // a little light through leaves, so shaded crowns are not flat dark
        {
            m.EnableKeyword("_EMISSION"); m.SetTexture("_EmissionMap", m.GetTexture("_BaseMap")); m.SetColor("_EmissionColor", Color.white * glow);
        }
        AssetDatabase.CreateAsset(m, asset);
        return m;
    }
    static Mesh Tuft(float aspect, string asset)
    {
        // Three crossed cards, both windings drawn one-sided with up normals: lit like the ground they grow from.
        var mesh = new Mesh();
        var verts = new List<Vector3>(); var uvs = new List<Vector2>(); var tris = new List<int>();
        for (var k = 0; k < 3; k++)
        {
            var a = Mathf.PI * k / 3f; var right = new Vector3(Mathf.Cos(a), 0f, Mathf.Sin(a)) * 0.5f * aspect;
            var b = verts.Count;
            verts.AddRange(new[] { -right + Vector3.down * 0.05f, right + Vector3.down * 0.05f, right + Vector3.up, -right + Vector3.up });
            uvs.AddRange(new[] { new Vector2(0, 0), new Vector2(1, 0), new Vector2(1, 1), new Vector2(0, 1) });
            tris.AddRange(new[] { b, b + 2, b + 1, b, b + 3, b + 2, b, b + 1, b + 2, b, b + 2, b + 3 });
        }
        mesh.SetVertices(verts); mesh.SetUVs(0, uvs); mesh.SetTriangles(tris, 0);
        mesh.SetNormals(Enumerable.Repeat(Vector3.up, verts.Count).ToList()); mesh.RecalculateBounds();
        AssetDatabase.CreateAsset(mesh, asset);
        return mesh;
    }

    public static void Build()
    {
        var request = JsonUtility.FromJson<Request>(File.ReadAllText(REQUEST_PATH));
        var errors = new List<string>();
        AssetDatabase.Refresh();
        var gen = request.generated + "/";
        var lit = Shader.Find("Universal Render Pipeline/Lit");

        // Materials: terrain layers, plants, cover and grass blades.
        var terrainLayers = new List<TerrainLayer>();
        for (var i = 0; i < request.layers.Length; i++)
        {
            var layer = request.layers[i];
            NormalMap(layer.normal);
            var tl = new TerrainLayer { diffuseTexture = AssetDatabase.LoadAssetAtPath<Texture2D>(layer.albedo),
                normalMapTexture = AssetDatabase.LoadAssetAtPath<Texture2D>(layer.normal), tileSize = new Vector2(layer.tile, layer.tile),
                smoothness = layer.smoothness, metallic = 0f, normalScale = 1f };
            AssetDatabase.CreateAsset(tl, gen + "layer_" + i + ".terrainlayer");
            terrainLayers.Add(tl);
        }
        foreach (var plant in request.plants)
        {
            Cutout(plant.leaves, 0.45f); NormalMap(plant.bark_normal);
            var bark = new Material(lit);
            bark.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(plant.bark));
            bark.SetTexture("_BumpMap", AssetDatabase.LoadAssetAtPath<Texture2D>(plant.bark_normal));
            bark.EnableKeyword("_NORMALMAP"); bark.SetFloat("_Smoothness", 0.12f);
            AssetDatabase.CreateAsset(bark, gen + plant.name + "_bark.mat");
            var leaves = CutoutMaterial(lit, plant.leaves, 0.45f, true, gen + plant.name + "_leaves.mat", 0.08f);
            var importer = (ModelImporter)AssetImporter.GetAtPath(plant.fbx);
            importer.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
            importer.importNormals = ModelImporterNormals.Import;
            importer.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "Bark"), bark);
            importer.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "Leaves"), leaves);
            importer.SaveAndReimport();
        }
        foreach (var group in request.cover) Cutout(group.texture, 0.45f);

        // Terrain.
        var data = new TerrainData { heightmapResolution = request.res, alphamapResolution = request.splat_res,
                                     size = new Vector3(request.size, request.height, request.size) };
        AssetDatabase.CreateAsset(data, gen + "terrain.asset");  // created first: creating it after painting reset the splat map
        var flat = Floats(request.heights_path, request.res * request.res);
        var heights = new float[request.res, request.res];
        for (var i = 0; i < request.res; i++) for (var j = 0; j < request.res; j++) heights[i, j] = flat[i * request.res + j];
        data.SetHeights(0, 0, heights);
        data.terrainLayers = terrainLayers.ToArray();
        var n = request.splat_res; var L = request.layer_count;
        var w = Floats(request.weights_path, n * n * L);
        var alpha = new float[n, n, L];
        for (var i = 0; i < n; i++) for (var j = 0; j < n; j++) for (var l = 0; l < L; l++) alpha[i, j, l] = w[(i * n + j) * L + l];
        data.SetAlphamaps(0, 0, alpha);
        EditorUtility.SetDirty(data); AssetDatabase.SaveAssets();
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        var terrainGo = Terrain.CreateTerrainGameObject(data);
        var terrain = terrainGo.GetComponent<Terrain>();
        terrain.materialTemplate = new Material(Shader.Find("Universal Render Pipeline/Terrain/Lit"));
        terrain.heightmapPixelError = 1f;
        var contributors = new List<GameObject> { terrainGo };

        // Scattered models and plants, each seated on the lowest ground under its footprint and sunk a little.
        var objects = 0;
        foreach (var p in request.placements)
        {
            var go = Wrap(p.fbx, new Vector3(p.x, terrain.SampleHeight(new Vector3(p.x, 0f, p.z)), p.z), p.yaw, p.scale);
            var box = Bounds(go);
            var ground = new[] { box.center, new Vector3(box.min.x, 0f, box.min.z), new Vector3(box.min.x, 0f, box.max.z),
                                 new Vector3(box.max.x, 0f, box.min.z), new Vector3(box.max.x, 0f, box.max.z) }
                         .Min(c => terrain.SampleHeight(new Vector3(c.x, 0f, c.z)));
            go.transform.position += Vector3.up * (ground - box.min.y - p.sink * box.size.y);
            contributors.Add(go); objects++;
        }

        // Structures: pieces turned, aligned and grounded; floor tiles' tops just above the grass; rubble; props.
        foreach (var s in request.structures)
        {
            var root = new GameObject(s.id); contributors.Add(root);
            foreach (var piece in s.pieces)
            {
                var go = Wrap(piece.fbx, new Vector3(piece.x, s.floor_y, piece.z), piece.yaw, 1f);
                if (piece.auto)  // an L corner turns its open side toward the structure's centre, read from the mesh
                    go.transform.rotation = Quaternion.Euler(0f, OpenSideYaw(go, new Vector3(s.x, 0f, s.z), out _, out _), 0f);
                var box = Bounds(go);
                var bottom = piece.floor ? s.floor_y + 0.06f - box.size.y : s.floor_y - 0.04f;
                go.transform.position += Vector3.up * (bottom - box.min.y);
                box = Bounds(go);
                if (piece.align == "max_z") go.transform.position += Vector3.forward * (piece.align_value - box.max.z);
                if (piece.align == "min_z") go.transform.position += Vector3.forward * (piece.align_value - box.min.z);
                if (piece.align == "max_x") go.transform.position += Vector3.right * (piece.align_value - box.max.x);
                if (piece.align == "min_x") go.transform.position += Vector3.right * (piece.align_value - box.min.x);
                go.transform.SetParent(root.transform, true); objects++;
            }
            foreach (var r in s.rubble)
            {
                Wrap(r.fbx, new Vector3(r.x, s.floor_y - 0.08f, r.z), r.yaw, r.scale).transform.SetParent(root.transform, true); objects++;
            }
            foreach (var p in s.props)
            {
                var go = Wrap(p.fbx, Vector3.zero, p.yaw, 1f);
                var box = Bounds(go);
                go.transform.localScale = Vector3.one * (p.height / box.size.y);
                box = Bounds(go);
                go.transform.position += new Vector3(p.x, p.y, p.z) - new Vector3(box.center.x, box.min.y, box.center.z);
                objects++;
            }
        }

        // Cover: foliage cards.
        var coverRoot = new GameObject("Cover"); var cards = 0;
        for (var g = 0; g < request.cover.Length; g++)
        {
            var group = request.cover[g];
            var mat = CutoutMaterial(lit, group.texture, 0.45f, false, gen + "cover_" + g + ".mat", 0f);
            var mesh = Tuft(group.aspect, gen + "cover_" + g + ".asset");
            for (var k = 0; k + 4 < group.items.Length; k += 5)
            {
                var go = new GameObject("card", typeof(MeshFilter), typeof(MeshRenderer));
                go.GetComponent<MeshFilter>().sharedMesh = mesh;
                var mr = go.GetComponent<MeshRenderer>(); mr.sharedMaterial = mat; mr.shadowCastingMode = ShadowCastingMode.Off;
                go.transform.SetParent(coverRoot.transform, false);
                go.transform.position = new Vector3(group.items[k], group.items[k + 1], group.items[k + 2]);
                go.transform.rotation = Quaternion.Euler(0f, group.items[k + 3], 0f);
                go.transform.localScale = Vector3.one * group.items[k + 4];
                cards++;
            }
        }

        // Grass: thin bent blade geometry from the density grid, coloured from the base layer's palette.
        var blades = 0;
        if (request.grass)
        {
            var palette = (TextureImporter)AssetImporter.GetAtPath(request.palette);
            palette.filterMode = FilterMode.Point; palette.mipmapEnabled = false; palette.wrapMode = TextureWrapMode.Clamp; palette.SaveAndReimport();
            var bladeMat = new Material(lit);
            bladeMat.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(request.palette));
            bladeMat.SetFloat("_Smoothness", 0.25f);
            AssetDatabase.CreateAsset(bladeMat, gen + "blades.mat");
            var size = request.grass_size; var cell = request.grass_cell;
            var density = Floats(request.grass_path, size * size);
            var rng = new System.Random(7);
            var field = new GameObject("Grass");
            const int Chunk = 16;  // cells per chunk side: 8 m chunks at 0.5 m cells
            for (var ci = 0; ci < size; ci += Chunk)
                for (var cj = 0; cj < size; cj += Chunk)
                {
                    var verts = new List<Vector3>(); var norms = new List<Vector3>(); var uvs = new List<Vector2>(); var tris = new List<int>();
                    for (var i = ci; i < Math.Min(ci + Chunk, size); i++)
                        for (var j = cj; j < Math.Min(cj + Chunk, size); j++)
                        {
                            var expected = density[i * size + j] * cell * cell;
                            var count = (int)expected + (rng.NextDouble() < expected - (int)expected ? 1 : 0);
                            for (var b = 0; b < count; b++)
                            {
                                var wx = request.grass_origin[0] + (j + (float)rng.NextDouble()) * cell;
                                var wz = request.grass_origin[1] + (i + (float)rng.NextDouble()) * cell;
                                var groundPoint = new Vector3(wx, terrain.SampleHeight(new Vector3(wx, 0f, wz)), wz);
                                var patch = 0.18f + 1.21f * Mathf.Pow(Mathf.PerlinNoise(wx * 0.13f, wz * 0.13f), 2.2f);
                                var h = patch * (0.6f + 0.6f * (float)rng.NextDouble());
                                var yaw = (float)(rng.NextDouble() * Math.PI * 2);
                                var lean = new Vector3(Mathf.Cos(yaw), 0f, Mathf.Sin(yaw)) * h * (0.15f + 0.45f * (float)rng.NextDouble());
                                var side = new Vector3(-Mathf.Sin(yaw + 1.2f), 0f, Mathf.Cos(yaw + 1.2f)) * (0.006f + 0.008f * (float)rng.NextDouble());
                                var u = (rng.Next(16) + 0.5f) / 16f;
                                var v0 = verts.Count;
                                var mid = groundPoint + Vector3.up * h * 0.55f + lean * 0.3f; var tip = groundPoint + Vector3.up * h + lean;
                                verts.AddRange(new[] { groundPoint - side, groundPoint + side, mid - side * 0.7f, mid + side * 0.7f, tip });
                                var up = (Vector3.up * 0.8f + lean.normalized * 0.2f).normalized;
                                norms.AddRange(new[] { up, up, up, up, up });
                                uvs.AddRange(new[] { new Vector2(u, 0.02f), new Vector2(u, 0.02f), new Vector2(u, 0.55f), new Vector2(u, 0.55f), new Vector2(u, 0.98f) });
                                tris.AddRange(new[] { v0, v0 + 2, v0 + 1, v0 + 1, v0 + 2, v0 + 3, v0 + 2, v0 + 4, v0 + 3,
                                                      v0, v0 + 1, v0 + 2, v0 + 1, v0 + 3, v0 + 2, v0 + 2, v0 + 3, v0 + 4 });
                                blades++;
                            }
                        }
                    if (verts.Count == 0) continue;
                    var mesh = new Mesh { indexFormat = IndexFormat.UInt32, name = "grass_" + ci + "_" + cj };
                    mesh.SetVertices(verts); mesh.SetNormals(norms); mesh.SetUVs(0, uvs); mesh.SetTriangles(tris, 0); mesh.RecalculateBounds();
                    var chunk = new GameObject(mesh.name, typeof(MeshFilter), typeof(MeshRenderer));
                    chunk.GetComponent<MeshFilter>().sharedMesh = mesh;
                    var mr = chunk.GetComponent<MeshRenderer>(); mr.sharedMaterial = bladeMat; mr.shadowCastingMode = ShadowCastingMode.Off;
                    chunk.transform.SetParent(field.transform, false);
                }
        }

        // Lighting: sun, sky, fog, post-processing and ambient occlusion, set before the bake so it matches.
        var camera = Camera.main;
        var sun = UnityEngine.Object.FindAnyObjectByType<Light>();
        sun.transform.rotation = Quaternion.Euler(request.sun_pitch, request.sun_yaw, 0f);
        sun.color = C(request.sun_colour); sun.intensity = request.sun_intensity; sun.shadows = LightShadows.Soft;
        var sky = new Material(Shader.Find("Skybox/Procedural"));
        sky.SetColor("_SkyTint", C(request.sky_tint)); sky.SetColor("_GroundColor", C(request.sky_ground));
        sky.SetFloat("_AtmosphereThickness", request.sky_thickness); sky.SetFloat("_Exposure", request.sky_exposure);
        AssetDatabase.CreateAsset(sky, gen + "sky.mat");
        RenderSettings.skybox = sky; RenderSettings.sun = sun; RenderSettings.ambientMode = AmbientMode.Skybox;
        RenderSettings.fog = request.fog; RenderSettings.fogMode = FogMode.Linear;
        RenderSettings.fogStartDistance = request.fog_start; RenderSettings.fogEndDistance = request.fog_end; RenderSettings.fogColor = C(request.fog_colour);
        var urp = UniversalRenderPipeline.asset;
        urp.shadowDistance = 160f; urp.shadowCascadeCount = 4;
        var profile = ScriptableObject.CreateInstance<VolumeProfile>();
        profile.Add<Tonemapping>(true).mode.Override(TonemappingMode.ACES);
        var colour = profile.Add<ColorAdjustments>(true);
        colour.postExposure.Override(request.grade_exposure); colour.contrast.Override(request.grade_contrast); colour.saturation.Override(request.grade_saturation);
        var balance = profile.Add<WhiteBalance>(true); balance.temperature.Override(request.grade_temperature); balance.tint.Override(request.grade_tint);
        var bloom = profile.Add<Bloom>(true); bloom.intensity.Override(request.bloom); bloom.threshold.Override(1.05f);
        profile.Add<Vignette>(true).intensity.Override(request.vignette);
        AssetDatabase.CreateAsset(profile, gen + "post.asset");
        var volume = new GameObject("Post").AddComponent<Volume>(); volume.isGlobal = true; volume.sharedProfile = profile;
        var cameraData = camera.GetUniversalAdditionalCameraData();
        cameraData.renderPostProcessing = true; cameraData.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
        if (request.ao)
        {
            // Every renderer's SSAO feature takes the scene's settings; these are project-wide renderer assets.
            var features = AssetDatabase.FindAssets("t:UniversalRendererData")
                .SelectMany(id => AssetDatabase.LoadAllAssetsAtPath(AssetDatabase.GUIDToAssetPath(id)))
                .Where(o => o != null && o.GetType().Name == "ScreenSpaceAmbientOcclusion").ToList();
            foreach (var feature in features)
            {
                var so = new SerializedObject(feature);
                so.FindProperty("m_Settings.Intensity").floatValue = request.ao_intensity;
                so.FindProperty("m_Settings.Radius").floatValue = request.ao_radius;
                so.FindProperty("m_Settings.DirectLightingStrength").floatValue = request.ao_direct;
                so.ApplyModifiedPropertiesWithoutUndo();
            }
            if (features.Count == 0) errors.Add("no URP renderer has a Screen Space Ambient Occlusion feature; ambient occlusion was not set");
        }
        Directory.CreateDirectory(Path.GetDirectoryName(request.scene_path));
        EditorSceneManager.SaveScene(scene, request.scene_path);

        // Global illumination: adaptive probe volumes with sky occlusion. Shaded areas otherwise went cold and blue.
        var bakeSeconds = 0f;
        if (request.gi)
        {
            var watch = System.Diagnostics.Stopwatch.StartNew();
            var pipeline = new SerializedObject(urp);
            pipeline.FindProperty("m_LightProbeSystem").intValue = 1;  // LightProbeSystem.ProbeVolumes
            pipeline.ApplyModifiedPropertiesWithoutUndo();
            foreach (var root in contributors)
                foreach (var item in root.GetComponentsInChildren<Transform>())
                    GameObjectUtility.SetStaticEditorFlags(item.gameObject, GameObjectUtility.GetStaticEditorFlags(item.gameObject) | StaticEditorFlags.ContributeGI);
            foreach (var r in UnityEngine.Object.FindObjectsByType<MeshRenderer>(FindObjectsSortMode.None)) r.receiveGI = ReceiveGI.LightProbes;
            sun.lightmapBakeType = LightmapBakeType.Mixed;
            new GameObject("Probe Volume").AddComponent<ProbeVolume>().mode = ProbeVolume.Mode.Global;
            EditorSceneManager.SaveScene(scene, request.scene_path);
            var set = ScriptableObject.CreateInstance<ProbeVolumeBakingSet>();
            set.skyOcclusion = request.sky_occlusion; set.minDistanceBetweenProbes = request.probe_spacing;
            AssetDatabase.CreateAsset(set, gen + "baking_set.asset");
            set.TryAddScene(AssetDatabase.AssetPathToGUID(request.scene_path));
            var settings = new LightingSettings { bakedGI = true, realtimeGI = false, mixedBakeMode = MixedLightingMode.IndirectOnly,
                lightmapper = LightingSettings.Lightmapper.ProgressiveGPU, lightmapResolution = 0.25f,
                directSampleCount = 8, indirectSampleCount = 64, environmentSampleCount = 64, maxBounces = 2 };
            AssetDatabase.CreateAsset(settings, gen + "lighting.lighting");
            Lightmapping.lightingSettings = settings;
            if (!Lightmapping.Bake()) errors.Add("the global illumination bake failed");
            bakeSeconds = (float)watch.Elapsed.TotalSeconds;
            // Reopen so the baked probe data loads; a render in the same session showed none of it.
            EditorSceneManager.SaveScene(scene, request.scene_path);
            scene = EditorSceneManager.OpenScene(request.scene_path, OpenSceneMode.Single);
            camera = Camera.main;
        }

        // Stills, then flythrough frames.
        var stills = new List<string>();
        camera.clearFlags = CameraClearFlags.Skybox; camera.farClipPlane = 600f;
        byte[] Shoot(Shot shot, int width, int height)
        {
            var target = new RenderTexture(width, height, 24);
            camera.targetTexture = target; camera.fieldOfView = shot.fov;
            camera.transform.position = new Vector3(shot.from[0], shot.from[1], shot.from[2]);
            camera.transform.LookAt(new Vector3(shot.to[0], shot.to[1], shot.to[2]));
            camera.Render(); camera.Render();  // the first render builds the terrain's patches in view
            RenderTexture.active = target;
            var image = new Texture2D(width, height, TextureFormat.RGB24, false);
            image.ReadPixels(new Rect(0, 0, width, height), 0, 0); image.Apply();
            RenderTexture.active = null; camera.targetTexture = null;
            var png = image.EncodeToPNG();
            // Destroy both: the editor does not free native textures, and 366 shots held about 2 GB.
            UnityEngine.Object.DestroyImmediate(image); target.Release(); UnityEngine.Object.DestroyImmediate(target);
            return png;
        }
        Directory.CreateDirectory(Path.Combine(request.out_dir, "stills"));
        foreach (var shot in request.stills)
        {
            var path = Path.Combine(request.out_dir, "stills", shot.name + ".png");
            File.WriteAllBytes(path, Shoot(shot, request.still_size[0], request.still_size[1]));
            stills.Add(path);
        }
        if (request.frames.Length > 0)
        {
            Directory.CreateDirectory(Path.Combine(request.out_dir, "frames"));
            for (var f = 0; f < request.frames.Length; f++)
                File.WriteAllBytes(Path.Combine(request.out_dir, "frames", $"frame_{f:0000}.png"),
                                   Shoot(request.frames[f], request.frame_size[0], request.frame_size[1]));
        }
        var report = new Report { scene = request.scene_path, stills = stills.ToArray(), frames = request.frames.Length,
            objects = objects, blades = blades, cover = cards, bake_seconds = bakeSeconds, errors = errors.ToArray() };
        File.WriteAllText(Path.Combine(request.out_dir, "report.json"), JsonUtility.ToJson(report, true));
        Debug.Log("SLOPFORGE_NATURAL_SCENE " + request.scene_path);
    }
}
'''
