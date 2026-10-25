import json
import os
import shutil
from itertools import product
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopforge.config import load_project
from slopforge.manifest import load_manifest
from slopforge.failures import StageFailure
from slopforge.initializer import init_project
from slopforge.pipelines import model


class PublicationTestCase(unittest.TestCase):
    """These tests exercise publication's rollback and identity rules; the prefab a prop type publishes (unity_weapon,
    a separate Unity run) is stood in by a clean report."""

    def setUp(self):
        super().setUp()
        stub = patch("slopforge.pipelines.model.build_weapon_prefab",
                     return_value={"errors": [], "prefab": "Assets/stub.prefab", "controller": "Assets/stub.controller",
                                   "motions": [], "tip_forward": True, "root_inside": True})
        stub.start()
        self.addCleanup(stub.stop)


class TextureApprovalRollbackTests(PublicationTestCase):
    def test_publication_preflight_failure_is_persisted_without_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            init_project(root)
            config = load_project(root)
            asset = {"name": "relic", "status": "awaiting_texture_approval",
                     "material_candidates": {"items": [{"number": 1, "status": "candidate"}]}}
            manifest = {"assets": {"prop:relic": asset}}
            failure = StageFailure("environment", "Unity CLI unavailable", operation="unity_preflight",
                                   remedy="install Unity or configure its CLI")

            with patch("slopforge.pipelines.model.unity_cli", side_effect=failure):
                with self.assertRaises(StageFailure):
                    model.approve_texture(root, config, manifest, "prop:relic", 1)

            self.assertEqual(asset["last_failure"]["category"], "environment")
            self.assertEqual(asset["last_failure"]["stage"], "preflight")
            self.assertEqual(asset.get("executions", []), [])

    def test_failed_publication_preserves_previous_outputs_and_source(self):
        for previously_approved, failure_stage in product((False, True), ("copy", "material", "interrupt", "backup", "lineage")):
            with self.subTest(previously_approved=previously_approved, failure_stage=failure_stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'Assets').mkdir()
                init_project(root)
                config = load_project(root)
                final = model.model_paths(root, config, 'relic')
                candidate = model.material_candidate_paths(root, config, 'relic', 1)
                keys = ('surface', 'fbx', 'blend', 'basecolor', 'normal', 'roughness',
                        'metallic', 'metallic_gloss', 'emission', 'preview_front',
                        'preview_side', 'preview_rear', 'preview_three_quarter')
                outputs = {}
                for name in keys:
                    candidate[name].parent.mkdir(parents=True, exist_ok=True)
                    candidate[name].write_bytes(('new ' + name).encode())
                    outputs[name] = candidate[name].relative_to(root).as_posix()
                source = root / 'retained.glb'
                source.write_bytes(b'original source')
                asset = {'name': 'relic', 'status': 'ready' if previously_approved else 'awaiting_texture_approval',
                         'source': {'glb': 'retained.glb'}, 'generator': {'workflow': {}, 'seed': {}},
                         'material_candidates': {'selected': 0 if previously_approved else None,
                             'items': [{'number': 1, 'status': 'candidate', 'prompt': 'steel',
                                        'outputs': outputs, 'validation': {'status': 'passed'}}]}}
                manifest = {'assets': {'prop:relic': asset}}
                before_status = asset["status"]
                before_selected = asset["material_candidates"]["selected"]
                destinations = [final[name] for name in (*keys, 'glb', 'unity_material', 'validation')]
                metadata = [path.with_suffix(path.suffix + '.meta') for path in destinations]
                if previously_approved:
                    for path in destinations + metadata:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(('old ' + path.name).encode())
                elif failure_stage == "backup":
                    final['surface'].parent.mkdir(parents=True, exist_ok=True)
                    final['surface'].write_bytes(b'orphan prior output')
                originals = {path: path.read_bytes() for path in destinations + metadata if path.exists()}

                def fail_material(*args, **_options):
                    final['unity_material'].write_bytes(b'partly replaced material')
                    for path in metadata:
                        path.write_bytes(b'Unity changed importer metadata')
                    raise RuntimeError('Unity failed')

                replace = os.replace
                replacements = 0

                def fail_copy(source_path, destination):
                    nonlocal replacements
                    if Path(destination).resolve() != (root / config['asset_pipeline']['manifest']).resolve():
                        replacements += 1
                    if failure_stage == 'interrupt' and replacements == 2:
                        raise KeyboardInterrupt('cancelled')
                    if failure_stage == 'copy' and Path(destination).resolve() != (root / config['asset_pipeline']['manifest']).resolve() and replacements == 2:
                        raise RuntimeError('Unity failed publication')
                    return replace(source_path, destination)

                copy2 = shutil.copy2
                def fail_backup(source_path, destination, *args, **kwargs):
                    if failure_stage == "backup" and Path(destination).parent.name.startswith("slopforge-texture-backup-"):
                        raise RuntimeError("publication backup failed")
                    return copy2(source_path, destination, *args, **kwargs)

                artifact_ref = model._artifact_ref
                def fail_lineage(*args, **kwargs):
                    if failure_stage == "lineage":
                        raise RuntimeError("publication lineage failed")
                    return artifact_ref(*args, **kwargs)

                with patch('slopforge.pipelines.model.os.replace', side_effect=fail_copy), \
                        patch('slopforge.pipelines.model.shutil.copy2', side_effect=fail_backup), \
                        patch('slopforge.pipelines.model.unity_cli', return_value='unity'), \
                        patch('slopforge.pipelines.model._artifact_ref', side_effect=fail_lineage), \
                        patch('slopforge.pipelines.model.build_unity_material',
                              side_effect=fail_material if failure_stage != "lineage" else None):
                    with self.assertRaises((RuntimeError, KeyboardInterrupt)):
                        model.approve_texture(root, config, manifest, 'prop:relic', 1, force=True)
                self.assertEqual(asset["status"], before_status)
                self.assertEqual(asset["material_candidates"]["selected"], before_selected)
                publication = asset["executions"][-1]
                self.assertEqual(publication["status"], "failed")
                self.assertEqual(publication["stages"][-1]["status"], "failed")
                self.assertEqual(publication["stages"][-1]["failure"]["stage"], "final_publication")
                self.assertEqual(publication["stages"][-1]["failure"]["category"],
                                 "interruption" if failure_stage == "interrupt" else "unknown")
                self.assertEqual(publication["failure"]["stage_id"], publication["stages"][-1]["id"])
                self.assertEqual(source.read_bytes(), b'original source')
                for path in destinations + metadata:
                    if path in originals:
                        self.assertEqual(path.read_bytes(), originals[path])
                    else:
                        self.assertFalse(path.exists(), str(path))

    def test_regenerated_concepts_block_publication_before_files_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, manifest = PlaceholderNormalGateTests()._setup(root)
            asset = manifest["assets"]["prop:relic"]
            asset["generator"] = {"workflow": "image_text2img_api.json"}  # what `generate` leaves behind
            with patch("slopforge.pipelines.model.unity_cli"):
                with self.assertRaisesRegex(ValueError, "approve a concept"):
                    model.approve_texture(root, config, manifest, "prop:relic", 1, allow_placeholder_normal=True)
            self.assertEqual(asset.get("executions", []), [])
            self.assertFalse(model.model_paths(root, config, "relic")["fbx"].exists())

    def test_backup_rollback_failure_records_terminal_failure(self):
        """When restoring a backup after publication failure fails, the
        publication must still be recorded as terminal-failed and the
        manifest saved with rollback-error context. The original
        publication error remains the primary failure evidence.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'Assets').mkdir()
            init_project(root)
            config = load_project(root)
            final = model.model_paths(root, config, 'relic')
            candidate = model.material_candidate_paths(root, config, 'relic', 1)
            keys = ('surface', 'fbx', 'blend', 'basecolor', 'normal', 'roughness',
                    'metallic', 'metallic_gloss', 'emission', 'preview_front',
                    'preview_side', 'preview_rear', 'preview_three_quarter')
            outputs = {}
            for name in keys:
                candidate[name].parent.mkdir(parents=True, exist_ok=True)
                candidate[name].write_bytes(('new ' + name).encode())
                outputs[name] = candidate[name].relative_to(root).as_posix()
            source = root / 'retained.glb'
            source.write_bytes(b'original source')
            asset = {'name': 'relic', 'status': 'awaiting_texture_approval',
                     'source': {'glb': 'retained.glb'}, 'generator': {'workflow': {}, 'seed': {}},
                     'material_candidates': {'selected': None,
                         'items': [{'number': 1, 'status': 'candidate', 'prompt': 'steel',
                                    'outputs': outputs, 'validation': {'status': 'passed'}}]}}
            manifest = {'assets': {'prop:relic': asset}}
            final['surface'].parent.mkdir(parents=True, exist_ok=True)
            final['surface'].write_bytes(b'orphan prior output')

            real_copy = shutil.copy2
            # During initial backup: source is production file, dest is in backup dir.
            # During restore: source is in backup dir, dest is production file.
            # We distinguish by checking if SOURCE is from a backup dir.

            def selective_fail(source_path, destination):
                # Check if this is a restore operation (source comes from backup)
                src_parent = Path(source_path).parent.name
                if src_parent.startswith("slopforge-texture-backup-"):
                    raise RuntimeError("backup restoration failed")
                return real_copy(source_path, destination)

            with patch('slopforge.pipelines.model.unity_cli', return_value='unity'), \
                 patch('slopforge.pipelines.model.build_unity_material',
                       side_effect=lambda _r, _f, out, _m, **_o: (_ for _ in ()).throw(RuntimeError("Unity failed"))), \
                 patch('slopforge.pipelines.model.shutil.copy2', side_effect=selective_fail):
                with self.assertRaises(RuntimeError):
                    model.approve_texture(root, config, manifest, 'prop:relic', 1, force=True)

                # Asset is still terminal-failed and manifest was saved.
                publication = asset['executions'][-1]
                self.assertEqual(asset['status'], 'awaiting_texture_approval')
                self.assertEqual(publication['status'], 'failed')
                self.assertEqual(publication['stages'][-1]['status'], 'failed')
                self.assertEqual(publication['stages'][-1]['failure']['stage'], 'final_publication')
                self.assertEqual(publication['failure']['message'], 'Unity failed')
                # Rollback error context preserved alongside original publication error.
                failure_evidence = publication['failure']['evidence']
                self.assertIn('rollback_failure', failure_evidence)
                self.assertIn('backup restoration failed', failure_evidence['rollback_failure'])
                self.assertTrue(failure_evidence['rollback_partial'])
                persisted = load_manifest(root / config['asset_pipeline']['manifest'])
                saved_publication = persisted['assets']['prop:relic']['executions'][-1]
                self.assertEqual(saved_publication['status'], 'failed')
                self.assertIn('backup restoration failed',
                              saved_publication['failure']['evidence']['rollback_failure'])


class PlaceholderNormalGateTests(PublicationTestCase):
    def _setup(self, root):
        from PIL import Image
        (root / "Assets").mkdir()
        init_project(root)
        config = load_project(root)
        candidate = model.material_candidate_paths(root, config, "relic", 1)
        outputs = {}
        for name in ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss",
                     "emission", "preview_front", "preview_side", "preview_rear", "preview_three_quarter"):
            candidate[name].parent.mkdir(parents=True, exist_ok=True)
            candidate[name].write_bytes(b"x")
            outputs[name] = candidate[name].relative_to(root).as_posix()
        Image.new("RGB", (1, 1), (0, 128, 128)).save(candidate["normal"])
        (root / "retained.glb").write_bytes(b"glb")
        asset = {"name": "relic", "status": "awaiting_texture_approval", "source": {"glb": "retained.glb"},
                 "material_candidates": {"items": [{"number": 1, "status": "candidate", "outputs": outputs}]}}
        return config, {"assets": {"prop:relic": asset}}

    def test_placeholder_normal_blocks_approval_before_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, manifest = self._setup(root)
            with patch("slopforge.pipelines.model.unity_cli"):
                with self.assertRaisesRegex(ValueError, "placeholder normal"):
                    model.approve_texture(root, config, manifest, "prop:relic", 1)
            self.assertEqual(manifest["assets"]["prop:relic"].get("executions", []), [])


class UnityPreviewTests(PublicationTestCase):
    def _candidate(self, root, config):
        from PIL import Image
        paths = model.material_candidate_paths(root, config, "relic", 1)
        outputs = {}
        for name in ("fbx", "basecolor", "normal", "emission", "metallic", "roughness"):
            paths[name].parent.mkdir(parents=True, exist_ok=True)
            if name in ("metallic", "roughness"):
                Image.new("L", (4, 4), 200).save(paths[name])
            else:
                paths[name].write_bytes(name.encode())
            outputs[name] = paths[name].relative_to(root).as_posix()
        return {"number": 1, "status": "candidate", "outputs": outputs}

    def test_failed_preview_removes_its_copies_from_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
            init_project(root)
            config = load_project(root)
            candidate = self._candidate(root, config)
            manifest = {"assets": {"prop:relic": {"name": "relic", "material_candidates": {"items": [candidate]}}}}
            copied = []

            def unity(_root, fbx, material, maps, render=None):
                copied.append(fbx.parent)
                fbx.parent.with_name(fbx.parent.name + ".meta").write_text("Unity folder meta")
                raise RuntimeError("Unsupported render pipeline")

            with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                    patch("slopforge.pipelines.model.build_unity_material", side_effect=unity):
                with self.assertRaisesRegex(RuntimeError, "Unsupported render pipeline"):
                    model.unity_preview(root, config, manifest, "prop:relic", 1)
            self.assertFalse(copied[0].exists())
            self.assertFalse(copied[0].with_name(copied[0].name + ".meta").exists())
            self.assertEqual(candidate["unity_preview"]["status"], "failed")

    def test_preview_imports_a_copy_and_leaves_approval_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
            init_project(root)
            config = load_project(root)
            candidate = self._candidate(root, config)
            asset = {"name": "relic", "status": "awaiting_texture_approval",
                     "material_candidates": {"selected": None, "items": [candidate]}}
            manifest = {"assets": {"prop:relic": asset}}
            calls = []

            def unity(_root, fbx, material, maps, render=None):
                calls.append((fbx, maps))
                Path(render).write_bytes(b"png")

            with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                    patch("slopforge.pipelines.model.build_unity_material", side_effect=unity):
                record = model.unity_preview(root, config, manifest, "prop:relic", 1)

            fbx, maps = calls[0]
            self.assertIn("CandidatePreviews", fbx.parts)
            self.assertEqual(fbx.read_bytes(), b"fbx")
            self.assertTrue(maps["metallic_gloss"].is_file())
            self.assertEqual(record["status"], "imported")
            self.assertEqual(record["unity_version"], "6000.6.3f1")
            self.assertTrue(record["render"].endswith("material_01/unity_preview.png"))
            self.assertEqual(candidate["unity_preview"], record)
            self.assertEqual((candidate["status"], candidate.get("approval")), ("candidate", None))
            self.assertEqual((asset["status"], asset["material_candidates"]["selected"]),
                             ("awaiting_texture_approval", None))
            self.assertFalse(model.model_paths(root, config, "relic")["fbx"].exists())

    def test_failed_import_is_recorded_and_raised(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.6.3f1\n")
            init_project(root)
            config = load_project(root)
            candidate = self._candidate(root, config)
            manifest = {"assets": {"prop:relic": {"name": "relic", "material_candidates": {"items": [candidate]}}}}
            with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                    patch("slopforge.pipelines.model.build_unity_material", side_effect=RuntimeError("no material")):
                with self.assertRaises(RuntimeError):
                    model.unity_preview(root, config, manifest, "prop:relic", 1)
            self.assertEqual(candidate["unity_preview"]["status"], "failed")
            self.assertEqual(candidate["unity_preview"]["error"], "no material")
            candidate["status"] = "failed"
            with self.assertRaises(ValueError):
                model.unity_preview(root, config, manifest, "prop:relic", 1)


class UnityIdentityTests(PublicationTestCase):
    KEYS = ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss",
            "emission", "preview_front", "preview_side", "preview_rear", "preview_three_quarter")

    def _setup(self, root):
        (root / "Assets").mkdir()
        init_project(root)
        config = load_project(root)
        self.candidate = model.material_candidate_paths(root, config, "relic", 1)
        outputs = {}
        for name in self.KEYS:
            self.candidate[name].parent.mkdir(parents=True, exist_ok=True)
            self.candidate[name].write_bytes(("first " + name).encode())
            outputs[name] = self.candidate[name].relative_to(root).as_posix()
        (root / "retained.glb").write_bytes(b"glb")
        asset = {"name": "relic", "status": "awaiting_texture_approval", "source": {"glb": "retained.glb"},
                 "generator": {"workflow": {}, "seed": {}},
                 "material_candidates": {"selected": None, "items": [
                     {"number": 1, "status": "candidate", "prompt": "steel", "outputs": outputs,
                      "validation": {"status": "passed"}}]}}
        return config, {"assets": {"prop:relic": asset}}

    def _unity(self, guids):
        def build(project_root, fbx, material, maps, render=None, lightmap_uvs=False):
            Path(material).write_bytes(b"material")
            paths = {"fbx": fbx, "material": material, **maps}
            return {"unity_version": "6000.6.3f1",
                    "assets": {role: {"path": Path(path).relative_to(project_root).as_posix(), "guid": guids[role]}
                               for role, path in paths.items()},
                    "material_textures": {role: guids[role] for role in maps}}
        return build

    def test_publication_records_the_unity_import_under_the_logical_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, manifest = self._setup(root)
            guids = {role: f"{index:032x}" for index, role in
                     enumerate(("fbx", "material", "basecolor", "normal", "metallic_gloss", "emission"))}
            with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                    patch("slopforge.pipelines.model.build_unity_material", side_effect=self._unity(guids)):
                model.approve_texture(root, config, manifest, "prop:relic", 1)
            record = load_manifest(root / config["asset_pipeline"]["manifest"])["assets"]["prop:relic"]["unity_import"]
            self.assertEqual(record["logical_id"], "prop:relic")
            self.assertEqual({role: entry["guid"] for role, entry in record["assets"].items()}, guids)

    def test_republish_that_changes_a_unity_guid_fails_and_restores_the_previous_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, manifest = self._setup(root)
            asset = manifest["assets"]["prop:relic"]
            guids = {role: f"{index:032x}" for index, role in
                     enumerate(("fbx", "material", "basecolor", "normal", "metallic_gloss", "emission"))}
            with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                    patch("slopforge.pipelines.model.build_unity_material", side_effect=self._unity(guids)):
                model.approve_texture(root, config, manifest, "prop:relic", 1)
            published = model.model_paths(root, config, "relic")["fbx"]
            first_import = json.loads(json.dumps(asset["unity_import"]))
            self.candidate["fbx"].write_bytes(b"second fbx")
            regenerated = dict(guids, fbx="f" * 32)  # e.g. the FBX's .meta was lost and regenerated on a fresh checkout
            with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                    patch("slopforge.pipelines.model.build_unity_material", side_effect=self._unity(regenerated)):
                with self.assertRaisesRegex(StageFailure, "changed the Unity GUID of the fbx") as caught:
                    model.approve_texture(root, config, manifest, "prop:relic", 1, force=True)
            self.assertEqual(caught.exception.category, "processing_validation")
            self.assertEqual(published.read_bytes(), b"first fbx")
            self.assertEqual(asset["unity_import"], first_import)
            self.assertEqual(asset["executions"][-1]["status"], "failed")
