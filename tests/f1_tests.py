# ================================================================
# Finding 1 tests: processed_mesh_reuse_decision must reject ambiguous provenance
# ================================================================
class Finding1ProcessedMeshProvenanceTests(unittest.TestCase):
    """Regression tests for Finding 1: retexture must reject ambiguous processed-mesh provenance."""

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
                 "executions": [{"stages": [succeeded, failed]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, processed, settings)
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
                 "executions": [{"stages": [s1, s2]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, processed, settings)
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
                 "executions": [{"stages": [stage]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, processed, settings)
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
                 "executions": [{"stages": [stage]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, processed, settings)
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
                 "executions": [{"stages": [stage]}]}
        decision = processed_mesh_reuse_decision(
            self.root, asset, processed, settings)
        self.assertReusable(decision)
