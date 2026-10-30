"""B7 in real Blender and Unity: the B1 fixture quadruped's keyed walk, baked by B6's bake, built into a fresh Unity
project as a Generic controller and prefab and played through Unity's test runner. Opt in with
SLOPFORGE_RUN_UNITY_ANIMATION=1; it needs Blender, the `unity` CLI and editor 6000.6.3f1 under the Hub (or
UNITY_EDITOR_PATH), and resolves com.unity.test-framework on first open."""
import json
import os
import shutil

import pytest

from slopforge.unity_animation import build_animator
from slopforge.unity_playmode import creature_play_script, read_measures, verify_play_mode
from tests.test_creature_bake_blender import bake, walk  # noqa: F401

pytestmark = pytest.mark.skipif(os.environ.get("SLOPFORGE_RUN_UNITY_ANIMATION") != "1",
                                reason="set SLOPFORGE_RUN_UNITY_ANIMATION=1 to build and play in Unity")
PACKAGES = {"dependencies": {"com.unity.test-framework": "1.8.0", "com.unity.modules.animation": "1.0.0"}}


def test_a_baked_walk_plays_in_place_facing_forward_at_its_size_in_unity(walk, tmp_path):  # noqa: F811
    report, request = bake(walk["root"] / "for_unity", walk, [k / 16 for k in range(121)])
    assert report["status"] == "complete", report.get("errors")
    project = tmp_path / "Unity"
    (project / "ProjectSettings").mkdir(parents=True)
    (project / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
    (project / "Packages").mkdir()
    (project / "Packages/manifest.json").write_text(json.dumps(PACKAGES))
    folder = project / "Assets/Creatures/quad"
    folder.mkdir(parents=True)
    shutil.copy(walk["root"] / "rig.fbx", folder / "quad_rig.fbx")
    shutil.copy(request["fbx"], folder / "walk.fbx")

    clip = {"state": "walk", "path": "Assets/Creatures/quad/walk.fbx", "loop": True, "root_motion": False,
            "speed": report["speed_mps"]}
    controller, prefab = build_animator(project, "quad", folder / "quad_rig.fbx", [clip], folder / "Unity")
    assert controller.is_file() and prefab.is_file()
    feet = {end: [chain[-1] for leg, chain in sorted(walk["chains"].items()) if leg.startswith(end)]
            for end in ("front", "hind")}
    window = report["window"]
    measures = folder / "Unity/quad_playmode.jsonl"
    script = creature_play_script(
        prefab.relative_to(project).as_posix(),
        [{"state": "walk", "length_s": window["end_s"] - window["start_s"], "speed_mps": report["speed_mps"],
          "stride_m": report["stride_m"]}],
        height=report["height_m"], front=feet["front"], hind=feet["hind"], root_bone="Hips", measures=measures)
    played = verify_play_mode(project, script, results=folder / "Unity/quad_playmode.xml")

    assert played["failed"] == []
    assert len(played["passed"]) == 4 and {"FacesForwardAtItsSize", "PlaysOnItsOwn"} <= set(played["passed"])
    assert [name.split("(")[0] for name in sorted(played["passed"]) if name.endswith(")")] == ["InPlace", "Plays"]
    measured = read_measures(measures)
    assert measured["faces_margin_m"] > 0 and abs(measured["height_m"] / report["height_m"] - 1) < 0.05
    assert abs(measured["clips"]["walk"]["length_s"] - (window["end_s"] - window["start_s"])) < 1 / 24
    assert measured["clips"]["walk"]["root_excursion_m"] < report["stride_m"] / 4
