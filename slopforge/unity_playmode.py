"""Play-mode verification of a published prefab through the Unity Test Framework (docs/UNITY.md).

The editor checks (unity_weapon.py) sample the clips; a game runs the Animator and the physics. This writes a
play-mode test assembly into the project, runs it with Unity's test runner, and reads the NUnit results: each
part's trigger moves it and brings it back, and the Rigidbody settles on a floor instead of falling through.
"""
import json
import os
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
    version_file = Path(project_root) / "ProjectSettings/ProjectVersion.txt"
    version = next((line.split(":", 1)[1].strip() for line in version_file.read_text().splitlines()
                    if line.startswith("m_EditorVersion:")), "")
    binary = HUB_EDITORS / version / "Unity.app/Contents/MacOS/Unity"
    if not binary.is_file():
        raise StageFailure("environment", f"Unity editor {version} is not installed under {HUB_EDITORS}",
                           operation="play_mode_preflight",
                           remedy=f"install editor {version} with the Hub, or set UNITY_EDITOR_PATH to its binary")
    return binary


def play_mode_script(prefab_asset_path, parts):
    """The NUnit play-mode tests for one prefab: a pulse per hinge or slide, and the physics settle."""
    # a parameterised coroutine test needs ExpectedResult = null, or NUnit reports "non-void return value"
    cases = "\n".join(f'    [TestCase("{part["name"]}", ExpectedResult = null)]'
                      for part in parts if part["kind"] in ("hinge", "slide"))
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

{cases}
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

    [UnityTest]
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


def verify_play_mode(project_root, prefab, parts, *, results):
    """Run the play-mode tests for `prefab` (an Assets path) in the project; writes `results` (NUnit XML) and
    returns parse_test_results' report. Raises StageFailure naming the failed tests."""
    root = Path(project_root).resolve()
    editor = editor_binary(root)
    folder = root / TEST_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SlopForgePlayMode.asmdef").write_text(json.dumps(ASSEMBLY, indent=2) + "\n")
    (folder / "PrefabPlayTests.cs").write_text(play_mode_script(prefab, parts))
    results = Path(results).resolve()
    results.parent.mkdir(parents=True, exist_ok=True)
    log = results.with_suffix(".log")
    try:
        subprocess.run([str(editor), "-batchmode", "-projectPath", str(root), "-logFile", str(log), "-runTests",
                        "-testPlatform", "PlayMode", "-testResults", str(results), "-assemblyNames", "SlopForgePlayMode"],
                       capture_output=True, text=True, check=False, timeout=1200)
    except subprocess.TimeoutExpired:
        raise StageFailure("environment", "Unity's play-mode test run did not finish in 20 minutes",
                           operation="play_mode_verification", remedy=f"read {log}") from None
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
            remedy="check the prefab's Animator and colliders in Play mode; the results file names each failure")
    return report
