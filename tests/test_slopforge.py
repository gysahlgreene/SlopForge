import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from PIL import Image

from slopforge.candidates import approve_image_candidate, generate_candidates
from slopforge.config import load_project
from slopforge.manifest import asset_key, load_manifest, new_record, save_manifest
from slopforge.paths import discover_project_root, resolve_workflow
from slopforge.style import build_prompt, load_style
from slopforge.taxonomy import canonical_type, load_taxonomy, output_path
from slopforge.validation import validate_image
from slopforge.cli import parse_args
from slopforge.cli import main as cli_main
from slopforge.initializer import init_project
from slopforge.conditioning import ensure_supported, resolve_conditioning
from slopforge.backends.blender import process_model
from slopforge.backends.comfyui import generate_image
from slopforge.paths import tool_root
from slopforge.pipelines.primitive import register_primitive
from slopforge.validation import validate_model_outputs
from processing.comfy_generate_3d import make_workflow
from processing.comfy_status import prompt_failure
from slopforge.doctor import run_doctor
from slopforge.pipelines.model import model_paths


def make_project(root):
    root = Path(root)
    (root / "Assets").mkdir(parents=True)
    (root / "ai/styles/plain/references/approved").mkdir(parents=True)
    (root / "ai/asset_types").mkdir(parents=True)
    (root / "ai/project.yaml").write_text("""project:\n  name: Test\nasset_pipeline:\n  active_style: plain\n  workflows:\n    image: image_text2img_api.json\n""")
    (root / "ai/styles/plain/style.yaml").write_text("""name: Plain\nversion: 1\nidentity: {genre: fantasy, rendering: painted, mood: [warm]}\nshape_language: {preferred: [rounded], avoid: [photorealistic]}\npalette: {}\nmaterials: {}\nsurface_language: {preferred: [matte], avoid: []}\nlighting: {description: soft, avoid: []}\nasset_rules: {}\nmaterial_generation: {rules: [surface only]}\n""")
    (root / "ai/asset_types/icon.yaml").write_text("""name: icon\npipeline: image\noutput_folder: Icons\nformat: PNG\nrequirements: [one subject]\navoid: [text]\n""")
    (root / "ai/asset_types/prop.yaml").write_text("""name: prop\npipeline: model\noutput_folder: Models\nface_budget: prop_faces\nrequirements: [isolated object]\navoid: [environment]\n""")
    (root / "ai/asset_types/primitive.yaml").write_text("""name: primitive\npipeline: native\noutput_folder: null\nrequirements: [Unity-native route]\navoid: []\n""")
    return root


class SlopForgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = make_project(Path(self.temp.name) / "project")

    def tearDown(self):
        self.temp.cleanup()

    def test_project_init_creates_minimum_project_files_without_engine_copy(self):
        target = Path(self.temp.name) / "new-game"
        (target / "Assets").mkdir(parents=True)
        init_project(target)
        self.assertTrue((target / "ai/project.yaml").is_file())
        self.assertTrue((target / "ai/styles/default/references/approved").is_dir())
        self.assertTrue((target / "ai/workflows").is_dir())
        self.assertTrue((target / "Assets/Art/Generated/Models").is_dir())
        self.assertFalse((target / "slopforge").exists())
        with self.assertRaises(FileExistsError):
            init_project(target)

    def test_project_root_discovery_walks_up_for_project_config(self):
        nested = self.root / "Assets/Scenes/Levels"
        nested.mkdir(parents=True)
        self.assertEqual(discover_project_root(nested), self.root.resolve())

    def test_config_and_arbitrary_style_load(self):
        config = load_project(self.root)
        style = load_style(self.root, config)
        self.assertEqual(config["asset_pipeline"]["active_style"], "plain")
        self.assertEqual(style["identity"]["genre"], "fantasy")

    def test_taxonomy_supports_model_alias_and_safe_output_paths(self):
        types = load_taxonomy(self.root)
        self.assertEqual(canonical_type("model", types), "prop")
        self.assertEqual(output_path(self.root, load_project(self.root), types["prop"], "terminal"),
                         (self.root / "Assets/Art/Generated/Models/terminal").resolve())
        with self.assertRaises(ValueError):
            output_path(self.root, load_project(self.root), types["prop"], "../escape")

    def test_project_style_and_type_rules_build_prompt(self):
        config = load_project(self.root)
        style = load_style(self.root, config)
        prompt = build_prompt(style, load_taxonomy(self.root)["icon"], "Health potion")
        self.assertIn("fantasy", prompt)
        self.assertIn("one subject", prompt)
        self.assertIn("Health potion", prompt)

    def test_project_workflow_override_precedes_toolkit_default(self):
        override = self.root / "ai/workflows/image_text2img_api.json"
        override.parent.mkdir(parents=True)
        override.write_text("{}")
        self.assertEqual(resolve_workflow(self.root, "image_text2img_api.json"), override.resolve())

    def test_toolkit_workflow_is_used_when_project_has_no_override(self):
        self.assertEqual(resolve_workflow(self.root, "image_text2img_api.json"),
                         (tool_root() / "workflows/image_text2img_api.json").resolve())

    def test_candidate_creation_and_approval_only_copies_selected_image(self):
        config = load_project(self.root)
        style = load_style(self.root, config)
        recipe = load_taxonomy(self.root)["icon"]
        manifest = load_manifest(self.root / "ai/assets/manifest.json")
        key = asset_key("icon", "potion")
        manifest["assets"][key] = new_record("icon", "potion", "Health potion", style, {"strategy": "text_only"})

        def backend(_prompt, destination, seed, metadata):
            Image.new("RGBA", (16, 16), (seed % 255, 10, 20, 255)).save(destination)
            metadata.write_text(json.dumps({"seed": seed, "model": "fixture"}))

        candidates = generate_candidates(self.root, config, recipe, style, "potion", "Health potion", 2,
                                         manifest, key, backend)
        result = approve_image_candidate(self.root, config, recipe, manifest, key, 2)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(manifest["assets"][key]["candidates"]["selected"], 2)
        self.assertEqual(result["status"], "passed")
        self.assertTrue((self.root / "Assets/Art/Generated/Icons/potion.png").is_file())

    def test_manifest_atomic_round_trip_keeps_candidate_history(self):
        path = self.root / "ai/assets/manifest.json"
        manifest = load_manifest(path)
        manifest["assets"]["icon:potion"] = {"name": "potion", "type": "icon", "status": "candidate",
                                                "candidates": {"items": [{"number": 1}], "selected": None}}
        save_manifest(path, manifest)
        self.assertEqual(load_manifest(path)["assets"]["icon:potion"]["candidates"]["items"], [{"number": 1}])

    def test_short_cli_and_explicit_forms_parse(self):
        self.assertTrue(parse_args(["model", "terminal", "wall object"]).auto_approve)
        explicit = parse_args(["generate", "icon", "potion", "red flask"])
        self.assertEqual(explicit.command, "generate")
        self.assertEqual(parse_args(["approve", "potion", "2"]).candidate, 2)

    def test_cli_dry_run_injects_project_style_without_generating(self):
        output = StringIO()
        with redirect_stdout(output):
            result = cli_main(["--project", str(self.root), "generate", "icon", "potion", "Health potion", "--dry-run"])
        self.assertEqual(result, 0)
        self.assertIn("fantasy", output.getvalue())
        self.assertIn("one subject", output.getvalue())
        self.assertFalse((self.root / "ai/assets/manifest.json").exists())

    def test_environment_overrides_comfyui_url(self):
        with patch.dict(os.environ, {"COMFYUI_URL": "http://example.test:99/", "COMFYUI_HOME": "/tmp/comfy-test",
                                     "BLENDER_BIN": "/tmp/blender-test", "SLOPFORGE_PYTHON": "/tmp/python",
                                     "SLOPFORGE_PROJECT_ROOT": str(self.root)}):
            tools = load_project(self.root)["asset_pipeline"]["tools"]
            self.assertEqual(tools["comfy_url"], "http://example.test:99")
            self.assertEqual(tools["comfy_home"], "/tmp/comfy-test")
            self.assertEqual(tools["blender"], "/tmp/blender-test")
            self.assertEqual(tools["asset_python"], "/tmp/python")
            with redirect_stdout(StringIO()):
                self.assertEqual(cli_main(["assets"]), 0)

    def test_primitive_is_native_route(self):
        args = parse_args(["generate", "primitive", "door_frame", "Simple doorway"])
        style = load_style(self.root, load_project(self.root))
        manifest = load_manifest(self.root / "ai/assets/manifest.json")
        record = register_primitive(manifest, load_project(self.root), style, args.name, args.description)
        self.assertEqual(record["route"], "unity_native_geometry")
        self.assertEqual(load_taxonomy(self.root)[args.asset_type]["pipeline"], "native")
        original_id, original_created = record["id"], record["created_at"]
        updated = register_primitive(manifest, load_project(self.root), style, args.name, "Updated doorway")
        self.assertEqual((updated["id"], updated["created_at"]), (original_id, original_created))
        self.assertEqual(updated["description"], "Updated doorway")
        with self.assertRaisesRegex(ValueError, "Asset name"):
            register_primitive(manifest, load_project(self.root), style, "../escape", "Unsafe name")

    def test_reference_mode_is_never_claimed_as_active_conditioning(self):
        config = load_project(self.root)
        config["asset_pipeline"]["conditioning"]["strategy"] = "reference"
        conditioning = resolve_conditioning(self.root, config, load_style(self.root, config))
        with self.assertRaisesRegex(NotImplementedError, "does not consume reference"):
            ensure_supported(conditioning)

    def test_hunyuan_workflow_uses_configured_checkpoint_and_seed(self):
        workflow = make_workflow("input.png", "pickup", "checkpoint.safetensors", 123)
        self.assertEqual(workflow["2"]["inputs"]["ckpt_name"], "checkpoint.safetensors")
        self.assertEqual(workflow["7"]["inputs"]["seed"], 123)

    def test_comfy_failed_prompt_reports_backend_error_immediately(self):
        entry = {"status": {"status_str": "error", "messages": [["execution_error", {"exception_message": "missing model"}]]}}
        self.assertIn("missing model", prompt_failure(entry))
        self.assertIsNone(prompt_failure({"status": {"status_str": "success"}}))

    def test_comfy_backend_uses_configured_workflow_url_and_seed(self):
        config = load_project(self.root)
        with patch.dict(os.environ, {"COMFYUI_URL": "http://localhost:9000/"}):
            with patch("slopforge.backends.comfyui.subprocess.run") as run:
                generate_image(self.root, config, "image_text2img_api.json", "prompt", self.root / "out.png",
                               "test/icon", 42, self.root / "out.json")
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--seed") + 1], "42")
        self.assertEqual(run.call_args.kwargs["env"]["COMFYUI_URL"], "http://localhost:9000")

    def test_blender_backend_forwards_model_face_budget(self):
        config = load_project(self.root)
        config["asset_pipeline"]["tools"]["blender"] = "/usr/bin/blender"
        with patch("slopforge.backends.blender.subprocess.run") as run:
            process_model(self.root, config, "in.glb", "out.fbx", "out.blend", [], 60000)
        self.assertEqual(run.call_args.args[0][-2:], ["--face-budget", "60000"])

    def test_model_validation_reports_when_blender_inspection_did_not_run(self):
        paths = {}
        for extension in (".glb", ".fbx", ".blend"):
            path = self.root / f"model{extension}"
            path.write_bytes(b"present")
            paths[extension[1:]] = path
        result = validate_model_outputs(paths, inspection=None, face_budget=100)
        self.assertEqual(result["status"], "passed_with_warnings")
        self.assertIn("inspection did not run", result["warnings"][0])

    def test_model_preview_path_is_safe_posix_blend_path(self):
        preview = model_paths(self.root, load_project(self.root), "smoke_relic")["blend"]
        relative = preview.relative_to(self.root.resolve()).as_posix()
        posix_path = PurePosixPath(relative)
        self.assertEqual(relative, "Assets/Art/Generated/Models/smoke_relic/smoke_relic_preview.blend")
        self.assertTrue(relative.endswith("_preview.blend"))
        self.assertNotIn("\\", relative)
        self.assertEqual(posix_path.as_posix(), relative)
        self.assertNotIn("..", posix_path.parts)

    def test_doctor_fails_when_onnxruntime_backend_is_missing(self):
        from unittest.mock import Mock

        def find_spec(name):
            return None if name == "onnxruntime" else Mock()

        output = StringIO()
        with redirect_stdout(output), patch("slopforge.doctor.urlopen", side_effect=OSError("offline")), \
                patch("slopforge.doctor.importlib.util.find_spec", side_effect=find_spec), \
                patch("slopforge.doctor.importlib.import_module", side_effect=ImportError("onnxruntime unavailable")):
            result = run_doctor()
        self.assertEqual(result, 1)
        self.assertIn("PASS Python packages — available", output.getvalue())
        self.assertIn('FAIL Background removal backend — onnxruntime unavailable; install "rembg[cpu]"', output.getvalue())

    def test_doctor_warns_when_configured_blender_does_not_exist(self):
        missing_blender = self.root / "missing-blender"
        output = StringIO()
        with redirect_stdout(output), patch.dict(os.environ, {"BLENDER_BIN": str(missing_blender)}), \
                patch("slopforge.doctor.urlopen", side_effect=OSError("offline")):
            result = run_doctor()
        self.assertEqual(result, 0)
        self.assertIn("WARN Blender", output.getvalue())
        self.assertNotIn("PASS Blender", output.getvalue())

    def test_image_validation_measures_dimensions_format_and_alpha(self):
        path = self.root / "sample.png"
        Image.new("RGBA", (8, 6), (1, 2, 3, 128)).save(path)
        result = validate_image(path, expected_format="PNG", require_alpha=True)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["measured"]["dimensions"], [8, 6])


if __name__ == "__main__":
    unittest.main()
