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


if __name__ == "__main__":
    unittest.main()
