import hashlib
import tempfile
import unittest
from pathlib import Path

import yaml

from slopforge.libraries import list_libraries, resolve_library


class ReferenceLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "ai/libraries/character").mkdir(parents=True)
        self.image = self.root / "references/alice.png"
        self.image.parent.mkdir()
        self.image.write_bytes(b"portrait-one")
        self.library_path = self.root / "ai/libraries/character/alice.yaml"
        self.write_library([{"id": "portrait", "path": "references/alice.png", "category": "identity",
                             "strength": 0.8, "sha256": hashlib.sha256(b"portrait-one").hexdigest()}])

    def tearDown(self):
        self.temp.cleanup()

    def write_library(self, entries):
        self.library_path.write_text(yaml.safe_dump({"name": "Alice", "kind": "character", "version": 1,
                                                    "entries": entries}, sort_keys=False))

    def test_resolves_ordered_project_reference_and_records_hash(self):
        library = resolve_library(self.root, "character/alice")
        self.assertEqual(library["entries"][0]["path"], str(self.image.resolve()))
        self.assertEqual(library["entries"][0]["category"], "identity")
        self.assertEqual(library["entries"][0]["strength"], 0.8)
        self.assertEqual(library["entries"][0]["status"], "ready")
        self.assertEqual(library["entries"][0]["sha256"], hashlib.sha256(b"portrait-one").hexdigest())

    def test_library_reports_missing_and_changed_files_without_copying(self):
        missing = self.root / "references/missing.png"
        self.write_library([{"id": "old", "path": "references/alice.png", "sha256": "0" * 64},
                            {"id": "missing", "path": str(missing)}])
        entries = resolve_library(self.root, "character/alice")["entries"]
        self.assertEqual([entry["status"] for entry in entries], ["changed", "missing"])
        self.assertFalse(missing.exists())

    def test_absolute_external_reference_is_resolved_in_place(self):
        external = Path(self.temp.name).parent / f"{Path(self.temp.name).name}-external.png"
        external.write_bytes(b"external")
        try:
            self.write_library([{"id": "external", "path": str(external)}])
            entry = resolve_library(self.root, "character/alice")["entries"][0]
            self.assertEqual(entry["path"], str(external.resolve()))
            self.assertTrue(external.is_file())
            self.assertEqual(entry["status"], "ready")
        finally:
            external.unlink(missing_ok=True)

    def test_resolves_only_approved_manifest_artifacts(self):
        manifest = {"assets": {"character:alice": {
            "id": "asset-alice", "name": "Alice", "status": "ready",
            "artifacts": {"portrait": {"id": "portrait", "path": "Assets/Alice.png",
                                         "approval": {"status": "approved"}}},
            "outputs": {"portrait": "Assets/Alice.png"}}}}
        (self.root / "Assets").mkdir()
        (self.root / "Assets/Alice.png").write_bytes(b"approved")
        self.write_library([{"id": "approved-face", "asset": {"asset_id": "asset-alice", "output_id": "portrait"}}])
        resolved = resolve_library(self.root, "character/alice", manifest)["entries"][0]
        self.assertEqual(resolved["path"], str((self.root / "Assets/Alice.png").resolve()))
        self.assertEqual(resolved["source"], {"asset_id": "asset-alice", "output_id": "portrait"})

    def test_rejects_unapproved_manifest_artifact(self):
        manifest = {"assets": {"prop:coin": {"id": "coin", "status": "ready", "artifacts": {
            "concept": {"path": "coin.png", "approval": {"status": "pending"}}}}}}
        self.write_library([{"id": "coin", "asset": {"asset_id": "coin", "output_id": "concept"}}])
        with self.assertRaisesRegex(ValueError, "not approved"):
            resolve_library(self.root, "character/alice", manifest)

    def test_library_membership_edits_are_visible_without_moving_files(self):
        self.write_library([{"id": "portrait", "path": "references/alice.png"},
                            {"id": "full-body", "path": "references/alice.png", "category": "silhouette"}])
        self.assertEqual([item["id"] for item in resolve_library(self.root, "character/alice")["entries"]],
                         ["portrait", "full-body"])
        self.assertEqual(list_libraries(self.root), ["character/alice"])
        self.assertTrue(self.image.is_file())


if __name__ == "__main__":
    unittest.main()
