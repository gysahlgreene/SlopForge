"""Assemble a kit layout in Unity: module prefabs (identity root, collider, static), a saved test scene, a render,
and checks that each module stands at its placement and meets its neighbours without gaps."""
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

from .unity_material import unity_cli


def build_kit_scene(project_root, kit, layout, placements, *, grid, tolerance, render):
    """Build Assets/Art/Generated/Scenes/<kit>_<layout>.unity from published modules; returns Unity's report.

    placements: dicts with module, fbx (asset path), pivot, x, y, z and rotation (degrees as text, or "auto").
    """
    root = Path(project_root).resolve()
    cli = unity_cli(root)
    editor_dir = root / "Assets/Editor"
    editor_dir.mkdir(parents=True, exist_ok=True)
    class_name = f"SlopForgeKitScene_{uuid.uuid4().hex}"
    script = editor_dir / f"{class_name}.cs"
    with tempfile.TemporaryDirectory(prefix="slopforge-unity-") as scratch:
        request, report = Path(scratch) / "request.json", Path(scratch) / "report.json"
        request.write_text(json.dumps({
            "kit": kit, "layout": layout, "grid": grid, "tolerance": tolerance,
            "prefab_folder": f"Assets/Art/Generated/Prefabs/{kit}",
            "scene_path": f"Assets/Art/Generated/Scenes/{kit}_{layout}.unity",
            "report_path": str(report), "render_path": str(Path(render).resolve()), "placements": placements}))
        script.write_text(_SCRIPT.replace("CLASS_NAME", class_name).replace("REQUEST_PATH", json.dumps(str(request))))
        try:
            subprocess.run([cli, "run", str(root), "--timeout", "900", "--", "-executeMethod", f"{class_name}.Build"],
                           check=True)
        finally:
            script.unlink(missing_ok=True)
            script.with_suffix(".cs.meta").unlink(missing_ok=True)
        return json.loads(report.read_text())


_SCRIPT = r'''using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class CLASS_NAME
{
    [Serializable] public class Placement { public string module, fbx, pivot, rotation; public float x, y, z; }
    [Serializable] public class Request
    {
        public string kit, layout, prefab_folder, scene_path, report_path, render_path;
        public float grid, tolerance; public Placement[] placements;
    }
    [Serializable] public class Instance
    {
        public string module, prefab; public float rotation, ground_error;
        public float[] bounds_min, bounds_max, opening; public bool collider, is_static;
    }
    [Serializable] public class Seam { public int a, b; public string axis; public float gap; }
    [Serializable] public class Report
    {
        public string unity_version, scene, render; public Instance[] instances; public Seam[] seams; public string[] errors;
    }

    // Lightmap contribution is left off: it needs lightmap UVs, which would change the published import settings.
    const StaticEditorFlags Static = StaticEditorFlags.BatchingStatic | StaticEditorFlags.OccluderStatic |
                                     StaticEditorFlags.OccludeeStatic | StaticEditorFlags.ReflectionProbeStatic;

    public static void Build()
    {
        var request = JsonUtility.FromJson<Request>(File.ReadAllText(REQUEST_PATH));
        AssetDatabase.Refresh();
        Directory.CreateDirectory(request.prefab_folder);
        Directory.CreateDirectory(Path.GetDirectoryName(request.scene_path));
        var prefabs = new Dictionary<string, GameObject>();
        foreach (var placement in request.placements)
        {
            if (prefabs.ContainsKey(placement.module)) continue;
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(placement.fbx);
            if (model == null) throw new Exception("Published module model is missing: " + placement.fbx);
            // An identity root over the imported model hides the FBX axis rotation from level designers.
            var root = new GameObject(placement.module);
            var child = (GameObject)PrefabUtility.InstantiatePrefab(model);
            child.transform.SetParent(root.transform, false);
            // The FBX root carries the Blender object's location as a translation; drop it so the module's origin
            // (its declared pivot) is the prefab's pivot. A floor tile otherwise stood its own thickness too high.
            child.transform.localPosition = Vector3.zero;
            foreach (var filter in child.GetComponentsInChildren<MeshFilter>())
                filter.gameObject.AddComponent<MeshCollider>().sharedMesh = filter.sharedMesh;
            foreach (var item in root.GetComponentsInChildren<Transform>())
                GameObjectUtility.SetStaticEditorFlags(item.gameObject, Static);
            prefabs[placement.module] = PrefabUtility.SaveAsPrefabAsset(root, request.prefab_folder + "/" + placement.module + ".prefab");
            UnityEngine.Object.DestroyImmediate(root);
        }

        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        var layoutRoot = new GameObject("Layout_" + request.layout);
        var centre = new Vector3(request.placements.Average(p => p.x), 0f, request.placements.Average(p => p.z));
        var instances = new List<Instance>();
        var bounds = new List<Bounds>();
        var errors = new List<string>();
        for (var index = 0; index < request.placements.Length; index++)
        {
            var placement = request.placements[index];
            var go = (GameObject)PrefabUtility.InstantiatePrefab(prefabs[placement.module]);
            go.transform.SetParent(layoutRoot.transform, false);
            go.transform.position = new Vector3(placement.x, placement.y, placement.z);
            var opening = Vector3.zero;
            var yaw = placement.rotation == "auto" ? OpenSideYaw(go, centre, placement.module, errors, out opening)
                                                   : float.Parse(placement.rotation, CultureInfo.InvariantCulture);
            go.transform.rotation = Quaternion.Euler(0f, yaw, 0f);
            var box = WorldBounds(go);
            bounds.Add(box);
            var standing = placement.pivot == "bottom_center" ? box.min.y : placement.pivot == "top_center" ? box.max.y : box.center.y;
            var instance = new Instance
            {
                module = placement.module, prefab = AssetDatabase.GetAssetPath(prefabs[placement.module]), rotation = yaw,
                ground_error = standing - placement.y, bounds_min = Floats(box.min), bounds_max = Floats(box.max),
                opening = placement.rotation == "auto" ? Floats(Quaternion.Euler(0f, yaw, 0f) * opening) : new float[0],
                collider = go.GetComponentsInChildren<MeshCollider>().Any(c => c.sharedMesh != null),
                is_static = (GameObjectUtility.GetStaticEditorFlags(go) & StaticEditorFlags.BatchingStatic) != 0
            };
            instances.Add(instance);
            var label = placement.module + " " + index;
            if (Mathf.Abs(instance.ground_error) > request.tolerance)
                errors.Add(label + " stands " + instance.ground_error.ToString("F3", CultureInfo.InvariantCulture) +
                           " m off its placement height for a " + placement.pivot + " pivot");
            if (!instance.collider) errors.Add(label + " has no mesh collider");
            if (!instance.is_static) errors.Add(label + " is not static");
        }

        // Neighbours: boxes that overlap on two axes and are separated by under a grid cell on the third.
        var seams = new List<Seam>();
        for (var a = 0; a < bounds.Count; a++)
            for (var b = a + 1; b < bounds.Count; b++)
            {
                var separation = new float[3];
                for (var axis = 0; axis < 3; axis++)
                    separation[axis] = Mathf.Max(bounds[a].min[axis] - bounds[b].max[axis], bounds[b].min[axis] - bounds[a].max[axis]);
                var gapAxis = Array.IndexOf(separation, separation.Max());
                var gap = separation[gapAxis];
                if (gap <= 0.001f || gap >= request.grid || separation.Where((value, axis) => axis != gapAxis).Any(value => value >= 0f))
                    continue;
                seams.Add(new Seam { a = a, b = b, axis = "xyz".Substring(gapAxis, 1), gap = gap });
                if (gap > request.tolerance)
                    errors.Add(request.placements[a].module + " " + a + " and " + request.placements[b].module + " " + b +
                               " leave a " + gap.ToString("F3", CultureInfo.InvariantCulture) + " m gap on " + "xyz".Substring(gapAxis, 1));
            }

        EditorSceneManager.SaveScene(scene, request.scene_path);
        Render(layoutRoot, request.render_path);
        File.WriteAllText(request.report_path, JsonUtility.ToJson(new Report
        {
            unity_version = Application.unityVersion, scene = request.scene_path, render = request.render_path,
            instances = instances.ToArray(), seams = seams.ToArray(), errors = errors.ToArray()
        }));
        Debug.Log("SLOPFORGE_KIT_SCENE " + request.scene_path);
    }

    // Turns a module whose top-down footprint has one nearly empty quadrant (an L corner) so that quadrant faces the
    // layout's centre. Reads the placed mesh, so it needs no assumption about the FBX axes.
    static float OpenSideYaw(GameObject go, Vector3 centre, string module, List<string> errors, out Vector3 opening)
    {
        opening = Vector3.zero;
        var box = WorldBounds(go);
        var counts = new int[4];
        foreach (var filter in go.GetComponentsInChildren<MeshFilter>())
            foreach (var vertex in filter.sharedMesh.vertices)
            {
                var point = filter.transform.TransformPoint(vertex) - box.center;
                counts[(point.x >= 0 ? 0 : 1) + (point.z >= 0 ? 0 : 2)]++;
            }
        var open = Array.IndexOf(counts, counts.Min());
        if (counts[open] > 0.1f * counts.Average())
        {
            errors.Add(module + " has rotation auto but no open side");
            return 0f;
        }
        opening = new Vector3(open % 2 == 0 ? 1f : -1f, 0f, open < 2 ? 1f : -1f);
        var wanted = centre - go.transform.position;
        wanted.y = 0f;
        var best = 0f;
        var bestDot = float.NegativeInfinity;
        for (var turn = 0; turn < 4; turn++)
        {
            var dot = Vector3.Dot(Quaternion.Euler(0f, 90f * turn, 0f) * opening, wanted);
            if (dot > bestDot) { bestDot = dot; best = 90f * turn; }
        }
        return best;
    }

    static Bounds WorldBounds(GameObject go)
    {
        var renderers = go.GetComponentsInChildren<Renderer>();
        var box = renderers[0].bounds;
        foreach (var renderer in renderers) box.Encapsulate(renderer.bounds);
        return box;
    }

    static float[] Floats(Vector3 value) { return new[] { value.x, value.y, value.z }; }

    static void Render(GameObject layout, string path)
    {
        DynamicGI.UpdateEnvironment();
        var box = WorldBounds(layout);
        var camera = Camera.main;
        var light = UnityEngine.Object.FindAnyObjectByType<Light>();
        camera.clearFlags = CameraClearFlags.SolidColor;
        camera.backgroundColor = new Color(0.32f, 0.33f, 0.35f);
        camera.fieldOfView = 30f;
        var distance = box.extents.magnitude / Mathf.Sin(camera.fieldOfView * 0.5f * Mathf.Deg2Rad) * 1.05f;
        camera.nearClipPlane = distance * 0.01f;
        camera.farClipPlane = distance * 4f;
        const int size = 1024;
        var target = new RenderTexture(size, size, 24);
        camera.targetTexture = target;
        var strip = new Texture2D(size * 4, size, TextureFormat.RGB24, false);
        for (var view = 0; view < 4; view++)
        {
            var rotation = Quaternion.Euler(view == 3 ? 70f : 32f, 35f + 90f * view, 0f);
            camera.transform.SetPositionAndRotation(box.center - rotation * Vector3.forward * distance, rotation);
            light.transform.rotation = Quaternion.Euler(50f, 35f + 90f * view - 30f, 0f);
            camera.Render();
            RenderTexture.active = target;
            strip.ReadPixels(new Rect(0, 0, size, size), size * view, 0);
            RenderTexture.active = null;
        }
        strip.Apply();
        File.WriteAllBytes(path, strip.EncodeToPNG());
    }
}
'''
