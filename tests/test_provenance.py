import hashlib
import tempfile
import unittest
from pathlib import Path

from slopforge.provenance import generator_provenance, workflow_sha256


class WorkflowProvenanceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
