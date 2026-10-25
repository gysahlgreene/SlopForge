"""A weapon's Unity prefab and motion clips: an identity root at the grip over the published FBX, one clip per moving
part (rest, limit, rest), an animator with a state per clip, and checks that each part moves as declared."""
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

from .unity_material import unity_cli

PENETRATION_TOLERANCE = 0.02  # share of a part's vertices inside the body over its rest value, through its range
PIVOT_TOLERANCE = 0.001  # metres a hinge's pivot may drift, and a slide's travel may miss its declared range by
ANGLE_TOLERANCE = 0.5  # degrees a hinge may miss its declared limit by


def build_weapon_prefab(project_root, name, fbx, parts, *, prefab, clip_folder, render, held=True, mass=1.0,
                        layer=None):
    """Build the prefab and clips; returns Unity's report, whose errors list every failed motion check.

    parts: the declared hinge and slide parts (name, kind, axis, min, max) in the weapon's frame as Unity shows it:
    x right, y up, z forward. The limit is the bound farther from rest (0); parts may be empty for a static asset.
    fbx, prefab, clip_folder and render are paths inside the Unity project. The prefab gets a convex collider per
    mesh, a Rigidbody of `mass`, the named layer when the project has it (a warning otherwise), sockets, and an
    Animator with a Rest state, a trigger and a hold bool per part. The tip and root checks are for held assets.
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
            "penetration_tolerance": PENETRATION_TOLERANCE,
            "held": bool(held), "mass": float(mass), "layer": layer or "",
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
        public string name, fbx, prefab, clip_folder, report_path, render_path, layer;
        public float pivot_tolerance, angle_tolerance, penetration_tolerance, mass; public bool held; public Part[] parts;
    }
    [Serializable] public class Socket { public string name; public float[] position; }
    [Serializable] public class Motion
    {
        public string part, kind, clip; public float pivot_drift, angle, travel, penetration; public float[] pivot;
    }
    [Serializable] public class Report
    {
        public string unity_version, prefab, controller, render, default_state; public Motion[] motions;
        public float[] bounds_min, bounds_max; public bool tip_forward, root_inside; public string[] errors, warnings;
        public int colliders; public float rigidbody_mass; public Socket[] sockets; public string[] parameters;
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
        var warnings = new List<string>();
        var controllerPath = request.clip_folder + "/" + request.name + ".controller";
        var controller = AnimatorController.CreateAnimatorControllerAtPath(controllerPath);
        // A game script drives the parts: Rest by default, a trigger "<part>" pulses rest -> limit -> rest, a bool
        // "<part>_open" holds the part at its limit while set.
        var machine = controller.layers[0].stateMachine;
        var rest = machine.AddState("Rest");
        machine.defaultState = rest;
        var parameters = new List<string>();
        var motions = new List<Motion>();
        var sockets = new List<Socket>();
        foreach (var part in request.parts)
        {
            var transform = root.GetComponentsInChildren<Transform>().FirstOrDefault(t => t.name == part.name);
            if (transform == null) { errors.Add("part " + part.name + " is not in the model"); continue; }
            var axis = part.axis == "x" ? Vector3.right : part.axis == "y" ? Vector3.up : Vector3.forward;
            // The root's axis in the part's space. The imported FBX root is scaled (100 with the importer's 0.01
            // file scale), so a slide's travel goes through the parent's scale too: 0.03 m once moved 3 m.
            var local = transform.parent.InverseTransformDirection(axis);
            var path = AnimationUtility.CalculateTransformPath(transform, root.transform);
            var restPosition = transform.localPosition;
            var restRotation = transform.localRotation;
            var clip = Pulse(request.name + "_" + part.name, transform, path, axis, part.kind, part.limit);
            var clipPath = request.clip_folder + "/" + clip.name + ".anim";
            AssetDatabase.CreateAsset(clip, clipPath);
            // the hold: one key at the limit, so the part stays there while "<part>_open" is set
            var hold = new AnimationClip { name = request.name + "_" + part.name + "_open" };
            if (part.kind == "slide")
                Curve(hold, path, "m_LocalPosition", new[] { restPosition + transform.parent.InverseTransformVector(axis * part.limit) });
            else
                Curve(hold, path, "m_LocalRotation", new[] { restRotation * Quaternion.AngleAxis(part.limit, local) });
            var holdPath = request.clip_folder + "/" + hold.name + ".anim";
            AssetDatabase.CreateAsset(hold, holdPath);
            controller.AddParameter(part.name, AnimatorControllerParameterType.Trigger);
            controller.AddParameter(part.name + "_open", AnimatorControllerParameterType.Bool);
            parameters.Add(part.name); parameters.Add(part.name + "_open");
            var pulse = machine.AddState(part.name); pulse.motion = clip;
            var pulseIn = rest.AddTransition(pulse); pulseIn.AddCondition(AnimatorConditionMode.If, 0, part.name);
            pulseIn.hasExitTime = false; pulseIn.duration = 0f;
            var pulseOut = pulse.AddTransition(rest); pulseOut.hasExitTime = true; pulseOut.exitTime = 1f; pulseOut.duration = 0f;
            var open = machine.AddState(part.name + "_open"); open.motion = hold;
            var openIn = rest.AddTransition(open); openIn.AddCondition(AnimatorConditionMode.If, 0, part.name + "_open");
            openIn.hasExitTime = false; openIn.duration = 0.25f;
            var openOut = open.AddTransition(rest); openOut.AddCondition(AnimatorConditionMode.IfNot, 0, part.name + "_open");
            openOut.hasExitTime = false; openOut.duration = 0.25f;
            motions.Add(Check(root, transform, clip, clipPath, part, axis, request, errors));
            // a socket at the part's pivot, parented to the part so it follows it
            sockets.Add(AddSocket(transform, "Socket_" + part.name, transform.position));
        }
        root.AddComponent<Animator>().runtimeAnimatorController = controller;
        // Physics: a convex collider per mesh (a part's collider moves with it), a Rigidbody on the root
        var colliders = 0;
        foreach (var filter in root.GetComponentsInChildren<MeshFilter>())
        {
            var collider = filter.gameObject.AddComponent<MeshCollider>();
            collider.sharedMesh = filter.sharedMesh;
            collider.convex = true;
            colliders++;
        }
        var body = root.AddComponent<Rigidbody>();
        body.mass = request.mass;
        if (!string.IsNullOrEmpty(request.layer))
        {
            var layer = LayerMask.NameToLayer(request.layer);
            if (layer < 0) warnings.Add("the project has no layer named " + request.layer + "; the prefab stays on Default");
            else foreach (var t in root.GetComponentsInChildren<Transform>()) t.gameObject.layer = layer;
        }
        var box = WorldBounds(root);
        var tipForward = box.max.z > -box.min.z;
        var rootInside = box.Contains(root.transform.position);
        if (request.held)
        {
            if (!tipForward) errors.Add("the weapon does not point along +Z from its root");
            if (!rootInside) errors.Add("the root (grip) lies outside the weapon's bounds");
            // Sockets a character holds and fires from: the grip at the root, the muzzle at the body's +Z end
            sockets.Add(AddSocket(root.transform, "Socket_Grip", root.transform.position));
            sockets.Add(AddSocket(root.transform, "Socket_Muzzle", MuzzlePoint(root, request)));
        }
        Render(root, request, request.render_path);
        var prefab = PrefabUtility.SaveAsPrefabAsset(root, request.prefab);
        UnityEngine.Object.DestroyImmediate(root);
        AssetDatabase.SaveAssets();
        File.WriteAllText(request.report_path, JsonUtility.ToJson(new Report
        {
            unity_version = Application.unityVersion, prefab = AssetDatabase.GetAssetPath(prefab),
            controller = controllerPath, render = request.render_path, motions = motions.ToArray(),
            bounds_min = Floats(box.min), bounds_max = Floats(box.max), tip_forward = tipForward,
            root_inside = rootInside, errors = errors.ToArray(), warnings = warnings.ToArray(),
            colliders = colliders, rigidbody_mass = request.mass, sockets = sockets.ToArray(),
            parameters = parameters.ToArray(), default_state = "Rest"
        }));
        Debug.Log("SLOPFORGE_WEAPON_PREFAB " + request.prefab);
    }

    // One pulse rest -> limit -> rest (1 s). The root's axis is taken into the part's space: the imported FBX root
    // is scaled (100 with the importer's 0.01 file scale), so a slide's travel goes through the parent's scale too.
    static AnimationClip Pulse(string name, Transform transform, string path, Vector3 axis, string kind, float limit)
    {
        var clip = new AnimationClip { name = name };
        var rest = transform.localPosition; var restRotation = transform.localRotation;
        if (kind == "slide")
            Curve(clip, path, "m_LocalPosition", new[] { rest, rest + transform.parent.InverseTransformVector(axis * limit), rest });
        else
            Curve(clip, path, "m_LocalRotation", new[] { restRotation,
                restRotation * Quaternion.AngleAxis(limit, transform.parent.InverseTransformDirection(axis)), restRotation });
        return clip;
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
        motion.penetration = Penetration(root, part, clip, request);
        if (motion.penetration > request.penetration_tolerance)
        {
            // A hinge's usual cause is the range's sign (docs/WEAPONS.md, Axes): say so when the mirrored range clears.
            // A slide's opposite direction leaves the body almost always, which says nothing about the right one.
            var mirrored = declared.kind != "hinge" ? 1f : Penetration(root, part, Pulse(clip.name + "_mirrored", part,
                AnimationUtility.CalculateTransformPath(part, root.transform), axis, declared.kind, -declared.limit), request);
            errors.Add(label + " penetrates the body through its range (" +
                       motion.penetration.ToString("F3", CultureInfo.InvariantCulture) + " of its vertices inside, over rest" +
                       (mirrored <= request.penetration_tolerance ? "; the opposite sign, " +
                        (-declared.limit).ToString("G", CultureInfo.InvariantCulture) + ", clears the body at " +
                        mirrored.ToString("F3", CultureInfo.InvariantCulture) : "") + ")");
        }
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

    // The part's vertices inside the rest of the model, sampled through its clip: a lid swinging into its chest, a
    // drawer travelling past its housing. A vertex is inside where the body's winding number is over a half
    // (Winding). The share over the rest pose is reported.
    static float Penetration(GameObject root, Transform part, AnimationClip clip, Request request)
    {
        // The body's triangles in world space; it stays still while the part's clip is sampled.
        var names = new HashSet<string>(request.parts.Select(p => p.name));
        var corners = new List<Vector3>();
        foreach (var filter in root.GetComponentsInChildren<MeshFilter>())
        {
            if (names.Contains(filter.name) || filter.transform.IsChildOf(part)) continue;
            var points = filter.sharedMesh.vertices;
            foreach (var index in filter.sharedMesh.triangles) corners.Add(filter.transform.TransformPoint(points[index]));
        }
        var mesh = part.GetComponentInChildren<MeshFilter>()?.sharedMesh;
        if (mesh == null || corners.Count == 0) return 0f;
        var body = corners.ToArray();
        var step = Mathf.Max(1, mesh.vertexCount / 400);
        var vertices = mesh.vertices.Where((v, i) => i % step == 0).ToArray();
        var shares = new List<float>();
        AnimationMode.StartAnimationMode();
        for (var sample = 0; sample <= 8; sample++)
        {
            AnimationMode.SampleAnimationClip(root, clip, 0.5f * sample / 8f);
            var filter = part.GetComponentInChildren<MeshFilter>();
            var inside = vertices.Count(vertex => Math.Abs(Winding(filter.transform.TransformPoint(vertex), body)) > 0.5);
            shares.Add((float)inside / vertices.Length);
        }
        AnimationMode.SampleAnimationClip(root, clip, 0f);
        AnimationMode.StopAnimationMode();
        return Mathf.Max(0f, shares.Max() - shares[0]);
    }

    // The generalized winding number of a point about triangles (three corners each): about 1 inside a closed
    // surface and 0 outside, and near that where it has holes. Generated bodies are open, so a ray's parity lied
    // (a hybrid pistol's open body held half its slide by parity, 2026-10-25); the Blender sweep
    // (mesh_cleanup.sweep_penetration) measures the same way.
    static double Winding(Vector3 point, Vector3[] corners)
    {
        double total = 0;
        for (var i = 0; i + 2 < corners.Length; i += 3)
        {
            Vector3 a = corners[i] - point, b = corners[i + 1] - point, c = corners[i + 2] - point;
            double la = a.magnitude, lb = b.magnitude, lc = c.magnitude;
            total += Math.Atan2(Vector3.Dot(a, Vector3.Cross(b, c)),
                                la * lb * lc + Vector3.Dot(a, b) * lc + Vector3.Dot(b, c) * la + Vector3.Dot(c, a) * lb);
        }
        return total / (2 * Math.PI);
    }

    static Socket AddSocket(Transform parent, string name, Vector3 position)
    {
        var socket = new GameObject(name);
        socket.transform.SetParent(parent, false);
        socket.transform.position = position;
        return new Socket { name = name, position = Floats(position) };
    }

    // The centroid of the body's vertices within 1% of its +Z extreme: where a held weapon fires from.
    static Vector3 MuzzlePoint(GameObject root, Request request)
    {
        var parts = new HashSet<string>(request.parts.Select(p => p.name));
        var points = new List<Vector3>();
        foreach (var filter in root.GetComponentsInChildren<MeshFilter>())
        {
            if (parts.Contains(filter.name)) continue;
            foreach (var vertex in filter.sharedMesh.vertices) points.Add(filter.transform.TransformPoint(vertex));
        }
        if (points.Count == 0) return WorldBounds(root).max;
        var maxZ = points.Max(p => p.z); var minZ = points.Min(p => p.z);
        var front = points.Where(p => p.z >= maxZ - 0.01f * (maxZ - minZ)).ToList();
        return new Vector3(front.Average(p => p.x), front.Average(p => p.y), front.Average(p => p.z));
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
