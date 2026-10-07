import json
import yaml
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from slopforge.exploration import parse_variations, promote_candidate
from slopforge.manifest import asset_key, new_record
from slopforge.candidates import generate_candidates
from slopforge.cli import main as cli_main
from slopforge.manifest import load_manifest
from slopforge.review import generate_review_board


class ExplorationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "Assets").mkdir()
        (self.root / "ai/asset_types").mkdir(parents=True)
        (self.root / "ai/styles/plain").mkdir(parents=True)
        (self.root / "ai/project.yaml").write_text("project: {name: Test}\nasset_pipeline: {active_style: plain}\n")
        (self.root / "ai/asset_types/concept.yaml").write_text(
            "name: concept\npipeline: image\noutput_folder: Icons\nformat: PNG\nrequirements: []\navoid: []\n")
        (self.root / "ai/styles/plain/style.yaml").write_text(
            "name: Plain\nversion: 1\nidentity: {}\nshape_language: {preferred: [], avoid: []}\n"
            "palette: {}\nmaterials: {}\nsurface_language: {preferred: [], avoid: []}\n"
            "lighting: {}\nasset_rules: {}\nmaterial_generation: {rules: []}\n")
        self.config = {"asset_pipeline": {"candidate_root": "ai/assets/candidates", "output_root": "Assets/Art"}}
        self.style = {"name": "Test", "version": 1}
        self.asset_type = {"name": "concept", "pipeline": "image", "format": "PNG", "alpha_required": False,
                           "output_folder": "Concepts"}
        self.manifest = {"assets": {}}

    def tearDown(self):
        self.temp.cleanup()

    def test_variations_parse_multiple_labeled_design_dimensions(self):
        self.assertEqual(parse_variations([
            "silhouette=wide and low;motif=three concentric rings",
            "silhouette=tall and narrow;materials=painted ceramic",
        ]), [
            {"silhouette": "wide and low", "motif": "three concentric rings"},
            {"silhouette": "tall and narrow", "materials": "painted ceramic"},
        ])
        with self.assertRaisesRegex(ValueError, "at least two"):
            parse_variations(["silhouette=round"])
        with self.assertRaisesRegex(ValueError, "repeats dimension"):
            parse_variations(["shape=round;shape=angular", "shape=square"])

    def test_generation_uses_and_records_each_deliberate_variation(self):
        variations = parse_variations(["shape=round", "shape=angular"])
        key = asset_key("concept", "relic_explore")
        self.manifest["assets"][key] = new_record("concept", "relic_explore", "A relic", self.style,
                                                   {"strategy": "text_only"})
        prompts = []

        def backend(prompt, destination, seed, metadata):
            prompts.append(prompt)
            Image.new("RGB", (8, 8), "red").save(destination)
            metadata.write_text(json.dumps({"workflow": "fixture.json", "seed": seed}))

        results = generate_candidates(self.root, self.config, self.asset_type, self.style, "relic_explore",
                                      "base prompt", 2, self.manifest, key, backend,
                                      variations=variations)
        self.assertIn("shape: round", prompts[0])
        self.assertIn("shape: angular", prompts[1])
        self.assertEqual([item["variation"] for item in results], variations)
        self.assertNotEqual(results[0]["seed"], results[1]["seed"])

    def test_promote_preserves_candidate_provenance_and_requires_fresh_target(self):
        key = asset_key("concept", "relic_explore")
        source = new_record("concept", "relic_explore", "A relic", self.style, {"strategy": "text_only"})
        source["generation_mode"] = "explore"
        image_path = self.root / "ai/assets/candidates/concept/relic_explore/candidate_01.png"
        image_path.parent.mkdir(parents=True)
        Image.new("RGB", (8, 8), "blue").save(image_path)
        source["candidates"] = {"selected": None, "items": [{
            "number": 1, "path": image_path.relative_to(self.root).as_posix(), "status": "candidate",
            "prompt": "prompt", "description": "A relic", "seed": 44, "variation": {"shape": "round"},
            "generator": {"workflow": "wf.json", "model": "model-a", "seed": 44},
        }]}
        self.manifest["assets"][key] = source

        promoted = promote_candidate(self.root, "ai/assets/candidates", self.manifest,
                                     "relic_explore", 1, "relic", self.asset_type, self.style)

        target = self.manifest["assets"]["concept:relic"]
        self.assertEqual(promoted, target)
        self.assertEqual(target["status"], "candidate")
        self.assertEqual(target["candidates"]["items"][0]["variation"], {"shape": "round"})
        self.assertEqual(target["candidates"]["items"][0]["generator"]["model"], "model-a")
        self.assertEqual(target["candidates"]["items"][0]["path"],
                         "ai/assets/candidates/concept/relic/candidate_01.png")
        self.assertTrue((self.root / target["candidates"]["items"][0]["path"]).is_file())
        self.assertNotEqual(target["candidates"]["items"][0]["path"], image_path.relative_to(self.root).as_posix())
        self.assertEqual(target["promoted_from"]["asset_id"], source["id"])
        self.assertEqual(source["candidates"]["items"][0]["status"], "promoted")
        with self.assertRaisesRegex(FileExistsError, "already exists"):
            promote_candidate(self.root, "ai/assets/candidates", self.manifest,
                              "relic_explore", 1, "relic", self.asset_type, self.style)

    def test_explore_cli_and_promote_create_normal_approval_candidate(self):
        def backend(_root, _config, _workflow, prompt, destination, _prefix, seed, metadata, **_kwargs):
            Image.new("RGB", (8, 8), "gold").save(destination)
            metadata.write_text(json.dumps({"workflow": "fixture.json", "seed": seed, "model": "fixture"}))

        with patch("slopforge.pipelines.image.generate_image", side_effect=backend):
            result = cli_main(["--project", str(self.root), "explore", "concept", "relic_ideas", "A relic",
                               "--variation", "silhouette=round", "--variation", "silhouette=angular"])
        self.assertEqual(result, 0)
        manifest_path = self.root / "ai/assets/manifest.json"
        manifest = load_manifest(manifest_path)
        exploration = manifest["assets"]["concept:relic_ideas"]
        self.assertEqual(exploration["generation_mode"], "explore")
        self.assertEqual(exploration["candidates"]["items"][1]["variation"], {"silhouette": "angular"})
        self.assertIn("explore · draft", generate_review_board(self.root, manifest).read_text())
        board = generate_review_board(self.root, manifest).read_text()
        self.assertIn("promote relic_ideas 1 --name relic_ideas_asset", board)
        self.assertNotIn("approve relic_ideas 1", board)
        self.assertNotIn("generate concept relic_ideas", board)
        self.assertEqual(cli_main(["--project", str(self.root), "promote", "relic_ideas", "1", "--name", "relic"]), 0)
        manifest = load_manifest(manifest_path)
        tracked = manifest["assets"]["concept:relic"]
        self.assertEqual(tracked["status"], "candidate")
        self.assertEqual(tracked["promoted_from"]["variation"], {"silhouette": "round"})
        self.assertEqual(cli_main(["--project", str(self.root), "approve", "relic", "1"]), 0)
        self.assertTrue((self.root / "Assets/Art/Generated/Icons/relic.png").is_file())


if __name__ == "__main__":
    unittest.main()
