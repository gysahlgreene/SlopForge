import tempfile
import unittest
from pathlib import Path

from slopforge import cli
from slopforge.config import load_project
from slopforge.initializer import init_project
from slopforge.manifest import acquire_project_lock, release_project_locks


class ProjectLockTests(unittest.TestCase):
    def tearDown(self):
        release_project_locks()

    def test_second_writer_stops_with_actionable_error_and_readers_still_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            init_project(root)
            manifest = root / load_project(root)["asset_pipeline"]["manifest"]
            with open(manifest.with_name(manifest.name + ".lock"), "a") as other_process:
                import fcntl
                fcntl.flock(other_process, fcntl.LOCK_EX | fcntl.LOCK_NB)  # another command holds the project
                with self.assertRaisesRegex(RuntimeError, "Another SlopForge command is changing this project"):
                    acquire_project_lock(manifest)
                self.assertEqual(cli.main(["--project", str(root), "generate", "prop", "crate", "Crate", "--dry-run"]), 1)
                self.assertEqual(cli.main(["--project", str(root), "assets"]), 0)
            self.assertEqual(cli.main(["--project", str(root), "generate", "prop", "crate", "Crate", "--dry-run"]), 0)
            acquire_project_lock(manifest)  # released after the previous command finished
