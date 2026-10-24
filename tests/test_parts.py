import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from slopforge.failures import StageFailure
from slopforge.parts import check_part_masks, make_part_masks, parse_part_spec, validate_parts


class PartSpecTests(unittest.TestCase):
    def test_parts_parse_with_kind_axis_range_and_description(self):
        self.assertEqual(parse_part_spec("grip=grip: leather-wrapped grip"),
                         {"name": "grip", "kind": "grip", "text": "leather-wrapped grip"})
        self.assertEqual(parse_part_spec("trigger=hinge:x:-20..0: curved trigger inside the guard"),
                         {"name": "trigger", "kind": "hinge", "axis": "x", "min": -20.0, "max": 0.0,
                          "text": "curved trigger inside the guard"})
        self.assertEqual(parse_part_spec("slide=slide:z:-0.03..0")["text"], "slide")  # the name stands in
        for bad in ("trigger=lever:x:0..1", "trigger=hinge:w:0..1", "trigger=hinge:x:5..1", "trigger=hinge:x",
                    "Trigger=grip", "=grip", "trigger=hinge:x:a..b"):
            with self.subTest(spec=bad), self.assertRaisesRegex(ValueError, "--part must be"):
                parse_part_spec(bad)
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_parts([parse_part_spec("a=grip"), parse_part_spec("a=hinge:x:0..1")])
        with self.assertRaisesRegex(ValueError, "one grip"):
            validate_parts([parse_part_spec("a=grip"), parse_part_spec("b=grip")])

    def test_a_part_the_concept_does_not_show_stops_before_mesh_inference(self):
        parts = [parse_part_spec("grip=grip"), parse_part_spec("trigger=hinge:x:-20..0")]
        check_part_masks({"parts": {"grip": {"share": 0.2}, "trigger": {"share": 0.004}}}, parts)
        for report in ({"parts": {"grip": {"share": 0.2}, "trigger": {"box": None}}},
                       {"parts": {"grip": {"share": 0.2}, "trigger": {"share": 0.0002}}}):
            with self.assertRaises(StageFailure) as caught:
                check_part_masks(report, parts)
            self.assertEqual((caught.exception.category, caught.exception.operation),
                             ("configuration", "part_mask_preflight"))
            self.assertIn("trigger", str(caught.exception))


class PartMaskRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        Image.new("RGBA", (40, 20), (90, 90, 90, 255)).save(self.root / "cutout.png")
        self.parts = [parse_part_spec("grip=grip: the grip")]

    def tearDown(self):
        self.temp.cleanup()

    def test_masks_need_a_configured_python(self):
        with self.assertRaises(StageFailure) as caught:
            make_part_masks({"asset_pipeline": {"tools": {}}}, self.root / "cutout.png", self.parts, self.root / "out")
        self.assertEqual(caught.exception.operation, "part_mask_preflight")

    def test_a_remote_run_cleans_up_only_the_directory_it_made(self):
        out = self.root / "out"
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            if command[-3:-1] == ["mktemp", "-d"]:
                # A login banner prints first; only mktemp's own line is a path to remove later.
                return subprocess.CompletedProcess(command, 0, "Welcome to the H100\n/tmp/slopforge-parts-Ab12\n", "")
            if command[0] == "scp" and command[-1] == str(out):
                out.mkdir(parents=True, exist_ok=True)
                Image.new("L", (40, 20), 255).save(out / "grip.png")
                (out / "masks.json").write_text(json.dumps({"parts": {"grip": {"share": 1.0}}}))
            return subprocess.CompletedProcess(command, 0, "", "")
        config = {"asset_pipeline": {"tools": {"parts_host": "gpu", "parts_python": "/opt/parts/bin/python"}}}
        with patch("slopforge.parts.subprocess.run", side_effect=run):
            report = make_part_masks(config, self.root / "cutout.png", self.parts, out)
        self.assertEqual(report["parts"]["grip"]["share"], 1.0)
        self.assertTrue((out / "parts_overlay.png").is_file())
        self.assertEqual(calls[-1], ["ssh", "-o", "BatchMode=yes", "gpu", "rm", "-rf", "--", "/tmp/slopforge-parts-Ab12"])

        def bad(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "/home/eoin\n", "")
        calls.clear()
        with patch("slopforge.parts.subprocess.run", side_effect=bad), self.assertRaisesRegex(RuntimeError, "work directory"):
            make_part_masks(config, self.root / "cutout.png", self.parts, out)
        self.assertFalse([command for command in calls if "rm" in command])  # never rm -rf an unchecked path


if __name__ == "__main__":
    unittest.main()
