import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopforge.unity_vfx import create_particle_prefab


class UnityVFXTests(unittest.TestCase):
    def test_particle_prefab_build_uses_sheet_grid_and_playback_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
            atlas = root / "Assets/fire_atlas.png"
            atlas.write_bytes(b"png")
            prefab = root / "Assets/fire.prefab"
            material = root / "Assets/fire.mat"

            def run(command, **kwargs):
                script = next((root / "Assets/Editor").glob("SlopForgeVFXBuilder_*.cs"))
                code = script.read_text()
                self.assertIn("using UnityEngine.Rendering;", code)
                self.assertIn("sheet.numTilesX = 4", code)
                self.assertIn("sheet.numTilesY = 2", code)
                self.assertIn("main.loop = true", code)
                self.assertIn("ParticleSystemAnimationType.WholeSheet", code)
                prefab.write_text("prefab")
                material.write_text("material")

            with patch("slopforge.unity_vfx.unity_cli", return_value="/unity"), \
                    patch("slopforge.unity_vfx.subprocess.run", side_effect=run):
                result = create_particle_prefab(root, atlas, prefab, material, columns=4, rows=2, loop=True)
            self.assertEqual(result, (prefab.resolve(), material.resolve()))

    def test_particle_prefab_rejects_external_atlas(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
            external = root.parent / "external.png"
            external.write_bytes(b"png")
            with self.assertRaisesRegex(ValueError, "inside the Unity project"):
                create_particle_prefab(root, external, root / "Assets/out.prefab", root / "Assets/out.mat",
                                       columns=1, rows=1, loop=False)
            external.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
