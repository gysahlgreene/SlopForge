"""Regression tests for slopforge.config _merge and DEFAULTS isolation."""

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from slopforge.config import DEFAULTS, _merge, load_project


def _make_project(root):
    root = Path(root)
    (root / "Assets").mkdir(parents=True)
    (root / "ai/styles/plain/references/approved").mkdir(parents=True)
    (root / "ai/asset_types").mkdir(parents=True)
    (root / "ai/project.yaml").write_text(
        "project:\n  name: Test\n"
        "asset_pipeline:\n  active_style: plain\n"
        "  workflows:\n    image: image_text2img_api.json\n"
    )
    (root / "ai/styles/plain/style.yaml").write_text(
        "name: Plain\nversion: 1\n"
        "identity: {genre: fantasy, rendering: painted, mood: [warm]}\n"
        "shape_language: {preferred: [rounded], avoid: []}\n"
        "palette: {}\nmaterials: {}\nsurface_language: {preferred: [matte], avoid: []}\n"
        "lighting: {description: soft, avoid: []}\nasset_rules: {}\n"
        "material_generation: {rules: []}\n"
    )
    for name, content in [
        ("icon", "name: icon\npipeline: image\noutput_folder: Icons\nformat: PNG"),
        ("prop", "name: prop\npipeline: model\noutput_folder: Models"),
        ("primitive", "name: primitive\npipeline: native\noutput_folder: null"),
    ]:
        (root / f"ai/asset_types/{name}.yaml").write_text(content)
    return root


class TestMergeIsolation(unittest.TestCase):
    def test_merge_returns_deep_copy_not_shared_references(self):
        result = _merge(DEFAULTS, {"active_style": "custom"})
        # Mutating the tools dict in the result must NOT affect DEFAULTS.
        result["tools"]["comfy_url"] = "http://mutated:9999"
        self.assertNotEqual(
            result["tools"]["comfy_url"], DEFAULTS["tools"]["comfy_url"]
        )

    def test_multiple_merge_calls_are_independent(self):
        result_a = _merge(DEFAULTS, {"tools": {"comfy_url": "http://a"}})
        result_b = _merge(DEFAULTS, {"tools": {"comfy_url": "http://b"}})
        self.assertEqual(result_a["tools"]["comfy_url"], "http://a")
        self.assertEqual(result_b["tools"]["comfy_url"], "http://b")
        result_a["tools"]["comfy_url"] = "http://a2"
        self.assertEqual(result_b["tools"]["comfy_url"], "http://b")


class TestLoadProjectEnvIsolation(unittest.TestCase):
    def test_env_var_override_does_not_corrupt_default_comfy_url(self):
        """load_project with COMFYUI_URL set must not mutate DEFAULTS."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_project(Path(tmpdir) / "project")
            with patch.dict(os.environ, {"COMFYUI_URL": "http://override.test:9000"}):
                config = load_project(root)
            self.assertEqual(
                config["asset_pipeline"]["tools"]["comfy_url"],
                "http://override.test:9000",
            )
            # DEFAULTS must be untouched.
            self.assertEqual(DEFAULTS["tools"]["comfy_url"], "http://127.0.0.1:8188")
            # Another call must see the original default.
            config2 = load_project(root)
            self.assertEqual(
                config2["asset_pipeline"]["tools"]["comfy_url"], "http://127.0.0.1:8188"
            )
            os.environ.pop("COMFYUI_URL", None)


if __name__ == "__main__":
    unittest.main()
