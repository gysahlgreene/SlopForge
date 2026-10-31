"""Play-mode verification of a published prefab through the Unity Test Framework (docs/UNITY.md).

The editor checks (unity_weapon.py) sample the clips; a game runs the Animator and the physics. This writes a
play-mode test assembly into the project, runs it with Unity's test runner, and reads the NUnit results: each
part's trigger moves it and brings it back, and the Rigidbody settles on a floor instead of falling through.
"""
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from .failures import StageFailure

TEST_FOLDER = "Assets/SlopForgeTests/PlayMode"
HUB_EDITORS = Path("/Applications/Unity/Hub/Editor")  # the Hub's install folder; UNITY_EDITOR_PATH overrides


def editor_binary(project_root):
    """The editor that opens this project, launched directly: the `unity` wrapper adds -quit, which ends a
    -runTests run before any test runs. UNITY_EDITOR_PATH names the binary; otherwise the project's version
    under the Hub's install folder."""
    override = os.environ.get("UNITY_EDITOR_PATH")
    if override:
        return Path(override)
    version = editor_version(project_root)
    binary = HUB_EDITORS / version / "Unity.app/Contents/MacOS/Unity"
    if not binary.is_file():
        raise StageFailure("environment", f"Unity editor {version} is not installed under {HUB_EDITORS}",
                           operation="play_mode_preflight",
                           remedy=f"install editor {version} with the Hub, or set UNITY_EDITOR_PATH to its binary")
    return binary


def editor_version(project_root):
    """The editor version the project names (ProjectSettings/ProjectVersion.txt), or "" when it names none."""
    version_file = Path(project_root) / "ProjectSettings/ProjectVersion.txt"
    if not version_file.is_file():
        return ""
    return next((line.split(":", 1)[1].strip() for line in version_file.read_text().splitlines()
                 if line.startswith("m_EditorVersion:")), "")


def play_mode_script(prefab_asset_path, parts):
    """The NUnit play-mode tests for one prefab: a pulse per hinge or slide, and the physics settle."""
    # a parameterised coroutine test needs ExpectedResult = null, or NUnit reports "non-void return value"
    cases = "\n".join(f'    [TestCase("{part["name"]}", ExpectedResult = null)]'
                      for part in parts if part["kind"] in ("hinge", "slide"))
    # NUnit fails a parameterised test with no cases ("No arguments were provided"): a static prefab has no pulse test
    pulses = f"""{cases}
    [UnityTest]
    public IEnumerator PartPulses(string part)
    {{
        var instance = Spawn();
        var body = instance.GetComponent<Rigidbody>();
        if (body != null) body.isKinematic = true;  // the pulse is measured on the part, not on a falling body
        var animator = instance.GetComponent<Animator>();
        Assert.IsNotNull(animator, "no Animator on the prefab");
        var transform = instance.GetComponentsInChildren<Transform>()[0];
        foreach (var t in instance.GetComponentsInChildren<Transform>()) if (t.name == part) transform = t;
        Assert.AreEqual(part, transform.name, "part missing: " + part);
        // world space: the imported root is scaled 100, so a 3 cm travel is 0.0003 in the part's local units
        var restPosition = transform.position; var restRotation = transform.rotation;
        yield return null;
        animator.SetTrigger(part);
        yield return new WaitForSeconds(0.5f);
        var moved = Vector3.Distance(transform.position, restPosition) +
                    Quaternion.Angle(transform.rotation, restRotation) * Mathf.Deg2Rad;
        Assert.Greater(moved, 0.001f, part + " did not move at mid-pulse");
        yield return new WaitForSeconds(1.5f);
        Assert.Less(Vector3.Distance(transform.position, restPosition), 0.002f, part + " did not return (position)");
        Assert.Less(Quaternion.Angle(transform.rotation, restRotation), 0.5f, part + " did not return (rotation)");
        Object.Destroy(instance);
    }}

""" if cases else ""
    return f"""using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEditor;
using UnityEngine.TestTools;

namespace SlopForge
{{
public class PrefabPlayTests
{{
    const string PrefabPath = "{prefab_asset_path}";

    static GameObject Spawn()
    {{
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
        Assert.IsNotNull(prefab, "prefab missing: " + PrefabPath);
        var instance = Object.Instantiate(prefab, new Vector3(0f, 0.5f, 0f), Quaternion.identity);
        return instance;
    }}

{pulses}    [UnityTest]
    public IEnumerator RestsOnTheGround()
    {{
        var floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
        floor.transform.localScale = new Vector3(10f, 1f, 10f);
        var instance = Spawn();
        var body = instance.GetComponent<Rigidbody>();
        Assert.IsNotNull(body, "no Rigidbody on the prefab");
        yield return new WaitForSeconds(3f);
        Assert.Greater(instance.transform.position.y, -0.05f, "fell through the floor: y " + instance.transform.position.y);
        Assert.Less(body.linearVelocity.magnitude, 0.05f, "still moving after 3 s: " + body.linearVelocity.magnitude);
        Object.Destroy(instance); Object.Destroy(floor);
    }}
}}
}}
"""


def creature_play_script(prefab_asset_path, clips, *, height, front, hind, root_bone, measures):
    """The NUnit play-mode tests for a creature prefab (B7): it faces +Z at the size B1 measured, plays its default
    state on its own, and each clip (`{state, length_s, speed_mps, stride_m}`) loops at its baked length with its
    speed parameter, finite, and in place. `front`/`hind` name each leg's last bone; the facing, size and each clip's
    measures are appended to `measures` as JSON lines (read_measures), the stance slide among them (recorded, not
    gated: D9's foot-slide limit is open)."""
    names = lambda bones: "new string[] {" + ", ".join(json.dumps(bone) for bone in bones) + "}"
    number = lambda value: f"{float(value)!r}f"
    plays = "\n".join(f"    [TestCase({json.dumps(clip['state'])}, {number(clip['length_s'])}, "
                      f"{number(clip['speed_mps'])}, ExpectedResult = null)]" for clip in clips)
    in_place = "\n".join(f"    [TestCase({json.dumps(clip['state'])}, {number(clip['stride_m'])}, "
                         f"{number(clip['speed_mps'])}, ExpectedResult = null)]" for clip in clips)
    return f"""using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using NUnit.Framework;
using UnityEngine;
using UnityEditor;
using UnityEngine.TestTools;

namespace SlopForge
{{
public class CreaturePlayTests
{{
    const string PrefabPath = {json.dumps(prefab_asset_path)};
    const string MeasuresPath = {json.dumps(str(measures))};
    const string RootBone = {json.dumps(root_bone)};
    const float Height = {number(height)};
    const int Samples = 48;
    static readonly string[] Front = {names(front)};
    static readonly string[] Hind = {names(hind)};

    [OneTimeSetUp]
    public void ClearMeasures() {{ if (File.Exists(MeasuresPath)) File.Delete(MeasuresPath); }}

    static void Measure(string json) {{ File.AppendAllText(MeasuresPath, json + "\\n"); }}
    static string Number(float value) {{
        return float.IsNaN(value) ? "null" : value.ToString("R", CultureInfo.InvariantCulture); }}

    static GameObject Spawn()
    {{
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
        Assert.IsNotNull(prefab, "prefab missing: " + PrefabPath);
        return Object.Instantiate(prefab, Vector3.zero, Quaternion.identity);
    }}

    static Transform Bone(GameObject instance, string name)
    {{
        var bone = instance.GetComponentsInChildren<Transform>().FirstOrDefault(t => t.name == name);
        Assert.IsNotNull(bone, "bone missing: " + name);
        return bone;
    }}

    static Vector3 Mean(GameObject instance, string[] bones)
    {{
        var sum = Vector3.zero;
        foreach (var name in bones) sum += Bone(instance, name).position;
        return sum / bones.Length;
    }}

    static Animator Start(GameObject instance, string state)
    {{
        var animator = instance.GetComponent<Animator>();
        Assert.IsNotNull(animator, "no Animator on the prefab");
        animator.Play(state, 0, 0f);
        animator.Update(0f);
        return animator;
    }}

    [Test]
    public void FacesForwardAtItsSize()
    {{
        var instance = Spawn();
        instance.GetComponent<Animator>().enabled = false;   // the bind pose, as B1 measured it
        // a game moves a creature along its transform's +Z, so the front feet lead
        float margin = Mean(instance, Front).z - Mean(instance, Hind).z;
        float low = float.MaxValue, high = float.MinValue;
        // the bind pose baked into the renderer's own space (useScale), then placed by its whole world matrix: an
        // imported mesh is not readable at run time, and the 2026-10-30 live runs measured 1/100 of the creature with
        // that bake placed without the node's FBX scale of 100, and 100x with an unscaled bake placed with it
        foreach (var skin in instance.GetComponentsInChildren<SkinnedMeshRenderer>())
        {{
            var mesh = new Mesh();
            skin.BakeMesh(mesh, true);
            var place = skin.transform.localToWorldMatrix;
            foreach (var vertex in mesh.vertices)
            {{
                float y = place.MultiplyPoint3x4(vertex).y;
                low = Mathf.Min(low, y); high = Mathf.Max(high, y);
            }}
            Object.Destroy(mesh);
        }}
        Object.Destroy(instance);
        Assert.Less(low, high, "no skinned mesh on the prefab");
        Measure("{{\\"faces_margin_m\\": " + Number(margin) + ", \\"height_m\\": " + Number(high - low) + "}}");
        Assert.Greater(margin, 0.1f * Height, "the front feet are not ahead along +Z (by " + margin + " m): a game " +
                       "moves the creature along its +Z");
        Assert.Less(Mathf.Abs((high - low) / Height - 1f), 0.05f, "imported " + (high - low) + " m tall, rigged " +
                    Height + " m");
    }}

    [UnityTest]
    public IEnumerator PlaysOnItsOwn()
    {{
        var instance = Spawn();
        var animator = instance.GetComponent<Animator>();
        Assert.IsNotNull(animator, "no Animator on the prefab");
        Assert.IsFalse(animator.applyRootMotion, "root motion is on: a creature's clips are delivered in place");
        var bones = instance.GetComponentsInChildren<Transform>();
        var rest = bones.Select(t => t.localRotation).ToArray();
        yield return new WaitForSeconds(1f);
        float turned = 0f;
        for (int i = 0; i < bones.Length; i++) turned = Mathf.Max(turned, Quaternion.Angle(rest[i], bones[i].localRotation));
        var moved = instance.transform.position.magnitude;
        var spun = Quaternion.Angle(instance.transform.rotation, Quaternion.identity);
        var scale = instance.transform.localScale;
        var time = animator.GetCurrentAnimatorStateInfo(0).normalizedTime;
        Object.Destroy(instance);
        Assert.Greater(time, 0f, "the default state did not advance in 1 s");
        Assert.Greater(turned, 5f, "no bone turned in 1 s of play");
        Assert.Less(moved, 0.001f, "the creature moved itself " + moved + " m");
        // a clip whose curves miss the rig's hierarchy moves the creature's own transform instead
        Assert.IsTrue(spun < 0.5f && (scale - Vector3.one).magnitude < 0.001f,
                      "the creature did not keep its own rotation and scale (turned " + spun + " deg, scale " + scale +
                      "): the clip's curves miss the rig's hierarchy");
    }}

{plays}
    [UnityTest]
    public IEnumerator Plays(string state, float length, float speed)
    {{
        var instance = Spawn();
        var animator = Start(instance, state);
        yield return null;
        var info = animator.GetCurrentAnimatorStateInfo(0);
        Assert.IsTrue(info.IsName(state), "no state " + state);
        Assert.IsTrue(info.loop, state + " does not loop");
        Assert.Less(Mathf.Abs(info.length - length), 1f / 24f + 0.001f, state + " lasts " + info.length +
                    " s; its loop was baked " + length + " s");
        Assert.AreEqual(speed, animator.GetFloat(state + "_speed"), 0.0001f, "the controller's " + state + "_speed");
        Measure("{{\\"clip\\": \\"" + state + "\\", \\"length_s\\": " + Number(info.length) + "}}");
        var bones = instance.GetComponentsInChildren<Transform>();
        var first = bones.Select(t => t.localRotation).ToArray();
        float turned = 0f;
        for (int k = 0; k < Samples; k++)
        {{
            animator.Play(state, 0, (float)k / Samples);
            animator.Update(0f);
            for (int i = 0; i < bones.Length; i++)
            {{
                var p = bones[i].localPosition; var q = bones[i].localRotation;
                float sum = p.x + p.y + p.z + q.x + q.y + q.z + q.w;
                Assert.IsFalse(float.IsNaN(sum) || float.IsInfinity(sum), bones[i].name + " is not finite in " +
                               state + " at " + k + "/" + Samples);
                turned = Mathf.Max(turned, Quaternion.Angle(first[i], q));
            }}
        }}
        Object.Destroy(instance);
        Assert.Greater(turned, 5f, state + ": no bone turns more than 5 degrees over its loop");
    }}

{in_place}
    [UnityTest]
    public IEnumerator InPlace(string state, float stride, float speed)
    {{
        var instance = Spawn();
        var animator = Start(instance, state);
        yield return null;
        float length = animator.GetCurrentAnimatorStateInfo(0).length;
        var root = Bone(instance, RootBone);
        var feet = Front.Concat(Hind).Select(name => Bone(instance, name)).ToArray();
        var track = new Vector3[Samples];
        var steps = new Vector3[feet.Length, Samples];
        for (int k = 0; k < Samples; k++)
        {{
            animator.Play(state, 0, (float)k / Samples);
            animator.Update(0f);
            track[k] = root.position;
            for (int f = 0; f < feet.Length; f++) steps[f, k] = feet[f].position;
        }}
        Object.Destroy(instance);
        // the root bone sways, but a walk that kept its travel moves a whole stride every period
        float excursion = 0f, span = 0f;
        foreach (var a in track)
            foreach (var b in track)
            {{
                excursion = Mathf.Max(excursion, new Vector2(a.x - b.x, a.z - b.z).magnitude);
                span = Mathf.Max(span, (a - b).magnitude);
            }}
        Assert.Greater(span, 0.001f, state + ": the root bone does not move, so in place proves nothing: its curves " +
                       "miss " + RootBone);
        // D9: moved along +Z at the recorded speed, a planted foot holds still (the bake's stance slide)
        float dt = length / Samples;
        var slides = new List<float>();
        for (int f = 0; f < feet.Length; f++)
        {{
            var heights = Enumerable.Range(0, Samples).Select(k => steps[f, k].y).OrderBy(y => y).ToArray();
            float planted = heights[Samples / 10] + 0.01f * Height;
            for (int k = 0; k < Samples; k++)
            {{
                int next = (k + 1) % Samples;
                if (steps[f, k].y > planted || steps[f, next].y > planted) continue;
                var moved = steps[f, next] - steps[f, k] + Vector3.forward * speed * dt;
                slides.Add(new Vector2(moved.x, moved.z).magnitude / dt);
            }}
        }}
        slides.Sort();
        float slide = slides.Count > 0 ? slides[slides.Count / 2] : float.NaN;
        Measure("{{\\"clip\\": \\"" + state + "\\", \\"root_excursion_m\\": " + Number(excursion) +
                ", \\"stance_slide_mps\\": " + Number(slide) + "}}");
        Assert.Less(excursion, stride / 4f, state + "'s root bone travels " + excursion + " m in a loop; its stride is " +
                    stride + " m: it is not in place");
    }}
}}
}}
"""


def read_measures(path):
    """The creature tests' JSON lines as one record: the facing and size, then each clip's measures."""
    measured = {"clips": {}}
    for line in Path(path).read_text().splitlines():
        item = json.loads(line)
        clip = item.pop("clip", None)
        (measured["clips"].setdefault(clip, {}) if clip else measured).update(item)
    return measured


ASSEMBLY = {"name": "SlopForgePlayMode", "references": ["UnityEngine.TestRunner", "UnityEditor.TestRunner"],
            "includePlatforms": [], "excludePlatforms": [], "allowUnsafeCode": False, "overrideReferences": True,
            "precompiledReferences": ["nunit.framework.dll"], "autoReferenced": False,
            "defineConstraints": ["UNITY_INCLUDE_TESTS"], "versionDefines": [], "noEngineReferences": False}


def parse_test_results(path):
    """NUnit 3 results from Unity's -testResults file: the passed test names and each failure with its message."""
    root = ElementTree.parse(path).getroot()
    report = {"passed": [], "failed": []}
    for case in root.iter("test-case"):
        if case.get("result") == "Passed":
            report["passed"].append(case.get("name"))
        else:
            message = case.find("failure/message")
            report["failed"].append({"name": case.get("name"),
                                     "message": (message.text or "").strip() if message is not None else case.get("result")})
    return report


def verify_play_mode(project_root, script, *, results, remedy=None):
    """Run a play-mode test script (play_mode_script, creature_play_script) in the project; writes `results` (NUnit
    XML) and returns parse_test_results' report. Raises StageFailure naming the failed tests, with `remedy` (the
    prefab checks' by default)."""
    root = Path(project_root).resolve()
    editor = editor_binary(root)
    folder = root / TEST_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SlopForgePlayMode.asmdef").write_text(json.dumps(ASSEMBLY, indent=2) + "\n")
    (folder / "PrefabPlayTests.cs").write_text(script)
    results = Path(results).resolve()
    results.parent.mkdir(parents=True, exist_ok=True)
    results.unlink(missing_ok=True)   # an earlier run's results must not answer for a run that never played
    log = results.with_suffix(".log")
    try:
        subprocess.run([str(editor), "-batchmode", "-projectPath", str(root), "-logFile", str(log), "-runTests",
                        "-testPlatform", "PlayMode", "-testResults", str(results), "-assemblyNames", "SlopForgePlayMode"],
                       capture_output=True, text=True, check=False, timeout=1200)
    except subprocess.TimeoutExpired:
        raise StageFailure("environment", "Unity's play-mode test run did not finish in 20 minutes",
                           operation="play_mode_verification", remedy=f"read {log}") from None
    finally:  # the test assembly is SlopForge's scaffolding, not the project's: it leaves with its .meta files
        shutil.rmtree(folder, ignore_errors=True)
        for parent in (folder.parent, folder):
            Path(str(parent) + ".meta").unlink(missing_ok=True)
        if folder.parent.is_dir() and not any(folder.parent.iterdir()):
            folder.parent.rmdir()
    if not results.is_file():
        tail = log.read_text(errors="replace")[-3000:] if log.is_file() else ""
        raise StageFailure("environment", "Unity's play-mode test run wrote no results",
                           operation="play_mode_verification",
                           remedy=f"read {log}: a compile error in the project or a missing com.unity.test-framework "
                                  "package stops the run before the tests; see docs/UNITY.md\n" + tail)
    report = parse_test_results(results)
    if report["failed"]:
        raise StageFailure("processing_validation", "play-mode checks failed: " + "; ".join(
            f"{item['name']}: {item['message']}" for item in report["failed"]), operation="play_mode_verification",
            remedy=remedy or "check the prefab's Animator and colliders in Play mode; the results file names each failure")
    return report
