import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from slopforge import unity_weapon
from slopforge.unity_weapon import build_weapon_prefab

UNITY_PROJECT = os.environ.get("SLOPFORGE_UNITY_PROJECT")
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"


class WeaponPrefabRequestTests(unittest.TestCase):
    def test_a_static_prop_gets_a_prefab_with_physics_and_no_held_checks(self):
        # Every published model asset gets a prefab: convex colliders, a Rigidbody, a layer; the tip and root
        # checks are for held weapons only.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
            (root / "Assets/Art/Generated/Models/chest").mkdir(parents=True)
            (root / "Assets/Art/Generated/Models/chest/chest.fbx").write_bytes(b"fbx")
            seen = {}

            def unity(command, **_kwargs):
                script = next(path for path in (root / "Assets/Editor").glob("SlopForgeWeapon_*.cs"))
                text = script.read_text()
                request_path = text.split("File.ReadAllText(")[1].split(")")[0]
                seen["request"] = json.loads(Path(json.loads(request_path)).read_text())
                seen["script"] = text
                Path(seen["request"]["report_path"]).write_text(json.dumps({"errors": [], "motions": []}))

            with patch("slopforge.unity_material.shutil.which", return_value="/usr/bin/unity"), \
                    patch.object(unity_weapon.subprocess, "run", side_effect=unity):
                build_weapon_prefab(root, "chest", root / "Assets/Art/Generated/Models/chest/chest.fbx", [],
                                    prefab=root / "Assets/Art/Generated/Models/chest/chest.prefab",
                                    clip_folder=root / "Assets/Art/Generated/Models/chest/Animations",
                                    render=root / "motion.png", held=False, mass=25.0, layer="Props")
            self.assertEqual((seen["request"]["parts"], seen["request"]["held"], seen["request"]["mass"],
                              seen["request"]["layer"]), ([], False, 25.0, "Props"))
            for needle in ("MeshCollider", "convex = true", "Rigidbody", "\"Rest\"", "AddParameter", "Socket_"):
                self.assertIn(needle, seen["script"])

    def test_the_request_names_each_part_and_the_limit_farther_from_rest(self):
        parts = [{"name": "slide", "kind": "slide", "axis": "z", "min": -0.03, "max": 0.0},
                 {"name": "trigger", "kind": "hinge", "axis": "x", "min": -20.0, "max": 0.0}]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
            (root / "Assets/Art/Generated/Weapons/pistol").mkdir(parents=True)
            (root / "Assets/Art/Generated/Weapons/pistol/pistol.fbx").write_bytes(b"fbx")
            seen = {}

            def unity(command, **_kwargs):
                script = next(path for path in (root / "Assets/Editor").glob("SlopForgeWeapon_*.cs"))
                request_path = script.read_text().split("File.ReadAllText(")[1].split(")")[0]
                seen["request"] = json.loads(Path(json.loads(request_path)).read_text())
                Path(seen["request"]["report_path"]).write_text(json.dumps({"errors": [], "motions": []}))
                seen["command"] = command

            with patch("slopforge.unity_material.shutil.which", return_value="/usr/bin/unity"), \
                    patch.object(unity_weapon.subprocess, "run", side_effect=unity):
                report = build_weapon_prefab(root, "pistol", root / "Assets/Art/Generated/Weapons/pistol/pistol.fbx",
                                             parts, prefab=root / "Assets/Art/Generated/Weapons/pistol/pistol.prefab",
                                             clip_folder=root / "Assets/Art/Generated/Weapons/pistol/Animations",
                                             render=root / "motion.png", layer="Weapons")
            self.assertEqual(report["errors"], [])
            self.assertEqual([(part["name"], part["kind"], part["axis"], part["limit"]) for part in seen["request"]["parts"]],
                             [("slide", "slide", "z", -0.03), ("trigger", "hinge", "x", -20.0)])
            self.assertEqual((seen["request"]["held"], seen["request"]["mass"], seen["request"]["layer"]), (True, 1.0, "Weapons"))
            self.assertEqual(seen["request"]["fbx"], "Assets/Art/Generated/Weapons/pistol/pistol.fbx")
            self.assertEqual(seen["request"]["clip_folder"], "Assets/Art/Generated/Weapons/pistol/Animations")
            self.assertIn("-executeMethod", seen["command"])
            self.assertEqual(list((root / "Assets/Editor").glob("*.cs")), [])  # the editor script is removed


@unittest.skipUnless(os.environ.get("SLOPFORGE_RUN_UNITY_IMPORT") == "1" and UNITY_PROJECT,
                     "set SLOPFORGE_RUN_UNITY_IMPORT=1 and SLOPFORGE_UNITY_PROJECT to a Built-in or URP project")
class WeaponPrefabLiveTests(unittest.TestCase):
    """Real Unity: a body with a slide and a hinged lever, exported as prepare_model does, gets a prefab, one clip per
    part, and the motion checks pass; a part declared beyond what its clip can do fails."""

    def setUp(self):
        self.root = Path(UNITY_PROJECT).resolve()
        self.folder = self.root / f"Assets/SlopForgeWeaponTest_{uuid.uuid4().hex[:8]}"
        self.folder.mkdir(parents=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        shutil.rmtree(self.folder, ignore_errors=True)
        Path(f"{self.folder}.meta").unlink(missing_ok=True)

    def _export(self):
        """A body slab along -Y (Blender forward) with a slide child above it and a lever child hanging below, pivots
        as separate_part sets them, exported as prepare_model does (Blender -Y becomes Unity +Z)."""
        script = f"""import bpy
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
def box(name, centre, size, pivot, parent=None, kind=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=centre)
    o = bpy.context.object; o.name = name; o.scale = size
    bpy.ops.object.transform_apply(location=True, scale=True)
    bpy.context.scene.cursor.location = pivot
    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    if parent: o.parent = parent; o.matrix_parent_inverse = parent.matrix_world.inverted()
    if kind: o['slopforge_part'] = kind
    bpy.ops.mesh.uv_texture_add(); o.data.materials.append(bpy.data.materials.new(name))
    return o
body = box('body', (0, -0.5, 0.1), (0.05, 1.0, 0.2), (0, 0, 0))
box('slide', (0, -0.5, 0.25), (0.05, 1.0, 0.1), (0, -0.5, 0.25), body, 'slide')
box('lever', (0, -0.3, -0.05), (0.02, 0.05, 0.1), (0, -0.325, 0.0), body, 'hinge')  # pivot on its top-back edge: it swings clear
box('flap', (0, -0.975, 0.3), (0.02, 0.05, 0.2), (0, -1.0, 0.2), body, 'hinge')  # standing on the slab's front end, hinged on the slab's top-front edge
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.fbx(filepath={str(self.folder / 'weapon.fbx')!r}, use_selection=True, object_types={{'MESH'}},
    axis_forward='-Z', axis_up='Y', apply_unit_scale=True, bake_space_transform=False, add_leaf_bones=False,
    use_custom_props=True)
"""
        subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script],
                       check=True, capture_output=True)
        return self.folder / "weapon.fbx"

    def test_a_slide_and_a_hinge_get_clips_that_move_them_as_declared(self):
        fbx = self._export()
        parts = [{"name": "slide", "kind": "slide", "axis": "z", "min": -0.03, "max": 0.0},
                 {"name": "lever", "kind": "hinge", "axis": "x", "min": -20.0, "max": 0.0}]
        render = self.folder / "motion.png"
        report = build_weapon_prefab(self.root, "weapon", fbx, parts, prefab=self.folder / "weapon.prefab",
                                     clip_folder=self.folder / "Animations", render=render, held=True, mass=1.0,
                                     layer=None)
        self.assertEqual(report["errors"], [])
        self.assertTrue((self.root / report["prefab"]).is_file())
        self.assertTrue(render.is_file())
        motions = {item["part"]: item for item in report["motions"]}
        self.assertAlmostEqual(motions["slide"]["travel"], -0.03, delta=0.001)
        self.assertAlmostEqual(motions["lever"]["angle"], -20.0, delta=0.5)
        self.assertLess(motions["lever"]["pivot_drift"], 0.001)
        self.assertTrue(report["tip_forward"] and report["root_inside"])
        for item in report["motions"]:
            self.assertTrue((self.root / item["clip"]).is_file())
        # in-game function: a convex collider per mesh, a Rigidbody with the declared mass, sockets, an Animator a
        # script can drive (Rest by default; a trigger and a hold bool per part)
        self.assertEqual(report["colliders"], 4)  # body, slide, lever, flap: one convex collider per mesh
        self.assertAlmostEqual(report["rigidbody_mass"], 1.0)
        sockets = {item["name"]: item["position"] for item in report["sockets"]}
        self.assertEqual(sorted(sockets), ["Socket_Grip", "Socket_Muzzle", "Socket_lever", "Socket_slide"])
        self.assertAlmostEqual(sockets["Socket_Muzzle"][2], 1.0, delta=0.01)  # the body's +Z end
        self.assertAlmostEqual(sockets["Socket_lever"][2], 0.325, delta=0.002)  # the lever's pivot
        self.assertEqual(report["default_state"], "Rest")
        self.assertEqual(sorted(report["parameters"]), ["lever", "lever_open", "slide", "slide_open"])
        self.assertEqual(report["warnings"], [])  # the test project has the layer, or none was asked
        # the motion range is sampled for interpenetration: these parts clear the body
        self.assertLessEqual(max(item["penetration"] for item in report["motions"]), 0.02)
        # The lever's pivot sits on its top-back edge, at the body's underside, 0.325 m forward of the root.
        self.assertAlmostEqual(motions["lever"]["pivot"][2], 0.325, delta=0.002)
        self.assertAlmostEqual(motions["lever"]["pivot"][1], 0.0, delta=0.002)

    def test_the_prefab_plays_in_play_mode(self):
        from slopforge.unity_playmode import verify_play_mode
        fbx = self._export()
        parts = [{"name": "slide", "kind": "slide", "axis": "z", "min": -0.03, "max": 0.0},
                 {"name": "lever", "kind": "hinge", "axis": "x", "min": -20.0, "max": 0.0}]
        build_weapon_prefab(self.root, "weapon", fbx, parts, prefab=self.folder / "weapon.prefab",
                            clip_folder=self.folder / "Animations", render=self.folder / "motion.png",
                            held=True, mass=1.0, layer=None)
        prefab = (self.folder / "weapon.prefab").relative_to(self.root).as_posix()
        report = verify_play_mode(self.root, prefab, parts, results=self.folder / "playmode.xml")
        self.assertEqual(report["failed"], [])
        self.assertEqual(sorted(report["passed"]), ['PartPulses("lever")', 'PartPulses("slide")', "RestsOnTheGround"])
        self.assertFalse((self.root / "Assets/SlopForgeTests").exists())  # the scaffolding leaves the project

    def test_a_hinge_that_swings_into_the_body_fails_the_penetration_check(self):
        fbx = self._export()
        # a flap at the slab's front end, folded back over the slab: in Unity's sense a negative turn about x takes
        # +y towards -z, into the slab; the mirrored range folds it forward, clear of everything
        parts = [{"name": "flap", "kind": "hinge", "axis": "x", "min": -150.0, "max": 0.0}]
        report = build_weapon_prefab(self.root, "weapon", fbx, parts, prefab=self.folder / "weapon.prefab",
                                     clip_folder=self.folder / "Animations", render=self.folder / "motion.png",
                                     held=True, mass=1.0, layer=None)
        self.assertTrue(any("penetrat" in error for error in report["errors"]), report["errors"])
        self.assertGreater(report["motions"][0]["penetration"], 0.1)
        # the usual cause is the sign (docs/WEAPONS.md, Axes): the error names the range that clears the slab
        self.assertTrue(any("opposite sign, 150" in error for error in report["errors"]), report["errors"])
