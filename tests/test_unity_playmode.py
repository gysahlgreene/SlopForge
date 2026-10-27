"""Play-mode verification of a published prefab: the script it writes and the NUnit results it reads."""
import tempfile
import unittest
from pathlib import Path

from slopforge.unity_playmode import editor_binary, parse_test_results, play_mode_script

RESULTS = """<?xml version="1.0" encoding="utf-8"?>
<test-run id="2" testcasecount="3" result="Failed" total="3" passed="2" failed="1">
  <test-suite type="Assembly" name="SlopForgePlayMode.dll" result="Failed">
    <test-case id="1001" name="PartPulses(&quot;slide&quot;)" fullname="SlopForge.PrefabPlayTests.PartPulses(&quot;slide&quot;)" result="Passed" duration="1.2" />
    <test-case id="1002" name="PartPulses(&quot;trigger&quot;)" fullname="SlopForge.PrefabPlayTests.PartPulses(&quot;trigger&quot;)" result="Failed" duration="1.2">
      <failure><message><![CDATA[trigger did not move: angle 0.00]]></message></failure>
    </test-case>
    <test-case id="1003" name="RestsOnTheGround" fullname="SlopForge.PrefabPlayTests.RestsOnTheGround" result="Passed" duration="2.1" />
  </test-suite>
</test-run>
"""


class PlayModeScriptTests(unittest.TestCase):
    def test_the_script_plays_every_part_and_drops_the_prefab_on_a_floor(self):
        script = play_mode_script("Assets/Art/Generated/Weapons/pistol/pistol.prefab",
                                 [{"name": "slide", "kind": "slide"}, {"name": "trigger", "kind": "hinge"}])
        self.assertIn("[UnityTest]", script)
        self.assertIn('"Assets/Art/Generated/Weapons/pistol/pistol.prefab"', script)
        self.assertIn('[TestCase("slide", ExpectedResult = null)]', script)
        self.assertIn('[TestCase("trigger", ExpectedResult = null)]', script)
        self.assertIn("SetTrigger(part)", script)  # the Animator parameter a game sets
        self.assertIn("RestsOnTheGround", script)  # physics: the Rigidbody settles on a floor, does not fall through

    def test_a_static_prefab_plays_only_the_physics_check(self):
        # 2026-10-27 live run (a supply crate, the prop type's static prefab): a parameterised test with no cases
        # fails in NUnit ("No arguments were provided"), so every static prop's publication failed in Play mode.
        for parts in ([], [{"name": "grip", "kind": "grip"}]):
            script = play_mode_script("Assets/Art/Generated/Models/supply_crate/supply_crate.prefab", parts)
            self.assertNotIn("PartPulses", script)
            self.assertIn("RestsOnTheGround", script)

    def test_the_editor_binary_comes_from_the_project_version_or_the_environment(self):
        # The `unity` wrapper adds -quit, which ends a -runTests run before any test runs (2026-10-25), so the
        # editor is launched directly: the project's version under the Hub's install folder, or UNITY_EDITOR_PATH.
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\nm_EditorVersionWithRevision: 6000.6.3f1 (abc)\n")
            hub = root / "Hub/Editor/6000.6.3f1/Unity.app/Contents/MacOS"; hub.mkdir(parents=True); (hub / "Unity").write_bytes(b"")
            with patch.dict("os.environ", {"UNITY_EDITOR_PATH": ""}), patch("slopforge.unity_playmode.HUB_EDITORS", root / "Hub/Editor"):
                self.assertEqual(editor_binary(root), hub / "Unity")
            with patch.dict("os.environ", {"UNITY_EDITOR_PATH": str(hub / "Unity")}), patch("slopforge.unity_playmode.HUB_EDITORS", root / "elsewhere"):
                self.assertEqual(editor_binary(root), hub / "Unity")
            with patch.dict("os.environ", {"UNITY_EDITOR_PATH": ""}), patch("slopforge.unity_playmode.HUB_EDITORS", root / "elsewhere"):
                with self.assertRaises(Exception) as caught:
                    editor_binary(root)
                self.assertIn("6000.6.3f1", str(caught.exception))

    def test_results_name_the_failed_tests_with_their_messages(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "results.xml"
            path.write_text(RESULTS)
            report = parse_test_results(path)
        self.assertEqual(report["passed"], ['PartPulses("slide")', "RestsOnTheGround"])
        self.assertEqual(report["failed"], [{"name": 'PartPulses("trigger")', "message": "trigger did not move: angle 0.00"}])


if __name__ == "__main__":
    unittest.main()
