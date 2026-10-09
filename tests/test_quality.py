import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopforge.config import load_project, select_quality_tier, workflow_node_inputs
from slopforge.quality import apply_workflow_inputs
from slopforge.backends.comfyui import generate_image, generate_model
from slopforge.provenance import generator_provenance
from slopforge.cli import parse_args
from slopforge.initializer import init_project
from slopforge.paths import resolve_workflow


class QualityTierTests(unittest.TestCase):
    def test_new_projects_default_to_mesh_pbr_and_hardware_appropriate_final_quality(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            init_project(root)
            for profile, resolution, texture_size in (("default", 1024, 2048),
                                                       ("mac", 1024, 2048),
                                                       ("h100", 1536, 4096),
                                                       ("h100_final", 1536, 4096)):
                with self.subTest(profile=profile), patch.dict("os.environ", {
                        "SLOPFORGE_COMPUTE_PROFILE": profile}, clear=True):
                    config = load_project(root)
                    pipeline = config["asset_pipeline"]
                    self.assertEqual(pipeline["selected_quality_tier"], "final")
                    workflow = pipeline["workflows"]["model"]
                    graph = json.loads(resolve_workflow(root, workflow).read_text())
                    apply_workflow_inputs(graph, workflow_node_inputs(config, "model", workflow))
                    self.assertEqual(graph["shape_upsample_stage"]["inputs"]["target_resolution"], resolution)
                    self.assertEqual(graph["maps"]["inputs"]["texture_size"], texture_size)
                    self.assertGreater(graph["crop"]["inputs"]["pad_factor"], 1.0)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "ai").mkdir()
        (self.root / "ai/project.yaml").write_text("""project: {name: quality-test}
asset_pipeline:
  active_style: plain
  defaults: {image_candidates: 4, model_candidates: 2, material_candidates: 2}
  workflows: {image: base.json}
  quality_tier: normal
  quality_tiers:
    draft:
      defaults: {image_candidates: 1, model_candidates: 1}
      workflows: {image: draft.json}
      workflow_inputs:
        image:
          mac.json: {"1": {width: 512, height: 512}}
          h100.json: {"1": {width: 768, height: 768}}
      estimate: {label: "about 1 minute", measured: false}
    normal: {}
    final:
      defaults: {image_candidates: 6}
  compute_profiles:
    mac: {workflows: {image: mac.json}}
    h100: {workflows: {image: h100.json}}
""")

    def tearDown(self):
        self.temp.cleanup()

    def test_compute_profile_and_quality_tier_are_independent_and_layered(self):
        with patch.dict("os.environ", {"COMFYUI_URL": "http://gpu.example:8188",
                                        "SLOPFORGE_COMPUTE_PROFILE": "h100",
                                        "SLOPFORGE_QUALITY_TIER": "draft"}, clear=True):
            config = load_project(self.root)
        pipeline = config["asset_pipeline"]
        self.assertEqual(pipeline["selected_compute_profile"], "h100")
        self.assertEqual(pipeline["selected_quality_tier"], "draft")
        self.assertEqual(pipeline["tools"]["comfy_url"], "http://gpu.example:8188")
        self.assertEqual(pipeline["workflows"]["image"], "h100.json")
        self.assertEqual(pipeline["defaults"]["image_candidates"], 1)
        self.assertEqual(workflow_node_inputs(config, "image", "h100.json"),
                         {"1": {"width": 768, "height": 768}})
        self.assertEqual(workflow_node_inputs(config, "image", "mac.json"),
                         {"1": {"width": 512, "height": 512}})

    def test_cli_tier_selection_overrides_project_default_without_changing_host(self):
        config = load_project(self.root)
        selected = select_quality_tier(config, "final")
        self.assertEqual(selected["asset_pipeline"]["selected_quality_tier"], "final")
        self.assertEqual(selected["asset_pipeline"]["defaults"]["image_candidates"], 6)
        self.assertEqual(selected["asset_pipeline"]["selected_compute_profile"], "default")
        self.assertEqual(selected["asset_pipeline"]["quality_settings"]["defaults"],
                         {"image_candidates": 6, "model_candidates": 3, "material_candidates": 3})

    def test_unknown_quality_tier_is_rejected(self):
        config = load_project(self.root)
        with self.assertRaisesRegex(ValueError, "Unknown quality tier"):
            select_quality_tier(config, "cinematic")

    def test_workflow_override_sets_only_configured_existing_inputs(self):
        graph = {"1": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024}}}
        apply_workflow_inputs(graph, {"1": {"width": 512, "height": 512}})
        self.assertEqual(graph["1"]["inputs"], {"width": 512, "height": 512})
        with self.assertRaisesRegex(ValueError, "missing node/input"):
            apply_workflow_inputs(graph, {"8": {"steps": 12}})

    def test_generate_cli_and_candidate_provenance_expose_quality(self):
        args = parse_args(["generate", "concept", "badge", "A badge", "--quality-tier", "draft"])
        self.assertEqual(args.quality_tier, "draft")
        provenance = generator_provenance("image.json", {"quality": {"tier": "draft", "settings": {}}})
        self.assertEqual(provenance["quality"]["tier"], "draft")

    def test_image_backend_passes_tier_inputs_and_settings_to_processor(self):
        workflow = self.root / "workflow.json"
        workflow.write_text("{}")
        config = {"asset_pipeline": {"tools": {"comfy_url": "http://gpu.example:8188"},
                    "selected_compute_profile": "h100", "selected_quality_tier": "draft",
                    "quality_settings": {"workflow_inputs": {"image": {"workflow.json": {"1": {"width": 512}}}}}}}
        with patch("slopforge.backends.comfyui.subprocess.run") as run:
            generate_image(self.root, config, workflow, "badge", self.root / "out.png", "badge", 1,
                           self.root / "meta.json")
        command = run.call_args.args[0]
        self.assertEqual(json.loads(command[command.index("--workflow-inputs") + 1]), {"1": {"width": 512}})
        self.assertEqual(json.loads(command[command.index("--quality") + 1]),
                         {"tier": "draft", "settings": config["asset_pipeline"]["quality_settings"]})

    def test_model_backend_passes_quality_inputs_to_three_d_processor(self):
        config = {"asset_pipeline": {"tools": {"hunyuan_checkpoint": "model.safetensors"},
                    "workflows": {"model": "trellis2_image_to_model_h100_api.json"},
                    "selected_quality_tier": "final",
                    "quality_settings": {"workflow_inputs": {"model": {
                        "trellis2_image_to_model_h100_api.json": {"10": {"resolution": 1024}}}}}}}
        with patch("slopforge.backends.comfyui.subprocess.run") as run, \
                patch("slopforge.backends.comfyui.blender_executable", return_value="blender"):
            generate_model(self.root, config, self.root / "concept.png", "statue", self.root / "statue.glb",
                           self.root / "mesh.json", 9, voxel_resolution=120)
        command = run.call_args.args[0]
        self.assertEqual(json.loads(command[command.index("--workflow-inputs") + 1]),
                         {"10": {"resolution": 1024}})
        self.assertEqual(json.loads(command[command.index("--quality") + 1])["tier"], "final")
        self.assertEqual(command[command.index("--voxel-resolution") + 1], "120")


if __name__ == "__main__":
    unittest.main()
