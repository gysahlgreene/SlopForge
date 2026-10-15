import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from slopforge.config import load_project
from slopforge.manifest import load_manifest, new_record, save_manifest
from slopforge.pipelines.model import approve, material_candidate_paths
from slopforge.provenance import file_sha256
from slopforge.style import load_style
from slopforge.taxonomy import load_taxonomy

from slopforge.pipelines.reuse import artifact_integrity, earliest_stale_stage, stage_reuse_decision


class PropReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "mesh.glb").write_bytes(b"mesh")
        self.input = {"id": "mesh:1", "sha256": hashlib.sha256(b"mesh").hexdigest()}
        self.output = {"id": "material:1", "type": "surface.swatch", "path": "mesh.glb",
                       "sha256": hashlib.sha256(b"mesh").hexdigest(), "stage": "material_generation",
                       "attempt": 1, "derived_from": [{"artifact_id": self.input["id"],
                                                          "sha256": self.input["sha256"]}]}
        metadata = {**self.output, "id": "material:metadata", "type": "generation.metadata"}
        self.stage = {"name": "material_generation", "attempt": 1, "status": "succeeded",
                      "inputs": [self.input], "outputs": [self.output, metadata], "settings": {"seed": 1}}

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
                         "outputs": [{**self.output, "type": "mesh.glb", "stage": "mesh_workflow_execution",
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

    def test_malformed_stage_record_is_not_reusable_without_raising(self):
        decision = stage_reuse_decision(self.root, None, inputs=[self.input], settings={})

        self.assertFalse(decision["reusable"])

    def test_mesh_workflow_stage_without_required_output_is_not_reusable(self):
        stage = {**self.stage, "name": "mesh_workflow_execution", "outputs": []}

        decision = stage_reuse_decision(self.root, stage, inputs=[self.input], settings={"seed": 1})

        self.assertFalse(decision["reusable"])

    def test_mesh_workflow_stage_without_required_mesh_type_is_not_reusable(self):
        output = {**self.output, "type": "generation.metadata",
                  "stage": "mesh_workflow_execution"}
        stage = {**self.stage, "name": "mesh_workflow_execution", "outputs": [output]}

        decision = stage_reuse_decision(self.root, stage, inputs=[self.input], settings={"seed": 1})

        self.assertFalse(decision["reusable"])

    def test_mesh_workflow_stage_with_exact_required_mesh_output_is_reusable(self):
        output = {**self.output, "type": "mesh.glb", "stage": "mesh_workflow_execution"}
        stage = {**self.stage, "name": "mesh_workflow_execution", "outputs": [output]}

        decision = stage_reuse_decision(self.root, stage, inputs=[self.input], settings={"seed": 1})

        self.assertTrue(decision["reusable"], decision["reasons"])

    def test_earliest_stale_stage_uses_fixed_stage_order(self):
        self.assertEqual(earliest_stale_stage(self.root, [self.stage], {
            "concept_generation": ([], {}), "material_generation": ([self.input], {"seed": 1})
        }), "concept_generation")

    def test_earliest_stale_stage_rejects_unknown_requested_stage(self):
        with self.assertRaisesRegex(ValueError, "unsupported prop stage"):
            earliest_stale_stage(self.root, [], {"mesh_preperation": ([], {})})


    def test_retexture_reuses_processed_mesh_only_for_matching_source_and_settings(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision

        source_path = self.root / "source.glb"
        processed_path = self.root / "processed.blend"
        source_path.write_bytes(b"source mesh")
        processed_path.write_bytes(b"processed mesh")
        source = {"id": "mesh:1", "type": "mesh.glb", "path": "source.glb",
                  "sha256": file_sha256(source_path), "stage": "mesh_workflow_execution", "attempt": 1,
                  "derived_from": []}
        settings = {"face_budget": 1000, "material_scale": 3.0}
        prepared = {"id": "prepared:1", "type": "mesh.prepared", "path": "processed.blend",
                    "sha256": file_sha256(processed_path), "stage": "mesh_preparation", "attempt": 1,
                    "derived_from": [{"artifact_id": source["id"], "sha256": source["sha256"]}]}
        asset = {"source": {"processed_mesh": "processed.blend"}, "executions": [{"id": "exec:1", "stages": [{
            "name": "mesh_preparation", "attempt": 1, "status": "succeeded",
            "inputs": [source], "settings": settings, "outputs": [prepared]}]}]}

        self.assertTrue(processed_mesh_reuse_decision(self.root, asset, source, settings)["reusable"])
        self.assertFalse(processed_mesh_reuse_decision(
            self.root, asset, source, {**settings, "material_scale": 2.0})["reusable"])
        processed_path.write_bytes(b"changed mesh")
        self.assertFalse(processed_mesh_reuse_decision(self.root, asset, source, settings)["reusable"])

    def test_retexture_rebuilds_missing_or_unknown_lineage_mesh(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision

        source_path = self.root / "source.glb"
        source_path.write_bytes(b"source mesh")
        source = {"id": "mesh:legacy", "type": "mesh.glb", "path": "source.glb",
                  "sha256": file_sha256(source_path), "stage": "mesh_workflow_execution", "attempt": 1,
                  "derived_from": []}
        asset = {"source": {"processed_mesh": "missing.blend"}, "executions": []}

        decision = processed_mesh_reuse_decision(self.root, asset, source, {})
        self.assertFalse(decision["reusable"])
        self.assertIn("no matching processed mesh lineage", " ".join(decision["reasons"]))
        self.assertFalse(processed_mesh_reuse_decision(self.root, asset, None, {})["reusable"])

    def test_retexture_accepts_recorded_mesh_processed_output_with_source_chain(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision

        source_path = self.root / "source.glb"
        prepared_path = self.root / "prepared.blend"
        processed_path = self.root / "processed.blend"
        source_path.write_bytes(b"source")
        prepared_path.write_bytes(b"prepared")
        processed_path.write_bytes(b"processed")
        source = {"id": "source", "type": "mesh.glb", "path": "source.glb",
                  "sha256": file_sha256(source_path), "stage": "mesh_workflow_execution", "attempt": 1,
                  "derived_from": []}
        prepared = {"id": "prepared", "type": "mesh.prepared", "path": "prepared.blend",
                    "sha256": file_sha256(prepared_path), "stage": "mesh_preparation", "attempt": 1,
                    "derived_from": [{"artifact_id": source["id"], "sha256": source["sha256"]}]}
        processed = {"id": "processed", "type": "mesh.processed", "path": "processed.blend",
                     "sha256": file_sha256(processed_path), "stage": "material_assembly_export", "attempt": 1,
                     "derived_from": [{"artifact_id": prepared["id"], "sha256": prepared["sha256"]}]}
        settings = {"face_budget": 1000, "material_scale": 3.0, "processing_tool_sha256": "tool"}
        asset = {"source": {"processed_mesh": "processed.blend"}, "executions": [{"id": "exec:1", "stages": [
            {"name": "mesh_preparation", "attempt": 1, "status": "succeeded", "inputs": [source],
             "settings": {}, "outputs": [prepared]},
            {"name": "material_assembly_export", "attempt": 1, "status": "succeeded",
             "inputs": [prepared], "settings": settings, "outputs": [processed]}]}]}

        self.assertTrue(processed_mesh_reuse_decision(self.root, asset, source, settings)["reusable"])

    def test_prop_child_reuse_requires_intact_matching_concept_execution(self):
        from slopforge.pipelines.model import prop_child_reuse_decision

        path = self.root / "candidate.png"
        path.write_bytes(b"concept")
        artifact = {"id": "concept-candidate:1", "type": "image.concept", "path": "candidate.png",
                    "sha256": file_sha256(path), "stage": "concept_generation", "attempt": 1,
                    "derived_from": []}
        stage = {"name": "concept_generation", "attempt": 1, "status": "succeeded", "inputs": [],
                 "settings": {"prompt": "brass relay", "seed": 7}, "outputs": [artifact]}
        execution = {"id": "execution:1", "status": "succeeded",
                     "identity_inputs": {"asset_type": "prop", "brief": "brass relay",
                                          "generation_prompt": "brass relay"}, "stages": [stage]}
        asset = {"type": "prop", "description": "brass relay", "generation_prompt": "brass relay",
                 "candidates": {"items": [{"number": 1, "status": "candidate", "path": "candidate.png",
                                              "execution_id": "execution:1", "artifact": artifact}]},
                 "executions": [execution]}
        child = {"id": "terminal", "type": "prop", "description": "brass relay",
                 "generation_prompt": "brass relay"}

        self.assertFalse(prop_child_reuse_decision(self.root, asset, {"status": "completed"}, child, {})["reusable"])
        child["description"] = "copper terminal"
        self.assertFalse(prop_child_reuse_decision(self.root, asset, {"status": "completed"}, child, {})["reusable"])


    def test_legacy_unknown_provenance_does_not_reuse_unproven_mesh(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision

        source = {"path": "legacy.glb", "type": "mesh.glb", "sha256": "a" * 64,
                  "id": "legacy-mesh", "stage": "legacy", "attempt": 1, "derived_from": []}
        decision = processed_mesh_reuse_decision(
            self.root, {"source": {"processed_mesh": "processed.blend"}, "executions": []}, source, {})
        self.assertFalse(decision["reusable"])

    def test_duplicate_filename_with_different_content_is_not_reused(self):
        duplicate = self.root / "other"
        duplicate.mkdir()
        (self.root / "mesh.glb").write_bytes(b"recorded content")
        (duplicate / "mesh.glb").write_bytes(b"different content")
        reference = {**self.output, "path": "other/mesh.glb",
                     "sha256": hashlib.sha256(b"recorded content").hexdigest()}

        decision = artifact_integrity(self.root, reference)
        self.assertFalse(decision[0])
        self.assertIn("hash mismatch", decision[1])




# ================================================================
# Finding 1 tests: processed_mesh_reuse_decision must reject ambiguous provenance
# ================================================================
class Finding1ProcessedMeshProvenanceTests(unittest.TestCase):
    """Regression tests for Finding 1: retexture must reject ambiguous processed-mesh provenance."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_valid_chain(self):
        """Create a valid processed-mesh provenance chain.

        source (mesh.glb) -> prepared (mesh.prepared) -> processed (mesh.processed)
        """
        source_path = self.root / "source.glb"
        processed_path = self.root / "processed.blend"
        source_path.write_bytes(b"source mesh")
        processed_path.write_bytes(b"processed mesh")
        source = {"id": "mesh:1", "type": "mesh.glb", "path": "source.glb",
                  "sha256": file_sha256(source_path),
                  "stage": "mesh_workflow_execution", "attempt": 1, "derived_from": []}
        prepared = {"id": "prepared:1", "type": "mesh.prepared", "path": "processed.blend",
                    "sha256": file_sha256(processed_path),
                    "stage": "mesh_preparation", "attempt": 1,
                    "derived_from": [{"artifact_id": source["id"], "sha256": source["sha256"]}]}
        processed = {"id": "processed:1", "type": "mesh.processed", "path": "processed.blend",
                     "sha256": file_sha256(processed_path),
                     "stage": "material_assembly_export", "attempt": 1,
                     "derived_from": [{"artifact_id": prepared["id"], "sha256": prepared["sha256"]}]}
        return source, prepared, processed, processed_path

    def _settings(self):
        return {"face_budget": 1000, "material_scale": 3.0,
                "processing_tool_sha256": "blender_sha"}

    def assertReusable(self, decision):
        self.assertTrue(decision["reusable"],
                        f"expected reusable, got reasons: {decision['reasons']}")
        self.assertEqual(decision["reasons"], [],
                         f"expected no reasons, got: {decision['reasons']}")

    def assertNotReusable(self, decision):
        self.assertFalse(decision["reusable"],
                         f"expected not reusable, got reasons: {decision['reasons']}")

    # A. succeeded processed-mesh stage + failed duplicate with same name/attempt -\u003e reject reuse
    def test_succeeded_and_failed_duplicate_same_name_attempt_rejects_reuse(self):
        """A failed duplicate with same stage name and attempt should not create ambiguity.

        The invariant: two stages with same name+attempt across executions means
        ambiguous provenance - we reject rather than guess."""
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source, prepared, processed, _ = self.make_valid_chain()
        settings = self._settings()
        succeeded = {"name": "material_assembly_export", "attempt": 1,
                      "status": "succeeded", "inputs": [prepared],
                      "settings": settings, "outputs": [processed]}
        failed = {"name": "material_assembly_export", "attempt": 1,
                  "status": "failed", "inputs": [prepared],
                  "settings": settings, "outputs": []}
        asset = {"source": {"processed_mesh": "processed.blend"},
                 "executions": [{"id": "exec:1", "stages": [succeeded]},
                                {"id": "exec:2", "stages": [failed]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, prepared, settings)
        self.assertNotReusable(decision)

    # B. two succeeded duplicate processed-mesh stage records -\u003e reject reuse
    def test_two_succeeded_duplicate_processed_mesh_stage_records_rejects_reuse(self):
        """Two succeeded stages with same name/attempt are ambiguous provenance."""
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source, prepared, processed, _ = self.make_valid_chain()
        settings = self._settings()
        s1 = {"name": "material_assembly_export", "attempt": 1,
              "status": "succeeded", "inputs": [prepared],
              "settings": settings, "outputs": [processed]}
        s2 = {"name": "material_assembly_export", "attempt": 1,
              "status": "succeeded", "inputs": [prepared],
              "settings": settings, "outputs": [processed]}
        asset = {"source": {"processed_mesh": "processed.blend"},
                 "executions": [{"id": "exec:1", "stages": [s1, s2]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, prepared, settings)
        self.assertNotReusable(decision)

    # C. one stage containing duplicate matching processed-mesh output IDs -\u003e reject reuse
    def test_duplicate_matching_output_id_in_stage_rejects_reuse(self):
        """An output with a duplicate ID within the same stage is ambiguous."""
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source, prepared, processed, _ = self.make_valid_chain()
        settings = self._settings()
        # Two outputs with same ID = ambiguous output identity
        stage = {"name": "material_assembly_export", "attempt": 1,
                 "status": "succeeded", "inputs": [prepared],
                 "settings": settings, "outputs": [processed, processed]}
        asset = {"source": {"processed_mesh": "processed.blend"},
                 "executions": [{"id": "exec:1", "stages": [stage]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, prepared, settings)
        self.assertNotReusable(decision)

    # D. output records stage/attempt values that disagree with containing stage -\u003e reject reuse
    def test_output_stage_attempt_disagree_with_containing_stage_rejects_reuse(self):
        """Output artifact whose stage or attempt does not match its containing stage is invalid.

        The invariant: the output's recorded attempt must agree with the containing
        stage's attempt. An output claiming a different attempt is not reliably
        attributable to this stage."""
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source, prepared, processed, _ = self.make_valid_chain()
        settings = self._settings()
        # Output with correct provenance but wrong attempt
        bad_output = {"id": "processed:1", "type": "mesh.processed",
                      "path": "processed.blend",
                      "sha256": file_sha256(self.root / "processed.blend"),
                      "stage": "material_assembly_export", "attempt": 99,
                      "derived_from": [{"artifact_id": prepared["id"],
                                        "sha256": prepared["sha256"]}]}
        stage = {"name": "material_assembly_export", "attempt": 1,
                 "status": "succeeded", "inputs": [prepared],
                 "settings": settings, "outputs": [bad_output]}
        asset = {"source": {"processed_mesh": "processed.blend"},
                 "executions": [{"id": "exec:1", "stages": [stage]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, prepared, settings)
        self.assertNotReusable(decision)

    # E. one exact unambiguous processed-mesh stage/output -\u003e reuse succeeds
    def test_exact_unambiguous_processed_mesh_stage_and_output_reuses(self):
        """A single unique succeeded stage with a unique matching output is reusable."""
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source, prepared, processed, _ = self.make_valid_chain()
        settings = self._settings()
        stage = {"name": "material_assembly_export", "attempt": 1,
                 "status": "succeeded", "inputs": [prepared],
                 "settings": settings, "outputs": [processed]}
        asset = {"source": {"processed_mesh": "processed.blend"},
                 "executions": [{"id": "exec:1", "stages": [stage]}]}
        # source_mesh must be the input to the stage that matches stage inputs
        decision = processed_mesh_reuse_decision(
            self.root, asset, prepared, settings)
        self.assertReusable(decision)

    # F. output recorded stage disagrees with containing stage -\u003e reject reuse
    def test_output_stage_mismatch_with_containing_stage_rejects_reuse(self):
        """Output artifact whose "stage" field disagrees with its containing
        stage's name is not reliably attributable to this stage.

        The invariant: after uniquely resolving the processed-mesh stage and
        output, the output's recorded stage must equal containing_stage.name
        and output.attempt must equal containing_stage.attempt.
        Both are required; any mismatch rejects conservatively."""
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source, prepared, processed, _ = self.make_valid_chain()
        settings = self._settings()
        # The output claims the correct type/path/hash/attempt but wrong stage
        bad_stage = "mesh_preparation"  # wrong: should be "material_assembly_export"
        bad_output = {"id": "processed:1", "type": "mesh.processed",
                      "path": "processed.blend",
                      "sha256": file_sha256(self.root / "processed.blend"),
                      "stage": bad_stage, "attempt": 1,
                      "derived_from": [{"artifact_id": prepared["id"],
                                        "sha256": prepared["sha256"]}]}
        stage = {"name": "material_assembly_export", "attempt": 1,
                 "status": "succeeded", "inputs": [prepared],
                 "settings": settings, "outputs": [bad_output]}
        asset = {"source": {"processed_mesh": "processed.blend"},
                 "executions": [{"id": "exec:1", "stages": [stage]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, prepared, settings)
        self.assertNotReusable(decision)
        self.assertTrue(
            any("stage" in r.lower() for r in decision["reasons"]),
            f"expected stage-related reason, got: {decision['reasons']}")


class Finding1MalformedSiblingRejectionTests(unittest.TestCase):
    """Regression tests for Finding 1: malformed members in authoritative
    provenance lists must fail closed rather than be silently skipped."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _make_base_fixture(self, stages):
        """Create a base fixture with identity checks that pass."""
        path = self.root / "candidate.png"
        path.write_bytes(b"concept")
        sha = file_sha256(path)
        valid_stage = {
            "name": "concept_generation", "attempt": 1,
            "status": "succeeded", "inputs": [],
            "settings": {"prompt": "brass relay", "variation": None, "seed": 7},
            "outputs": [{"id": "concept-candidate:1", "type": "image.concept",
                         "path": "candidate.png", "sha256": sha,
                         "stage": "concept_generation", "attempt": 1,
                         "derived_from": []}]
        }
        execution = {
            "id": "execution:1", "status": "succeeded",
            "identity_inputs": {"asset_type": "prop", "brief": "brass relay",
                                 "generation_prompt": "brass relay",
                                 "style": "default",
                                 "conditioning": {"strategy": "text_only"},
                                 "quality": {"tier": "normal", "settings": {}},
                                 "candidate_attempts": [{"seed": 7, "variation": None}]},
            "stages": stages
        }
        artifact = {"id": "concept-candidate:1", "type": "image.concept",
                    "path": "candidate.png", "sha256": sha,
                    "stage": "concept_generation", "attempt": 1,
                    "derived_from": []}
        asset = {
            "type": "prop", "description": "brass relay",
            "generation_prompt": "brass relay",
            "candidates": {"items": [{"number": 1, "status": "candidate",
                                       "path": "candidate.png",
                                       "execution_id": "execution:1",
                                       "artifact": artifact}]},
            "executions": [execution]
        }
        child = {"id": "terminal", "type": "prop", "description": "brass relay",
                 "generation_prompt": "brass relay",
                 "requested_style_identity": "default",
                 "requested_conditioning": {"strategy": "text_only"}}
        child_stage = {"status": "completed",
                       "candidate_execution_ids": ["execution:1"]}
        return asset, child, child_stage

    # A. model.py candidate provenance: valid evidence + None sibling
    def test_candidate_provenance_with_malformed_none_stage_sibling_rejects(self):
        """A valid candidate stage + None sibling in execution_stages must reject."""
        from slopforge.pipelines.model import prop_child_reuse_decision
        valid_stage = {
            "name": "concept_generation", "attempt": 1,
            "status": "succeeded", "inputs": [],
            "settings": {"prompt": "brass relay", "variation": None, "seed": 7},
            "outputs": [{"id": "concept-candidate:1", "type": "image.concept",
                         "path": "candidate.png", "sha256": "s", "stage": "concept_generation",
                         "attempt": 1, "derived_from": []}]
        }
        asset, child, child_stage = self._make_base_fixture([valid_stage, None])
        decision = prop_child_reuse_decision(
            self.root, asset, child_stage, child,
            {"asset_pipeline": {"defaults": {"image_candidates": 1}}})
        self.assertFalse(
            decision["reusable"],
            f"expected rejected for corrupted stage, got: {decision['reasons']}")

    # B. model.py candidate provenance: valid evidence + non-dict sibling
    def test_candidate_provenance_with_malformed_string_stage_sibling_rejects(self):
        """A valid candidate stage + string entry in execution_stages must reject."""
        from slopforge.pipelines.model import prop_child_reuse_decision
        valid_stage = {
            "name": "concept_generation", "attempt": 1,
            "status": "succeeded", "inputs": [],
            "settings": {"prompt": "brass relay", "variation": None, "seed": 7},
            "outputs": [{"id": "concept-candidate:1", "type": "image.concept",
                         "path": "candidate.png", "sha256": "s", "stage": "concept_generation",
                         "attempt": 1, "derived_from": []}]
        }
        asset, child, child_stage = self._make_base_fixture([valid_stage, "corrupted_entry"])
        decision = prop_child_reuse_decision(
            self.root, asset, child_stage, child,
            {"asset_pipeline": {"defaults": {"image_candidates": 1}}})
        self.assertFalse(
            decision["reusable"],
            f"expected rejected for corrupted stage, got: {decision['reasons']}")

    # C. single valid stage must still succeed
    def test_single_valid_stage_still_succeeds(self):
        """An execution with exactly one valid, uniquely-matching stage must pass."""
        from slopforge.pipelines.model import prop_child_reuse_decision
        path = self.root / "candidate.png"
        path.write_bytes(b"concept")
        sha = file_sha256(path)
        valid_stage = {
            "name": "concept_generation", "attempt": 1,
            "status": "succeeded", "inputs": [],
            "settings": {"prompt": "brass relay", "variation": None, "seed": 7},
            "outputs": [{"id": "concept-candidate:1", "type": "image.concept",
                         "path": "candidate.png", "sha256": sha,
                         "stage": "concept_generation", "attempt": 1,
                         "derived_from": []}]
        }
        asset, child, child_stage = self._make_base_fixture([valid_stage])
        decision = prop_child_reuse_decision(
            self.root, asset, child_stage, child,
            {"asset_pipeline": {"defaults": {"image_candidates": 1}}})
        self.assertTrue(
            decision["reusable"],
            f"expected reusable, got: {decision['reasons']}")

    def test_valid_candidate_execution_with_malformed_execution_sibling_rejects(self):
        from slopforge.pipelines.model import prop_child_reuse_decision
        asset, child, child_stage = self._make_base_fixture([])
        asset["executions"][0]["stages"] = [{
            "name": "concept_generation", "attempt": 1, "status": "succeeded",
            "inputs": [], "settings": {"prompt": "brass relay", "variation": None, "seed": 7},
            "outputs": [asset["candidates"]["items"][0]["artifact"]],
        }]
        asset["executions"].append({"id": "broken", "status": "failed", "stages": "malformed"})
        decision = prop_child_reuse_decision(self.root, asset, child_stage, child,
            {"asset_pipeline": {"defaults": {"image_candidates": 1}}})
        self.assertFalse(decision["reusable"])

    def test_valid_candidate_stage_with_malformed_dict_sibling_rejects(self):
        from slopforge.pipelines.model import prop_child_reuse_decision
        asset, child, child_stage = self._make_base_fixture([])
        asset["executions"][0]["stages"] = [{
            "name": "concept_generation", "attempt": 1, "status": "succeeded",
            "inputs": [], "settings": {"prompt": "brass relay", "variation": None, "seed": 7},
            "outputs": [asset["candidates"]["items"][0]["artifact"]],
        }, {"name": "unrelated_stage"}]
        decision = prop_child_reuse_decision(self.root, asset, child_stage, child,
            {"asset_pipeline": {"defaults": {"image_candidates": 1}}})
        self.assertFalse(decision["reusable"])

    def test_valid_candidate_stage_with_malformed_artifact_identity_sibling_rejects(self):
        from slopforge.pipelines.model import prop_child_reuse_decision
        asset, child, child_stage = self._make_base_fixture([])
        artifact = asset["candidates"]["items"][0]["artifact"]
        malformed_output = {**artifact, "id": "broken", "sha256": "z" * 64,
                            "stage": "unrelated_stage"}
        asset["executions"][0]["stages"] = [{
            "name": "concept_generation", "attempt": 1, "status": "succeeded",
            "inputs": [], "settings": {"prompt": "brass relay", "variation": None, "seed": 7},
            "outputs": [artifact],
        }, {"name": "unrelated_stage", "attempt": 1, "status": "failed",
            "inputs": [], "settings": {}, "outputs": [malformed_output]}]
        decision = prop_child_reuse_decision(self.root, asset, child_stage, child,
            {"asset_pipeline": {"defaults": {"image_candidates": 1}}})
        self.assertFalse(decision["reusable"])


class Finding2AdoptStageDuplicateRejectTests(unittest.TestCase):
    """Regression tests for Finding 2: _adopt_stage must reject duplicate
    stage identity, not silently pick first/last."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_context(self, stages):
        manifest = {"assets": {"test-key": {
            "executions": [{"id": "exec-1", "status": "running"}]}}}
        return {"manifest": manifest, "key": "test-key",
                "execution_id": "exec-1", "root": self.root,
                "pipeline": {"manifest": "manifest.json"},
                "reuse_execution": {"id": "prior-exe", "stages": stages}}

    # A. _adopt_stage: succeeded + failed duplicate same name/attempt -> no adoption
    def test_adopt_stage_succeeded_failed_duplicate_rejects(self):
        from slopforge.pipelines.model import _adopt_stage
        succeeded = {"name": "concept_generation", "attempt": 1,
                     "status": "succeeded", "inputs": [], "outputs": [], "settings": {}}
        failed = {"name": "concept_generation", "attempt": 1,
                  "status": "failed", "inputs": [], "outputs": [], "settings": {}}
        ctx = self.make_context([succeeded, failed])
        self.assertIsNone(_adopt_stage(ctx, "concept_generation", 1, [], {}))

    # B. _adopt_stage: two succeeded duplicates same name/attempt -> no adoption
    def test_adopt_stage_two_succeeded_duplicates_rejects(self):
        from slopforge.pipelines.model import _adopt_stage
        s1 = {"name": "material_assembly_export", "attempt": 1,
              "status": "succeeded", "inputs": [], "outputs": [], "settings": {}}
        s2 = {"name": "material_assembly_export", "attempt": 1,
              "status": "succeeded", "inputs": [], "outputs": [], "settings": {}}
        ctx = self.make_context([s1, s2])
        self.assertIsNone(_adopt_stage(ctx, "material_assembly_export", 1, [], {}))

    def test_adopt_stage_rejects_malformed_same_name_attempt_sibling(self):
        from slopforge.pipelines.model import _adopt_stage
        valid = {"name": "material_assembly_export", "attempt": 1,
                 "status": "succeeded", "inputs": [], "outputs": [], "settings": {}}
        malformed = {"name": "material_assembly_export", "attempt": "1",
                     "status": "failed", "inputs": [], "outputs": [], "settings": {}}
        ctx = self.make_context([valid, malformed])

        self.assertIsNone(_adopt_stage(ctx, "material_assembly_export", 1, [], {}))

    def test_adopt_stage_ignores_valid_unrelated_stage_identity(self):
        from slopforge.pipelines.model import _adopt_stage
        valid = {"name": "material_assembly_export", "attempt": 1,
                 "status": "succeeded", "inputs": [], "outputs": [], "settings": {}}
        unrelated = {"name": "concept_generation", "attempt": "1",
                     "status": "failed", "inputs": [], "outputs": [], "settings": {}}
        ctx = self.make_context([valid, unrelated])

        self.assertIsNone(_adopt_stage(ctx, "material_assembly_export", 1, [], {}))

    def test_adopt_stage_rejects_ambiguous_current_execution_identity(self):
        from slopforge.pipelines.model import _adopt_stage
        valid = {"name": "material_assembly_export", "attempt": 1,
                 "status": "succeeded", "inputs": [], "outputs": [], "settings": {}}
        ctx = self.make_context([valid])
        current = ctx["manifest"]["assets"]["test-key"]["executions"][0]
        ctx["manifest"]["assets"]["test-key"]["executions"].append(dict(current))

        self.assertIsNone(_adopt_stage(ctx, "material_assembly_export", 1, [], {}))

    # C. _adopt_stage: exactly one valid -> adoption still succeeds
    def test_adopt_stage_single_valid_succeeds(self):
        from slopforge.pipelines.model import _adopt_stage
        path = Path(self.root) / "mesh.glb"
        path.write_bytes(b"mesh")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        output = {"id": "output:1", "type": "image.concept", "path": "mesh.glb",
                  "sha256": sha, "stage": "concept_generation",
                  "attempt": 1, "derived_from": []}
        valid = {"name": "concept_generation", "attempt": 1,
                 "status": "succeeded", "inputs": [], "settings": {},
                 "outputs": [output]}
        ctx = self.make_context([valid])
        result = _adopt_stage(ctx, "concept_generation", 1, [], {})
        self.assertIsNotNone(result)

    def test_adopt_stage_rejects_valid_target_with_malformed_dict_sibling(self):
        from slopforge.pipelines.model import _adopt_stage
        valid = {"name": "concept_generation", "attempt": 1,
                 "status": "succeeded", "inputs": [], "outputs": [], "settings": {}}
        ctx = self.make_context([valid, {"name": "broken"}])
        self.assertIsNone(_adopt_stage(ctx, "concept_generation", 1, [], {}))

    def test_adopt_stage_rejects_malformed_artifact_in_unrelated_stage(self):
        from slopforge.pipelines.model import _adopt_stage
        target = {"name": "concept_generation", "attempt": 1,
                  "status": "succeeded", "inputs": [], "outputs": [], "settings": {}}
        bad = {"id": "bad", "type": "image.concept", "path": "mesh.glb", "sha256": "z" * 64,
               "stage": "unrelated_stage", "attempt": 1, "derived_from": []}
        sibling = {"name": "unrelated_stage", "attempt": 1, "status": "failed",
                   "inputs": [], "outputs": [bad], "settings": {}}
        self.assertIsNone(_adopt_stage(self.make_context([target, sibling]),
                                       "concept_generation", 1, [], {}))


class AssemblyStageOutputContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = {"id": "in:1", "sha256": "a" * 64}
        self.required_types = {"mesh.fbx", "project.blend", "preview.front", "preview.side",
                               "preview.rear", "preview.three_quarter", "validation.json"}
        self.outputs = []
        for index, kind in enumerate(sorted(self.required_types)):
            path = f"out-{index}.bin"
            (self.root / path).write_bytes(kind.encode())
            self.outputs.append({"id": f"out:{index}", "type": kind, "path": path,
                                 "sha256": file_sha256(self.root / path),
                                 "stage": "material_assembly_export", "attempt": 1,
                                 "derived_from": [{"artifact_id": "in:1", "sha256": "a" * 64}]})
        self.stage = {"name": "material_assembly_export", "attempt": 1, "status": "succeeded",
                      "inputs": [self.input], "outputs": self.outputs, "settings": {}}

    def test_assembly_stage_without_outputs_is_not_reusable(self):
        decision = stage_reuse_decision(self.root, {**self.stage, "outputs": []},
                                        inputs=[self.input], settings={})
        self.assertFalse(decision["reusable"])

    def test_assembly_stage_missing_required_type_is_not_reusable(self):
        decision = stage_reuse_decision(self.root, {**self.stage,
            "outputs": [output for output in self.outputs if output["type"] != "validation.json"]},
            inputs=[self.input], settings={})
        self.assertFalse(decision["reusable"])

    def test_assembly_stage_with_required_output_is_reusable(self):
        decision = stage_reuse_decision(self.root, self.stage, inputs=[self.input], settings={})
        self.assertTrue(decision["reusable"], decision["reasons"])

    def test_empty_project_relative_output_path_fails_closed_without_raising(self):
        decision = stage_reuse_decision(self.root, {**self.stage,
            "outputs": [{**self.outputs[0], "path": "."}]}, inputs=[self.input], settings={})
        self.assertFalse(decision["reusable"])

    def test_other_consumed_stages_cannot_reuse_without_producer_outputs(self):
        for name in ("conditioning_preparation", "material_generation", "material_map_acquisition"):
            with self.subTest(name=name):
                stage = {**self.stage, "name": name, "outputs": []}
                decision = stage_reuse_decision(self.root, stage, inputs=[self.input], settings={})
                self.assertFalse(decision["reusable"])

    def test_incomplete_textured_mesh_worker_material_outputs_are_not_reusable(self):
        output = {**self.outputs[0], "type": "texture.basecolor",
                  "stage": "material_generation"}
        stage = {**self.stage, "name": "material_generation", "outputs": [output]}
        decision = stage_reuse_decision(self.root, stage, inputs=[self.input], settings={})
        self.assertFalse(decision["reusable"])

    def test_complete_textured_mesh_worker_material_outputs_are_reusable(self):
        outputs = []
        for index, kind in enumerate(("texture.basecolor", "texture.normal",
                                      "texture.roughness", "texture.metallic")):
            path = f"texture-{index}.bin"
            (self.root / path).write_bytes(kind.encode())
            outputs.append({"id": f"texture:{index}", "type": kind, "path": path,
                            "sha256": file_sha256(self.root / path),
                            "stage": "material_generation", "attempt": 1,
                            "derived_from": [{"artifact_id": "in:1", "sha256": "a" * 64}]})
        stage = {**self.stage, "name": "material_generation", "outputs": outputs}
        decision = stage_reuse_decision(self.root, stage, inputs=[self.input], settings={})
        self.assertTrue(decision["reusable"], decision["reasons"])


class MaterialMapStageOutputContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = {"id": "surface:1", "sha256": "a" * 64}
        self.required_types = {
            "texture.basecolor", "texture.normal", "texture.roughness",
            "texture.metallic", "texture.metallic_gloss", "texture.emission",
        }
        self.outputs = []
        for index, kind in enumerate(sorted(self.required_types)):
            path = f"map-{index}.bin"
            (self.root / path).write_bytes(kind.encode())
            self.outputs.append({"id": f"map:{index}", "type": kind, "path": path,
                                 "sha256": file_sha256(self.root / path),
                                 "stage": "material_map_acquisition", "attempt": 1,
                                 "derived_from": [{"artifact_id": "surface:1",
                                                   "sha256": self.input["sha256"]}]})
        self.stage = {"name": "material_map_acquisition", "attempt": 1, "status": "succeeded",
                      "inputs": [self.input], "outputs": self.outputs, "settings": {}}

    def test_material_map_stage_with_complete_producer_outputs_is_reusable(self):
        decision = stage_reuse_decision(self.root, self.stage, inputs=[self.input], settings={})

        self.assertTrue(decision["reusable"], decision["reasons"])

    def test_material_map_stage_missing_only_basecolor_is_not_reusable(self):
        outputs = [item for item in self.outputs if item["type"] != "texture.basecolor"]

        decision = stage_reuse_decision(self.root, {**self.stage, "outputs": outputs},
                                        inputs=[self.input], settings={})

        self.assertFalse(decision["reusable"])
        self.assertIn("texture.basecolor", " ".join(decision["reasons"]))

    def test_material_map_stage_with_empty_outputs_is_not_reusable(self):
        decision = stage_reuse_decision(self.root, {**self.stage, "outputs": []},
                                        inputs=[self.input], settings={})

        self.assertFalse(decision["reusable"])

    def test_material_map_stage_keeps_artifact_integrity_and_lineage_validation(self):
        output = self.outputs[0]
        (self.root / output["path"]).write_bytes(b"changed")
        invalid_hash = stage_reuse_decision(self.root, self.stage,
                                            inputs=[self.input], settings={})
        self.assertIn("hash mismatch", " ".join(invalid_hash["reasons"]))

        (self.root / output["path"]).write_bytes(output["type"].encode())
        bad_lineage = [dict(item) for item in self.outputs]
        bad_lineage[0] = {**bad_lineage[0], "derived_from": []}
        invalid_lineage = stage_reuse_decision(
            self.root, {**self.stage, "outputs": bad_lineage}, inputs=[self.input], settings={})
        self.assertIn("lineage mismatch", " ".join(invalid_lineage["reasons"]))


class Finding3DuplicateOutputIDRejectTests(unittest.TestCase):
    """Regression tests for Finding 3: stage_reuse_decision must reject
    duplicate output IDs, not silently reuse."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "test.glb").write_bytes(b"mesh")

    # A. duplicate output ID with both valid hashes -> reject reuse
    def test_stage_reuse_duplicate_output_id_different_path_rejects(self):
        from slopforge.pipelines.reuse import stage_reuse_decision
        sha1 = file_sha256(Path(self.root, "test.glb"))
        # Two outputs with same ID, different paths
        valid_file = Path(self.root) / "valid.glb"
        valid_file.write_bytes(b"valid")
        sha2 = hashlib.sha256(valid_file.read_bytes()).hexdigest()
        outputs = [
            {"id": "mesh:1", "type": "mesh.glb", "path": "test.glb",
             "sha256": sha1, "stage": "material_generation",
             "attempt": 1, "derived_from": []},
            {"id": "mesh:1", "type": "mesh.glb", "path": "valid.glb",
             "sha256": sha2, "stage": "material_generation",
             "attempt": 1, "derived_from": []}
        ]
        stage = {"name": "material_generation", "attempt": 1,
                 "status": "succeeded", "inputs": [],
                 "outputs": outputs, "settings": {}}
        decision = stage_reuse_decision(self.root, stage, inputs=[], settings={})
        self.assertFalse(decision["reusable"],
                        f"expected rejected, got reasons: {decision['reasons']}")

    # B. duplicate output ID even when one matches exactly -> reject ambiguity
    def test_stage_reuse_duplicate_output_id_one_exact_rejects(self):
        from slopforge.pipelines.reuse import stage_reuse_decision
        sha = file_sha256(Path(self.root, "test.glb"))
        outputs = [
            {"id": "mesh:1", "type": "mesh.glb", "path": "test.glb",
             "sha256": sha, "stage": "material_generation",
             "attempt": 1, "derived_from": []},
            {"id": "mesh:1", "type": "mesh.glb", "path": "test.glb",
             "sha256": sha, "stage": "material_generation",
             "attempt": 1, "derived_from": []}
        ]
        stage = {"name": "material_generation", "attempt": 1,
                 "status": "succeeded", "inputs": [], "outputs": outputs,
                 "settings": {}}
        decision = stage_reuse_decision(self.root, stage, inputs=[], settings={})
        self.assertFalse(decision["reusable"],
                        f"expected rejected, got reasons: {decision['reasons']}")

    # C. unique valid outputs -> reuse still succeeds
    def test_stage_reuse_unique_outputs_succeeds(self):
        sha = file_sha256(Path(self.root, "test.glb"))
        outputs = [
            {"id": "surface:1", "type": "surface.swatch", "path": "test.glb",
             "sha256": sha, "stage": "material_generation", "attempt": 1, "derived_from": []},
            {"id": "metadata:1", "type": "generation.metadata", "path": "test.glb",
             "sha256": sha, "stage": "material_generation", "attempt": 1, "derived_from": []},
        ]
        stage = {"name": "material_generation", "attempt": 1,
                 "status": "succeeded", "inputs": [], "outputs": outputs,
                 "settings": {}}
        decision = stage_reuse_decision(self.root, stage, inputs=[], settings={})
        self.assertTrue(decision["reusable"])


class Finding4ProcessedMeshMalformedProvenanceTests(unittest.TestCase):
    """Regression tests for Finding 4: malformed processed-mesh provenance
    members must fail closed rather than raise AttributeError/TypeError."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "source.glb").write_bytes(b"source mesh")
        (self.root / "processed.blend").write_bytes(b"processed mesh")

    # A. malformed execution member (None)
    def test_malformed_none_execution_member_does_not_raise(self):
        """A None member in asset['executions'] must not raise."""
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source = {"id": "mesh:1", "type": "mesh.glb",
                  "path": "source.glb",
                  "sha256": file_sha256(Path(self.root, "source.glb")),
                  "stage": "material_assembly_export", "attempt": 1,
                  "derived_from": []}
        asset = {"source": {"processed_mesh": "processed.blend",
                             "source_mesh_id": "mesh:1",
                             "source_mesh_path": "source.glb",
                             "source_mesh_sha256": file_sha256(Path(self.root, "source.glb"))},
                 "executions": [None, None]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, source, {})
        self.assertFalse(decision["reusable"])

    # B. valid execution with malformed stage member (None)
    def test_malformed_none_stage_member_does_not_raise(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        path = Path(self.root) / "source.glb"
        sha = file_sha256(path)
        source = {"id": "mesh:1", "type": "mesh.glb",
                  "path": "source.glb", "sha256": sha,
                  "stage": "material_assembly_export", "attempt": 1,
                  "derived_from": []}
        asset = {"source": {"processed_mesh": "processed.blend",
                             "source_mesh_id": "mesh:1",
                             "source_mesh_path": "source.glb",
                             "source_mesh_sha256": sha},
                 "executions": [{"stages": [None, {"name": "mesh_preparation", "attempt": 1}]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, source, {})
        self.assertFalse(decision["reusable"])

    # C. valid stage with malformed output member (None)
    def test_malformed_none_output_member_does_not_raise(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source_path = self.root / "source.glb"
        processed_path = self.root / "processed.blend"
        source = {"id": "mesh:1", "type": "mesh.glb",
                  "path": "source.glb",
                  "sha256": file_sha256(source_path),
                  "stage": "material_assembly_export", "attempt": 1,
                  "derived_from": []}
        asset = {"source": {"processed_mesh": "processed.blend",
                             "source_mesh_id": "mesh:1",
                             "source_mesh_path": "source.glb",
                             "source_mesh_sha256": file_sha256(source_path)},
                 "executions": [{"stages": [{"name": "mesh_preparation", "attempt": 1,
                                            "status": "succeeded",
                                            "inputs": [source],
                                            "outputs": [None],
                                            "settings": {}}]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, source, {"face_budget": 1000, "material_scale": 3.0})
        self.assertFalse(decision["reusable"])

    # D. mixed valid + malformed sibling
    def test_mixed_valid_plus_malformed_sibling_does_not_raise(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source_path = self.root / "source.glb"
        processed_path = self.root / "processed.blend"
        source = {"id": "mesh:1", "type": "mesh.glb",
                  "path": "source.glb",
                  "sha256": file_sha256(source_path),
                  "stage": "material_assembly_export", "attempt": 1,
                  "derived_from": []}
        prepared = {"id": "prepared:1", "type": "mesh.prepared",
                    "path": "processed.blend",
                    "sha256": file_sha256(processed_path),
                    "stage": "mesh_preparation", "attempt": 1,
                    "derived_from": [{"artifact_id": source["id"],
                                      "sha256": source["sha256"]}]}
        processed = {"id": "processed:1", "type": "mesh.processed",
                     "path": "processed.blend",
                     "sha256": file_sha256(processed_path),
                     "stage": "material_assembly_export", "attempt": 1,
                     "derived_from": [{"artifact_id": prepared["id"],
                                       "sha256": prepared["sha256"]}]}
        valid_stage = {"name": "material_assembly_export", "attempt": 1,
                       "status": "succeeded", "inputs": [prepared],
                       "settings": {"face_budget": 1000, "material_scale": 3.0},
                       "outputs": [processed]}
        asset = {"source": {"processed_mesh": "processed.blend",
                             "source_mesh_id": "mesh:1",
                             "source_mesh_path": "source.glb",
                             "source_mesh_sha256": file_sha256(source_path)},
                 "executions": [{"stages": [valid_stage, None]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, prepared, {"face_budget": 1000, "material_scale": 3.0})
        self.assertFalse(decision["reusable"])

    # D. malformed output as the only output member (Step 2 anti-pattern)
    def test_malformed_output_in_step2_does_not_raise(self):
        """A stage whose outputs list contains a valid output alongside
        a None sibling in Step 2 output scanning must reject provenance,
        not silently ignore the None."""
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source_path = self.root / "source.glb"
        processed_path = self.root / "processed.blend"
        source = {"id": "mesh:1", "type": "mesh.glb",
                  "path": "source.glb",
                  "sha256": file_sha256(source_path),
                  "stage": "mesh_preparation", "attempt": 1,
                  "derived_from": []}
        prepared = {"id": "prepared:1", "type": "mesh.prepared",
                    "path": "processed.blend",
                    "sha256": file_sha256(processed_path),
                    "stage": "mesh_preparation", "attempt": 1,
                    "derived_from": [{"artifact_id": source["id"],
                                      "sha256": source["sha256"]}]}
        processed = {"id": "processed:1", "type": "mesh.processed",
                     "path": "processed.blend",
                     "sha256": file_sha256(processed_path),
                     "stage": "material_assembly_export", "attempt": 1,
                     "derived_from": [{"artifact_id": prepared["id"],
                                       "sha256": prepared["sha256"]}]}
        # Stage with outputs containing valid output + None sibling
        bad_outputs_stage = {"name": "material_assembly_export", "attempt": 1,
                             "status": "succeeded", "inputs": [prepared],
                             "settings": {"face_budget": 1000, "material_scale": 3.0},
                             "outputs": [processed, None]}
        asset = {"source": {"processed_mesh": "processed.blend",
                             "source_mesh_id": "mesh:1",
                             "source_mesh_path": "source.glb",
                             "source_mesh_sha256": file_sha256(source_path)},
                 "executions": [{"stages": [bad_outputs_stage]}]}
        # Must NOT raise and must reject (None sibling is malformed)
        decision = processed_mesh_reuse_decision(
            self.root, asset, prepared, {"face_budget": 1000, "material_scale": 3.0})
        self.assertFalse(
            decision["reusable"],
            f"expected rejection for malformed output member, got: {decision['reasons']}")

    # E. fully valid unambiguous provenance - reuse still succeeds
    def test_fully_valid_unambiguous_provenance_succeeds(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source_path = self.root / "source.glb"
        processed_path = self.root / "processed.blend"
        source = {"id": "mesh:1", "type": "mesh.glb",
                  "path": "source.glb",
                  "sha256": file_sha256(source_path),
                  "stage": "material_assembly_export", "attempt": 1,
                  "derived_from": []}
        prepared = {"id": "prepared:1", "type": "mesh.prepared",
                    "path": "processed.blend",
                    "sha256": file_sha256(processed_path),
                    "stage": "mesh_preparation", "attempt": 1,
                    "derived_from": [{"artifact_id": source["id"],
                                      "sha256": source["sha256"]}]}
        processed = {"id": "processed:1", "type": "mesh.processed",
                     "path": "processed.blend",
                     "sha256": file_sha256(processed_path),
                     "stage": "material_assembly_export", "attempt": 1,
                     "derived_from": [{"artifact_id": prepared["id"],
                                       "sha256": prepared["sha256"]}]}
        valid_stage = {"name": "material_assembly_export", "attempt": 1,
                       "status": "succeeded", "inputs": [prepared],
                       "settings": {"face_budget": 1000, "material_scale": 3.0},
                       "outputs": [processed]}
        asset = {"source": {"processed_mesh": "processed.blend",
                             "source_mesh_id": "mesh:1",
                             "source_mesh_path": "source.glb",
                             "source_mesh_sha256": file_sha256(source_path)},
                 "executions": [{"id": "exec:1", "stages": [valid_stage]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, prepared, {"face_budget": 1000, "material_scale": 3.0})
        self.assertTrue(decision["reusable"])

    def test_valid_output_with_malformed_dictionary_sibling_rejects(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source_path = self.root / "source.glb"
        processed_path = self.root / "processed.blend"
        source = {"id": "mesh:1", "type": "mesh.glb", "path": "source.glb",
                  "sha256": file_sha256(source_path), "stage": "mesh_preparation",
                  "attempt": 1, "derived_from": []}
        prepared = {"id": "prepared:1", "type": "mesh.prepared", "path": "processed.blend",
                    "sha256": file_sha256(processed_path), "stage": "mesh_preparation",
                    "attempt": 1, "derived_from": [{"artifact_id": source["id"], "sha256": source["sha256"]}]}
        processed = {"id": "processed:1", "type": "mesh.processed", "path": "processed.blend",
                     "sha256": file_sha256(processed_path), "stage": "material_assembly_export",
                     "attempt": 1, "derived_from": [{"artifact_id": prepared["id"], "sha256": prepared["sha256"]}]}
        settings = {"face_budget": 1000, "material_scale": 3.0}
        stage = {"name": "material_assembly_export", "attempt": 1, "status": "succeeded",
                 "inputs": [prepared], "settings": settings, "outputs": [processed, {"id": "malformed"}]}
        asset = {"source": {"processed_mesh": "processed.blend"},
                 "executions": [{"id": "exec:1", "stages": [stage]}]}
        decision = processed_mesh_reuse_decision(self.root, asset, prepared, settings)
        self.assertFalse(decision["reusable"])

    def test_malformed_processed_stage_attempt_rejects_without_exception(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source = {"id": "mesh:1", "type": "mesh.glb", "path": "source.glb",
                  "sha256": file_sha256(self.root / "source.glb"), "stage": "mesh_preparation",
                  "attempt": 1, "derived_from": []}
        stage = {"name": "mesh_preparation", "attempt": [], "status": "succeeded",
                 "inputs": [source], "settings": {}, "outputs": []}
        result = processed_mesh_reuse_decision(
            self.root, {"source": {"processed_mesh": "processed.blend"},
                        "executions": [{"id": "exec:1", "stages": [stage]}]}, source, {})
        self.assertFalse(result["reusable"])

    def test_malformed_dictionary_execution_and_stage_siblings_reject(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision
        source = {"id": "mesh:1", "type": "mesh.glb", "path": "source.glb",
                  "sha256": file_sha256(self.root / "source.glb"), "stage": "mesh_preparation",
                  "attempt": 1, "derived_from": []}
        stage = {"name": "mesh_preparation", "attempt": 1, "status": "succeeded",
                 "inputs": [source], "settings": {}, "outputs": []}
        executions = [{"id": "exec:1", "stages": [stage, {"name": "mesh_preparation"}]},
                      {"id": "malformed"}]
        result = processed_mesh_reuse_decision(
            self.root, {"source": {"processed_mesh": "processed.blend"},
                        "executions": executions}, source, {})
        self.assertFalse(result["reusable"])

class MalformedStageIdentityTypeTests(unittest.TestCase):
    def test_unhashable_output_id_rejects_without_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "out.glb"
            path.write_bytes(b"out")
            output = {"id": [], "type": "mesh.glb", "path": "out.glb",
                      "sha256": file_sha256(path), "stage": "material_generation",
                      "attempt": 1, "derived_from": []}
            stage = {"name": "material_generation", "attempt": 1, "status": "succeeded",
                     "inputs": [], "outputs": [output], "settings": {}}
            decision = stage_reuse_decision(root, stage, inputs=[], settings={})
            self.assertFalse(decision["reusable"])


class PropApprovalReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "Assets").mkdir()
        (self.root / "ai/styles/plain/references/approved").mkdir(parents=True)
        (self.root / "ai/asset_types").mkdir()
        (self.root / "ai/project.yaml").write_text("""project: {name: Test}
asset_pipeline:
  active_style: plain
  workflows: {image: image_text2img_api.json}
""")
        (self.root / "ai/styles/plain/style.yaml").write_text("""name: Plain
version: 1
identity: {genre: fantasy, rendering: painted, mood: [warm]}
shape_language: {preferred: [rounded], avoid: [photorealistic]}
palette: {}
materials: {}
surface_language: {preferred: [matte], avoid: []}
lighting: {description: soft, avoid: []}
asset_rules: {}
material_generation: {rules: [surface only]}
""")
        (self.root / "ai/asset_types/prop.yaml").write_text("""name: prop
pipeline: model
output_folder: Models
face_budget: prop_faces
requirements: [isolated object]
avoid: [environment]
""")
        self.config = load_project(self.root)
        self.config["asset_pipeline"]["defaults"].update(model_candidates=1, material_candidates=1)
        self.config["_quality_base_pipeline"]["defaults"].update(model_candidates=1, material_candidates=1)
        self.style = load_style(self.root)
        self.asset_type = load_taxonomy(self.root)["prop"]
        self.asset = new_record("prop", "relay", "Copper relay", self.style, {"strategy": "text_only"})
        self.manifest = {"schema_version": 4, "assets": {"prop:relay": self.asset}}
        concept = self.root / "concept.png"
        Image.new("RGB", (512, 512), "red").save(concept)
        self.asset["candidates"] = {"selected": None, "items": [self._candidate(1, concept)]}
        self.calls = {name: 0 for name in ("prepare", "mesh", "material", "maps", "assembly")}
        self.fail_once = None
        self.fail_times = {}
        self.interrupt_once = None

    def _candidate(self, number, path):
        return {"number": number, "status": "candidate", "path": path.relative_to(self.root).as_posix(),
                "description": "Copper relay", "artifact": {"id": f"concept:{number}", "type": "image.concept",
                "path": path.relative_to(self.root).as_posix(), "sha256": file_sha256(path),
                "stage": "concept_generation", "attempt": number, "derived_from": []}}

    def _recipe_candidate_reuse_case(self):
        from slopforge.pipelines.model import prop_child_reuse_decision

        candidate = self._candidate(1, self.root / "concept.png")
        execution = {"id": "execution:1", "status": "succeeded",
                     "identity_inputs": {"brief": "Copper relay", "generation_prompt": "Copper relay",
                                          "style": {"name": "plain", "version": 1},
                                          "conditioning": {"strategy": "text_only", "references": []},
                                          "quality": {"tier": "normal", "settings": {}},
                                          "candidate_attempts": [{"seed": 1, "variation": None}]},
                     "stages": [{"name": "concept_generation", "attempt": 1, "status": "succeeded",
                                 "inputs": [], "settings": {"prompt": "Copper relay",
                                     "variation": None, "seed": 1},
                                 "outputs": [dict(candidate["artifact"])]}]}
        candidate["execution_id"] = execution["id"]
        self.asset["executions"] = [execution]
        self.asset["candidates"]["items"] = [candidate]
        child = {"description": "Copper relay", "generation_prompt": "Copper relay",
                 "requested_style_identity": {"name": "plain", "version": 1},
                 "requested_conditioning": {"strategy": "text_only", "references": []}}
        config = {"asset_pipeline": {"defaults": {"image_candidates": 1}}}
        decide = lambda: prop_child_reuse_decision(
            self.root, self.asset, {"candidate_execution_ids": [execution["id"]]}, child, config)
        return candidate, execution, decide

    def test_recipe_candidate_reuse_rejects_execution_sibling_missing_required_fields(self):
        _, _, decide = self._recipe_candidate_reuse_case()
        self.asset["executions"].append({"id": "broken", "stages": []})

        self.assertFalse(decide()["reusable"])

    def test_recipe_candidate_reuse_rejects_execution_sibling_with_bad_required_type(self):
        _, _, decide = self._recipe_candidate_reuse_case()
        self.asset["executions"].append({"id": "broken", "status": "failed",
                                         "identity_inputs": [], "stages": []})

        self.assertFalse(decide()["reusable"])

    def test_recipe_candidate_reuse_ignores_valid_unrelated_execution_identity(self):
        _, _, decide = self._recipe_candidate_reuse_case()
        self.asset["executions"].append({"id": "other", "status": "failed",
                                         "identity_inputs": {}, "stages": []})

        self.assertTrue(decide()["reusable"])

    def test_recipe_candidate_reuse_accepts_exact_candidate_with_valid_records(self):
        self.assertTrue(self._recipe_candidate_reuse_case()[2]()["reusable"])

    def test_recipe_candidate_path_must_match_recorded_stage_output(self):
        candidate, _, decide = self._recipe_candidate_reuse_case()
        unrelated = self.root / "unrelated.png"
        unrelated.write_bytes(b"unrelated but intact")
        candidate["path"] = "unrelated.png"
        candidate["artifact"]["path"] = "unrelated.png"
        candidate["artifact"]["sha256"] = file_sha256(unrelated)

        decision = decide()

        self.assertFalse(decision["reusable"])

    def test_recipe_candidate_hash_must_match_recorded_stage_output(self):
        candidate, _, decide = self._recipe_candidate_reuse_case()
        candidate["artifact"]["sha256"] = "0" * 64

        decision = decide()

        self.assertFalse(decision["reusable"])

    def test_recipe_candidate_path_field_must_match_its_artifact(self):
        candidate, _, decide = self._recipe_candidate_reuse_case()
        unrelated = self.root / "unrelated.png"
        unrelated.write_bytes(b"unrelated but intact")
        candidate["path"] = "unrelated.png"

        decision = decide()

        self.assertFalse(decision["reusable"])

    def test_recipe_candidate_rejects_duplicate_stage_attempt_provenance(self):
        _, execution, decide = self._recipe_candidate_reuse_case()
        execution["stages"].append(dict(execution["stages"][0]))

        decision = decide()

        self.assertFalse(decision["reusable"])

    def test_recipe_candidate_reuses_exact_unambiguous_stage_output(self):
        _, _, decide = self._recipe_candidate_reuse_case()

        self.assertTrue(decide()["reusable"])

    def test_recipe_candidate_rejects_stage_seed_conflicting_with_execution_identity(self):
        _, execution, decide = self._recipe_candidate_reuse_case()
        execution["stages"][0]["settings"] = {
            "prompt": "Copper relay", "variation": None, "seed": 2}

        self.assertFalse(decide()["reusable"])

    def test_recipe_candidate_rejects_stage_variation_conflicting_with_execution_identity(self):
        _, execution, decide = self._recipe_candidate_reuse_case()
        execution["stages"][0]["settings"] = {
            "prompt": "Copper relay", "variation": {"finish": "red"}, "seed": 1}

        self.assertFalse(decide()["reusable"])

    def test_recipe_candidate_rejects_stage_prompt_conflicting_with_request(self):
        _, execution, decide = self._recipe_candidate_reuse_case()
        execution["stages"][0]["settings"] = {
            "prompt": "Silver relay", "variation": None, "seed": 1}

        self.assertFalse(decide()["reusable"])

    def test_recipe_candidate_rejects_malformed_same_name_stage_attempt(self):
        _, execution, decide = self._recipe_candidate_reuse_case()
        execution["stages"].append({**execution["stages"][0], "attempt": "1"})

        self.assertFalse(decide()["reusable"])

    def test_recipe_child_reuse_rejects_missing_quality_identity(self):
        _, execution, decide = self._recipe_candidate_reuse_case()
        del execution["identity_inputs"]["quality"]

        decision = decide()

        self.assertFalse(decision["reusable"])
        self.assertIn("quality identity is unknown", " ".join(decision["reasons"]))

    def _maybe_fail(self, name):
        self.calls[name] += 1
        if self.interrupt_once == name:
            self.interrupt_once = None
            raise KeyboardInterrupt(f"interrupted {name}")
        if self.fail_times.get(name, 0):
            self.fail_times[name] -= 1
            raise RuntimeError(f"interrupted {name}")
        if self.fail_once == name:
            self.fail_once = None
            raise RuntimeError(f"interrupted {name}")

    def _commands(self, command, check):
        if "prepare_3d_input.py" in command[1]:
            self._maybe_fail("prepare")
            Image.new("RGBA", (32, 32), "white").save(command[command.index("--cutout") + 1])
            Image.new("RGB", (32, 32), "white").save(command[command.index("--output") + 1])
        elif "make_pbr_maps.py" in command[1]:
            self._maybe_fail("maps")
            for name in ("normal", "roughness", "metallic", "emission"):
                Image.new("RGB", (32, 32), "white").save(command[command.index("--" + name) + 1])

    def _mesh(self, _root, _config, _image, _name, destination, metadata, seed, _budget=None, **_kwargs):
        self._maybe_fail("mesh")
        destination.write_bytes(b"mesh")
        info = {"workflow": "model.json", "seed": seed, "model": "mesh"}
        if _config["asset_pipeline"]["workflows"].get("model"):
            info["textured"] = True
            info["textures"] = {}
            for name in ("basecolor", "normal", "roughness", "metallic"):
                texture = destination.parent / f"{name}.png"
                Image.new("RGB", (32, 32), "white").save(texture)
                info["textures"][name] = texture.name
        metadata.write_text(json.dumps(info))

    def _material(self, _root, _config, _workflow, _prompt, destination, _prefix, seed, metadata, **_kwargs):
        self._maybe_fail("material")
        Image.new("RGB", (32, 32), "blue").save(destination)
        metadata.write_text(json.dumps({"workflow": "image.json", "seed": seed}))

    def _assembly(self, _root, _config, _source, fbx, blend, _textures, _budget, **kwargs):
        self._maybe_fail("assembly")
        for path in (fbx, blend, kwargs["stage_mesh"]):
            path.write_bytes(b"assembled")
        kwargs["preview_dir"].mkdir(parents=True, exist_ok=True)
        for name in ("front", "side", "rear", "three_quarter"):
            (kwargs["preview_dir"] / f"{fbx.stem}_{name}.png").write_bytes(b"preview")

    def _approve(self, *, resume=False, material_prompt=None):
        with ExitStack() as stack:
            stack.enter_context(patch("slopforge.pipelines.model.subprocess.run", side_effect=self._commands))
            stack.enter_context(patch("slopforge.pipelines.model.generate_model", side_effect=self._mesh))
            stack.enter_context(patch("slopforge.pipelines.model.generate_image", side_effect=self._material))
            stack.enter_context(patch("slopforge.pipelines.model.process_model", side_effect=self._assembly))
            stack.enter_context(patch("slopforge.pipelines.model.blender_executable", return_value="blender"))
            stack.enter_context(patch("slopforge.pipelines.model.inspect_model", return_value={}))
            stack.enter_context(patch("slopforge.pipelines.model.validate_model_outputs",
                                      return_value={"status": "passed", "errors": [], "warnings": [], "measured": {}}))
            return approve(self.root, self.config, self.asset_type, self.style, self.manifest,
                           "prop:relay", 1, resume=resume, material_prompt=material_prompt,
                           material_count=1, quality_tier="normal")

    def _mark_interrupted(self):
        self.asset = self.manifest["assets"]["prop:relay"]
        self.asset["executions"][-1]["status"] = "running"
        self.asset["executions"][-1].pop("finished_at", None)
        save_manifest(self.root / self.config["asset_pipeline"]["manifest"], self.manifest)

    def test_identical_execution_reuses_completed_outputs(self):
        self._approve()
        before = dict(self.calls)
        self._mark_interrupted()
        self._approve(resume=True)
        self.assertEqual(self.calls, before)
        self.assertTrue(self.asset["executions"][-1]["reuse_decisions"])

    def test_material_map_acquisition_records_all_six_producer_outputs(self):
        self._approve()
        stage = next(stage for stage in self.asset["executions"][-1]["stages"]
                     if stage["name"] == "material_map_acquisition")

        self.assertEqual({item["type"] for item in stage["outputs"]}, {
            "texture.basecolor", "texture.normal", "texture.roughness",
            "texture.metallic", "texture.metallic_gloss", "texture.emission",
        })

    def test_approve_cli_exposes_explicit_resume_flag(self):
        from slopforge.cli import parse_args

        self.assertTrue(parse_args(["approve", "relay", "1", "--resume"]).resume)

    def test_selected_concept_change_invalidates_mesh_material_and_publication(self):
        self._approve()
        self._mark_interrupted()
        other = self.root / "other.png"
        Image.new("RGB", (512, 512), "green").save(other)
        self.asset["candidates"]["items"][0] = self._candidate(1, other)
        with self.assertRaisesRegex(ValueError, "concept|candidate"):
            self._approve(resume=True)
        self.assertEqual(self.calls["mesh"], 1)

    def test_material_only_change_reuses_mesh_and_rebuilds_descendants(self):
        self._approve()
        self._mark_interrupted()
        self._approve(resume=True, material_prompt="oxidized copper")
        self.assertEqual((self.calls["mesh"], self.calls["material"], self.calls["assembly"]), (1, 2, 2))

    def test_geometry_settings_change_invalidates_geometry_and_descendants(self):
        self._approve()
        self._mark_interrupted()
        self.asset_type["voxel_resolution"] = 128
        self._approve(resume=True)
        self.assertEqual((self.calls["mesh"], self.calls["material"]), (2, 2))

    def test_model_workflow_content_change_invalidates_geometry(self):
        workflows = self.root / "ai/workflows"
        workflows.mkdir()
        workflow = workflows / "model.json"
        workflow.write_text(json.dumps({"1": {"class_type": "Example", "inputs": {"resolution": 128}}}))
        self.config["asset_pipeline"]["workflows"]["model"] = "model.json"
        self._approve()
        self._mark_interrupted()
        workflow.write_text(json.dumps({"1": {"class_type": "Example", "inputs": {"resolution": 256}}}))
        self._approve(resume=True)
        self.assertEqual(self.calls["mesh"], 2)

    def test_processing_settings_change_invalidates_assembly_only(self):
        self._approve()
        self._mark_interrupted()
        self.config["asset_pipeline"]["material_scale"] = 2.0
        self.config["_quality_base_pipeline"]["material_scale"] = 2.0
        self._approve(resume=True)
        self.assertEqual((self.calls["mesh"], self.calls["material"], self.calls["maps"], self.calls["assembly"]),
                         (1, 1, 1, 2))

    def test_missing_preview_rebuilds_assembly_without_inference(self):
        self._approve()
        self._mark_interrupted()
        previous = self.asset["material_candidates"]["items"][-1]
        (self.root / previous["outputs"]["preview_front"]).unlink()
        self._approve(resume=True)
        self.assertEqual((self.calls["mesh"], self.calls["material"], self.calls["assembly"]), (1, 1, 2))

    def test_interruption_resumes_at_earliest_incomplete_stage(self):
        self.fail_once = "prepare"
        with self.assertRaises(RuntimeError):
            self._approve()
        self._approve(resume=True)
        self.assertEqual((self.calls["prepare"], self.calls["mesh"]), (2, 1))

    def test_process_interruption_resumes_from_persisted_running_stage(self):
        self.interrupt_once = "mesh"
        with self.assertRaisesRegex(KeyboardInterrupt, "interrupted mesh"):
            self._approve()
        manifest_path = self.root / self.config["asset_pipeline"]["manifest"]
        self.manifest = load_manifest(manifest_path)
        self.asset = self.manifest["assets"]["prop:relay"]
        execution = self.asset["executions"][-1]
        self.assertEqual(execution["status"], "failed")
        self.assertEqual(next(stage for stage in execution["stages"]
                              if stage["name"] == "conditioning_preparation")["status"], "succeeded")
        self.assertEqual(next(stage for stage in execution["stages"]
                              if stage["name"] == "mesh_workflow_execution")["status"], "failed")
        self.assertEqual(next(stage for stage in execution["stages"]
                              if stage["name"] == "mesh_workflow_execution")["failure"]["category"],
                         "interruption")
        self._approve(resume=True)
        self.assertEqual((self.calls["prepare"], self.calls["mesh"]), (1, 2))

    def test_failed_stage_retries_without_regenerating_valid_ancestors(self):
        self.fail_times["mesh"] = 1
        with self.assertRaises(ValueError):
            self._approve()
        self._approve(resume=True)
        self.assertEqual((self.calls["prepare"], self.calls["mesh"]), (1, 2))

    def test_swatches_resume_after_map_or_assembly_failure(self):
        for failed_stage in ("maps", "assembly"):
            with self.subTest(stage=failed_stage):
                self.setUp()
                self.fail_once = failed_stage
                with self.assertRaises(ValueError):
                    self._approve()
                self._approve(resume=True)
                self.assertEqual(self.calls["mesh"], 1)

    def test_resume_retries_mesh_after_nonretryable_failure_before_material_stage(self):
        self.config["asset_pipeline"]["defaults"]["model_candidates"] = 2
        self.config["_quality_base_pipeline"]["defaults"]["model_candidates"] = 2
        self.fail_times["mesh"] = 1
        self.fail_once = "material"
        with self.assertRaises(ValueError):
            self._approve()
        self.assertEqual(self.calls["mesh"], 1)
        with self.assertRaises(ValueError):
            self._approve(resume=True)
        self.assertEqual(self.calls["mesh"], 2)
        self._approve(resume=True)
        self.assertEqual(self.calls["mesh"], 2)

    def test_prior_succeeded_status_does_not_override_fingerprint_mismatch(self):
        self._approve()
        self._mark_interrupted()
        old = self.asset["executions"][-1]
        self.config["asset_pipeline"]["material_scale"] = 2.0
        self.config["_quality_base_pipeline"]["material_scale"] = 2.0
        self._approve(resume=True)
        self.assertEqual(self.calls["assembly"], 2)
        self.assertEqual(next(stage for stage in old["stages"] if stage["name"] == "material_assembly_export")["status"],
                         "succeeded")
        self.assertTrue(any(not item["reusable"] for item in self.asset["executions"][-1]["reuse_decisions"]))

    def test_manifest_reload_preserves_same_reuse_decision(self):
        self._approve()
        execution = self.asset["executions"][-1]
        stage = next(item for item in execution["stages"]
                     if item["name"] == "material_assembly_export")
        before = stage_reuse_decision(self.root, stage, inputs=stage["inputs"], settings=stage["settings"])
        manifest_path = self.root / self.config["asset_pipeline"]["manifest"]
        save_manifest(manifest_path, self.manifest)
        self.manifest = load_manifest(manifest_path)
        self.asset = self.manifest["assets"]["prop:relay"]
        stage = next(item for item in self.asset["executions"][-1]["stages"]
                     if item["name"] == "material_assembly_export")
        after = stage_reuse_decision(self.root, stage, inputs=stage["inputs"], settings=stage["settings"])

        self.assertEqual(before, after)

    def test_missing_artifact_recomputes_at_owning_stage(self):
        self._approve()
        self._mark_interrupted()
        previous = self.asset["material_candidates"]["items"][-1]
        (self.root / previous["outputs"]["surface"]).unlink()
        self._approve(resume=True)

        self.assertEqual((self.calls["mesh"], self.calls["material"], self.calls["assembly"]), (1, 2, 2))

    def test_hash_mismatch_recomputes_at_owning_stage(self):
        self._approve()
        self._mark_interrupted()
        source = self.asset["source"]["glb"]
        (self.root / source).write_bytes(b"replaced mesh content")
        self._approve(resume=True)

        self.assertEqual(self.calls["mesh"], 2)

    def test_material_only_image_quality_change_preserves_mesh(self):
        self._approve()
        self._mark_interrupted()
        pipeline = self.config["_quality_base_pipeline"]
        pipeline.setdefault("quality_tiers", {}).setdefault("normal", {}).setdefault(
            "workflow_inputs", {})["image"] = {
                "image_text2img_api.json": {"1": {"inputs": {"steps": 4}}}}
        self._approve(resume=True)

        self.assertEqual(self.calls["mesh"], 1, self.asset["executions"][-1]["reuse_decisions"])
        self.assertEqual(self.calls["material"], 2)

    def test_recipe_child_reuse_rejects_unknown_conditioning_and_wrong_candidate(self):
        from slopforge.pipelines.model import prop_child_reuse_decision

        candidate = self._candidate(1, self.root / "concept.png")
        execution = {"id": "execution:1", "status": "succeeded",
                     "identity_inputs": {"brief": "Copper relay", "generation_prompt": "Copper relay",
                                          "style": {"name": "plain", "version": 1},
                                          "conditioning": {"strategy": "text_only", "references": []},
                                          "workflow": {"identifier": "image.json", "sha256": None, "configured_inputs": {}},
                                          "quality": {"tier": "normal", "settings": {}},
                                          "candidate_attempts": [{"seed": 1, "variation": None}]},
                     "stages": [{"name": "concept_generation", "attempt": 1, "status": "succeeded",
                                 "inputs": [], "settings": {"prompt": "Copper relay",
                                     "variation": None, "seed": 1},
                                 "outputs": [candidate["artifact"]]}]}
        candidate["execution_id"] = execution["id"]
        self.asset["executions"] = [execution]
        self.asset["candidates"]["items"] = [candidate]
        child = {"description": "Copper relay", "generation_prompt": "Copper relay"}
        child.update({"requested_style_identity": {"name": "plain", "version": 1},
                      "requested_conditioning": {"strategy": "text_only", "references": []}})
        self.assertTrue(prop_child_reuse_decision(
            self.root, self.asset, {"candidate_execution_ids": [execution["id"]]}, child,
            {"asset_pipeline": {"defaults": {"image_candidates": 1}}})["reusable"])

        execution["identity_inputs"]["conditioning"] = {"status": "unknown"}
        self.assertFalse(prop_child_reuse_decision(
            self.root, self.asset, {"candidate_execution_ids": [execution["id"]]}, child,
            {"asset_pipeline": {"defaults": {"image_candidates": 1}}})["reusable"])

    def test_corrupt_worker_texture_prevents_mesh_execution_adoption(self):
        """Worker-owned maps are part of mesh execution integrity, even if GLB is intact."""
        from slopforge.pipelines.model import _adopt_stage

        mesh_path = self.root / "mesh.glb"
        map_path = self.root / "basecolor.png"
        mesh_path.write_bytes(b"mesh")
        map_path.write_bytes(b"basecolor")
        concept = {"id": "concept:1", "type": "image.concept", "path": "concept.png",
                   "sha256": "a" * 64, "stage": "concept_generation", "attempt": 1,
                   "derived_from": []}
        conditioning = {"id": "conditioning:1", "type": "image.3d_input", "path": "input.png",
                        "sha256": "b" * 64, "stage": "conditioning_preparation", "attempt": 1,
                        "derived_from": []}
        settings = {"seed": 7}
        old_stage = {"name": "mesh_workflow_execution", "attempt": 1, "status": "succeeded",
                     "inputs": [concept, conditioning], "settings": settings,
                     "outputs": [{"id": "mesh:1", "type": "mesh.glb", "path": "mesh.glb",
                                  "sha256": file_sha256(mesh_path), "stage": "mesh_workflow_execution",
                                  "attempt": 1, "derived_from": [{"artifact_id": conditioning["id"],
                                      "sha256": conditioning["sha256"]}]}]}
        worker_map = {"id": "map:1", "type": "texture.basecolor", "path": "basecolor.png",
                      "sha256": file_sha256(map_path), "stage": "mesh_output_acquisition", "attempt": 1,
                      "derived_from": [{"artifact_id": conditioning["id"], "sha256": conditioning["sha256"]}]}
        prior = {"id": "prior", "stages": [old_stage,
                 {"name": "mesh_output_acquisition", "attempt": 1, "status": "succeeded",
                  "inputs": [conditioning], "settings": {}, "outputs": [worker_map]}]}
        current = {"id": "current", "stages": [], "reuse_decisions": []}
        manifest = {"assets": {"prop:relay": {"executions": [current]}}}
        context = {"root": self.root, "pipeline": {"manifest": "manifest.json"},
                   "manifest": manifest, "key": "prop:relay", "execution_id": "current",
                   "reuse_execution": prior}

        map_path.write_bytes(b"corrupted")
        self.assertIsNone(_adopt_stage(context, "mesh_workflow_execution", 1,
                                       [concept, conditioning], settings))

    # ---------------------------------------------------------------
    # Finding 2  — execution ID must resolve uniquely
    # All tests below MUST be RED before the production fix is applied.
    # ---------------------------------------------------------------

    def test_prop_child_reuse_rejects_valid_execution_plus_failed_duplicate_with_same_id(self):
        """A valid execution with a failed duplicate sharing the same ID must reject."""
        from slopforge.pipelines.model import prop_child_reuse_decision

        path = self.root / "concept.png"
        path.write_bytes(b"concept")
        artifact = {"id": "c:1", "type": "image.concept", "path": "concept.png",
                    "sha256": file_sha256(path), "stage": "concept_generation",
                    "attempt": 1, "derived_from": []}
        stage = {"name": "concept_generation", "attempt": 1, "status": "succeeded",
                 "inputs": [], "settings": {"prompt": "b", "variation": None, "seed": 1},
                 "outputs": [artifact]}
        good_exec = {"id": "dup-id", "status": "succeeded",
                     "identity_inputs": {"asset_type": "prop", "brief": "b",
                                          "generation_prompt": "b",
                                          "candidate_attempts": [{"seed": 1, "variation": None}],
                                          "style": {"name": "default", "version": 1},
                                          "conditioning": {"strategy": "text_only", "references": []},
                                          "quality": {"tier": "normal", "settings": {}},
                                          "workflow": {"identifier": "i.json", "sha256": None,
                                                       "configured_inputs": {}}},
                     "stages": [stage]}
        failed_exec = {"id": "dup-id", "status": "failed",
                       "identity_inputs": {}, "stages": [stage]}
        asset = {"type": "prop", "description": "b", "generation_prompt": "b",
                 "candidates": {"items": [{"number": 1, "status": "candidate",
                                            "path": "concept.png",
                                            "execution_id": "dup-id",
                                            "artifact": artifact}]},
                 "executions": [good_exec, failed_exec]}
        child = {"id": "t", "type": "prop", "description": "b", "generation_prompt": "b",
                 "requested_style_identity": {"name": "default", "version": 1},
                 "requested_conditioning": {"strategy": "text_only", "references": []}}

        decision = prop_child_reuse_decision(self.root, asset,
                                             {"candidate_execution_ids": ["dup-id"]},
                                             child, {"asset_pipeline": {"defaults": {"image_candidates": 1}}})
        self.assertFalse(decision["reusable"])

    def test_prop_child_reuse_rejects_malformed_record_before_duplicate_matching(self):
        """All execution records must be valid before matching duplicate IDs."""
        from slopforge.pipelines.model import prop_child_reuse_decision

        path = self.root / "concept.png"
        path.write_bytes(b"concept")
        artifact = {"id": "c:1", "type": "image.concept", "path": "concept.png",
                    "sha256": file_sha256(path), "stage": "concept_generation",
                    "attempt": 1, "derived_from": []}
        stage = {"name": "concept_generation", "attempt": 1, "status": "succeeded",
                 "inputs": [], "settings": {"prompt": "b", "variation": None, "seed": 1},
                 "outputs": [artifact]}
        valid_exec = {"id": "dup-id", "status": "succeeded",
                      "identity_inputs": {"brief": "b", "generation_prompt": "b",
                                          "candidate_attempts": [{"seed": 1, "variation": None}],
                                          "style": {"name": "default", "version": 1},
                                          "conditioning": {"strategy": "text_only", "references": []},
                                          "quality": {"tier": "normal", "settings": {}},
                                          "workflow": {"identifier": "i.json", "sha256": None,
                                                       "configured_inputs": {}}},
                      "stages": [stage]}
        malformed_duplicate = {"id": "dup-id", "status": "failed",
                                "identity_inputs": "contradictory", "stages": "malformed"}
        asset = {"type": "prop", "description": "b",
                 "candidates": {"items": [{"number": 1, "status": "candidate",
                                            "path": "concept.png", "execution_id": "dup-id",
                                            "artifact": artifact}]}}
        child = {"description": "b", "generation_prompt": "b",
                 "requested_style_identity": {"name": "default", "version": 1},
                 "requested_conditioning": {"strategy": "text_only", "references": []}}
        config = {"asset_pipeline": {"defaults": {"image_candidates": 1}}}

        decisions = [prop_child_reuse_decision(
            self.root, {**asset, "executions": executions},
            {"candidate_execution_ids": ["dup-id"]}, child, config)
            for executions in ([valid_exec, malformed_duplicate],
                               [malformed_duplicate, valid_exec])]

        self.assertEqual(decisions[0], decisions[1])
        self.assertEqual(decisions[0], {
            "reusable": False, "reasons": ["prop child execution records are missing or malformed"]})

    def test_prop_child_reuse_rejects_two_seemingly_valid_executions_same_id(self):
        """Two valid executions with the same ID must be rejected."""
        from slopforge.pipelines.model import prop_child_reuse_decision

        path = self.root / "concept.png"
        path.write_bytes(b"concept")
        artifact = {"id": "c:1", "type": "image.concept", "path": "concept.png",
                    "sha256": file_sha256(path), "stage": "concept_generation",
                    "attempt": 1, "derived_from": []}
        stage = {"name": "concept_generation", "attempt": 1, "status": "succeeded",
                 "inputs": [], "settings": {"prompt": "b", "variation": None, "seed": 1},
                 "outputs": [artifact]}
        exec_a = {"id": "dup-id", "status": "succeeded",
                  "identity_inputs": {"asset_type": "prop", "brief": "b",
                                      "generation_prompt": "b",
                                      "candidate_attempts": [{"seed": 1, "variation": None}],
                                      "style": {"name": "default", "version": 1},
                                      "conditioning": {"strategy": "text_only", "references": []},
                                      "quality": {"tier": "normal", "settings": {}},
                                      "workflow": {"identifier": "i.json", "sha256": None,
                                                   "configured_inputs": {}}},
                  "stages": [stage]}
        exec_b = {"id": "dup-id", "status": "succeeded",
                  "identity_inputs": {"asset_type": "prop", "brief": "b",
                                      "generation_prompt": "b",
                                      "candidate_attempts": [{"seed": 1, "variation": None}],
                                      "style": {"name": "default", "version": 1},
                                      "conditioning": {"strategy": "text_only", "references": []},
                                      "quality": {"tier": "normal", "settings": {}},
                                      "workflow": {"identifier": "i.json", "sha256": None,
                                                   "configured_inputs": {}}},
                  "stages": [stage]}
        asset = {"type": "prop", "description": "b", "generation_prompt": "b",
                 "candidates": {"items": [{"number": 1, "status": "candidate",
                                            "path": "concept.png",
                                            "execution_id": "dup-id",
                                            "artifact": artifact}]},
                 "executions": [exec_a, exec_b]}
        child = {"id": "t", "type": "prop", "description": "b", "generation_prompt": "b",
                 "requested_style_identity": {"name": "default", "version": 1},
                 "requested_conditioning": {"strategy": "text_only", "references": []}}

        decision = prop_child_reuse_decision(self.root, asset,
                                             {"candidate_execution_ids": ["dup-id"]},
                                             child, {"asset_pipeline": {"defaults": {"image_candidates": 1}}})
        self.assertFalse(decision["reusable"])

    def test_prop_child_reuse_succeeds_with_exactly_one_valid_execution(self):
        """Exactly one matching execution must allow reuse to proceed."""
        from slopforge.pipelines.model import prop_child_reuse_decision

        path = self.root / "concept.png"
        path.write_bytes(b"concept")
        artifact = {"id": "c:1", "type": "image.concept", "path": "concept.png",
                    "sha256": file_sha256(path), "stage": "concept_generation",
                    "attempt": 1, "derived_from": []}
        stage = {"name": "concept_generation", "attempt": 1, "status": "succeeded",
                 "inputs": [], "settings": {"prompt": "b", "variation": None, "seed": 1},
                 "outputs": [artifact]}
        execution = {"id": "single-id", "status": "succeeded",
                     "identity_inputs": {"asset_type": "prop", "brief": "b",
                                          "generation_prompt": "b",
                                          "candidate_attempts": [{"seed": 1, "variation": None}],
                                          "style": {"name": "default", "version": 1},
                                          "conditioning": {"strategy": "text_only", "references": []},
                                          "quality": {"tier": "normal", "settings": {}},
                                          "workflow": {"identifier": "i.json", "sha256": None,
                                                       "configured_inputs": {}}},
                     "stages": [stage]}
        asset = {"type": "prop", "description": "b", "generation_prompt": "b",
                 "candidates": {"items": [{"number": 1, "status": "candidate",
                                            "path": "concept.png",
                                            "execution_id": "single-id",
                                            "artifact": artifact}]},
                 "executions": [execution]}
        child = {"id": "t", "type": "prop", "description": "b", "generation_prompt": "b",
                 "requested_style_identity": {"name": "default", "version": 1},
                 "requested_conditioning": {"strategy": "text_only", "references": []}}

        decision = prop_child_reuse_decision(self.root, asset,
                                             {"candidate_execution_ids": ["single-id"]},
                                             child, {"asset_pipeline": {"defaults": {"image_candidates": 1}}})
        self.assertTrue(decision["reusable"])
class RemainingProcessedMeshMalformedProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "source.glb").write_bytes(b"source")
        (self.root / "processed.blend").write_bytes(b"processed")
        self.settings = {"face_budget": 1000, "material_scale": 3.0}
        self.source = self._artifact("source", "mesh.glb", "source.glb", "mesh_workflow_execution", [])
        self.processed = self._artifact(
            "processed", "mesh.processed", "processed.blend", "material_assembly_export",
            [{"artifact_id": "source", "sha256": self.source["sha256"]}],
        )
        self.valid_stage = {
            "name": "material_assembly_export", "attempt": 1, "status": "succeeded",
            "inputs": [self.source], "settings": self.settings, "outputs": [self.processed],
        }

    def _artifact(self, artifact_id, artifact_type, path, stage, derived_from):
        return {
            "id": artifact_id, "type": artifact_type, "path": path,
            "sha256": file_sha256(self.root / path), "stage": stage,
            "attempt": 1, "derived_from": derived_from,
        }

    def _decision(self, executions):
        from slopforge.pipelines.model import processed_mesh_reuse_decision

        asset = {"source": {"processed_mesh": "processed.blend"}, "executions": executions}
        return processed_mesh_reuse_decision(self.root, asset, self.source, self.settings)

    def test_valid_execution_with_none_execution_sibling_is_rejected(self):
        decision = self._decision([
            {"id": "execution:1", "status": "succeeded", "stages": [self.valid_stage]}, None,
        ])
        self.assertFalse(decision["reusable"])
        self.assertIn("malformed", " ".join(decision["reasons"]))

    def test_valid_stage_with_none_stage_sibling_is_rejected(self):
        execution = {"id": "execution:1", "status": "succeeded",
                     "stages": [self.valid_stage, None]}
        decision = self._decision([execution])
        self.assertFalse(decision["reusable"])
        self.assertIn("malformed", " ".join(decision["reasons"]))

    def test_valid_output_with_none_output_sibling_is_rejected_before_status_filtering(self):
        malformed_sibling = {
            "name": "material_assembly_export", "attempt": 2, "status": "failed",
            "inputs": [], "settings": {"different": True},
            "outputs": [self.processed, None],
        }
        execution = {"id": "execution:1", "status": "succeeded",
                     "stages": [malformed_sibling, self.valid_stage]}
        decision = self._decision([execution])
        self.assertFalse(decision["reusable"])
        self.assertIn("malformed", " ".join(decision["reasons"]))

    def test_malformed_output_as_only_output_is_rejected(self):
        malformed_stage = {
            "name": "material_assembly_export", "attempt": 2, "status": "failed",
            "inputs": [], "settings": {"different": True}, "outputs": [None],
        }
        decision = self._decision([{"id": "execution:1", "status": "failed",
                                   "stages": [malformed_stage]}])
        self.assertFalse(decision["reusable"])
        self.assertIn("malformed", " ".join(decision["reasons"]))

    def test_valid_provenance_remains_reusable(self):
        decision = self._decision([{"id": "execution:1", "status": "succeeded",
                                    "stages": [self.valid_stage]}])
        self.assertEqual(decision, {"reusable": True, "reasons": []})

    def test_processed_mesh_rejects_correct_derivation_with_unrelated_parent(self):
        self.processed["derived_from"].append({
            "artifact_id": "unrelated", "sha256": "f" * 64})

        decision = self._decision([{"id": "execution:1", "status": "succeeded",
                                    "stages": [self.valid_stage]}])

        self.assertFalse(decision["reusable"])

    def test_processed_mesh_rejects_missing_recorded_stage_parent(self):
        extra_input = {"id": "extra", "sha256": "e" * 64}
        self.valid_stage["inputs"].append(extra_input)

        decision = self._decision([{"id": "execution:1", "status": "succeeded",
                                    "stages": [self.valid_stage]}])

        self.assertFalse(decision["reusable"])

    def test_processed_mesh_reuses_exact_recorded_parent_relation(self):
        decision = self._decision([{"id": "execution:1", "status": "succeeded",
                                    "stages": [self.valid_stage]}])

        self.assertTrue(decision["reusable"], decision["reasons"])

    def test_malformed_source_record_fails_closed_without_raising(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision

        asset = {"source": None, "executions": [
            {"id": "execution:1", "status": "succeeded", "stages": [self.valid_stage]},
        ]}
        decision = processed_mesh_reuse_decision(self.root, asset, self.source, self.settings)

        self.assertFalse(decision["reusable"])
        self.assertIn("malformed", " ".join(decision["reasons"]))

    def test_processed_mesh_rejects_distinct_outputs_for_same_required_path(self):
        duplicate = {**self.processed, "id": "processed:duplicate"}
        self.valid_stage["outputs"].append(duplicate)

        decision = self._decision([{"id": "execution:1", "status": "succeeded",
                                    "stages": [self.valid_stage]}])

        self.assertFalse(decision["reusable"])

    def test_stage_identity_ambiguity_precedes_cached_path_checks(self):
        from slopforge.pipelines.model import processed_mesh_reuse_decision

        duplicate = {"name": "mesh_preparation", "attempt": 1,
                     "inputs": [], "outputs": []}
        asset = {"source": {}, "executions": [
            {"id": "execution:1", "stages": [duplicate]},
            {"id": "execution:2", "stages": [dict(duplicate)]},
        ]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, self.source, self.settings)
        self.assertIn("duplicate stage identity", " ".join(decision["reasons"]))


if __name__ == "__main__":
    unittest.main()
