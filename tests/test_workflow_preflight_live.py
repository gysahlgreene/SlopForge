import json
import os
import unittest
from pathlib import Path

from slopforge.backends.comfyui import ComfyUIClient
from slopforge.paths import tool_root
from slopforge.workflow_requirements import load_workflow_requirements, validate_workflow_requirements


@unittest.skipUnless(os.environ.get("SLOPFORGE_COMFYUI_PREFLIGHT") == "1",
                     "set SLOPFORGE_COMFYUI_PREFLIGHT=1 to check workflows against a live ComfyUI")
class LiveWorkflowPreflightTests(unittest.TestCase):
    def test_bundled_workflows_match_live_comfyui_capabilities(self):
        client = ComfyUIClient(os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188"), timeout=15)
        node_info = client.node_types()
        for path in sorted((tool_root() / "workflows").glob("*.json")):
            with self.subTest(workflow=path.name):
                workflow = json.loads(path.read_text())
                manifest = load_workflow_requirements(path)
                self.assertIsNotNone(manifest, f"missing sidecar for {path.name}")
                self.assertEqual(validate_workflow_requirements(path, workflow, manifest), [])
                client.validate_workflow(workflow, node_info)


if __name__ == "__main__":
    unittest.main()
