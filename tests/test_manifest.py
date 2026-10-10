import copy
import json
import tempfile
import unittest
from pathlib import Path

from slopforge import manifest as manifest_module
from slopforge.manifest import (
    _migrate,
    add_dependency,
    children_of,
    new_record,
    register_artifact,
    save_manifest,
    set_artifact_approval,
    set_parent,
)


class ManifestTests(unittest.TestCase):
    def make_asset(self, name):
        style = {"name": "default", "version": 1}
        return new_record("prop", name, name, style, {"strategy": "text_only"})

    def test_schema_v2_upgrade_preserves_unknown_fields_and_compatibility_outputs(self):
        source = {
            "schema_version": 2,
            "active_style": {"name": "default", "version": 1},
            "custom_top_level": {"retained": True},
            "assets": {"icon:coin": {
                "id": "coin-id", "name": "coin", "type": "icon",
                "outputs": {"image": "Assets/coin.png"},
                "approval": {"status": "approved"},
                "generator": {"workflow": "coin.json", "seed": 17},
                "custom_asset_field": [1, 2, 3],
            }},
        }

        migrated = _migrate(source)

        self.assertEqual(migrated["schema_version"], 4)
        self.assertEqual(migrated["custom_top_level"], source["custom_top_level"])
        asset = migrated["assets"]["icon:coin"]
        self.assertEqual(asset["custom_asset_field"], [1, 2, 3])
        self.assertEqual(asset["outputs"], {"image": "Assets/coin.png"})
        self.assertEqual(asset["executions"], [])
        self.assertEqual(asset["lineage_status"]["status"], "unknown")

    def test_legacy_upgrade_preserves_unknown_and_approval_provenance(self):
        old_asset = {
            "asset": "Assets/old.png", "workflow": "old.json",
            "approval": {"status": "approved", "reviewer": "user"},
            "generator": {"workflow": "old.json", "model": "model-a", "seed": 41},
            "custom": {"keep": "me"},
        }
        source = {"style": {"name": "legacy", "version": 2, "custom_style_field": "retained"},
                  "custom_top_level": "retained", "assets": {"icon:old": old_asset}}

        migrated = _migrate(source)

        record = migrated["assets"]["icon:old"]
        self.assertEqual(migrated["custom_top_level"], "retained")
        self.assertEqual(record["legacy"], old_asset)
        self.assertEqual(record["generator"], old_asset["generator"])
        self.assertEqual(record["approval"], old_asset["approval"])
        self.assertEqual(migrated["active_style"]["custom_style_field"], "retained")
        self.assertEqual(record["outputs"]["asset"], "Assets/old.png")

    def test_future_schema_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "newer than supported"):
            _migrate({"schema_version": 5, "assets": {}})

    def test_v3_manifest_migrates_lineage_as_unknown(self):
        source = {"schema_version": 3, "active_style": {}, "assets": {"prop:coin": {
            "id": "coin-id", "name": "coin", "type": "prop", "description": "A brass coin",
            "generator": {"workflow": "old.json", "model": "model-a", "seed": 41},
            "outputs": {"fbx": "Assets/coin.fbx"}, "model_attempts": [{"number": 1, "status": "qualified"}],
        }}}

        migrated = _migrate(source)

        record = migrated["assets"]["prop:coin"]
        self.assertEqual(migrated["schema_version"], 4)
        self.assertEqual(record["generator"], source["assets"]["prop:coin"]["generator"])
        self.assertEqual(record["outputs"], source["assets"]["prop:coin"]["outputs"])
        self.assertEqual(record["model_attempts"], source["assets"]["prop:coin"]["model_attempts"])
        self.assertEqual(record["executions"], [])
        self.assertEqual(record["lineage_status"], {
            "status": "unknown", "reason": "legacy manifest predates execution lineage"})

    def test_stage_attempt_transitions_and_artifact_refs_round_trip(self):
        for helper in ("start_execution", "start_stage", "begin_stage", "finish_stage", "finish_execution"):
            self.assertTrue(callable(getattr(manifest_module, helper, None)), helper)
        asset = self.make_asset("coin")
        execution = manifest_module.start_execution(asset, {"brief": "A brass coin"})
        stage = manifest_module.start_stage(execution, "mesh_preparation", 1, [], {"face_budget": 1000}, {})
        self.assertEqual(stage["status"], "pending")
        manifest_module.begin_stage(stage)
        self.assertEqual(stage["status"], "running")
        output = {"id": "mesh:1", "type": "model.glb", "path": "ai/mesh.glb",
                  "sha256": "a" * 64, "stage": "mesh_preparation", "attempt": 1,
                  "derived_from": []}
        manifest_module.finish_stage(stage, "succeeded", outputs=[output])
        manifest_module.finish_execution(execution, "succeeded")
        manifest = {"schema_version": 4, "assets": {"prop:coin": asset}}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            save_manifest(path, manifest)
            loaded = _migrate(json.loads(path.read_text()))

        self.assertEqual(loaded["assets"]["prop:coin"]["executions"], [execution])

    def test_stage_attempt_rejects_invalid_state_or_external_path(self):
        self.assertTrue(callable(getattr(manifest_module, "start_execution", None)))
        execution = manifest_module.start_execution(self.make_asset("coin"), {"brief": "A brass coin"})
        stage = manifest_module.start_stage(execution, "mesh_preparation", 1, [], {}, {})
        with self.assertRaisesRegex(ValueError, "stage status"):
            manifest_module.finish_stage(stage, "stale")
        manifest_module.begin_stage(stage)
        with self.assertRaisesRegex(ValueError, "project"):
            manifest_module.finish_stage(stage, "succeeded", outputs=[{
                "id": "mesh:1", "type": "model.glb", "path": "../outside.glb",
                "sha256": "a" * 64, "stage": "mesh_preparation", "attempt": 1,
                "derived_from": [],
            }])

    def test_atomic_record_stays_simple_until_outputs_or_relationships_are_added(self):
        asset = self.make_asset("coin")
        self.assertNotIn("artifacts", asset)
        self.assertNotIn("parent_id", asset)
        self.assertNotIn("dependencies", asset)

    def test_typed_outputs_keep_legacy_paths_and_independent_approval(self):
        asset = self.make_asset("pilot")
        manifest = {"schema_version": 4, "assets": {"character:pilot": asset}}
        model = register_artifact(
            manifest, "character:pilot", "model", "model.glb",
            "Assets/Art/Generated/Characters/pilot/model.glb", status="ready", approval_status="approved",
            provenance={"workflow": "image.json", "seed": 17},
            validation={"status": "passed", "errors": []},
        )
        rig = register_artifact(
            manifest, "character:pilot", "rig", "model.rigged",
            "ai/assets/candidates/pilot/rigged.fbx", status="candidate",
            derived_from=[{"asset_id": asset["id"], "output_id": "model"}],
            provenance={"provider": "blender_rigify"},
            validation={"status": "passed_with_warnings", "warnings": ["review deformations"]},
        )

        self.assertEqual(asset["outputs"]["model"], "Assets/Art/Generated/Characters/pilot/model.glb")
        self.assertEqual(asset["outputs"]["rig"], "ai/assets/candidates/pilot/rigged.fbx")
        self.assertEqual(model["type"], "model.glb")
        self.assertEqual(rig["derived_from"], [{"asset_id": asset["id"], "output_id": "model"}])
        self.assertEqual(rig["validation"]["warnings"], ["review deformations"])
        self.assertEqual(rig["approval"]["status"], "pending")

        set_artifact_approval(manifest, "character:pilot", "rig", "approved", approved_by="user")
        self.assertEqual(rig["approval"]["status"], "approved")
        self.assertEqual(rig["approval"]["approved_by"], "user")
        self.assertEqual(model["approval"]["status"], "approved")

    def test_parent_children_and_output_dependencies_are_explicit(self):
        pack = self.make_asset("pack")
        icon = self.make_asset("icon")
        manifest = {"schema_version": 3, "assets": {"pack:ui": pack, "icon:health": icon}}
        register_artifact(manifest, "pack:ui", "atlas", "image.atlas", "Assets/UI/atlas.png")

        set_parent(manifest, "icon:health", "pack:ui")
        add_dependency(manifest, "icon:health", "pack:ui", output_id="atlas")

        self.assertEqual(icon["parent_id"], pack["id"])
        self.assertEqual([asset["id"] for asset in children_of(manifest, "pack:ui")], [icon["id"]])
        self.assertEqual(icon["dependencies"], [{"asset_id": pack["id"], "output_id": "atlas"}])
        with self.assertRaisesRegex(ValueError, "cycle"):
            set_parent(manifest, "pack:ui", "icon:health")
        add_dependency(manifest, "icon:health", "pack:ui", output_id="atlas")
        self.assertEqual(len(icon["dependencies"]), 1)

    def test_artifact_paths_must_be_project_relative(self):
        asset = self.make_asset("coin")
        manifest = {"schema_version": 3, "assets": {"prop:coin": asset}}
        for path in ("/tmp/coin.png", "../outside.png"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                register_artifact(manifest, "prop:coin", "image", "image.png", path)

    def test_artifacts_relationships_and_provenance_round_trip_atomically(self):
        asset = self.make_asset("pilot")
        manifest = {"schema_version": 4, "assets": {"character:pilot": asset}}
        register_artifact(manifest, "character:pilot", "model", "model.glb", "Assets/Pilot/model.glb",
                          provenance={"workflow": "model.json", "seed": 99})
        manifest["assets"]["character:pilot"]["custom"] = {"retained": True}
        expected = copy.deepcopy(manifest)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            save_manifest(path, manifest)
            loaded = _migrate(json.loads(path.read_text()))

        self.assertEqual(loaded, expected)


if __name__ == "__main__":
    unittest.main()
