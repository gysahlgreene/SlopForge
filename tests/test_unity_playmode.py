"""Play-mode verification of a published prefab: the script it writes and the NUnit results it reads."""
import tempfile
import unittest
from pathlib import Path

from slopforge.unity_playmode import (creature_play_script, editor_binary, parse_test_results, play_mode_script,
                                      read_measures, verify_play_mode)

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

    def test_the_creature_script_checks_facing_size_playback_and_in_place_per_clip(self):
        script = creature_play_script(
            "Assets/Generated/Creatures/wolf/Unity/wolf.prefab",
            [{"state": "walk_s2", "length_s": 1.6875, "speed_mps": 0.41, "stride_m": 0.7}], height=0.78,
            front=["FrontPaw.L", "FrontPaw.R"], hind=["HindPaw.L", "HindPaw.R"], root_bone="Hips",
            measures="/project/wolf_playmode.jsonl")
        self.assertIn('"Assets/Generated/Creatures/wolf/Unity/wolf.prefab"', script)
        self.assertIn("const float Height = 0.78f;", script)
        self.assertIn('new string[] {"FrontPaw.L", "FrontPaw.R"}', script)
        self.assertIn('new string[] {"HindPaw.L", "HindPaw.R"}', script)
        self.assertIn('"/project/wolf_playmode.jsonl"', script)
        self.assertIn("public void FacesForwardAtItsSize()", script)
        self.assertIn("public IEnumerator PlaysOnItsOwn()", script)   # the default state, in real time
        # 2026-10-30 live: a clip's root curves landed on the prefab's own transform and scaled it 100x
        self.assertIn("did not keep its own rotation and scale", script)
        self.assertIn('[TestCase("walk_s2", 1.6875f, 0.41f, ExpectedResult = null)]', script)   # Plays
        self.assertIn('[TestCase("walk_s2", 0.7f, 0.41f, ExpectedResult = null)]', script)      # InPlace
        self.assertIn("the root bone does not move", script)   # an unanimated root would pass in place vacuously

    def test_the_play_mode_run_takes_its_script_and_leaves_no_test_assembly(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seen = []

            def run(command, **kwargs):
                seen.append((root / "Assets/SlopForgeTests/PlayMode/PrefabPlayTests.cs").read_text())
                Path(command[command.index("-testResults") + 1]).write_text(RESULTS.replace(
                    'result="Failed" duration="1.2">', 'result="Passed" duration="1.2">'))
            with patch("slopforge.unity_playmode.editor_binary", return_value="Unity"), \
                    patch("slopforge.unity_playmode.subprocess.run", side_effect=run):
                report = verify_play_mode(root, "// the creature's tests", results=root / "out/results.xml")
            self.assertEqual(seen, ["// the creature's tests"])
            self.assertEqual(len(report["passed"]), 3)
            self.assertFalse((root / "Assets/SlopForgeTests").exists())

    def test_a_run_that_writes_no_results_fails_even_with_an_old_results_file(self):
        # review 2026-10-30: a failed run's results stay beside the prefab; a later run that never played (editor
        # crash, compile error) would have read them back as a pass
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "out").mkdir()
            (root / "out/results.xml").write_text(RESULTS.replace('result="Failed" duration="1.2">',
                                                                  'result="Passed" duration="1.2">'))
            with patch("slopforge.unity_playmode.editor_binary", return_value="Unity"), \
                    patch("slopforge.unity_playmode.subprocess.run"), self.assertRaises(Exception) as caught:
                verify_play_mode(root, "// tests", results=root / "out/results.xml")
            self.assertIn("wrote no results", str(caught.exception))

    def test_the_creature_measures_merge_into_the_facing_and_one_record_per_clip(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wolf_playmode.jsonl"
            path.write_text('{"faces_margin_m": 0.42, "height_m": 0.781}\n'
                            '{"clip": "walk_s2", "length_s": 1.6875}\n'
                            '{"clip": "walk_s2", "root_excursion_m": 0.04, "stance_slide_mps": 0.06}\n')
            self.assertEqual(read_measures(path), {"faces_margin_m": 0.42, "height_m": 0.781, "clips": {
                "walk_s2": {"length_s": 1.6875, "root_excursion_m": 0.04, "stance_slide_mps": 0.06}}})

    def test_results_name_the_failed_tests_with_their_messages(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "results.xml"
            path.write_text(RESULTS)
            report = parse_test_results(path)
        self.assertEqual(report["passed"], ['PartPulses("slide")', "RestsOnTheGround"])
        self.assertEqual(report["failed"], [{"name": 'PartPulses("trigger")', "message": "trigger did not move: angle 0.00"}])


if __name__ == "__main__":
    unittest.main()
