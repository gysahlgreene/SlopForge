"""A weapon's Unity prefab and motion clips: an identity root at the grip over the published FBX, one clip per moving
part (rest, limit, rest), an animator with a state per clip, and checks that each part moves as declared."""
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

from .unity_material import unity_cli

PIVOT_TOLERANCE = 0.001  # metres a hinge's pivot may drift, and a slide's travel may miss its declared range by
ANGLE_TOLERANCE = 0.5  # degrees a hinge may miss its declared limit by


def build_weapon_prefab(project_root, name, fbx, parts, *, prefab, clip_folder, render):
    """Build the prefab and clips; returns Unity's report, whose errors list every failed motion check.

    parts: the declared hinge and slide parts (name, kind, axis, min, max) in the weapon's frame as Unity shows it:
    x right, y up, z forward. The limit is the bound farther from rest (0). fbx, prefab, clip_folder and render are
    paths inside the Unity project.
    """
    root = Path(project_root).resolve()
    cli = unity_cli(root)
    editor_dir = root / "Assets/Editor"
    editor_dir.mkdir(parents=True, exist_ok=True)
    class_name = f"SlopForgeWeapon_{uuid.uuid4().hex}"
    script = editor_dir / f"{class_name}.cs"
    inside = lambda path: Path(path).resolve().relative_to(root).as_posix()
    with tempfile.TemporaryDirectory(prefix="slopforge-unity-") as scratch:
        request, report = Path(scratch) / "request.json", Path(scratch) / "report.json"
        request.write_text(json.dumps({
            "name": name, "fbx": inside(fbx), "prefab": inside(prefab), "clip_folder": inside(clip_folder),
            "report_path": str(report), "render_path": str(Path(render).resolve()),
            "pivot_tolerance": PIVOT_TOLERANCE, "angle_tolerance": ANGLE_TOLERANCE,
            "parts": [{"name": part["name"], "kind": part["kind"], "axis": part["axis"],
                       "limit": max((part["min"], part["max"]), key=abs)} for part in parts]}))
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
using UnityEditor.Animations;
using UnityEngine;

public static class CLASS_NAME
{
    [Serializable] public class Part { public string name, kind, axis; public float limit; }
    [Serializable] public class Request
    {
        public string name, fbx, prefab, clip_folder, report_path, render_path;
        public float pivot_tolerance, angle_tolerance; public Part[] parts;
    }
    [Serializable] public class Motion
    {
        public string part, kind, clip; public float pivot_drift, angle, travel; public float[] pivot;
    }
    [Serializable] public class Report
    {
        public string unity_version, prefab, controller, render; public Motion[] motions;
        public float[] bounds_min, bounds_max; public bool tip_forward, root_inside; public string[] errors;
    }

    public static void Build()
    {
        var request = JsonUtility.FromJson<Request>(File.ReadAllText(REQUEST_PATH));
        AssetDatabase.Refresh();
        // A scene with its default camera and light, for the sampling and the render.
        UnityEditor.SceneManagement.EditorSceneManager.NewScene(
            UnityEditor.SceneManagement.NewSceneSetup.DefaultGameObjects, UnityEditor.SceneManagement.NewSceneMode.Single);
        Directory.CreateDirectory(Path.GetDirectoryName(request.prefab));
        Directory.CreateDirectory(request.clip_folder);
        var model = AssetDatabase.LoadAssetAtPath<GameObject>(request.fbx);
        if (model == null) throw new Exception("Published weapon model is missing: " + request.fbx);
        // An identity root over the imported model: the FBX root carries the Blender object's location (the grip
        // centre), which is dropped so the grip sits at the prefab's origin, as kit modules sit on theirs.
        var root = new GameObject(request.name);
        var child = (GameObject)PrefabUtility.InstantiatePrefab(model);
        child.transform.SetParent(root.transform, false);
        child.transform.localPosition = Vector3.zero;
        var errors = new List<string>();
        var controllerPath = request.clip_folder + "/" + request.name + ".controller";
        var controller = AnimatorController.CreateAnimatorControllerAtPath(controllerPath);
        var motions = new List<Motion>();
        foreach (var part in request.parts)
        {
            var transform = root.GetComponentsInChildren<Transform>().FirstOrDefault(t => t.name == part.name);
            if (transform == null) { errors.Add("part " + part.name + " is not in the model"); continue; }
            var axis = part.axis == "x" ? Vector3.right : part.axis == "y" ? Vector3.up : Vector3.forward;
            // The root's axis in the part's space. The imported FBX root is scaled (100 with the importer's 0.01
            // file scale), so a slide's travel goes through the parent's scale too: 0.03 m once moved 3 m.
            var local = transform.parent.InverseTransformDirection(axis);
            var clip = new AnimationClip { name = request.name + "_" + part.name };
            var path = AnimationUtility.CalculateTransformPath(transform, root.transform);
            var restPosition = transform.localPosition;
            var restRotation = transform.localRotation;
            if (part.kind == "slide")
            {
                var limitPosition = restPosition + transform.parent.InverseTransformVector(axis * part.limit);
                Curve(clip, path, "m_LocalPosition", new[] { restPosition, limitPosition, restPosition });
            }
            else
            {
                var limitRotation = restRotation * Quaternion.AngleAxis(part.limit, local);
                Curve(clip, path, "m_LocalRotation", new[] { restRotation, limitRotation, restRotation });
            }
            var clipPath = request.clip_folder + "/" + clip.name + ".anim";
            AssetDatabase.CreateAsset(clip, clipPath);
            controller.AddMotion(clip);
            motions.Add(Check(root, transform, clip, clipPath, part, axis, request, errors));
        }
        root.AddComponent<Animator>().runtimeAnimatorController = controller;
        var box = WorldBounds(root);
        var tipForward = box.max.z > -box.min.z;
        var rootInside = box.Contains(root.transform.position);
        if (!tipForward) errors.Add("the weapon does not point along +Z from its root");
        if (!rootInside) errors.Add("the root (grip) lies outside the weapon's bounds");
        Render(root, request, request.render_path);
        var prefab = PrefabUtility.SaveAsPrefabAsset(root, request.prefab);
        UnityEngine.Object.DestroyImmediate(root);
        AssetDatabase.SaveAssets();
        File.WriteAllText(request.report_path, JsonUtility.ToJson(new Report
        {
            unity_version = Application.unityVersion, prefab = AssetDatabase.GetAssetPath(prefab),
            controller = controllerPath, render = request.render_path, motions = motions.ToArray(),
            bounds_min = Floats(box.min), bounds_max = Floats(box.max), tip_forward = tipForward,
            root_inside = rootInside, errors = errors.ToArray()
        }));
        Debug.Log("SLOPFORGE_WEAPON_PREFAB " + request.prefab);
    }

    static void Curve(AnimationClip clip, string path, string property, Vector3[] keys)
    {
        var names = new[] { ".x", ".y", ".z" };
        for (var axis = 0; axis < 3; axis++)
        {
            var curve = new AnimationCurve(keys.Select((key, index) => new Keyframe(index * 0.5f, key[axis])).ToArray());
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(Transform), property + names[axis]), curve);
        }
    }

    static void Curve(AnimationClip clip, string path, string property, Quaternion[] keys)
    {
        var names = new[] { ".x", ".y", ".z", ".w" };
        for (var axis = 0; axis < 4; axis++)
        {
            var curve = new AnimationCurve(keys.Select((key, index) => new Keyframe(index * 0.5f, key[axis])).ToArray());
            AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve(path, typeof(Transform), property + names[axis]), curve);
        }
    }

    // Samples the clip at rest and at its limit and compares the part's world motion with the declaration.
    static Motion Check(GameObject root, Transform part, AnimationClip clip, string clipPath, Part declared, Vector3 axis,
                        Request request, List<string> errors)
    {
        AnimationMode.StartAnimationMode();
        AnimationMode.SampleAnimationClip(root, clip, 0f);
        var restPosition = part.position; var restRotation = part.rotation;
        AnimationMode.SampleAnimationClip(root, clip, 0.5f);
        var limitPosition = part.position; var limitRotation = part.rotation;
        AnimationMode.SampleAnimationClip(root, clip, 0f);
        AnimationMode.StopAnimationMode();
        var motion = new Motion { part = declared.name, kind = declared.kind, clip = clipPath, pivot = Floats(restPosition) };
        var label = declared.kind + " " + declared.name;
        if (declared.kind == "slide")
        {
            var displacement = limitPosition - restPosition;
            motion.travel = Vector3.Dot(displacement, axis);
            var sideways = (displacement - axis * motion.travel).magnitude;
            if (Mathf.Abs(motion.travel - declared.limit) > request.pivot_tolerance || sideways > request.pivot_tolerance)
                errors.Add(label + " travels " + motion.travel.ToString("F4", CultureInfo.InvariantCulture) + " m along " +
                           declared.axis + " (declared " + declared.limit.ToString("F4", CultureInfo.InvariantCulture) + ")");
        }
        else
        {
            motion.pivot_drift = (limitPosition - restPosition).magnitude;
            (Quaternion.Inverse(restRotation) * limitRotation).ToAngleAxis(out var angle, out var turned);
            motion.angle = angle * Mathf.Sign(Vector3.Dot(turned, axis));
            if (motion.pivot_drift > request.pivot_tolerance)
                errors.Add(label + " pivot drifts " + motion.pivot_drift.ToString("F4", CultureInfo.InvariantCulture) + " m");
            if (Mathf.Abs(motion.angle - declared.limit) > request.angle_tolerance)
                errors.Add(label + " turns " + motion.angle.ToString("F2", CultureInfo.InvariantCulture) + " degrees about " +
                           declared.axis + " (declared " + declared.limit.ToString("F2", CultureInfo.InvariantCulture) + ")");
        }
        return motion;
    }

    static Bounds WorldBounds(GameObject go)
    {
        var renderers = go.GetComponentsInChildren<Renderer>();
        var box = renderers[0].bounds;
        foreach (var renderer in renderers) box.Encapsulate(renderer.bounds);
        return box;
    }

    static float[] Floats(Vector3 value) { return new[] { value.x, value.y, value.z }; }

    // A strip: the weapon at rest, then at each part's limit, from a three-quarter view.
    static void Render(GameObject root, Request request, string path)
    {
        DynamicGI.UpdateEnvironment();
        var box = WorldBounds(root);
        var camera = Camera.main;
        var light = UnityEngine.Object.FindAnyObjectByType<Light>();
        camera.clearFlags = CameraClearFlags.SolidColor;
        camera.backgroundColor = new Color(0.32f, 0.33f, 0.35f);
        camera.fieldOfView = 30f;
        var distance = box.extents.magnitude / Mathf.Sin(camera.fieldOfView * 0.5f * Mathf.Deg2Rad) * 1.05f;
        camera.nearClipPlane = distance * 0.01f;
        camera.farClipPlane = distance * 4f;
        var rotation = Quaternion.Euler(20f, -125f, 0f);
        camera.transform.SetPositionAndRotation(box.center - rotation * Vector3.forward * distance, rotation);
        light.transform.rotation = rotation * Quaternion.Euler(25f, -35f, 0f);
        const int size = 768;
        var target = new RenderTexture(size, size, 24);
        camera.targetTexture = target;
        var clips = root.GetComponent<Animator>() == null ? new AnimationClip[0]
            : ((AnimatorController)root.GetComponent<Animator>().runtimeAnimatorController).animationClips;
        var frames = 1 + clips.Length;
        var strip = new Texture2D(size * frames, size, TextureFormat.RGB24, false);
        AnimationMode.StartAnimationMode();
        for (var frame = 0; frame < frames; frame++)
        {
            if (frame > 0) AnimationMode.SampleAnimationClip(root, clips[frame - 1], 0.5f);
            camera.Render();
            RenderTexture.active = target;
            strip.ReadPixels(new Rect(0, 0, size, size), size * frame, 0);
            RenderTexture.active = null;
            if (frame > 0) AnimationMode.SampleAnimationClip(root, clips[frame - 1], 0f);
        }
        AnimationMode.StopAnimationMode();
        camera.targetTexture = null;
        strip.Apply();
        File.WriteAllBytes(path, strip.EncodeToPNG());
    }
}
'''
