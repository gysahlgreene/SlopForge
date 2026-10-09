import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CHECKER = Path(__file__).resolve().parents[1] / "scripts/check-docs.py"


class DocsCheckTests(unittest.TestCase):
    def check_fixture(self, public_text):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
            (root / "scripts").mkdir()
            (root / "scripts/check-docs.py").write_bytes(CHECKER.read_bytes())
            (root / ".gitignore").write_text("/docs/superpowers/\n")
            (root / "docs/superpowers").mkdir(parents=True)
            (root / "docs/superpowers/private.md").write_text("Local path: /Users/example/private/file\n")
            (root / "docs/README.md").write_text(public_text)
            return subprocess.run([sys.executable, str(root / "scripts/check-docs.py")],
                                  cwd=root, capture_output=True, text=True)

    def test_ignored_working_notes_do_not_fail_public_docs_check(self):
        result = self.check_fixture("# Public documentation\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_new_public_guides_are_checked_before_staging(self):
        result = self.check_fixture("[Missing guide](missing.md)\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing link missing.md", result.stderr)
