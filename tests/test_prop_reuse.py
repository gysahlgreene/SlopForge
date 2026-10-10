import hashlib
import tempfile
import unittest
from pathlib import Path

from slopforge.pipelines.reuse import artifact_integrity, earliest_stale_stage, stage_reuse_decision


class PropReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "mesh.glb").write_bytes(b"mesh")
        self.input = {"id": "mesh:1", "sha256": hashlib.sha256(b"mesh").hexdigest()}
        self.output = {"id": "material:1", "type": "texture", "path": "mesh.glb",
                       "sha256": hashlib.sha256(b"mesh").hexdigest(), "stage": "material_generation",
                       "attempt": 1, "derived_from": [{"artifact_id": self.input["id"],
                                                          "sha256": self.input["sha256"]}]}
        self.stage = {"name": "material_generation", "attempt": 1, "status": "succeeded",
                      "inputs": [self.input], "outputs": [self.output], "settings": {"seed": 1}}

    def test_identical_semantic_inputs_and_intact_artifact_are_reusable(self):
        self.assertTrue(stage_reuse_decision(self.root, self.stage, inputs=[self.input], settings={"seed": 1})["reusable"])

    def test_changed_input_or_settings_is_stale(self):
        decision = stage_reuse_decision(self.root, self.stage,
            inputs=[{"id": "mesh:2", "sha256": "0" * 64}], settings={"seed": 2})
        self.assertFalse(decision["reusable"])
        self.assertTrue(any("semantic mismatch" in reason for reason in decision["reasons"]))
        broken = {**self.stage, "outputs": [{**self.output, "derived_from": []}]}
        self.assertIn("lineage mismatch", " ".join(stage_reuse_decision(self.root, broken,
            inputs=[self.input], settings={"seed": 1})["reasons"]))

    def test_package_stage_outputs_may_record_valid_input_subsets(self):
        concept = {"id": "concept:1", "sha256": "1" * 64}
        conditioning = {"id": "conditioning:1", "sha256": "2" * 64}
        package_shape = {**self.stage, "name": "mesh_workflow_execution",
                         "inputs": [concept, conditioning],
                         "outputs": [{**self.output, "stage": "mesh_workflow_execution",
                             "derived_from": [{"artifact_id": conditioning["id"],
                                               "sha256": conditioning["sha256"]}]}]}
        self.assertTrue(stage_reuse_decision(self.root, package_shape,
            inputs=[concept, conditioning], settings={"seed": 1})["reusable"])
        unrelated = {**package_shape, "outputs": [{**package_shape["outputs"][0],
            "derived_from": [{"artifact_id": "foreign", "sha256": "3" * 64}]}]}
        self.assertIn("lineage mismatch", " ".join(stage_reuse_decision(self.root, unrelated,
            inputs=[concept, conditioning], settings={"seed": 1})["reasons"]))

    def test_output_identity_must_match_stage(self):
        for changed in ({"id": ""}, {"stage": "material_assembly_export"}, {"attempt": 2}):
            with self.subTest(changed=changed):
                decision = stage_reuse_decision(self.root, {**self.stage,
                    "outputs": [{**self.output, **changed}]}, inputs=[self.input], settings={"seed": 1})
                self.assertFalse(decision["reusable"])

    def test_nonpositive_stage_attempt_is_not_reusable(self):
        for attempt in (-1, True):
            with self.subTest(attempt=attempt):
                malformed = {**self.stage, "attempt": attempt,
                             "outputs": [{**self.output, "attempt": attempt}]}
                decision = stage_reuse_decision(self.root, malformed,
                    inputs=[self.input], settings={"seed": 1})
                self.assertFalse(decision["reusable"])

    def test_missing_or_hash_mismatched_output_is_stale(self):
        missing = {**self.output, "path": "missing.glb"}
        self.assertIn("missing", " ".join(stage_reuse_decision(self.root, {**self.stage, "outputs": [missing]},
            inputs=[self.input], settings={"seed": 1})["reasons"]))
        (self.root / "mesh.glb").write_bytes(b"changed")
        self.assertIn("hash mismatch", " ".join(stage_reuse_decision(self.root, self.stage,
            inputs=[self.input], settings={"seed": 1})["reasons"]))

    def test_same_basename_different_content_is_not_substituted(self):
        (self.root / "elsewhere").mkdir()
        (self.root / "elsewhere/mesh.glb").write_bytes(b"different content")
        decision = artifact_integrity(self.root, {**self.output, "path": "absent/mesh.glb"})
        self.assertFalse(decision[0])
        self.assertIn("missing", decision[1])

    def test_nonterminal_stage_is_not_reusable(self):
        decision = stage_reuse_decision(self.root, {**self.stage, "status": "running"},
            inputs=[self.input], settings={"seed": 1})
        self.assertFalse(decision["reusable"])

    def test_earliest_stale_stage_uses_fixed_stage_order(self):
        self.assertEqual(earliest_stale_stage(self.root, [self.stage], {
            "concept_generation": ([], {}), "material_generation": ([self.input], {"seed": 1})
        }), "concept_generation")

    def test_earliest_stale_stage_rejects_unknown_requested_stage(self):
        with self.assertRaisesRegex(ValueError, "unsupported prop stage"):
            earliest_stale_stage(self.root, [], {"mesh_preperation": ([], {})})


if __name__ == "__main__":
    unittest.main()
