import os
from itertools import product
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopforge.config import load_project
from slopforge.initializer import init_project
from slopforge.pipelines import model


class TextureApprovalRollbackTests(unittest.TestCase):
    def test_failed_publication_preserves_previous_outputs_and_source(self):
        for previously_approved, failure_stage in product((False, True), ("copy", "material")):
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
                    if failure_stage == 'copy' and Path(destination).resolve() != (root / config['asset_pipeline']['manifest']).resolve() and replacements == 2:
                        raise RuntimeError('Unity failed publication')
                    return replace(source_path, destination)

                with patch('slopforge.pipelines.model.os.replace', side_effect=fail_copy), \
                        patch('slopforge.pipelines.model.unity_cli', return_value='unity'), \
                        patch('slopforge.pipelines.model.build_unity_material', side_effect=fail_material):
                    with self.assertRaisesRegex(RuntimeError, 'Unity failed'):
                        model.approve_texture(root, config, manifest, 'prop:relic', 1, force=True)
                self.assertEqual(asset["status"], before_status)
                self.assertEqual(asset["material_candidates"]["selected"], before_selected)
                publication = asset["executions"][-1]
                self.assertEqual(publication["status"], "failed")
                self.assertEqual(publication["stages"][-1]["status"], "failed")
                self.assertEqual(source.read_bytes(), b'original source')
                for path in destinations + metadata:
                    if path in originals:
                        self.assertEqual(path.read_bytes(), originals[path])
                    else:
                        self.assertFalse(path.exists(), str(path))
