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


class TextureApprovalRollbackTests(unittest.TestCase):
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
        for previously_approved, failure_stage in product((False, True), ("copy", "material", "interrupt", "backup")):
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

                def fail_material(*args):
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

                with patch('slopforge.pipelines.model.os.replace', side_effect=fail_copy), \
                        patch('slopforge.pipelines.model.shutil.copy2', side_effect=fail_backup), \
                        patch('slopforge.pipelines.model.unity_cli', return_value='unity'), \
                        patch('slopforge.pipelines.model.build_unity_material', side_effect=fail_material):
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
                       side_effect=lambda _r, _f, out, _m: (_ for _ in ()).throw(RuntimeError("Unity failed"))), \
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
