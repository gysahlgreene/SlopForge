# ================================================================
# Finding 2 tests: publication lineage must match recorded parents/inputs
# ================================================================
class Finding2PublicationLineageTests(unittest.TestCase):
    """Regression tests for Finding 2: publication readiness must validate lineage."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "Assets").mkdir(parents=True)

    def make_fixture(self, parent_id=None):
        """Build a valid publication fixture. Use `parent_id` to override the parent."""
        path = self.root / "Assets/approved.fbx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"approved output")
        real_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        
        stage_input = {
            "id": "candidate:1", "type": "surface.swatch",
            "path": "Assets/src.png", "sha256": "src_sha256",
            "stage": "concept_generation", "attempt": 1, "derived_from": []
        }
        
        candidate_output = {
            "id": stage_input["id"], "type": stage_input["type"],
            "path": stage_input["path"],
            "sha256": stage_input["sha256"],
            "stage": stage_input["stage"], "attempt": stage_input["attempt"],
            "derived_from": stage_input["derived_from"]}
        candidate_stage = {"name": "material_assembly_export", "attempt": 1,
                           "status": "succeeded", "inputs": [], "settings": {},
                           "outputs": [candidate_output]}
        source_exec = {"id": "source-exec:1", "status": "succeeded",
                       "parent_execution_id": None, "identity_inputs": {},
                       "stages": [candidate_stage]}
        
        # pub-exec-1 is a clean ID (no :published: in it)
        pub_exec = {"id": "pub-exec-1", "status": "succeeded",
                    "parent_execution_id": parent_id or "source-exec:1",
                    "identity_inputs": {},
                    "stages": [{"name": "final_publication", "attempt": 1,
                                "status": "succeeded", "inputs": [stage_input],
                                "settings": {}, "outputs": []}]}
        
        published_ref = {
            "id": "pub-exec-1:published:model",
            "type": "model.fbx",
            "path": "Assets/approved.fbx",
            "sha256": real_sha,
            "stage": "final_publication", "attempt": 1,
            "derived_from": [{"artifact_id": candidate_output["id"],
                              "sha256": candidate_output["sha256"]}]}

class Finding2LineageValidationTests(Finding2PublicationLineageTests):
    """Tests for _published_output_provenance and readiness validation."""

    # A. otherwise valid publication execution with wrong/unrelated parent_execution_id
    #     -> readiness rejected
    def test_wrong_parent_execution_id_invalidates_readiness(self):
        """A publication execution whose parent points to an unrelated source
        should invalidate readiness."""
        from slopforge.recipes import _ready_output_error
        asset, source_exec, pub_exec, _, _ = self.make_fixture(
            parent_id="unrelated-exec:999")
        
        # Also remove the real source so the parent is unresolvable
        asset["executions"] = [e for e in asset["executions"]
                               if e["id"] != "source-exec:1"]
        
        error = _ready_output_error(self.root, asset)
        self.assertIsNotNone(error)
        self.assertNotEqual(asset["status"], "ready")

    # B. otherwise valid publication output whose derived_from disagrees
    #     with the recorded publication inputs -> readiness rejected
    def test_derived_from_disagrees_with_stage_inputs_invalidates_readiness(self):
        """Published output derived_from that does not match the final_publication
        stage inputs should invalidate readiness."""
        from slopforge.recipes import _published_output_provenance
        asset, source_exec, pub_exec, published_ref, stage_input = \
            self.make_fixture()
        
        # Break the lineage: derived_from no longer matches stage inputs
        published_ref["derived_from"] = [
            {"artifact_id": "ghost-input", "sha256": "fake_sha"}]
        
        error = _published_output_provenance(published_ref, asset["executions"])
        self.assertIsNotNone(error)

    # C. publication execution parent and output derivation disagree with each other
    #     -> readiness rejected
    def test_parent_and_derivation_disagree_invalidates_readiness(self):
        """If the publication execution's parent and the output's derived_from
        trace to different sources, the lineage is internally inconsistent."""
        from slopforge.recipes import _published_output_provenance, _ready_output_error
        asset, source_exec, pub_exec, published_ref, stage_input = \
            self.make_fixture()
        
        # Create a separate source and make everything point to different things
        other_exe = {"id": "other-source:1", "status": "succeeded",
                     "parent_execution_id": None, "identity_inputs": {},
                     "stages": []}
        other_input = {"id": "other:cand:1", "type": "surface.swatch",
                       "path": "Assets/other.png", "sha256": "other_sha",
                       "stage": "concept_generation", "attempt": 1, "derived_from": []}
        
        # Make parent point to another source
        pub_exec["parent_execution_id"] = other_exe["id"]
        # While stage inputs + derived_from point to source_exec
        # This is the inconsistency: parent and derivation disagree
        asset["executions"].append(other_exe)
        
        error = _published_output_provenance(published_ref, asset["executions"])
        self.assertIsNotNone(error,
            "expected lineage inconsistency to be rejected")

    # D. missing required lineage evidence -> reject conservatively
    def test_missing_source_execution_invalidates_readiness(self):
        """If the publication execution's parent_execution_id references a
        missing source execution, readiness must be rejected."""
        from slopforge.recipes import _ready_output_error
        asset, source_exec, pub_exec, _, _ = self.make_fixture()
        
        # Remove source from executions and reference a non-existent parent
        pub_exec["parent_execution_id"] = "absent-exec"
        asset["executions"] = [e for e in asset["executions"]
                               if e["id"] != "source-exec:1"]
        
        error = _ready_output_error(self.root, asset)
        self.assertIsNotNone(error)
        self.assertNotEqual(asset["status"], "ready")

    # E. valid publication lineage chain -> readiness remains valid
    def test_valid_publication_lineage_preserves_readiness(self):
        """A valid lineage chain should preserve readiness."""
        from slopforge.recipes import _ready_output_error
        asset, source_exec, pub_exec, published_ref, stage_input = \
            self.make_fixture()
        
        error = _ready_output_error(self.root, asset)
        # Valid lineage: error should be None and status stays "ready"
        self.assertIsNone(error)
        self.assertEqual(asset["status"], "ready")
