import tempfile
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from slopforge.backends.comfyui import ComfyUIClient
from processing.comfy_generate import bind_reference_inputs
from slopforge.cli import parse_args
from slopforge.conditioning import ensure_supported, resolve_conditioning


class ConditioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.approved = self.root / "ai/styles/plain/references/approved"
        (self.approved / "characters").mkdir(parents=True)
        (self.approved / "props").mkdir()
        (self.approved / "characters/alice.png").write_bytes(b"alice")
        (self.approved / "props/relay.png").write_bytes(b"relay")
        (self.approved / "generic.png").write_bytes(b"generic")
        self.style = {"_directory": self.root / "ai/styles/plain"}
        self.config = {"asset_pipeline": {"workflows": {"image": "image_text2img_api.json"},
                                            "conditioning": {"strategy": "reference", "max_references": 3,
                                                              "strength": 0.7}}}

    def tearDown(self):
        self.temp.cleanup()

    def test_resolves_only_explicit_references_with_per_reference_strength(self):
        result = resolve_conditioning(self.root, self.config, self.style,
                                      reference_paths=["ai/styles/plain/references/approved/characters/alice.png"],
                                      reference_categories=["props"])
        self.assertEqual(result["references"], [
            {"path": "ai/styles/plain/references/approved/characters/alice.png", "strength": 0.7},
            {"path": "ai/styles/plain/references/approved/props/relay.png", "strength": 0.7},
        ])

    def test_resolves_library_membership_without_changing_its_domain_metadata(self):
        entries = [{"id": "portrait", "path": str(self.approved / "characters/alice.png"),
                    "category": "identity", "strength": 0.82, "sha256": "abc", "status": "ready",
                    "source": {"path": str(self.approved / "characters/alice.png")}}]
        result = resolve_conditioning(self.root, self.config, self.style, reference_entries=entries)
        self.assertEqual(result["references"], [{
            "path": "ai/styles/plain/references/approved/characters/alice.png", "strength": 0.82,
            "library_entry_id": "portrait", "category": "identity", "sha256": "abc",
            "expected_sha256": None, "source": {"path": str(self.approved / "characters/alice.png")},
        }])

    def test_rejects_changed_library_entry_before_generation(self):
        with self.assertRaisesRegex(ValueError, "is changed"):
            resolve_conditioning(self.root, self.config, self.style,
                                reference_entries=[{"id": "portrait", "path": "/tmp/portrait.png",
                                                    "status": "changed"}])

    def test_generate_cli_accepts_library_selector(self):
        args = parse_args(["generate", "concept", "badge", "A badge", "--reference-library", "character/alice"])
        self.assertEqual(args.reference_library, "character/alice")

    def test_rejects_reference_outside_approved_library(self):
        elsewhere = self.root / "private.png"
        elsewhere.write_bytes(b"private")
        with self.assertRaisesRegex(ValueError, "approved reference library"):
            resolve_conditioning(self.root, self.config, self.style, reference_paths=[elsewhere])

    def test_explicit_selection_cannot_silently_exceed_configured_limit(self):
        self.config["asset_pipeline"]["conditioning"]["max_references"] = 1
        with self.assertRaisesRegex(ValueError, "exceeding conditioning.max_references=1"):
            resolve_conditioning(self.root, self.config, self.style,
                                 reference_paths=["ai/styles/plain/references/approved/generic.png",
                                                  "ai/styles/plain/references/approved/props/relay.png"])

    def test_category_selection_does_not_add_uncategorized_references(self):
        result = resolve_conditioning(self.root, self.config, self.style, reference_categories=["props"])
        self.assertEqual([item["path"] for item in result["references"]],
                         ["ai/styles/plain/references/approved/props/relay.png"])

    def test_reference_strategy_requires_a_workflow_slot(self):
        condition = {"strategy": "reference", "references": [{"path": "ref.png", "strength": 0.5}]}
        with self.assertRaisesRegex(NotImplementedError, "workflow_inputs"):
            ensure_supported(condition, [])

    def test_workflow_slots_receive_uploaded_names_and_strengths(self):
        class Client:
            def upload_input(self, path, subfolder):
                return {"name": Path(path).name, "subfolder": subfolder}

        workflow = {"10": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
                    "11": {"class_type": "ReferenceConditioning", "inputs": {"strength": 0.1}}}
        mapping = [{"image": {"node": "10", "input": "image"},
                    "strength": {"node": "11", "input": "strength"}}]
        used = bind_reference_inputs(Client(), workflow,
                                     [{"path": "/tmp/alice.png", "strength": 0.75}], mapping)
        self.assertEqual(workflow["10"]["inputs"]["image"], "slopforge/references/alice.png")
        self.assertEqual(workflow["11"]["inputs"]["strength"], 0.75)
        self.assertEqual(used[0]["path"], "/tmp/alice.png")

    def test_workflow_mapping_fails_before_upload_when_input_is_missing(self):
        class Client:
            def upload_input(self, *_args, **_kwargs):
                raise AssertionError("must validate graph before upload")

        with self.assertRaisesRegex(ValueError, "node/input"):
            bind_reference_inputs(Client(), {"10": {"inputs": {}}},
                                  [{"path": "/tmp/ref.png", "strength": 0.5}],
                                  [{"image": {"node": "10", "input": "image"}}])

    def test_reference_upload_is_bound_in_workflow_submitted_to_http_service(self):
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                body = json.dumps({
                    "LoadImage": {"input": {"required": {"image": [["uploaded.png"], {}]}}},
                    "ReferenceConditioning": {"input": {"required": {"strength": ["FLOAT", {"min": 0, "max": 1}]}}},
                }).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if self.path == "/upload/image":
                    received.setdefault("uploads", []).append(body)
                    response = {"name": f"uploaded-{len(received['uploads'])}.png", "subfolder": "slopforge/references"}
                else:
                    received["prompt"] = json.loads(body)["prompt"]
                    response = {"prompt_id": "prompt-1"}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            reference = self.approved / "characters/alice.png"
            second_reference = self.approved / "props/relay.png"
            workflow = {"10": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
                        "11": {"class_type": "ReferenceConditioning", "inputs": {"strength": 0.1}},
                        "12": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
                        "13": {"class_type": "ReferenceConditioning", "inputs": {"strength": 0.1}}}
            mapping = [{"image": {"node": "10", "input": "image"},
                        "strength": {"node": "11", "input": "strength"}},
                       {"image": {"node": "12", "input": "image"},
                        "strength": {"node": "13", "input": "strength"}}]
            client = ComfyUIClient(f"http://127.0.0.1:{server.server_port}")
            used = bind_reference_inputs(client, workflow,
                                         [{"path": str(reference), "strength": 0.8},
                                          {"path": str(second_reference), "strength": 0.55}], mapping)
            client.queue_workflow(workflow)
            self.assertIn(b"alice.png", received["uploads"][0])
            self.assertIn(b"relay.png", received["uploads"][1])
            self.assertEqual(received["prompt"]["10"]["inputs"]["image"],
                             "slopforge/references/uploaded-1.png")
            self.assertEqual(received["prompt"]["11"]["inputs"]["strength"], 0.8)
            self.assertEqual(received["prompt"]["12"]["inputs"]["image"],
                             "slopforge/references/uploaded-2.png")
            self.assertEqual(received["prompt"]["13"]["inputs"]["strength"], 0.55)
            self.assertEqual(used[0]["path"], str(reference))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
