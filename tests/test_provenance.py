import hashlib
import copy
import tempfile
import unittest
from pathlib import Path

from slopforge import provenance as provenance_module
from slopforge.provenance import generator_provenance, workflow_sha256


class WorkflowProvenanceTests(unittest.TestCase):
    def test_artifact_hash_uses_content_not_filename(self):
        self.assertTrue(callable(getattr(provenance_module, "file_sha256", None)))
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.glb"
            second = Path(temporary) / "renamed.glb"
            first.write_bytes(b"mesh bytes")
            second.write_bytes(b"mesh bytes")
            first_hash = provenance_module.file_sha256(first)
            self.assertEqual(first_hash, provenance_module.file_sha256(second))
            second.write_bytes(b"different mesh bytes")
            self.assertNotEqual(first_hash, provenance_module.file_sha256(second))

    def test_execution_identity_uses_semantic_inputs_only(self):
        self.assertTrue(callable(getattr(provenance_module, "execution_identity", None)))
        base = {
            "asset": {"type": "prop", "brief": "A brass coin", "project_path": "project-a"},
            "concept": {"artifact_id": "concept:2", "sha256": "a" * 64, "path": "candidate-a.png"},
            "workflow": {"id": "trellis", "sha256": "b" * 64, "effective_sha256": "c" * 64},
            "settings": {"seed": 17, "model_filename": "model-a.safetensors", "resolution": 1024},
            "references": [{"sha256": "d" * 64, "path": "reference-a.png"}],
            "invocation": {"uuid": "run-a", "started_at": "2026-01-01", "candidate_number": 2,
                           "prompt_id": "prompt-a", "output_filename": "mesh-a.glb"},
        }
        baseline = provenance_module.execution_identity(base)
        reordered = {key: copy.deepcopy(base[key]) for key in reversed(base)}
        reordered["asset"] = {key: base["asset"][key] for key in reversed(base["asset"])}
        reordered["concept"]["path"] = "elsewhere/candidate.png"
        reordered["asset"]["project_path"] = "project-b"
        reordered["references"][0]["path"] = "other/reference.png"
        reordered["invocation"] = {"uuid": "run-b", "started_at": "2027-02-03", "candidate_number": 9,
                                   "prompt_id": "prompt-b", "output_filename": "mesh-b.glb"}
        self.assertEqual(baseline, provenance_module.execution_identity(reordered))

        for section, key, value in (
                ("asset", "brief", "A silver coin"),
                ("concept", "sha256", "e" * 64),
                ("workflow", "effective_sha256", "f" * 64),
                ("settings", "resolution", 2048),
                ("settings", "seed", 18),
                ("settings", "model_filename", "model-b.safetensors"),
                ("references", 0, {"sha256": "0" * 64, "path": "reference-a.png"}),
        ):
            changed = copy.deepcopy(base)
            if section == "references":
                changed[section][key] = value
            else:
                changed[section][key] = value
            self.assertNotEqual(baseline, provenance_module.execution_identity(changed), (section, key))

    def test_effective_workflow_identity_tracks_bound_values_but_ignores_upload_names(self):
        self.assertTrue(callable(getattr(provenance_module, "canonical_workflow_identity", None)))
        source = {"1": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
                  "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "old"}}}
        effective = {"1": {"class_type": "LoadImage", "inputs": {"image": "upload-a.png"}},
                     "2": {"class_type": "SaveImage", "inputs": {"filename_prefix": "output-a"}},
                     "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "A brass coin"}},
                     "4": {"class_type": "KSampler", "inputs": {"seed": 17}},
                     "prompt_id": "prompt-a"}
        base = provenance_module.canonical_workflow_identity(source, effective, {"1.image": "a" * 64})
        renamed = copy.deepcopy(effective)
        renamed["1"]["inputs"]["image"] = "different-upload-name.png"
        renamed["2"]["inputs"]["filename_prefix"] = "output-b"
        renamed["prompt_id"] = "prompt-b"
        same = provenance_module.canonical_workflow_identity(source, renamed, {"1.image": "a" * 64})
        self.assertEqual(base["effective_sha256"], same["effective_sha256"])
        self.assertEqual(base["bindings"], same["bindings"])
        for changed_graph, uploaded in (
                ({**effective, "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "A silver coin"}}},
                 {"1.image": "a" * 64}),
                ({**effective, "4": {"class_type": "KSampler", "inputs": {"seed": 18}}, "prompt_id": "prompt-a"},
                 {"1.image": "a" * 64}),
                (effective, {"1.image": "b" * 64}),
        ):
            self.assertNotEqual(base["effective_sha256"],
                                provenance_module.canonical_workflow_identity(source, changed_graph, uploaded)["effective_sha256"])

    def test_provenance_facts_distinguish_known_unavailable_and_not_recorded(self):
        self.assertTrue(callable(getattr(provenance_module, "provenance_fact", None)))
        fact = provenance_module.provenance_fact
        self.assertEqual(fact("known", value="ComfyUI 0.3"),
                         {"status": "known", "value": "ComfyUI 0.3"})
        self.assertEqual(fact("unavailable", reason="API omitted weight revision"),
                         {"status": "unavailable", "reason": "API omitted weight revision"})
        self.assertEqual(fact("not_recorded", reason="legacy record"),
                         {"status": "not_recorded", "reason": "legacy record"})
        with self.assertRaisesRegex(ValueError, "Known facts require a value"):
            fact("known")
        with self.assertRaisesRegex(ValueError, "reason"):
            fact("unavailable")
        with self.assertRaisesRegex(ValueError, "provenance fact status"):
            fact("unknown")

    def test_workflow_hash_is_content_based_and_keeps_paths_out_of_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "workflow.json"
            content = b'{"nodes": []}\n'
            path.write_bytes(content)

            digest = workflow_sha256(path)
            provenance = generator_provenance("workflow.json", {"workflow_sha256": digest})

        self.assertEqual(digest, hashlib.sha256(content).hexdigest())
        self.assertEqual(provenance["workflow"], "workflow.json")
        self.assertEqual(provenance["workflow_sha256"], digest)
        self.assertNotIn(temporary, str(provenance))

    def test_synthesized_workflow_does_not_claim_a_file_hash(self):
        provenance = generator_provenance("hunyuan3d_image_to_model_api", {"workflow_sha256": None})
        self.assertNotIn("workflow_sha256", provenance)

    def test_generator_provenance_records_workflow_requirements_identity(self):
        identity = {"id": "image.text_to_image", "version": 1, "schema_version": 1}
        provenance = generator_provenance("image_text2img_api.json", {"workflow_requirements": identity})
        self.assertEqual(provenance["workflow_requirements"], identity)

    def test_legacy_workflow_provenance_marks_requirements_unknown(self):
        provenance = generator_provenance("legacy.json", {"workflow_requirements": {"status": "unknown"}})
        self.assertEqual(provenance["workflow_requirements"], {"status": "unknown"})


if __name__ == "__main__":
    unittest.main()
