"""The image pipeline's approve publishes into the Unity project, so it is a delivery: the candidate's worker record
and the processing it runs (a cut-out, a tiling material's inpaint and upscale) decide whether it may ship."""
import json
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from slopforge.failures import StageFailure
from slopforge.pipelines import image

APACHE = {"source": "z_image_turbo_bf16.safetensors", "status": "cleared", "terms": "Apache-2.0",
          "terms_version": "model card", "read_on": "2026-10-27"}


def project(tmp_path, recorded):
    (tmp_path / "Foliage").mkdir()
    Image.new("RGBA", (4, 4), (10, 200, 10, 255)).save(tmp_path / "Foliage/tuft.png")
    generator = {"workflow": "image_text2img_api.json", **({"output_rights": recorded} if recorded is not None else {})}
    manifest = {"assets": {"foliage:tuft": {"name": "tuft", "description": "tuft", "outputs": {"image": "Foliage/tuft.png"},
                                            "candidates": {"items": [{"number": 1, "generator": generator}]}}}}
    return manifest


def approve(tmp_path, manifest, processing="cutout", **patches):
    with patch("slopforge.pipelines.image.approve_image_candidate", return_value={"status": "passed"}), \
            patch("slopforge.pipelines.image.make_cutout", return_value=(3, 4)), \
            patch("slopforge.pipelines.image.make_tiling_material", **patches) if patches else nullcontext():
        return image.approve(tmp_path, {}, {"name": "foliage", "processing": processing}, manifest, "foliage:tuft", 1)


def test_a_cleared_cutout_ships_and_records_its_rights(tmp_path):
    manifest = project(tmp_path, [APACHE])
    approve(tmp_path, manifest)
    rights = manifest["assets"]["foliage:tuft"]["output_rights"]
    assert rights["status"] == "cleared"
    assert [item["source"] for item in rights["sources"]] == ["z_image_turbo_bf16.safetensors", "background_removal"]
    assert not (tmp_path / "Foliage/tuft.SlopForge-NOTICES.txt").exists()


@pytest.mark.parametrize("recorded", [None, [{"source": "ae.safetensors", "status": "unknown", "reason": "unread"}]])
def test_a_candidate_without_cleared_rights_is_refused_before_publishing(tmp_path, recorded):
    manifest = project(tmp_path, recorded)
    with patch("slopforge.pipelines.image.approve_image_candidate") as publish, pytest.raises(StageFailure) as failure:
        image.approve(tmp_path, {}, {"name": "foliage", "processing": "cutout"}, manifest, "foliage:tuft", 1)
    publish.assert_not_called()
    assert failure.value.category == "configuration" and "approve" in str(failure.value)


def test_an_unsourced_upscaler_stops_a_tiling_material_and_puts_the_old_one_back(tmp_path):
    manifest = project(tmp_path, [APACHE])
    before = json.loads(json.dumps(manifest["assets"]["foliage:tuft"]))
    unknown = {"source": "RealESRGAN_x4plus.safetensors", "status": "unknown", "reason": "no documented source"}
    tiles = tmp_path / "Foliage/tuft"
    def tiling(root, config, source, prompt, out_dir, seams="cut"):
        out_dir.mkdir()
        (out_dir / "basecolor.png").write_bytes(b"tile")
        return {"basecolor": out_dir / "basecolor.png"}, {"upscale": {"workflow": "image_upscale_esrgan_api.json",
                                                                       "output_rights": [unknown]}}
    with pytest.raises(StageFailure, match="RealESRGAN"):
        approve(tmp_path, manifest, "tiling_material", side_effect=tiling)
    assert manifest["assets"]["foliage:tuft"] == before and not tiles.exists()


def test_owed_notices_ship_beside_the_image(tmp_path):
    notice = {"source": "x", "status": "attribution_required", "terms": "Some licence", "terms_version": "1",
              "read_on": "2026-10-27", "notice": "Built with X."}
    manifest = project(tmp_path, [notice])
    approve(tmp_path, manifest)
    assert "Built with X." in (tmp_path / "Foliage/tuft.SlopForge-NOTICES.txt").read_text()
