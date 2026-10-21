import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from slopforge.failures import StageFailure
from slopforge.provenance import file_sha256
from slopforge.unity_material import build_unity_material

ROLES = ("basecolor", "normal", "metallic_gloss", "emission")


def fake_unity(root, guids, texture_guids=None):
    """subprocess.run stand-in: writes the import report the generated editor script would write."""
    def run(*_args, **_kwargs):
        script = next((root / "Assets/Editor").glob("*.cs")).read_text()
        paths = dict(re.findall(r'Describe\("(\w+)", "([^"]+)"\)', script))
        paths.update(fbx=re.search(r'fbxPath = "([^"]+)"', script)[1],
                     material=re.search(r'materialPath = "([^"]+)"', script)[1])
        (root / paths["material"]).write_bytes(b"material")
        report = {"unity_version": "6000.6.3f1",
                  "assets": [{"role": role, "path": path, "guid": guids[role], "importer": "Importer",
                              "settings_sha256": "0" * 64} for role, path in paths.items()],
                  "material_textures": [{"role": role, "path": paths[role],
                                         "guid": (texture_guids or guids)[role]} for role in ROLES]}
        Path(re.search(r'reportPath = "([^"]+)"', script)[1]).write_text(json.dumps(report))
    return run


class UnityImportReportTests(unittest.TestCase):
    def _project(self, root):
        maps = {name: root / f"Assets/Relic/{name}.png" for name in ROLES}
        for path in maps.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(path.stem.encode())
        (root / "Assets/Relic/relic.fbx").write_bytes(b"fbx")
        return maps

    def test_report_records_guid_importer_and_file_hash_per_role(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            maps = self._project(root)
            guids = {role: uuid.uuid4().hex for role in ("fbx", "material", *ROLES)}
            with patch("slopforge.unity_material.unity_cli", return_value="unity"), \
                    patch("slopforge.unity_material.subprocess.run", side_effect=fake_unity(root, guids)):
                record = build_unity_material(root, root / "Assets/Relic/relic.fbx",
                                              root / "Assets/Relic/relic.mat", maps)
            self.assertEqual({role: entry["guid"] for role, entry in record["assets"].items()}, guids)
            self.assertEqual(record["assets"]["fbx"]["path"], "Assets/Relic/relic.fbx")
            self.assertEqual(record["assets"]["basecolor"]["sha256"], file_sha256(maps["basecolor"]))
            self.assertEqual(record["assets"]["material"]["sha256"], file_sha256(root / "Assets/Relic/relic.mat"))
            self.assertEqual(record["material_textures"], {role: guids[role] for role in ROLES})
            self.assertEqual(record["unity_version"], "6000.6.3f1")
            self.assertFalse(list((root / "Assets/Editor").glob("*.cs")))

    def test_material_referencing_another_texture_stops_the_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            maps = self._project(root)
            guids = {role: uuid.uuid4().hex for role in ("fbx", "material", *ROLES)}
            stale = dict(guids, normal=uuid.uuid4().hex)
            with patch("slopforge.unity_material.unity_cli", return_value="unity"), \
                    patch("slopforge.unity_material.subprocess.run", side_effect=fake_unity(root, guids, stale)):
                with self.assertRaisesRegex(StageFailure, "does not reference the published normal") as caught:
                    build_unity_material(root, root / "Assets/Relic/relic.fbx", root / "Assets/Relic/relic.mat", maps)
            self.assertEqual(caught.exception.category, "processing_validation")


UNITY_PROJECT = os.environ.get("SLOPFORGE_UNITY_PROJECT")
BLENDER = os.environ.get("BLENDER_BIN") or shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"


@unittest.skipUnless(os.environ.get("SLOPFORGE_RUN_UNITY_IMPORT") == "1" and UNITY_PROJECT,
                     "set SLOPFORGE_RUN_UNITY_IMPORT=1 and SLOPFORGE_UNITY_PROJECT to a Built-in or URP project")
class UnityImportIdentityLiveTests(unittest.TestCase):
    """Real Unity: replacing, reimporting and renaming keep or separate asset identity as intended."""

    def _cube(self, path, size):
        script = ("import bpy; bpy.ops.wm.read_factory_settings(use_empty=True); "
                  f"bpy.ops.mesh.primitive_cube_add(size={size}); obj = bpy.context.object; "
                  "obj.data.materials.append(bpy.data.materials.new('relic_PBR')); "
                  "bpy.ops.mesh.uv_texture_add(); "
                  f"bpy.ops.export_scene.fbx(filepath={str(path)!r}, use_selection=True)")
        subprocess.run([BLENDER, "--background", "--python-exit-code", "1", "--python-expr", script],
                       check=True, capture_output=True)

    def _publish(self, folder, size, colour):
        """Write the asset the way approve-texture does: replace each file in place."""
        folder.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp())
        self._cube(staging / "relic.fbx", size)
        for role in ROLES:
            Image.new("RGBA", (8, 8), colour).save(staging / f"{role}.png")
        for item in staging.iterdir():
            os.replace(item, folder / item.name)
        shutil.rmtree(staging)
        return build_unity_material(self.root, folder / "relic.fbx", folder / "relic_PBR.mat",
                                    {role: folder / f"{role}.png" for role in ROLES})

    def _metas(self, folder):
        return {path.name: path.read_bytes() for path in folder.glob("*.meta")}

    def setUp(self):
        self.root = Path(UNITY_PROJECT).resolve()
        self.test_root = self.root / f"Assets/SlopForgeIdentityTest_{uuid.uuid4().hex[:8]}"

    def tearDown(self):
        shutil.rmtree(self.test_root, ignore_errors=True)
        self.test_root.with_name(self.test_root.name + ".meta").unlink(missing_ok=True)

    def test_replace_reimport_and_rename_keep_identity_rules(self):
        first = self._publish(self.test_root / "relic", 1.0, (200, 40, 40, 255))
        replaced = self._publish(self.test_root / "relic", 2.0, (40, 200, 40, 255))
        guids = {role: entry["guid"] for role, entry in first["assets"].items()}
        # Replacing the files at the same logical identity keeps every GUID and the material's references.
        self.assertEqual({role: entry["guid"] for role, entry in replaced["assets"].items()}, guids)
        self.assertNotEqual(first["assets"]["fbx"]["sha256"], replaced["assets"]["fbx"]["sha256"])
        self.assertNotEqual(first["assets"]["basecolor"]["sha256"], replaced["assets"]["basecolor"]["sha256"])
        self.assertEqual(replaced["material_textures"], {role: guids[role] for role in ROLES})
        # Reimporting unchanged sources alters nothing: same record, same .meta and material bytes, no extra files.
        metas, files = self._metas(self.test_root / "relic"), sorted(p.name for p in (self.test_root / "relic").iterdir())
        again = build_unity_material(self.root, self.test_root / "relic/relic.fbx",
                                     self.test_root / "relic/relic_PBR.mat",
                                     {role: self.test_root / f"relic/{role}.png" for role in ROLES})
        self.assertEqual(again, replaced)
        self.assertEqual(self._metas(self.test_root / "relic"), metas)
        self.assertEqual(sorted(p.name for p in (self.test_root / "relic").iterdir()), files)
        # A new name is a distinct asset and leaves the original untouched.
        renamed = self._publish(self.test_root / "relic_copy", 1.0, (40, 40, 200, 255))
        self.assertFalse({entry["guid"] for entry in renamed["assets"].values()} & set(guids.values()))
        self.assertEqual(self._metas(self.test_root / "relic"), metas)
