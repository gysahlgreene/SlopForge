import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from PIL import Image, ImageStat

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
from slopforge.pipelines import model
from slopforge.validation import validate_model_outputs
from processing.comfy_generate_3d import make_workflow
from processing.comfy_status import prompt_failure
from processing.make_pbr_maps import main as make_pbr_maps
from slopforge.doctor import run_doctor
from slopforge.pipelines.model import material_candidate_paths, model_paths
from slopforge.pipelines.model import approve as approve_model


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
        self.assertTrue((target / "ai/recipes/starter_icons.yaml").is_file())
        self.assertTrue((target / "ai/libraries").is_dir())
        self.assertTrue((target / "ai/styles/default/references/approved").is_dir())
        self.assertTrue((target / "ai/workflows").is_dir())
        self.assertTrue((target / "Assets/Art/Generated/Models").is_dir())
        self.assertTrue((target / "AGENTS.md").is_file())
        self.assertTrue((target / "CLAUDE.md").is_file())
        self.assertTrue((target / ".continue/rules/asset-generation.md").is_file())
        self.assertFalse((target / "slopforge").exists())
        with self.assertRaises(FileExistsError):
            init_project(target)

    def test_init_installs_agent_instructions_without_overwriting_existing_ones(self):
        target = Path(self.temp.name) / "agent-game"
        (target / "Assets").mkdir(parents=True)
        (target / "AGENTS.md").write_text("Keep my project instructions.\n")
        continue_rules = target / ".continue/rules"
        continue_rules.mkdir(parents=True)
        (continue_rules / "art-direction.md").write_text("Keep my Continue rule.\n")

        init_project(target)

        self.assertEqual((target / "AGENTS.md").read_text(), "Keep my project instructions.\n")
        self.assertEqual((target / "CLAUDE.md").read_text().strip(), "@AGENTS.md")
        self.assertEqual((continue_rules / "art-direction.md").read_text(), "Keep my Continue rule.\n")
        self.assertTrue((continue_rules / "asset-generation.md").is_file())

    def test_make_guides_image_generation_review_and_approval(self):
        project = Path(self.temp.name) / "fresh-unity-project"
        (project / "Assets").mkdir(parents=True)
        prompts = []
        output = StringIO()

        def answer(prompt):
            prompts.append(prompt)
            if "Style number:" in prompt:
                return ""
            if "Type number or name:" in prompt:
                return "icon"
            if "Short name" in prompt:
                return "guided_potion"
            if "Describe what" in prompt:
                return "A small red healing potion"
            if "Candidate number" in prompt:
                return "2"
            if "Approve candidate" in prompt:
                return "y"
            raise AssertionError(f"Unexpected prompt: {prompt}")

        def backend(_root, _config, _workflow, _prompt, destination, _prefix, seed, metadata):
            Image.new("RGB", (16, 16), (seed % 255, 10, 20)).save(destination)
            metadata.write_text(json.dumps({"seed": seed, "model": "fixture"}))

        from slopforge.pipelines import image as image_pipeline
        approve_image = image_pipeline.approve

        def approve_with_warning(*args):
            result = approve_image(*args)
            result["status"] = "passed_with_warnings"
            result["warnings"] = ["background is opaque; inspect the icon in Unity"]
            manifest, key = args[3], args[4]
            manifest["assets"][key]["validation"] = result
            return result

        with patch("builtins.input", side_effect=answer), \
                patch("slopforge.cli._check_comfy", return_value=None, create=True), \
                patch("slopforge.cli._open_candidates", create=True), \
                patch("slopforge.pipelines.image.approve", side_effect=approve_with_warning), \
                patch("slopforge.pipelines.image.generate_image", side_effect=backend), \
                redirect_stdout(output):
            result = cli_main(["--project", str(project), "make"])

        record = load_manifest(project / "ai/assets/manifest.json")["assets"]["icon:guided_potion"]
        self.assertEqual(result, 0)
        self.assertEqual(record["candidates"]["selected"], 2)
        self.assertEqual(record["status"], "ready")
        self.assertTrue((project / "Assets/Art/Generated/Icons/guided_potion.png").is_file())
        self.assertTrue((project / "AGENTS.md").is_file())
        self.assertNotIn('"checks"', output.getvalue())
        self.assertIn("Export completed with warnings", output.getvalue())
        self.assertIn("background is opaque; inspect the icon in Unity", output.getvalue())
        self.assertNotIn("Style number:", prompts)
        self.assertIn("Using your only art style: Default", output.getvalue())
        self.assertIn("Next", output.getvalue())

    def test_make_ctrl_c_cancels_without_traceback(self):
        error = StringIO()
        with patch("slopforge.cli.discover_project_root", side_effect=FileNotFoundError), \
                patch("builtins.input", side_effect=KeyboardInterrupt), redirect_stdout(StringIO()), \
                redirect_stderr(error):
            result = cli_main(["make"])

        self.assertEqual(result, 130)
        self.assertIn("Cancelled", error.getvalue())
        self.assertNotIn("Traceback", error.getvalue())

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

    def test_approval_records_selected_candidate_provenance(self):
        config = load_project(self.root)
        style = load_style(self.root, config)
        recipe = load_taxonomy(self.root)["icon"]
        manifest = {"assets": {"icon:potion": new_record("icon", "potion", "Potion", style, {"strategy": "text_only"})}}

        def backend(_prompt, destination, seed, metadata):
            Image.new("RGB", (16, 16), "red").save(destination)
            metadata.write_text(json.dumps({"seed": seed, "model": "fixture", "prompt_id": str(seed)}))

        generated = generate_candidates(self.root, config, recipe, style, "potion", "Potion", 2,
                                        manifest, "icon:potion", backend)
        approve_image_candidate(self.root, config, recipe, manifest, "icon:potion", 1)
        self.assertEqual(manifest["assets"]["icon:potion"]["generator"], generated[0]["generator"])

    def test_cli_auto_approval_keeps_first_candidate_provenance(self):
        def backend(_root, _config, _workflow, _prompt, destination, _prefix, seed, metadata):
            Image.new("RGB", (16, 16), "red").save(destination)
            metadata.write_text(json.dumps({"workflow": "fixture.json", "seed": seed,
                                            "model": "fixture", "prompt_id": str(seed)}))

        with patch("slopforge.pipelines.image.generate_image", side_effect=backend), redirect_stdout(StringIO()):
            result = cli_main(["--project", str(self.root), "generate", "icon", "potion", "Health potion",
                               "--count", "2", "--auto-approve"])
        self.assertEqual(result, 0)
        record = load_manifest(self.root / "ai/assets/manifest.json")["assets"]["icon:potion"]
        self.assertEqual(record["status"], "ready")
        self.assertEqual(record["generator"], record["candidates"]["items"][0]["generator"])
        self.assertEqual(record["description"], "Health potion")
        self.assertEqual(record["candidates"]["selected"], 1)

    def test_corrupt_candidate_cannot_replace_approved_image(self):
        config = load_project(self.root)
        style = load_style(self.root, config)
        recipe = load_taxonomy(self.root)["icon"]
        record = new_record("icon", "potion", "Potion", style, {"strategy": "text_only"})
        manifest = {"assets": {"icon:potion": record}}

        def backend(_prompt, destination, seed, metadata):
            Image.new("RGB", (16, 16), "red").save(destination)

        generated = generate_candidates(self.root, config, recipe, style, "potion", "Potion", 2,
                                        manifest, "icon:potion", backend)
        approve_image_candidate(self.root, config, recipe, manifest, "icon:potion", 1)
        final = output_path(self.root, config, recipe, "potion")
        original = final.read_bytes()
        (self.root / generated[1]["path"]).write_bytes(b"corrupted after generation")
        with self.assertRaisesRegex(ValueError, "invalid image"):
            approve_image_candidate(self.root, config, recipe, manifest, "icon:potion", 2, force=True)
        self.assertEqual(final.read_bytes(), original)
        self.assertEqual(record["candidates"]["selected"], 1)
        self.assertEqual(record["status"], "ready")
        self.assertEqual(list(final.parent.glob(".potion.png.*")), [])

    def test_older_image_approval_restores_original_description_and_style(self):
        config = load_project(self.root)
        style = load_style(self.root, config)
        recipe = load_taxonomy(self.root)["icon"]
        record = new_record("icon", "potion", "Health potion", style, {"strategy": "text_only"})
        manifest = {"assets": {"icon:potion": record}}

        def backend(_prompt, destination, seed, metadata):
            Image.new("RGB", (16, 16), "red").save(destination)

        generate_candidates(self.root, config, recipe, style, "potion", "First styled prompt", 1,
                            manifest, "icon:potion", backend, semantic_description="Health potion")
        style["name"], style["version"] = "Different", 2
        record.update(description="Mana potion", style="Different", style_version=2)
        generate_candidates(self.root, config, recipe, style, "potion", "Second styled prompt", 1,
                            manifest, "icon:potion", backend, semantic_description="Mana potion")
        approve_image_candidate(self.root, config, recipe, manifest, "icon:potion", 1)
        self.assertEqual((record["description"], record["style"], record["style_version"]),
                         ("Health potion", "Plain", 1))

    def test_material_prompt_requests_surface_instead_of_physical_prop(self):
        style = load_style(self.root, load_project(self.root))
        recipe = load_taxonomy(self.root)["prop"]
        prompt = build_prompt(style, recipe, "Ancient relic", mode="material")
        self.assertIn("flat material surface", prompt)
        self.assertIn("no standalone object", prompt)
        self.assertNotIn("isolated object", prompt)
        self.assertIn("Ancient relic", prompt)
        self.assertIn("fantasy", prompt)

    def test_material_maps_are_derived_from_the_surface_and_emission_is_opt_in(self):
        source = self.root / "surface.png"
        Image.new("RGB", (32, 32), "gray").save(source)
        pixels = [(value // 4, value // 2, value) for y in range(32) for x in range(32)
                  for value in [40 + (x * 5 + y * 3) % 170]]
        texture = Image.new("RGB", (32, 32))
        texture.putdata(pixels)
        texture.save(source)
        outputs = {name: self.root / f"{name}.png" for name in ("normal", "roughness", "metallic", "emission")}
        argv = ["make_pbr_maps.py", "--basecolor", str(source), "--prompt",
                "weathered rough stone with tiny copper flecks"]
        for name, path in outputs.items():
            argv.extend((f"--{name}", str(path)))
        with patch("sys.argv", argv):
            make_pbr_maps()
        self.assertGreater(max(ImageStat.Stat(Image.open(outputs["normal"])).stddev), 0)
        self.assertGreater(ImageStat.Stat(Image.open(outputs["roughness"])).stddev[0], 0)
        self.assertEqual(set(Image.open(outputs["metallic"]).getdata()), {12})
        self.assertEqual(set(Image.open(outputs["emission"]).getdata()), {(0, 0, 0)})

        argv[argv.index("--prompt") + 1] = "emissive blue stone"
        with patch("sys.argv", argv):
            make_pbr_maps()
        self.assertTrue(any(pixel != (0, 0, 0) for pixel in Image.open(outputs["emission"]).getdata()))

    def test_model_approval_rejects_changed_style_before_processing(self):
        config = load_project(self.root)
        style = load_style(self.root, config)
        recipe = load_taxonomy(self.root)["prop"]
        record = new_record("prop", "relic", "Relic", style, {"strategy": "text_only"})
        manifest = {"assets": {"prop:relic": record}}

        def backend(_prompt, destination, seed, metadata):
            Image.new("RGB", (16, 16), "red").save(destination)

        generate_candidates(self.root, config, recipe, style, "relic", "Relic", 1,
                            manifest, "prop:relic", backend)
        style["identity"]["rendering"] = "photorealistic"
        with patch("slopforge.pipelines.model.subprocess.run", side_effect=AssertionError("Processing started before style check")), \
                self.assertRaisesRegex(ValueError, "style.*changed"):
            approve_model(self.root, config, recipe, style, manifest, "prop:relic", 1)
        self.assertFalse(model_paths(self.root, config, "relic")["directory"].exists())

    def test_model_approval_accepts_original_and_legacy_style(self):
        config = load_project(self.root)
        style = load_style(self.root, config)
        recipe = load_taxonomy(self.root)["prop"]
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                record = new_record("prop", "relic", "Relic", style, {"strategy": "text_only"})
                manifest = {"assets": {"prop:relic": record}}

                def backend(_prompt, destination, seed, metadata):
                    Image.new("RGB", (16, 16), "red").save(destination)

                generate_candidates(self.root, config, recipe, style, "relic", "Relic", 1,
                                    manifest, "prop:relic", backend)
                if legacy:
                    record["candidates"]["items"][0].pop("style")
                with patch("slopforge.pipelines.model.subprocess.run", side_effect=RuntimeError("inference disabled")), \
                        self.assertRaisesRegex(RuntimeError, "inference disabled"):
                    approve_model(self.root, config, recipe, style, manifest, "prop:relic", 1, force=True)
                self.assertEqual(record["status"], "failed")
                self.assertEqual(record["candidates"]["selected"], 1)

    def test_model_approval_uses_agent_material_prompt_and_records_mesh_previews(self):
        config, style = load_project(self.root), load_style(self.root)
        recipe = load_taxonomy(self.root)["prop"]
        record = new_record("prop", "relic", "Ancient relic", style, {"strategy": "text_only"})
        manifest = {"assets": {"prop:relic": record}}

        def concept_backend(_prompt, destination, seed, metadata):
            Image.new("RGB", (64, 64), "gray").save(destination)
            metadata.write_text(json.dumps({"workflow": "concept.json", "seed": seed, "model": "image-model"}))

        generate_candidates(self.root, config, recipe, style, "relic", "Ancient relic", 1,
                            manifest, "prop:relic", concept_backend)

        authored_material_prompt = "Seamless brushed titanium, charcoal panels, cyan luminous insets."

        def write_generated_image(_root, _config, _workflow, prompt, destination, _prefix, seed, metadata):
            self.assertEqual(prompt, authored_material_prompt)
            Image.new("RGB", (64, 64), (90, 100, 110)).save(destination)
            metadata.write_text(json.dumps({"workflow": "material.json", "seed": seed, "model": "image-model"}))

        def run_script(command, check):
            if "prepare_3d_input.py" in command[1]:
                Image.new("RGBA", (64, 64), (120, 120, 120, 255)).save(command[command.index("--cutout") + 1])
                Image.new("RGB", (64, 64), "white").save(command[command.index("--output") + 1])
            elif "make_pbr_maps.py" in command[1]:
                for flag in ("--normal", "--roughness", "--metallic", "--emission"):
                    Image.new("RGB", (64, 64), "gray").save(command[command.index(flag) + 1])

        def generate_mesh(_root, _config, _image, _name, destination, metadata, seed):
            destination.write_bytes(b"glb")
            metadata.write_text(json.dumps({"workflow": "mesh.json", "seed": seed, "model": "mesh-model"}))

        def process_mesh(_root, _config, _glb, fbx, blend, textures, _budget, **options):
            fbx.write_bytes(b"fbx")
            blend.write_bytes(b"blend")
            Image.new("RGB", (64, 64), (90, 100, 110)).save(textures[0])
            if not options["reuse_stage_mesh"]:
                Path(options["stage_mesh"]).write_bytes(b"processed mesh")
            Path(options["preview_dir"]).mkdir(parents=True, exist_ok=True)
            for name in ("front", "side", "rear"):
                Image.new("RGB", (16, 16), "gray").save(Path(options["preview_dir"]) / f"relic_{name}.png")

        with patch("slopforge.pipelines.model.generate_image", side_effect=write_generated_image), \
                patch("slopforge.pipelines.model.generate_model", side_effect=generate_mesh), \
                patch("slopforge.pipelines.model.process_model", side_effect=process_mesh) as process, \
                patch("slopforge.pipelines.model.inspect_model", return_value={
                    "status": "passed", "errors": [], "warnings": [], "measured": {"face_count": 8, "uv_layers": 1}}), \
                patch("slopforge.pipelines.model.subprocess.run", side_effect=run_script) as run_scripts:
            result = approve_model(self.root, config, recipe, style, manifest, "prop:relic", 1,
                                  material_prompt=authored_material_prompt)

        self.assertEqual(result["status"], "awaiting_texture_approval")
        self.assertEqual(len(record["material_candidates"]["items"]), 2)
        self.assertEqual(record["material_prompt"], authored_material_prompt)
        self.assertEqual(record["generator"]["workflow"]["material"], "material.json")
        self.assertEqual(Path(record["material_candidates"]["items"][0]["outputs"]["preview_front"]).name,
                         "relic_front.png")
        self.assertEqual(Path(process.call_args.kwargs["surface_source"]).name, "surface_source.png")
        self.assertNotIn("concept", process.call_args.kwargs)
        self.assertTrue(process.call_args.kwargs["reuse_stage_mesh"])
        pbr_command = next(call.args[0] for call in run_scripts.call_args_list
                           if "make_pbr_maps.py" in call.args[0][1])
        self.assertEqual(Path(pbr_command[pbr_command.index("--basecolor") + 1]).name, "surface_source.png")
        self.assertNotIn("--source", pbr_command)

    def test_approved_material_candidate_replaces_outputs_and_marks_asset_ready(self):
        config, style = load_project(self.root), load_style(self.root)
        asset = new_record("prop", "relic", "Ancient relic", style, {"strategy": "text_only"})
        asset["generator"] = {"workflow": {"concept": "concept.json", "mesh": "mesh.json", "material": None},
                              "seed": {"concept": 1, "mesh": 2}}
        manifest = {"assets": {"prop:relic": asset}}
        candidate_paths = material_candidate_paths(self.root, config, "relic", 1)
        keys = ("surface", "fbx", "blend", "basecolor", "normal", "roughness", "metallic", "metallic_gloss", "emission",
                "preview_front", "preview_side", "preview_rear")
        outputs = {}
        for name in keys:
            path = candidate_paths[name]
            path.parent.mkdir(parents=True, exist_ok=True)
            if name == "metallic_gloss":
                Image.new("RGBA", (8, 8), (0, 0, 0, 255)).save(path)
            else:
                path.write_bytes(name.encode())
            outputs[name] = path.relative_to(self.root).as_posix()
        asset["material_candidates"] = {"items": [{"number": 1, "status": "candidate", "prompt": "Brushed steel",
                                                        "seed": 3, "outputs": outputs,
                                                        "generator": {"workflow": "material.json", "model": "image-model"},
                                                        "validation": {"status": "passed", "errors": [],
                                                                       "warnings": [], "measured": {}}}],
                                         "selected": None}

        with patch("slopforge.pipelines.model.unity_cli", return_value="unity"), \
                patch("slopforge.pipelines.model.build_unity_material") as build_material:
            result = model.approve_texture(self.root, config, manifest, "prop:relic", 1)
        build_material.assert_called_once()

        final_paths = model_paths(self.root, config, "relic")
        self.assertEqual(asset["status"], "ready")
        self.assertEqual(asset["material_candidates"]["selected"], 1)
        self.assertEqual(asset["material_prompt"], "Brushed steel")
        self.assertEqual(result["status"], "passed")
        for name in keys:
            expected = candidate_paths[name].read_bytes() if name == "metallic_gloss" else name.encode()
            self.assertEqual(final_paths[name].read_bytes(), expected)

    def test_retexture_rebuilds_missing_stage_mesh_for_older_approved_models(self):
        root = self.root.resolve()
        config, style = load_project(root), load_style(root)
        asset = new_record("prop", "relic", "Ancient relic", style, {"strategy": "text_only"})
        paths = model_paths(root, config, "relic")
        paths["glb"].parent.mkdir(parents=True, exist_ok=True)
        paths["glb"].write_bytes(b"existing glb")
        paths["cutout"].write_bytes(b"existing cutout")
        asset["status"] = "ready"
        asset["source"] = {"glb": paths["glb"].relative_to(root).as_posix(),
                           "cutout": paths["cutout"].relative_to(root).as_posix()}
        asset["candidates"] = {"items": [{"number": 1}], "selected": 1}
        manifest = {"assets": {"prop:relic": asset}}
        failed = {"number": 1, "status": "failed", "error": "fixture failure"}
        with patch("slopforge.pipelines.model._generate_material_candidate", return_value=failed) as generate:
            candidates = model.retexture(root, config, load_taxonomy(root)["prop"], style,
                                         manifest, "prop:relic", count=1)
        self.assertEqual(candidates, [failed])
        self.assertEqual(asset["source"]["processed_mesh"], paths["processed_mesh"].relative_to(root).as_posix())
        self.assertEqual(generate.call_args.args[-1], paths["processed_mesh"])

    def test_force_init_preserves_manifest_history(self):
        target = Path(self.temp.name) / "new-game"
        (target / "Assets").mkdir(parents=True)
        init_project(target)
        manifest_path = target / "ai/assets/manifest.json"
        manifest = load_manifest(manifest_path)
        manifest["assets"]["icon:potion"] = {"name": "potion", "status": "ready", "candidates": {"items": [{"number": 1}]}}
        save_manifest(manifest_path, manifest)
        original = manifest_path.read_bytes()
        init_project(target, force=True)
        self.assertEqual(manifest_path.read_bytes(), original)

    def test_short_cli_and_explicit_forms_parse(self):
        self.assertTrue(parse_args(["model", "terminal", "wall object"]).auto_approve)
        explicit = parse_args(["generate", "icon", "potion", "red flask"])
        self.assertEqual(explicit.command, "generate")
        authored = parse_args(["generate", "icon", "potion", "Red flask", "--image-prompt", "exact\nimage prompt"])
        self.assertEqual(authored.image_prompt, "exact\nimage prompt")
        self.assertEqual(parse_args(["approve", "potion", "2"]).candidate, 2)
        material = parse_args(["retexture", "terminal", "--material-prompt", "blue steel", "--count", "3"])
        self.assertEqual((material.name, material.material_prompt, material.count), ("terminal", "blue steel", 3))
        approved = parse_args(["approve-texture", "terminal", "4"])
        self.assertEqual((approved.name, approved.candidate), ("terminal", 4))

    def test_agent_image_prompt_is_sent_verbatim_and_keeps_asset_brief(self):
        authored_prompt = "A hand-painted brass key, three-quarter view, deep teal enamel accents."
        with patch("slopforge.pipelines.image.generate_image") as generate_image, redirect_stdout(StringIO()):
            def write_candidate(_root, _config, _workflow, prompt, destination, _prefix, _seed, metadata):
                self.assertEqual(prompt, authored_prompt)
                Image.new("RGB", (16, 16), "gold").save(destination)
                metadata.write_text(json.dumps({"workflow": "fixture.json", "model": "fixture"}))
            generate_image.side_effect = write_candidate
            result = cli_main(["--project", str(self.root), "generate", "icon", "brass_key",
                               "An old key for the archive", "--image-prompt", authored_prompt, "--count", "1"])

        self.assertEqual(result, 0)
        record = load_manifest(self.root / "ai/assets/manifest.json")["assets"]["icon:brass_key"]
        self.assertEqual(record["description"], "An old key for the archive")
        self.assertEqual(record["candidates"]["items"][0]["description"], "An old key for the archive")
        self.assertEqual(record["candidates"]["items"][0]["prompt"], authored_prompt)

    def test_agent_model_prompt_is_sent_verbatim_and_saved_as_candidate_provenance(self):
        authored_prompt = "A broad, waist-high alien terminal with one recessed cyan display, front view."
        config, style = load_project(self.root), load_style(self.root)
        recipe = load_taxonomy(self.root)["prop"]
        manifest = {"assets": {"prop:terminal": new_record("prop", "terminal", "Door control", style,
                                                               {"strategy": "text_only"})}}

        def write_candidate(_root, _config, _workflow, prompt, destination, _prefix, _seed, metadata):
            self.assertEqual(prompt, authored_prompt)
            Image.new("RGB", (16, 16), "slategray").save(destination)
            metadata.write_text(json.dumps({"workflow": "fixture.json", "model": "fixture"}))

        with patch("slopforge.pipelines.model.generate_image", side_effect=write_candidate):
            model.generate(self.root, config, recipe, style, "terminal", "Door control", 1,
                           manifest, "prop:terminal", generation_prompt=authored_prompt)

        candidate = manifest["assets"]["prop:terminal"]["candidates"]["items"][0]
        self.assertEqual(candidate["description"], "Door control")
        self.assertEqual(candidate["prompt"], authored_prompt)

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

    def test_reference_mode_requires_explicit_workflow_mapping(self):
        config = load_project(self.root)
        config["asset_pipeline"]["conditioning"]["strategy"] = "reference"
        (self.root / "ai/styles/plain/references/approved/reference.png").write_bytes(b"image")
        conditioning = resolve_conditioning(self.root, config, load_style(self.root, config))
        with self.assertRaisesRegex(NotImplementedError, "workflow_inputs"):
            ensure_supported(conditioning)

    def test_library_cli_lists_and_shows_resolved_membership(self):
        import yaml
        from io import StringIO
        (self.root / "ai/libraries/character").mkdir(parents=True)
        (self.root / "ai/libraries/character/alice.yaml").write_text(yaml.safe_dump({
            "kind": "character", "name": "Alice", "entries": [{"id": "portrait", "path": "missing.png"}],
        }))
        (self.root / "ai/styles/plain/style.yaml").unlink()
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["--project", str(self.root), "library", "list"]), 0)
        self.assertEqual(output.getvalue().strip(), "character/alice")
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["--project", str(self.root), "library", "show", "character/alice"]), 0)
        self.assertEqual(json.loads(output.getvalue())["entries"][0]["status"], "missing")

    def test_review_command_writes_local_board_from_manifest(self):
        from slopforge.manifest import save_manifest
        candidate = self.root / "ai/assets/candidates/icon/token.png"
        candidate.parent.mkdir(parents=True)
        Image.new("RGB", (8, 8), "gold").save(candidate)
        save_manifest(self.root / "ai/assets/manifest.json", {"schema_version": 3, "assets": {
            "icon:token": {"id": "token-id", "name": "token", "type": "icon", "status": "candidate",
                           "candidates": {"items": [{"number": 1, "path": "ai/assets/candidates/icon/token.png",
                                                         "status": "candidate"}], "selected": None}}}})
        with redirect_stdout(StringIO()):
            self.assertEqual(cli_main(["--project", str(self.root), "review"]), 0)
        self.assertIn("token", (self.root / "slopforge-review.html").read_text())

    def test_reject_cli_records_reason_without_touching_other_candidates(self):
        from slopforge.manifest import save_manifest
        save_manifest(self.root / "ai/assets/manifest.json", {"schema_version": 3, "assets": {
            "icon:token": {"id": "token-id", "name": "token", "type": "icon", "status": "candidate",
                           "candidates": {"items": [{"number": 1, "status": "candidate"},
                                                         {"number": 2, "status": "candidate"}], "selected": None}}}})
        with redirect_stdout(StringIO()):
            self.assertEqual(cli_main(["--project", str(self.root), "reject", "token", "1",
                                       "--reason", "wrong shape"]), 0)
        record = load_manifest(self.root / "ai/assets/manifest.json")["assets"]["icon:token"]
        self.assertEqual(record["candidates"]["items"][0]["review"]["reason"], "wrong shape")
        self.assertEqual(record["candidates"]["items"][1]["status"], "candidate")

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
            process_model(self.root, config, "in.glb", "out.fbx", "out.blend", [], 60000,
                          surface_source="surface.png", preview_dir="previews",
                          material_scale=4.0, stage_mesh="processed.blend", reuse_stage_mesh=True)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--face-budget") + 1], "60000")
        self.assertEqual(command[command.index("--surface-source") + 1], "surface.png")
        self.assertNotIn("--concept", command)
        self.assertEqual(command[command.index("--preview-dir") + 1], "previews")
        self.assertEqual(command[command.index("--material-scale") + 1], "4.0")
        self.assertIn("--reuse-stage-mesh", command)
        self.assertEqual(command[command.index("--") + 1], "processed.blend")

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
        with redirect_stdout(output), patch("slopforge.doctor.ComfyUIClient.health", side_effect=OSError("offline")), \
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
                patch("slopforge.doctor.ComfyUIClient.health", side_effect=OSError("offline")):
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
