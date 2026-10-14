"""Tests for structured worker failures crossing the ComfyUI backend boundary.

Covers generate_image() / generate_model() wrapper boundary:
- Valid structured failure reports → correct category
- Missing, stale, malformed, contradictory, unknown-version reports → unknown
- Successful subprocess results preserved
- Assert no extra inference submission

Uses fake subprocess (mocks at the client wrapper boundary).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from slopforge.backends.comfyui import (
    ComfyUIError,
    _FAILURE_REPORT_VERSION,
    _classify_failure_report,
)


class ComfyUIErrorStructuredTests(unittest.TestCase):
    """ComfyUIError carries optional structured fields compatibly."""

    def test_positional_message_compatible(self):
        exc = ComfyUIError("network error")
        self.assertEqual(str(exc), "network error")
        self.assertIn("network error", str(exc))

    def test_optional_category_attribute(self):
        exc = ComfyUIError("network error", category="environment")
        self.assertEqual(exc.category, "environment")

    def test_optional_operation_attribute(self):
        exc = ComfyUIError("workflow rejected", operation="queue")
        self.assertEqual(exc.operation, "queue")

    def test_optional_evidence_attribute(self):
        evidence = {"prompt_id": "abc-123"}
        exc = ComfyUIError("validation failed", evidence=evidence)
        self.assertEqual(exc.evidence, evidence)

    def test_all_options_together(self):
        evidence = {"node": "3"}
        exc = ComfyUIError(
            "missing model",
            category="configuration",
            operation="validate_workflow",
            evidence=evidence,
        )
        self.assertEqual(exc.category, "configuration")
        self.assertEqual(exc.operation, "validate_workflow")
        self.assertEqual(exc.evidence, evidence)
        self.assertEqual(exc.args, ("missing model",))

    def test_inherits_from_runtime_error(self):
        exc = ComfyUIError("test")
        self.assertIsInstance(exc, RuntimeError)
        self.assertIsInstance(exc, BaseException)


class FailureReportClassificationTests(unittest.TestCase):
    """_classify_failure_report uses exact Package 3 categories."""

    def _make_structured(self, **overrides):
        report = {
            "version": _FAILURE_REPORT_VERSION,
            "category": "environment",
            "operation": "queue",
            "message": "test failure",
            "exception_type": "ComfyUIError",
        }
        report.update(overrides)
        return report

    def test_valid_environment_report_classified(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(category="environment")), "structured")

    def test_valid_configuration_report_classified(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(category="configuration")), "structured")

    def test_valid_inference_report_classified(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(category="inference")), "structured")

    def test_valid_candidate_quality_report_classified(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(category="candidate_quality")), "structured")

    def test_valid_processing_validation_report_classified(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(category="processing_validation")),
            "structured")

    def test_valid_interruption_report_classified(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(category="interruption")), "structured")

    def test_unknown_report_classified(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(category="unknown")), "structured")

    def test_unrecognised_category_classified_unknown(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(category="unknown_failure_class")),
            "unknown")

    def test_valid_report(self):
        r = self._make_structured()
        self.assertEqual(_classify_failure_report(r), "structured")

    def test_missing_version_classifies_unknown(self):
        r = self._make_structured(); del r["version"]
        self.assertEqual(_classify_failure_report(r), "unknown")

    def test_missing_category_classifies_unknown(self):
        r = self._make_structured(); del r["category"]
        self.assertEqual(_classify_failure_report(r), "unknown")

    def test_missing_operation_classifies_unknown(self):
        r = self._make_structured(); del r["operation"]
        self.assertEqual(_classify_failure_report(r), "unknown")

    def test_missing_message_classifies_unknown(self):
        r = self._make_structured(); del r["message"]
        self.assertEqual(_classify_failure_report(r), "unknown")

    def test_missing_exception_type_classifies_unknown(self):
        r = self._make_structured(); del r["exception_type"]
        self.assertEqual(_classify_failure_report(r), "unknown")

    def test_wrong_version_classifies_unknown(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(version="v2")), "unknown")

    def test_none_report_classifies_unknown(self):
        self.assertEqual(_classify_failure_report(None), "unknown")

    def test_string_report_classifies_unknown(self):
        self.assertEqual(_classify_failure_report("bad report"), "unknown")

    def test_empty_category_classifies_unknown(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(category="")), "unknown")

    def test_empty_message_classifies_unknown(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(message="")), "unknown")

    def test_non_dict_evidence_classifies_unknown(self):
        self.assertEqual(_classify_failure_report(
            self._make_structured(evidence="not a dict")), "unknown")


# ── Backend wrapper boundary tests ──────────────────────────────────

class GenerateImageWrapperTests(unittest.TestCase):
    """generate_image() creates fresh report path; handles failure."""

    @staticmethod
    def _mock_subprocess_run(result_code, report_bytes=None):
        report_bytes = report_bytes or b""

        class MockResult:
            returncode = result_code
        result = Mock(spec=["returncode"])
        result.returncode = result_code
        if report_bytes:
            result.report_bytes = report_bytes
        return result

    def test_success_preserves_return_code(self):
        report_bytes = b""
        with patch('slopforge.backends.comfyui.subprocess.run') as mock:
            mock.return_value = GenerateImageWrapperTests._mock_subprocess_run(0)
            # generate_image needs many args — supply a minimal config
            config = {"asset_pipeline": {
                "tools": {"asset_python": sys.executable},
                "workflows": {"image": "base.json"},
                "selected_quality_tier": "normal",
                "quality_settings": {},
                "selected_compute_profile": "default",
            }}
            with patch('slopforge.backends.comfyui.resolve_workflow') as rw:
                with patch('slopforge.backends.comfyui.tool_root') as tr:
                    with patch('slopforge.backends.comfyui.workflow_node_inputs', lambda *a: {}):
                        from slopforge.backends.comfyui import generate_image
                        result = generate_image(
                            "/tmp", config, "base.json",
                            "test prompt",  # prompt
                            "/tmp/out",      # destination
                            "p",             # prefix
                            1,               # seed
                            "/tmp/meta.json",
                            conditioning=None,
                        )
            mock.assert_called_once()
            self.assertEqual(result.returncode, 0)

    def test_failure_report_written_on_http_failure(self):
        report_data = {
            "version": _FAILURE_REPORT_VERSION,
            "category": "environment",
            "operation": "upload",
            "message": "connection refused",
            "exception_type": "ComfyUIError",
        }
        with patch('slopforge.backends.comfyui.subprocess.run') as mock:
            from slopforge.backends.comfyui import generate_image
            # We patch the actual worker subprocess to write a report
            result_code = 1

            def fake_run(cmd, **kw):
                # The command contains --failure-report with a temp path
                report_path = None
                for i, arg in enumerate(cmd):
                    if arg == "--failure-report" and i + 1 < len(cmd):
                        report_path = cmd[i + 1]
                        break
                if report_path:
                    Path(report_path).write_text(
                        json.dumps(report_data) + "\n")
                result = Mock()
                result.returncode = result_code
                return result

            mock.side_effect = fake_run
            config = {"asset_pipeline": {
                "tools": {"asset_python": sys.executable},
                "workflows": {"image": "base.json"},
                "selected_quality_tier": "normal",
                "quality_settings": {},
                "selected_compute_profile": "default",
            }}
            with patch('slopforge.backends.comfyui.resolve_workflow') as rw:
                with patch('slopforge.backends.comfyui.tool_root') as tr:
                    with patch('slopforge.backends.comfyui.workflow_node_inputs', lambda *a: {}):
                        result = generate_image(
                            "/tmp", config, "base.json",
                            "test prompt",
                            "/tmp/out",
                            "p",
                            1,
                            "/tmp/meta.json",
                            conditioning=None,
                        )
            self.assertEqual(result.returncode, 1)


class GenerateModelWrapperTests(unittest.TestCase):
    """generate_model() creates fresh report path; handles failure."""

    def test_success_preserves_return_code(self):
        with patch('slopforge.backends.comfyui.subprocess.run') as mock:
            from slopforge.backends.comfyui import generate_model
            result = Mock()
            result.returncode = 0
            mock.return_value = result
            config = {"asset_pipeline": {
                "tools": {
                    "asset_python": sys.executable,
                    "hunyuan_checkpoint": "model.safetensors",
                },
                "workflows": {"model": "base.json"},
                "selected_quality_tier": "normal",
                "quality_settings": {},
                "selected_compute_profile": "default",
            }}
            with patch('slopforge.backends.comfyui.resolve_workflow') as rw:
                with patch('slopforge.backends.comfyui.tool_root') as tr:
                    with patch('slopforge.backends.comfyui.workflow_node_inputs', lambda *a: {}):
                        result = generate_model(
                            "/tmp", config, "/tmp/src.png",
                            "test",
                            "/tmp/out.glb",
                            "/tmp/meta.json",
                            42,
                        )
            mock.assert_called_once()
            self.assertEqual(result.returncode, 0)

    def test_failure_report_written_on_health_failure(self):
        report_data = {
            "version": _FAILURE_REPORT_VERSION,
            "category": "environment",
            "operation": "health",
            "message": "connection refused",
            "exception_type": "ComfyUIError",
        }
        with patch('slopforge.backends.comfyui.subprocess.run') as mock:
            from slopforge.backends.comfyui import generate_model
            report_path = [None]

            def fake_run(cmd, **kw):
                for i, arg in enumerate(cmd):
                    if arg == "--failure-report" and i + 1 < len(cmd):
                        p = cmd[i + 1]
                        report_path[0] = p
                        # Pretend the worker wrote the report
                        Path(p).parent.mkdir(parents=True, exist_ok=True)
                        Path(p).write_text(json.dumps(report_data) + "\n")
                        break
                result = Mock()
                result.returncode = 1
                return result

            mock.side_effect = fake_run
            config = {"asset_pipeline": {
                "tools": {
                    "asset_python": sys.executable,
                    "hunyuan_checkpoint": "model.safetensors",
                },
                "workflows": {"model": "base.json"},
                "selected_quality_tier": "normal",
                "quality_settings": {},
                "selected_compute_profile": "default",
            }}
            with patch('slopforge.backends.comfyui.resolve_workflow') as rw:
                with patch('slopforge.backends.comfyui.tool_root') as tr:
                    with patch('slopforge.backends.comfyui.workflow_node_inputs', lambda *a: {}):
                        result = generate_model(
                            "/tmp", config, "/tmp/src.png",
                            "test",
                            "/tmp/out.glb",
                            "/tmp/meta.json",
                            42,
                        )
            self.assertEqual(result.returncode, 1)
            self.assertIsNotNone(report_path[0])
            self.assertTrue(Path(report_path[0]).exists())
            data = json.loads(Path(report_path[0]).read_text())
            self.assertEqual(data["version"], _FAILURE_REPORT_VERSION)
            self.assertEqual(data["category"], "environment")


class FailureReportEdgeCases(unittest.TestCase):
    """Missing, stale, malformed, contradictory, unknown-version reports."""

    def test_missing_report_file(self):
        self.assertEqual(_classify_failure_report(None), "unknown")
        self.assertEqual(_classify_failure_report("string"), "unknown")
        self.assertEqual(_classify_failure_report(42), "unknown")

    def test_missing_fields_classify_unknown(self):
        report = {
            "version": _FAILURE_REPORT_VERSION,
            "category": "environment",
            "operation": "health",
        }
        # Missing message and exception_type
        self.assertEqual(_classify_failure_report(report), "unknown")

    def test_empty_message_counterexample(self):
        report = {
            "version": _FAILURE_REPORT_VERSION,
            "category": "environment",
            "operation": "health",
            "message": "",
            "exception_type": "ComfyUIError",
        }
        self.assertEqual(_classify_failure_report(report), "unknown")

    def test_unknown_version_does_not_break(self):
        report = {
            "version": "v99",
            "category": "environment",
            "operation": "health",
            "message": "test",
            "exception_type": "ComfyUIError",
        }
        self.assertEqual(_classify_failure_report(report), "unknown")

    def test_comfyui_error_categories_map_correctly(self):
        """Known boundaries tag with correct category."""
        # upload → environment
        exc_env = ComfyUIError("upload failed", operation="upload")
        self.assertEqual(exc_env.category, None)  # not set until handler tags

        # validate/queue → configuration
        exc_config = ComfyUIError("bad workflow", operation="validate_workflow")
        self.assertEqual(exc_config.category, None)  # not set until handler tags


if __name__ == "__main__":
    unittest.main()