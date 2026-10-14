"""Tests for structured worker failure transport across the ComfyUI backend boundary.

Focuses on generate_image() and generate_model() wrapper behavior:
- Valid structured reports raise StageFailure with preserved structured fields
- Malformed/missing reports raise unknown category StageFailure
- Successful subprocess results are unchanged
- Failed subprocess cannot be silently treated as success
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from slopforge.backends.comfyui import (
    ComfyUIClient,
    ComfyUIError,
)
from slopforge.backends.comfyui import (
    generate_image,
    generate_model,
)
from slopforge.backends.comfyui import (
    ComfyUIError,
    _FAILURE_REPORT_VERSION,
    _classify_failure_report,
    _write_failure_report,
    _build_failure_from_report,
)
from slopforge.failures import StageFailure


class BuildFailureFromReportTests(unittest.TestCase):
    """Tests for _build_failure_from_report directly."""

    def test_missing_report_raises_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = str(Path(tmp) / "missing.json")
            failed = _build_failure_from_report(report_path, default_category="test_category")
        self.assertIsInstance(failed, StageFailure)
        self.assertEqual(failed.category, "test_category")
        self.assertEqual(failed.message, "failure report missing or unreadable")

    def test_unparseable_report_raises_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "bad.json"
            report_path.write_text("not valid json {")
            failed = _build_failure_from_report(report_path)
        self.assertIsInstance(failed, StageFailure)
        self.assertEqual(failed.category, "unknown")

    def test_valid_report_preserves_structured_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "valid.json"
            report_data = {
                "version": _FAILURE_REPORT_VERSION,
                "category": "inference",
                "operation": "upload",
                "message": "upload failed",
                "exception_type": "ComfyUIError",
                "evidence": {"image": "test.png", "path": Path(tmp).name},
            }
            report_path.write_text(json.dumps(report_data) + "\n")
            failed = _build_failure_from_report(report_path)
        self.assertIsInstance(failed, StageFailure)
        self.assertEqual(failed.category, "inference")
        self.assertEqual(failed.operation, "upload")
        self.assertEqual(failed.message, "upload failed")
        self.assertEqual(failed.evidence, report_data["evidence"])

    def test_invalid_classification_report_raises_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "bad_class.json"
            report_data = {
                "version": _FAILURE_REPORT_VERSION,
                "category": "unrecognised_category",
                "operation": "test",
                "message": "test",
                "exception_type": "ComfyUIError",
            }
            report_path.write_text(json.dumps(report_data) + "\n")
            failed = _build_failure_from_report(report_path)
        self.assertIsInstance(failed, StageFailure)
        self.assertEqual(failed.category, "unknown")  # rejected → unknown

    def test_none_report_path_raises_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = str(Path(tmp) / "missing.json")
            failed = _build_failure_from_report(report_path, default_category="custom")
        self.assertIsInstance(failed, StageFailure)
        self.assertEqual(failed.category, "custom")


class WrapperBoundaryTests(unittest.TestCase):
    """Test generate_image() and generate_model() wrapper behavior."""

    def _make_image_config(self):
        return {"asset_pipeline": {
            "tools": {"asset_python": sys.executable},
            "workflows": {"image": "base.json"},
            "selected_quality_tier": "normal",
            "quality_settings": {},
            "selected_compute_profile": "default",
            "comfy_url": "http://127.0.0.1:8188",
        }}

    def test_success_preserves_result(self):
        """Successful subprocess returns unchanged result."""
        with patch('slopforge.backends.comfyui.subprocess.run') as mock:
            mock_result = Mock()
            mock_result.returncode = 0
            mock.return_value = mock_result

            with patch('slopforge.backends.comfyui.resolve_workflow') as rw:
                with patch('slopforge.backends.comfyui.tool_root') as tr:
                    with patch('slopforge.backends.comfyui.workflow_node_inputs', lambda *a: {}):
                        result = generate_image(
                            "/tmp", self._make_image_config(), "base.json",
                            "test", "/tmp/out", "p", 1, "/tmp/meta")
        self.assertIs(result, mock_result)

    def test_failure_raises_stage_failure_from_valid_report(self):
        """Failed subprocess raises StageFailure from valid structured report."""
        report_data = {
            "version": _FAILURE_REPORT_VERSION,
            "category": "inference",
            "operation": "upload",
            "message": "upload failed",
            "exception_type": "ComfyUIError",
            "evidence": {"image": "test.png"},
        }

        with patch('slopforge.backends.comfyui.subprocess.run') as mock:
            mock_result = Mock()
            mock_result.returncode = 1
            mock.return_value = mock_result

            # Store report_path from the command and write the valid report
            captured_report_path = [None]
            captured_dirs = []
            def capture_and_write(cmd, **kw):
                for i, arg in enumerate(cmd):
                    if arg == "--failure-report" and i + 1 < len(cmd):
                        captured_report_path[0] = cmd[i + 1]
                        break
                return mock_result
            mock.side_effect = capture_and_write

            config = self._make_image_config()
            with tempfile.TemporaryDirectory() as tmp:
                dest_dir = Path(tmp) / "output"
                dest_dir.mkdir()
                dest = dest_dir / "out.png"

                captured_report_path = [None]
                def capture(cmd, **kw):
                    for i, arg in enumerate(cmd):
                        if arg == "--failure-report" and i + 1 < len(cmd):
                            captured_report_path[0] = cmd[i + 1]
                            break

                    # Write a VALID report file (simulate worker writing it)
                    if captured_report_path[0]:
                        rp = Path(captured_report_path[0])
                        rp.parent.mkdir(parents=True, exist_ok=True)
                        rp.write_text(json.dumps(report_data) + "\n")

                    return mock_result

                mock.side_effect = capture

                with patch('slopforge.backends.comfyui.resolve_workflow'):
                    with patch('slopforge.backends.comfyui.tool_root'):
                        with patch('slopforge.backends.comfyui.workflow_node_inputs', lambda *a: {}):
                            with self.assertRaises(StageFailure) as cm:
                                generate_image(
                                    "/tmp", config, "base.json",
                                    "test", str(dest), "p", 1,
                                    "/tmp/meta")

            failed = cm.exception
            self.assertIsInstance(failed, StageFailure)
            self.assertEqual(failed.category, "inference")

    def test_failure_raises_unknown_on_missing_report(self):
        """Failed subprocess with missing report raises unknown category."""
        with patch('slopforge.backends.comfyui.subprocess.run') as mock:
            mock_result = Mock()
            mock_result.returncode = 1
            mock.return_value = mock_result

            captured_report_path = [None]
            def capture_cmd(cmd, **kw):
                for i, arg in enumerate(cmd):
                    if arg == "--failure-report" and i + 1 < len(cmd):
                        captured_report_path[0] = cmd[i + 1]
                        break
                return mock_result
            mock.side_effect = capture_cmd

            # Create a report directory but don't write a report
            with tempfile.TemporaryDirectory() as tmp:
                dest_dir = Path(tmp) / "output"
                dest_dir.mkdir()
                dest = dest_dir / "out.png"

                # Ensure no report file exists from previous tests
                report_path = captured_report_path[0]
                if report_path:
                    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
                    # Don't write any report file

                config = self._make_image_config()
                with patch('slopforge.backends.comfyui.resolve_workflow') as rw:
                    with patch('slopforge.backends.comfyui.tool_root') as tr:
                        with patch('slopforge.backends.comfyui.workflow_node_inputs', lambda *a: {}):
                            with self.assertRaises(StageFailure) as cm:
                                generate_image(
                                    "/tmp", config, "base.json",
                                    "test", str(dest), "p", 1,
                                    "/tmp/meta")

            failed = cm.exception
            self.assertIsInstance(failed, StageFailure)
            self.assertEqual(failed.category, "environment")

    def test_success_is_not_treated_as_failure(self):
        """A successful subprocess return cannot be silently treated as success
        — i.e. it does NOT raise."""
        with patch('slopforge.backends.comfyui.subprocess.run') as mock:
            mock_result = Mock()
            mock_result.returncode = 0
            mock.return_value = mock_result

            config = self._make_image_config()
            with patch('slopforge.backends.comfyui.resolve_workflow') as rw:
                with patch('slopforge.backends.comfyui.tool_root') as tr:
                    with patch('slopforge.backends.comfyui.workflow_node_inputs', lambda *a: {}):
                        result = generate_image(
                            "/tmp", config, "base.json",
                            "test", "/tmp/out", "p", 1, "/tmp/meta")
        # No exception raised — success preserved
        self.assertIsInstance(result, Mock)
        self.assertEqual(result.returncode, 0)


class ComfyUIClientCategoryTests(unittest.TestCase):
    """Verify client boundaries tag errors with correct categories."""

    def test_http_connection_error_tags_environment(self):
        """HTTP connection errors are tagged environment."""
        with patch("slopforge.backends.comfyui.urlopen") as mock_open:
            mock_open.side_effect = OSError("connection refused")
            client = ComfyUIClient("http://localhost:8188")
            with self.assertRaises(ComfyUIError) as cm:
                client.health()
            self.assertEqual(cm.exception.category, "environment")

    def test_validate_workflow_tags_configuration(self):
        """validate_workflow errors are tagged configuration."""
        client = ComfyUIClient("http://localhost:8188")
        with self.assertRaises(ComfyUIError) as cm:
            client.validate_workflow({})
        self.assertEqual(cm.exception.category, "configuration")

    def test_queue_workflow_rejection_tags_configuration(self):
        """queue_workflow rejection errors are tagged configuration."""
        client = ComfyUIClient("http://localhost:8188")
        with patch.object(client, 'json') as mock_json:
            mock_json.return_value = {"error": "bad", "prompt_id": None}
            with self.assertRaises(ComfyUIError) as cm:
                client.queue_workflow({})
            self.assertEqual(cm.exception.category, "configuration")

    def test_wait_for_completion_timeout_tags_inference(self):
        """wait_for_completion timeout errors are tagged inference."""
        client = ComfyUIClient("http://localhost:8188")
        client.history = lambda pid: None  # Never returns entry
        import time as _time
        start = _time.monotonic()
        with self.assertRaises(ComfyUIError) as cm:
            client.wait_for_completion("pid", timeout=0.1, poll_interval=0.05)
        elapsed = _time.monotonic() - start
        self.assertLessEqual(elapsed, 0.3)  # Should timeout quickly
        self.assertEqual(cm.exception.category, "inference")


if __name__ == "__main__":
    unittest.main()
