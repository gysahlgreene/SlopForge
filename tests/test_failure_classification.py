"""Table-driven tests for the shared failure vocabulary and candidate rejection.

Cover every named category, edge-case counters, JSON safety, and the full
candidate-quality rejection predicate (valid, mixed, legacy, and invalid).

Uses real validate_model_outputs output as test fixtures (Blocker 3).
"""

import json
import math
import unittest

from slopforge.validation import validate_model_outputs
from slopforge.failures import (
    StageFailure,
    candidate_quality_rejection,
    failure_record,
    should_retry,
)

# ── Fixtures generated from the real validator ──────────────────────────

def _make_valid_report():
    """Generate a base report via the real validator."""
    return validate_model_outputs(
        {},
        inspection={
            "status": "passed",
            "errors": [],
            "warnings": [],
            "measured": {
                "mesh_objects": 1, "vertex_count": 24,
                "face_count": 8, "dimensions": [1, 1, 1],
                "uv_layers": 1, "material_count": 1,
                "image_texture_count": 4,
                "component_count": 60, "nonmanifold_edge_count": 5,
                "transforms_applied": True,
                "missing_textures": [],
            },
        },
        max_components=50,
        max_nonmanifold_edges=None,
        max_boundary_edges=None,
    )

def _quality_report(component_count=60, max_components=50):
    """A complete valid topology-only rejection report."""
    report = validate_model_outputs(
        {},
        inspection={
            "status": "passed", "errors": [], "warnings": [],
            "measured": {
                "mesh_objects": 1, "vertex_count": 24,
                "face_count": 8, "dimensions": [1, 1, 1],
                "uv_layers": 1, "material_count": 1,
                "image_texture_count": 4,
                "component_count": component_count,
                "nonmanifold_edge_count": 5,
                "transforms_applied": True,
                "missing_textures": [],
            },
        },
        max_components=max_components,
        max_nonmanifold_edges=None,
        max_boundary_edges=None,
    )
    return report


class TestFailureRecord(unittest.TestCase):
    """failure_record produces correct JSON-safe records for every path."""

    def _roundtrip(self, record):
        return json.loads(json.dumps(record))

    def test_stage_failure_category_fields(self):
        sf = StageFailure("configuration", "missing workflow",
                          operation="preflight", remedy="check workflow path")
        rec = failure_record(sf, stage="mesh_workflow_execution",
                             attempt=1, operation="preflight")
        self.assertEqual(rec["category"], "configuration")

    def test_empty_message_is_valid(self):
        rec = failure_record(RuntimeError(""),
                             stage="test", attempt=1, operation="test")
        self.assertEqual(rec["category"], "unknown")
        self.assertNotEqual(rec["message"], "")

    def test_unknown_exception_defaults_unknown_category(self):
        rec = failure_record(ValueError("bang"),
                             stage="test", attempt=None, operation="test")
        self.assertEqual(rec["category"], "unknown")

    def test_keyboard_interrupt_classifies_interruption(self):
        rec = failure_record(KeyboardInterrupt("stop"),
                             stage="test", attempt=1, operation="test")
        self.assertEqual(rec["category"], "interruption")

    def test_json_roundtrip_preserves_all_fields(self):
        sf = StageFailure("inference", "timeout",
                          operation="submit", remedy="retry prompt",
                          stage="mesh_workflow_execution", stage_id="abc-123",
                          evidence={"prompt_id": "abc-123"})
        rec = failure_record(sf, stage="mesh_workflow_execution",
                             attempt=1, operation="submit", stage_id="abc-123")
        loaded = self._roundtrip(rec)
        self.assertEqual(loaded["stage_id"], "abc-123")
        self.assertEqual(loaded["evidence"]["prompt_id"], "abc-123")

    def test_worker_leaf_stage_precedence_over_parent(self):
        sf = StageFailure("processing_validation", "bad image",
                          operation="validate_image", remedy="fix image",
                          stage="mesh_workflow_execution",
                          stage_id="leaf-id")
        rec = failure_record(sf, stage="mesh_generation",
                             attempt=1, operation="worker", stage_id="leaf-id")
        self.assertEqual(rec["stage_id"], "leaf-id")
        self.assertEqual(rec["stage"], "mesh_workflow_execution")

    def test_candidate_quality_record_carries_validation_evidence(self):
        rec = failure_record(StageFailure("candidate_quality", "topology below threshold",
                        operation="mesh_inspection", remedy="try next seed",
                        evidence={"validation": {"status": "failed"}}),
                        stage="mesh_workflow_execution", attempt=1, operation="mesh")
        self.assertIn("validation", rec["evidence"])
        self.assertEqual(rec["evidence"]["validation"]["status"], "failed")

    def test_retry_counter_uses_limit_not_status(self):
        sf = StageFailure("candidate_quality", "too many components",
                          operation="inspect", remedy="next seed",
                          evidence={"validation": _quality_report(60, 50)})
        rec = failure_record(sf, stage="mesh_generation",
                             attempt=5, operation="inspect")
        # Attempt 1 of 3 — retryable
        self.assertTrue(should_retry(rec, used=1, limit=3))
        # At budget
        self.assertFalse(should_retry(rec, used=3, limit=3))

    # ── Blocker 1: untyped path preserves stage name ──────────────────────

    def test_untyped_runtime_error_preserves_stage_name(self):
        """A RuntimeError with a distinct stage_id must not store stage_id as name."""
        rec = failure_record(RuntimeError("worker crashed"),
                             stage="mesh_workflow_execution",
                             stage_id="parent-id",
                             attempt=1, operation="worker")
        self.assertEqual(rec["stage"], "mesh_workflow_execution")
        self.assertEqual(rec["stage_id"], "parent-id")

    def test_untyped_exception_no_stage_id(self):
        rec = failure_record(ValueError("unhandled"),
                             stage="concept_generation",
                             attempt=None, operation="worker")
        self.assertEqual(rec["stage"], "concept_generation")
        self.assertIsNone(rec["stage_id"])

    def test_leaf_omitted_uses_parent(self):
        sf = StageFailure("configuration", "missing workflow",
                          operation="preflight", remedy="check",
                          stage="mesh_workflow_execution")
        rec = failure_record(sf, stage="mesh_workflow_execution",
                             attempt=None, operation="preflight",
                             stage_id="parent-id")
        self.assertEqual(rec["stage"], "mesh_workflow_execution")
        self.assertEqual(rec["stage_id"], "parent-id")

    def test_no_explicit_values(self):
        sf = StageFailure("environment", "no blender",
                          operation="verify", remedy="install")
        rec = failure_record(sf, stage="mesh_generation",
                             attempt=1, operation="verify")
        self.assertEqual(rec["stage"], "mesh_generation")
        self.assertIsNone(rec["stage_id"])

    def test_leaf_name_remains_name(self):
        sf = StageFailure("inference", "timeout",
                          operation="submit", remedy="retry",
                          stage="mesh_workflow_execution",
                          stage_id="uuid-abc-123")
        rec = failure_record(sf, stage="other",
                             attempt=2, operation="submit",
                             stage_id="uuid-def-456")
        self.assertEqual(rec["stage"], "mesh_workflow_execution")
        self.assertEqual(rec["stage_id"], "uuid-abc-123")


class TestFailureRecordRetryable(unittest.TestCase):
    """Blocker 2: retryable derived from validated evidence."""

    def test_unproven_candidate_quality_stores_retryable_false(self):
        sf = StageFailure("candidate_quality", "unproven",
                          operation="inspect", remedy="inspect")
        rec = failure_record(sf, stage="mesh_workflow_execution",
                             attempt=1, operation="worker")
        self.assertFalse(rec["retryable"])

    def test_retryable_incomplete_record_blocks(self):
        incomplete = {"category": "candidate_quality",
                      "evidence": {"validation": _quality_report(60, 50)}}
        self.assertFalse(should_retry(incomplete, used=1, limit=3))

    def test_retryable_missing_required_fields_blocks(self):
        partial = {"category": "candidate_quality", "stage": "mesh",
                   "attempt": 1, "operation": "worker"}
        self.assertFalse(should_retry(partial, used=1, limit=3))

    def test_retryable_tampered_retryable_flag_blocks(self):
        tampered = {"category": "candidate_quality", "stage": "mesh",
                    "attempt": 1, "operation": "worker",
                    "retryable": True,
                    "evidence": {"validation": {
                        "status": "passed", "errors": [],
                        "failure_codes": [],
                    }}}
        self.assertFalse(should_retry(tampered, used=1, limit=3))

    def test_valid_quality_retry_includes_evidence(self):
        sf = StageFailure("candidate_quality", "too many components",
                          operation="inspect", remedy="next",
                          evidence={"validation": _quality_report(60, 50)})
        rec = failure_record(sf, stage="mesh", attempt=1, operation="inspect")
        self.assertTrue(rec["retryable"])
        self.assertTrue(should_retry(rec, used=1, limit=3))


class TestShouldRetry(unittest.TestCase):
    """should_retry enforces the retry policy strictly."""

    def test_candidate_quality_at_exhaustion(self):
        rec = failure_record(_quality_report(60, 50),
                             stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=3, limit=3))
        self.assertFalse(should_retry(rec, used=5, limit=3))

    def test_configuration_category_never_retries(self):
        rec = failure_record(StageFailure("configuration", "bad config",
                        operation="preflight", remedy="fix"),
                        stage="preflight", attempt=1, operation="preflight")
        self.assertFalse(should_retry(rec, used=0, limit=3))

    def test_environment_category_never_retries(self):
        rec = failure_record(StageFailure("environment", "missing blender",
                        operation="verify", remedy="install blender"),
                        stage="env_check", attempt=1, operation="verify")
        self.assertFalse(should_retry(rec, used=0, limit=3))

    def test_inference_category_never_retries(self):
        rec = failure_record(StageFailure("inference", "network error",
                        operation="submit", remedy="fix network"),
                        stage="mesh_submission", attempt=1, operation="submit")
        self.assertFalse(should_retry(rec, used=0, limit=3))

    def test_processing_validation_never_retries(self):
        rec = failure_record(StageFailure("processing_validation", "invalid mesh",
                        operation="process", remedy="fix"),
                        stage="mesh_prep", attempt=1, operation="process")
        self.assertFalse(should_retry(rec, used=0, limit=3))

    def test_interruption_never_retries(self):
        rec = failure_record(StageFailure("interruption", "keyboard interrupt",
                        operation="worker", remedy="inspect"),
                        stage="mesh", attempt=1, operation="worker")
        self.assertFalse(should_retry(rec, used=0, limit=3))

    def test_unknown_never_retries(self):
        rec = failure_record(ValueError("crash"),
                            stage="mesh", attempt=1, operation="worker")
        self.assertFalse(should_retry(rec, used=0, limit=3))

    def test_invalid_record_types(self):
        self.assertFalse(should_retry("not a dict", used=1, limit=3))
        self.assertFalse(should_retry({"category": None}, used=1, limit=3))
        self.assertFalse(should_retry({"category": ""}, used=1, limit=3))

    # Invalid counters
    def test_zero_used_rejected(self):
        rec = failure_record(_quality_report(60, 50),
                             stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=0, limit=3))

    def test_negative_used_rejected(self):
        rec = failure_record(_quality_report(60, 50),
                             stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=-1, limit=3))

    def test_zero_limit_rejected(self):
        rec = failure_record(_quality_report(60, 50),
                             stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=1, limit=0))

    def test_negative_limit_rejected(self):
        rec = failure_record(_quality_report(60, 50),
                             stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=1, limit=-1))

    def test_bool_used_rejected(self):
        rec = failure_record(_quality_report(60, 50),
                             stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=True, limit=3))

    def test_bool_limit_rejected(self):
        rec = failure_record(_quality_report(60, 50),
                             stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=1, limit=True))

    def test_null_used_rejected(self):
        rec = failure_record(_quality_report(60, 50),
                             stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=None, limit=3))

    def test_null_limit_rejected(self):
        rec = failure_record(_quality_report(60, 50),
                             stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=1, limit=None))

    def test_no_evidence_does_not_retry(self):
        sf = StageFailure("candidate_quality", "topology fail",
                          operation="inspect", remedy="next")
        rec = failure_record(sf, stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=1, limit=3))

    def test_incomplete_evidence_does_not_retry(self):
        sf = StageFailure("candidate_quality", "topology fail",
                          operation="inspect", remedy="next",
                          evidence={"validation": {"status": "failed"}})
        rec = failure_record(sf, stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=1, limit=3))

    def test_mixed_evidence_does_not_retry(self):
        sf = StageFailure("candidate_quality", "topology fail",
                          operation="inspect", remedy="next",
                          evidence={"validation": {
                              "status": "passed", "errors": ["topology"],
                              "failure_codes": ["component_budget"],
                              "measured": {"component_count": 50, "face_count": 10},
                              "limits": {"max_components": 50,
                                         "max_nonmanifold_edges": None,
                                         "max_boundary_edges": None},
                          }})
        rec = failure_record(sf, stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=1, limit=3))

    def test_tampered_evidence_does_not_retry(self):
        sf = StageFailure("candidate_quality", "topology fail",
                          operation="inspect", remedy="next",
                          evidence={"validation": {
                              "status": "failed",
                              "errors": ["topology"],
                              "failure_codes": ["component_budget"],
                              "measured": {"component_count": "not a number",
                                           "face_count": 10},
                              "limits": {"max_components": 50,
                                         "max_nonmanifold_edges": None,
                                         "max_boundary_edges": None},
                          }})
        rec = failure_record(sf, stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=1, limit=3))

    def test_null_limits_does_not_retry(self):
        sf = StageFailure("candidate_quality", "topology fail",
                          operation="inspect", remedy="next",
                          evidence={"validation": {
                              "status": "failed",
                              "errors": ["topology"],
                              "failure_codes": ["component_budget"],
                              "measured": {"component_count": 60, "face_count": 10},
                              "limits": None,
                          }})
        rec = failure_record(sf, stage="mesh", attempt=1, operation="inspect")
        self.assertFalse(should_retry(rec, used=1, limit=3))


class TestCandidateQualityRejection(unittest.TestCase):
    """candidate_quality_rejection validates complete inspection reports."""

    def test_component_budget_exceeds_limit(self):
        report = _quality_report(60, 50)
        self.assertTrue(candidate_quality_rejection(report))

    def test_concept_silhouette_mismatch_is_a_retryable_quality_rejection(self):
        from slopforge.validation import apply_concept_silhouette

        def report(error):
            return apply_concept_silhouette(validate_model_outputs(
                {}, inspection={"status": "passed", "errors": [], "warnings": [],
                                "measured": {"mesh_objects": 1, "vertex_count": 24, "face_count": 8,
                                             "dimensions": [1, 1, 1], "uv_layers": 1, "material_count": 1,
                                             "image_texture_count": 4, "component_count": 1,
                                             "nonmanifold_edge_count": 0, "transforms_applied": True,
                                             "missing_textures": []}}), {"aspect_error": error})

        turned = report(0.69)  # a reconstruction that came out facing sideways
        self.assertEqual(turned["failure_codes"], ["concept_silhouette"])
        self.assertTrue(candidate_quality_rejection(turned))
        self.assertNotEqual(report(0.03)["status"], "failed")
        self.assertNotIn("concept_silhouette", report(0.03).get("failure_codes", []))

    def test_missing_declared_emitter_is_a_retryable_quality_rejection_only_below_its_minimum(self):
        from slopforge.validation import apply_declared_emitter
        missing = apply_declared_emitter(_quality_report(1, 50) | {"status": "passed", "errors": [],
                                                                  "failure_codes": []}, 0.0)
        self.assertEqual(missing["failure_codes"], ["emitter_missing"])
        self.assertTrue(candidate_quality_rejection(missing))
        found = json.loads(json.dumps(missing))
        found["measured"]["emissive_fraction"] = 0.0065  # a report whose code contradicts its measurement
        self.assertFalse(candidate_quality_rejection(found))

    def test_skipped_concept_projection_is_recorded_as_a_warning(self):
        from slopforge.validation import apply_concept_silhouette

        validation = apply_concept_silhouette(
            {"status": "passed", "errors": [], "warnings": []},
            {"status": "skipped", "aspect_error": 0.08,
             "reason": "model and concept proportions differ by 8.0% (> 5%)"})
        self.assertEqual(validation["status"], "passed_with_warnings")
        self.assertTrue(any("concept projection skipped" in item and "8.0%" in item
                            for item in validation["warnings"]), validation["warnings"])
        projected = apply_concept_silhouette({"status": "passed", "errors": [], "warnings": []},
                                             {"status": "projected", "aspect_error": 0.02})
        self.assertEqual((projected["status"], projected["warnings"]), ("passed", []))

    def test_nonmanifold_budget_exceeds_limit(self):
        report = validate_model_outputs(
            {},
            inspection={"status": "passed", "errors": [], "warnings": [],
                         "measured": {
                             "mesh_objects": 1, "vertex_count": 24,
                             "face_count": 8, "dimensions": [1, 1, 1],
                             "uv_layers": 1, "material_count": 1,
                             "image_texture_count": 4,
                             "component_count": 60,
                             "nonmanifold_edge_count": 20,
                             "transforms_applied": True,
                             "missing_textures": [],
                         }},
            max_components=None,
            max_nonmanifold_edges=10,
            max_boundary_edges=None,
        )
        self.assertTrue(candidate_quality_rejection(report))

    def test_boundary_budget_exceeds_limit(self):
        report = validate_model_outputs(
            {},
            inspection={"status": "passed", "errors": [], "warnings": [],
                         "measured": {
                             "mesh_objects": 1, "vertex_count": 24,
                             "face_count": 8, "dimensions": [1, 1, 1],
                             "uv_layers": 1, "material_count": 1,
                             "image_texture_count": 4,
                             "component_count": 60,
                             "nonmanifold_edge_count": 5,
                             "boundary_edge_count": 30,
                             "transforms_applied": True,
                             "missing_textures": [],
                         }},
            max_components=None,
            max_nonmanifold_edges=None,
            max_boundary_edges=20,
        )
        # Note: boundary_edge_count triggers boundary_budget error
        self.assertTrue(candidate_quality_rejection(report))

    def test_metric_exceeding_limit_is_rejected(self):
        """This is validated by _quality_report-based tests. Full chain."""
        report = _quality_report(60, 50)
        sf = StageFailure("candidate_quality",
                          "too many components",
                          operation="inspect", remedy="next",
                          evidence={"validation": report})
        rec = failure_record(sf, stage="mesh", attempt=1, operation="inspect")
        self.assertTrue(candidate_quality_rejection(rec["evidence"]["validation"]))
        self.assertTrue(should_retry(rec, used=1, limit=3))

    def test_mixed_quality_and_nonquality_failure_codes(self):
        v = {
            "status": "failed", "errors": ["topology", "missing_output"],
            "failure_codes": ["component_budget", "missing_output"],
        }
        self.assertFalse(candidate_quality_rejection(v))

    def test_mixed_quality_and_surface_failure_codes(self):
        v = {
            "status": "failed", "errors": ["topology", "surface problem"],
            "failure_codes": ["component_budget", "surface_invalid"],
        }
        self.assertFalse(candidate_quality_rejection(v))

    def test_legacy_code_fails_closed(self):
        v = {"status": "failed", "errors": ["old problem"],
             "failure_codes": ["legacy_code"]}
        self.assertFalse(candidate_quality_rejection(v))

    def test_missing_code_mismatched_length(self):
        v = {"status": "failed", "errors": ["topology", "missing_output"],
             "failure_codes": ["component_budget"]}
        self.assertFalse(candidate_quality_rejection(v))

    def test_missing_failure_codes_field(self):
        v = {"status": "failed", "errors": ["topology"]}
        self.assertFalse(candidate_quality_rejection(v))

    def test_empty_failure_codes_list(self):
        v = {"status": "failed", "errors": ["topology"], "failure_codes": []}
        self.assertFalse(candidate_quality_rejection(v))

    def test_invalid_face_values_reject(self):
        """face_count=False, -1, NaN should all reject."""
        base_report = _quality_report(60, 50)
        base_report = dict(base_report)
        base_report["measured"] = dict(base_report["measured"])
        for fv, label in [(False, "False"), (-1, "-1"), (float("nan"), "NaN"),
                           (float("inf"), "inf"), (None, "None")]:
            report = base_report
            r_copy = dict(report["measured"])
            r_copy["face_count"] = fv
            report = dict(base_report, measured=r_copy)
            self.assertFalse(candidate_quality_rejection(report),
                             msg=f"face_count={label} should reject")

    def test_missing_required_metrics_reject(self):
        base_report = _quality_report(60, 50)
        for metric in ("uv_layers", "material_count", "transforms_applied"):
            m_copy = dict(base_report["measured"])
            if metric in m_copy:
                m_copy[metric] = 0 if metric in ("component_count",) else None
                report = dict(base_report, measured=m_copy)
                self.assertFalse(candidate_quality_rejection(report),
                                 msg=f"modified {metric}")

    def test_overlarge_integer_handled(self):
        """10**1000 must not OverflowError."""
        # This should NOT raise, regardless of the rejection result
        m_copy = dict(_quality_report(50, 50)["measured"])
        m_copy["component_count"] = 10**1000
        # Don't check the result — only that it doesn't crash
        candidate_quality_rejection(
            dict(_quality_report(50, 50), measured=m_copy))

    def test_negative_metric_fails_closed(self):
        base = dict(_quality_report(-1, 50))
        base["measured"] = dict(base["measured"])
        base["measured"]["component_count"] = -1
        self.assertFalse(candidate_quality_rejection(base))

    def test_non_string_error_member_fails_closed(self):
        base = dict(_quality_report(60, 50))
        base["errors"] = [None]
        self.assertFalse(candidate_quality_rejection(base))

    def test_incomplete_report_fails_closed(self):
        v = {"status": "failed", "errors": ["topology"],
             "failure_codes": ["component_budget"],
             "measured": {"component_count": 60}}
        self.assertFalse(candidate_quality_rejection(v))

    def test_invalid_limits_container_fails_closed(self):
        base = dict(_quality_report(60, 50))
        base["limits"] = "not a dict"
        self.assertFalse(candidate_quality_rejection(base))

    def test_metric_below_limit_not_rejected(self):
        self.assertFalse(candidate_quality_rejection(_quality_report(40, 50)))

    def test_metric_equal_to_limit_not_rejected(self):
        self.assertFalse(candidate_quality_rejection(_quality_report(50, 50)))

    def test_boolean_metric_fails_closed(self):
        base = dict(_quality_report(60, 50))
        base["measured"] = dict(base.get("measured", {}))
        base["measured"]["component_count"] = True
        self.assertFalse(candidate_quality_rejection(base))

    def test_none_metric_fails_closed(self):
        base = dict(_quality_report(60, 50))
        base["measured"] = dict(base["measured"])
        base["measured"]["component_count"] = None
        self.assertFalse(candidate_quality_rejection(base))

    def test_nan_metric_fails_closed(self):
        base = dict(_quality_report(60, 50))
        base["measured"] = dict(base["measured"])
        base["measured"]["component_count"] = float("nan")
        self.assertFalse(candidate_quality_rejection(base))

    def test_inf_metric_fails_closed(self):
        base = dict(_quality_report(60, 50))
        base["measured"] = dict(base["measured"])
        base["measured"]["component_count"] = float("inf")
        self.assertFalse(candidate_quality_rejection(base))

    def test_boolean_threshold_fails_closed(self):
        base = dict(_quality_report(60, 50))
        base["limits"] = dict(base["limits"])
        base["limits"]["max_components"] = True
        self.assertFalse(candidate_quality_rejection(base))

    def test_missing_threshold_key_fails_closed(self):
        report = _quality_report(60, 50)
        report = dict(report, limits={})
        self.assertFalse(candidate_quality_rejection(report))

    def test_missing_measured_fails_closed(self):
        base = dict(_quality_report(60, 50))
        base["measured"] = {}
        self.assertFalse(candidate_quality_rejection(base))

    def test_non_pass_status_fails_closed(self):
        self.assertFalse(candidate_quality_rejection({"status": "passed"}))

    def test_passed_validation_returns_false(self):
        self.assertFalse(candidate_quality_rejection({"status": "passed", "errors": []}))

    def test_none_input(self):
        self.assertFalse(candidate_quality_rejection(None))

    def test_string_input(self):
        self.assertFalse(candidate_quality_rejection("not a dict"))

    def test_list_input(self):
        self.assertFalse(candidate_quality_rejection([1, 2]))


class TestStageFailureStr(unittest.TestCase):

    def test_with_stage(self):
        sf = StageFailure("configuration", "missing workflow",
                          operation="preflight", remedy="check path",
                          stage="concept_generation")
        s = str(sf)
        self.assertIn("concept_generation", s)
        self.assertIn("(configuration)", s)
        self.assertIn("missing workflow", s)
        self.assertIn("check path", s)

    def test_without_stage(self):
        sf = StageFailure("environment", "no blender",
                          operation="verify", remedy="install blender")
        s = str(sf)
        self.assertIn("(environment)", s)
        self.assertIn("no blender", s)
        self.assertIn("install blender", s)


class TestFailureRecordJsonSafetyFull(unittest.TestCase):
    """Blocker 4: Full JSON safety across all evidence boundaries."""

    def test_object_in_evidence_raises_on_dump(self):
        sf = StageFailure("unknown", "bad evidence",
                          operation="worker", remedy="inspect",
                          evidence={"value": object()})
        rec = failure_record(sf, stage="mesh", attempt=1, operation="worker")
        json.dumps(rec, allow_nan=False)

    def test_non_dict_evidence_type_strips(self):
        for ev in [("string", "test"), (42, 1), ([1, 2], "list"),
                    (None, None), (1.5, "float")]:
            sf = StageFailure("configuration", "ev",
                              operation="preflight", remedy="fix",
                              evidence=ev[0])
            rec = failure_record(sf, stage="test",
                                 attempt=1, operation="preflight")
            self.assertEqual(rec["evidence"], {})
            json.dumps(rec, allow_nan=False)

    def test_nested_invalid_objects_stripped(self):
        obj = object()
        sf = StageFailure("unknown", "nested",
                          operation="worker", remedy="inspect",
                          evidence={"deep": {"obj": obj, "nan": float("nan"),
                                            "inf": float("inf")}})
        rec = failure_record(sf, stage="mesh", attempt=1, operation="worker")
        json.dumps(rec, allow_nan=False)

    def test_nan_evidence_is_replaced(self):
        """NaN in evidence replaced with safe fallback, not just stripped."""
        sf = StageFailure("configuration", "fail",
                          operation="preflight", remedy="next",
                          evidence={"value": float("nan")})
        rec = failure_record(sf, stage="mesh", attempt=1, operation="test")
        # Evidence is the safe fallback, not the original with NaN values
        self.assertTrue("value" not in rec["evidence"])
        json.dumps(rec, allow_nan=False)

    def test_empty_message_uses_fallback(self):
        sf = StageFailure("configuration", "",
                          operation="preflight", remedy="fix")
        rec = failure_record(sf, stage="mesh", attempt=1, operation="test")
        self.assertNotEqual(rec["message"], "")
        self.assertIn("configuration", rec["message"])


class TestFinding6KeyboardInterrupt(unittest.TestCase):

    def test_keyboard_interrupt_classified_as_interruption(self):
        rec = failure_record(KeyboardInterrupt("stop"),
                             stage="mesh", attempt=1, operation="worker")
        self.assertEqual(rec["category"], "interruption")
        self.assertFalse(rec["retryable"])
        self.assertEqual(rec["exception_type"], "KeyboardInterrupt")
        self.assertIn("inspect", rec["remedy"].lower())


if __name__ == "__main__":
    unittest.main()


# ── Blocker 1 regressions: complete inspection rejects broken geometry ─

class TestCompleteInspectionRejections(unittest.TestCase):
    """Blocker 1: invalid geometry/UV/bounds/texture must prevent retry."""

    def test_zero_face_count_rejects(self):
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["face_count"] = 0
        self.assertFalse(candidate_quality_rejection(r))

    def test_zero_vertex_count_rejects(self):
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["vertex_count"] = 0
        self.assertFalse(candidate_quality_rejection(r))

    def test_zero_mesh_objects_rejects(self):
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["mesh_objects"] = 0
        self.assertFalse(candidate_quality_rejection(r))

    def test_zero_uv_layers_rejects(self):
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["uv_layers"] = 0
        self.assertFalse(candidate_quality_rejection(r))

    def test_zero_material_count_rejects(self):
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["material_count"] = 0
        self.assertFalse(candidate_quality_rejection(r))

    def test_negative_dimensions_reject(self):
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["dimensions"] = [-1, 1, 1]
        self.assertFalse(candidate_quality_rejection(r))

    def test_nan_dimensions_reject(self):
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["dimensions"] = [float("nan"), 1, 1]
        self.assertFalse(candidate_quality_rejection(r))

    def test_missing_textures_rejects(self):
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["missing_textures"] = ["missing.png"]
        self.assertFalse(candidate_quality_rejection(r))

    def test_vertex_count_below_three_rejects(self):
        """Validator: vertex_count must be >= 3."""
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["vertex_count"] = 1
        self.assertFalse(candidate_quality_rejection(r))

    def test_dimensions_below_one_e_minus_five_rejects(self):
        """Validator: dimensions[i] must be > 1e-5 (non-degenerate bounds)."""
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["dimensions"] = [1e-6, 1, 1]
        self.assertFalse(candidate_quality_rejection(r))

    def test_negative_image_texture_count_rejects(self):
        """Validator: image_texture_count must be non-negative."""
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["image_texture_count"] = -1
        self.assertFalse(candidate_quality_rejection(r))

    def test_string_image_texture_count_rejects(self):
        """Validator: image_texture_count must be numeric."""
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["image_texture_count"] = "bad"
        self.assertFalse(candidate_quality_rejection(r))


# ── Blocker 2 regressions: overflow-safe numeric comparisons ─

class TestOverflowSafeComparisons(unittest.TestCase):
    """Blocker 2: huge integers must not OverflowError."""

    def test_huge_measured_component_count_no_crash(self):
        r = dict(_quality_report(60, 50))
        r["measured"] = dict(r["measured"])
        r["measured"]["component_count"] = 10 ** 1000
        result = candidate_quality_rejection(r)
        self.assertTrue(type(result) is bool)

    def test_huge_limit_max_components_no_crash(self):
        r = dict(_quality_report(60, 50))
        r["limits"] = dict(r["limits"])
        r["limits"]["max_components"] = 10 ** 1000
        result = candidate_quality_rejection(r)
        self.assertTrue(type(result) is bool)


# ── Blocker 3 regressions: malformed present fields block retry ─

class TestMalformedPresentFieldsBlockRetry(unittest.TestCase):
    """Blocker 3: malformed field values must not authorize retry."""

    def test_list_stage_blocks_retry(self):
        r = dict(_quality_report(60, 50))
        rec = failure_record(StageFailure("candidate_quality", "bad",
                          operation="inspect", remedy="next",
                          evidence={"validation": r}),
                             stage="mesh", stage_id="id", attempt=1, operation="inspect")
        rec["stage"] = ["material_assembly_export"]
        self.assertFalse(should_retry(rec, used=1, limit=3))

    def test_none_message_blocks_retry(self):
        r = dict(_quality_report(60, 50))
        rec = failure_record(StageFailure("candidate_quality", "bad",
                          operation="inspect", remedy="next",
                          evidence={"validation": r}),
                             stage="mesh", stage_id="id", attempt=1, operation="inspect")
        rec["message"] = None
        self.assertFalse(should_retry(rec, used=1, limit=3))

    def test_string_retryable_blocks_retry(self):
        r = dict(_quality_report(60, 50))
        rec = failure_record(StageFailure("candidate_quality", "bad",
                          operation="inspect", remedy="next",
                          evidence={"validation": r}),
                             stage="mesh", stage_id="id", attempt=1, operation="inspect")
        rec["retryable"] = "yes"
        self.assertFalse(should_retry(rec, used=1, limit=3))

    def test_negative_attempt_blocks_retry(self):
        """Negative attempt is malformed; candidate-quality retries require
        a positive attempt number."""
        r = dict(_quality_report(60, 50))
        rec = failure_record(StageFailure("candidate_quality", "bad",
                          operation="inspect", remedy="next",
                          evidence={"validation": r}),
                             stage="mesh", stage_id="id", attempt=1, operation="inspect")
        rec["attempt"] = -1
        self.assertFalse(should_retry(rec, used=1, limit=3))


# ── Deep evidence test (from external acceptance) ─

class TestDeepEvidence(unittest.TestCase):
    def test_deep_evidence_does_not_hide_original_failure(self):
        value = None
        for _ in range(1500):
            value = [value]
        failure = failure_record(
            StageFailure("unknown", "original worker error",
                         operation="worker", remedy="inspect",
                         evidence={"deep": value}),
            stage="mesh_workflow_execution", attempt=1, operation="worker",
        )
        self.assertFalse(failure["retryable"])
        self.assertIn("original worker error", failure["message"])
        json.dumps(failure, allow_nan=False)


class TestValidatorMalformedTopologyMetrics(unittest.TestCase):
    def _report(self, **overrides):
        measured = {
            "mesh_objects": 1, "vertex_count": 24, "face_count": 8,
            "dimensions": [1, 1, 1], "uv_layers": 1, "material_count": 1,
            "image_texture_count": 4, "component_count": 1,
            "nonmanifold_edge_count": 0, "boundary_edge_count": 0,
            "transforms_applied": True, "missing_textures": [],
        }
        measured.update(overrides)
        return validate_model_outputs(
            {}, inspection={"status": "passed", "errors": [], "warnings": [],
                           "measured": measured},
            max_components=50, max_nonmanifold_edges=10, max_boundary_edges=10,
        )

    def test_nan_boundary_count_is_invalid_instead_of_passing(self):
        report = self._report(boundary_edge_count=float("nan"))
        self.assertEqual(report["status"], "failed")
        self.assertIn("metric_invalid", report["failure_codes"])

    def test_negative_boundary_count_is_invalid_instead_of_passing(self):
        report = self._report(boundary_edge_count=-1)
        self.assertEqual(report["status"], "failed")
        self.assertIn("metric_invalid", report["failure_codes"])

    def test_boolean_count_is_invalid(self):
        report = self._report(component_count=True)
        self.assertEqual(report["status"], "failed")
        self.assertIn("metric_invalid", report["failure_codes"])

    def test_oversized_integer_metric_fails_closed_without_raising(self):
        report = self._report(component_count=10 ** 1000)
        self.assertEqual(report["status"], "failed")
        self.assertIn("metric_invalid", report["failure_codes"])


class PropComponentBudgetTests(unittest.TestCase):
    def test_new_projects_retry_props_with_more_than_five_visible_parts(self):
        import tempfile
        from pathlib import Path
        from slopforge.initializer import init_project
        from slopforge.taxonomy import load_taxonomy
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            init_project(root)
            limit = load_taxonomy(root)["prop"]["max_components"]
        self.assertEqual(limit, 5)  # owner-declared props criterion v2
        within, over = (_quality_report(component_count=count, max_components=limit) for count in (5, 6))
        self.assertNotIn("component_budget", within.get("failure_codes", []))
        self.assertTrue(candidate_quality_rejection(over))

    def test_new_projects_check_prop_base_colour_against_the_concept(self):
        import tempfile
        from pathlib import Path
        from slopforge.initializer import init_project
        from slopforge.taxonomy import load_taxonomy
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            init_project(root)
            prop = load_taxonomy(root)["prop"]
        # Owner-declared 2026-10-21, calibrated on the protocol jugs and crates.
        self.assertEqual((prop["max_concept_hue_difference"], prop["min_concept_chroma_ratio"]), (4, 0.6))
        self.assertEqual(prop["max_concept_darkened_share"], 0.4)  # calibrated 2026-10-24 on 147 labelled views

    def test_mesh_that_no_longer_fits_the_concept_retries_the_next_seed(self):
        # 2026-10-22: shattered glass bottles fitted the concept outline at 0.71-0.75 and passed every other check;
        # whole props fitted 0.86-0.99. UV area stopped separating them once islands were padded by 4 texels.
        import tempfile
        from pathlib import Path
        from slopforge.initializer import init_project
        from slopforge.taxonomy import load_taxonomy
        from slopforge.validation import apply_concept_fit
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Assets").mkdir()
            init_project(root)
            prop = load_taxonomy(root)["prop"]
        self.assertEqual(prop["min_concept_fit"], 0.8)
        self.assertNotIn("min_uv_area", prop)
        shattered = apply_concept_fit(_quality_report(component_count=1), {"silhouette_iou": 0.75}, 0.8)
        whole = apply_concept_fit(_quality_report(component_count=1), {"silhouette_iou": 0.92}, 0.8)
        unmeasured = apply_concept_fit(_quality_report(component_count=1), {"status": "failed"}, 0.8)
        self.assertIn("concept_fit", shattered["failure_codes"])
        self.assertTrue(candidate_quality_rejection(shattered))
        self.assertNotIn("concept_fit", whole.get("failure_codes", []))
        self.assertNotIn("concept_fit", unmeasured.get("failure_codes", []))

    def test_module_stretched_past_its_limit_stops_without_retrying(self):
        # A module's stretch comes from its concept's proportions, so another mesh seed would stretch again
        # (2026-10-22: a doorway concept stretched 1.45 to fit 3 x 3 m).
        from slopforge.validation import apply_module_stretch
        squeezed = apply_module_stretch(_quality_report(component_count=1), 1.45, 1.3)
        fitted = apply_module_stretch(_quality_report(component_count=1), 1.11, 1.3)
        unlimited = apply_module_stretch(_quality_report(component_count=1), 1.45, None)
        self.assertIn("module_stretch", squeezed["failure_codes"])
        self.assertIn("stretched 1.45 times", squeezed["errors"][-1])
        self.assertFalse(candidate_quality_rejection(squeezed))
        from slopforge.pipelines.model import _validation_failure
        stop = _validation_failure(squeezed, stage="material_assembly_export", attempt=1)
        self.assertEqual(stop["remedy"], "approve a concept closer to the module's proportions")
        self.assertEqual((fitted["status"], fitted["measured"]["axis_stretch"]), ("passed", 1.11))
        self.assertEqual((unlimited["status"], unlimited["failure_codes"]), ("passed", []))  # no limit declared

    def test_corner_module_without_an_open_side_is_a_retryable_quality_failure(self):
        # 2026-10-22: stone corners that reconstructed as an L left one footprint quarter at 0.00; one that came out
        # a solid block measured 0.86 in every quarter.
        from slopforge.validation import apply_module_footprint
        block = apply_module_footprint(_quality_report(component_count=1), [0.86, 0.86, 0.86, 0.86], "corner")
        corner = apply_module_footprint(_quality_report(component_count=1), [0.69, 0.92, 0.75, 0.0], "corner")
        wall = apply_module_footprint(_quality_report(component_count=1), [1.0, 1.0, 1.0, 1.0], None)
        self.assertIn("module_footprint", block["failure_codes"])
        self.assertTrue(candidate_quality_rejection(block))
        self.assertNotIn("module_footprint", corner.get("failure_codes", []))
        self.assertEqual(corner["measured"]["open_quadrant"], 0.0)
        self.assertNotIn("module_footprint", wall.get("failure_codes", []))
        # M2-v2 T2: a wedge leaves its open quarter empty, but its arms thin toward their ends.
        report = _quality_report(component_count=1)
        report["measured"]["arm_taper"] = [1.724, 1.816]
        wedge = apply_module_footprint(report, [0.44, 0.40, 0.47, 0.02], "corner")
        self.assertEqual(wedge["failure_codes"], ["module_taper"])
        self.assertIn("wedge", wedge["errors"][-1])
        self.assertTrue(candidate_quality_rejection(wedge))
        report = _quality_report(component_count=1)
        report["measured"]["arm_taper"] = [1.002, 1.007]
        self.assertEqual(apply_module_footprint(report, [0.31, 0.55, 0.37, 0.0], "corner").get("failure_codes", []), [])

    def test_a_generated_part_below_its_mask_coverage_is_retried(self):
        from slopforge.validation import apply_part_coverage
        declared = [{"name": "grip", "kind": "grip"}, {"name": "slide", "kind": "slide"}, {"name": "trigger", "kind": "hinge"}]
        generated = {"slide": 0.5, "trigger": 0.9}
        report = apply_part_coverage(_quality_report(component_count=1), generated, declared, 0.6)
        self.assertEqual(report["failure_codes"], ["part_missing"])
        self.assertIn("slide", report["errors"][-1])
        self.assertEqual(report["measured"]["part_coverage"], {"slide": 0.5, "trigger": 0.9})
        self.assertEqual(report["limits"]["min_part_coverage"], 0.6)
        self.assertTrue(candidate_quality_rejection(report))
        passing = apply_part_coverage(_quality_report(component_count=1), {**generated, "slide": 0.6}, declared, 0.6)
        self.assertEqual(passing.get("failure_codes", []), [])
        absent = apply_part_coverage(_quality_report(component_count=1), {}, declared, 0.6)
        self.assertEqual(absent["failure_codes"], ["part_missing"])

    def test_a_part_that_swings_into_its_body_is_retried_before_materials(self):
        # The C3 chest's lid (0.169 of its vertices inside the body over rest) reached Unity before it failed; the
        # final pass now sweeps each part through its declared range in Blender, so a seed is retried early.
        from slopforge.validation import apply_part_penetration
        declared = [{"name": "lid", "kind": "hinge"}, {"name": "drawer", "kind": "slide"}]
        report = apply_part_penetration(_quality_report(component_count=1), {"lid": 0.169, "drawer": 0.004}, declared, 0.02)
        self.assertEqual(report["failure_codes"], ["part_penetrates"])
        self.assertIn("lid 0.17", report["errors"][-1])
        self.assertEqual(report["measured"]["part_penetration"], {"lid": 0.169, "drawer": 0.004})
        self.assertEqual((report["measured"]["moving_parts_penetrating"], report["limits"]["max_part_penetration"]), (1, 0.02))
        self.assertTrue(candidate_quality_rejection(report))
        passing = apply_part_penetration(_quality_report(component_count=1), {"lid": 0.01, "drawer": 0.0}, declared, 0.02)
        self.assertEqual(passing.get("failure_codes", []), [])
        unmeasured = apply_part_penetration(_quality_report(component_count=1), {}, declared, 0.02)
        self.assertEqual(unmeasured.get("failure_codes", []), [])  # the cut route measures nothing: no verdict

    def test_a_base_colour_without_textured_pixels_records_no_metric_and_stays_retryable(self):
        # 2026-10-25 live pistol: an all-black atlas left no texels to measure, the chroma metrics became NaN, the
        # failure record could not carry its evidence, and a retryable part_missing was reported as final.
        import json, tempfile
        from pathlib import Path
        from PIL import Image
        from slopforge.validation import apply_concept_colour, concept_colour_fidelity
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            concept = Image.new("RGBA", (32, 32), (0, 0, 0, 0)); concept.paste((160, 90, 40, 255), (4, 4, 28, 28))
            concept.save(root / "cutout.png")
            Image.new("RGB", (32, 32), (0, 0, 0)).save(root / "basecolor.png")
            fidelity = concept_colour_fidelity(root / "cutout.png", root / "basecolor.png")
            self.assertEqual((fidelity["texture_chroma"], fidelity["concept_hue_difference"], fidelity["concept_chroma_ratio"]),
                             (None, None, None))
            json.dumps(fidelity, allow_nan=False)  # the failure record must be able to carry it
            report = apply_concept_colour(_quality_report(component_count=1), fidelity, max_hue_difference=4,
                                          min_chroma_ratio=0.6)
            self.assertEqual(report["status"], "passed_with_warnings")
            self.assertTrue(any("no textured pixels" in warning for warning in report["warnings"]))
            json.dumps(report, allow_nan=False)

    def test_a_failed_concept_view_names_its_error_in_the_warning(self):
        # The view script reports {"status": "failed", "error": ...}; the warning printed "(not rendered)" instead
        from slopforge.validation import apply_concept_colour
        fidelity = {"colour_source": "atlas", "concept_chroma": 30.0, "texture_chroma": 20.0,
                    "concept_hue_difference": 1.0, "concept_chroma_ratio": 0.67, "concept_darkened_share": None,
                    "concept_view": {"status": "failed", "error": "Expected one mesh in x.glb, found 4"}}
        report = apply_concept_colour(_quality_report(component_count=1), fidelity, max_hue_difference=4,
                                      min_chroma_ratio=0.6, max_darkened_share=0.4)
        self.assertTrue(any("Expected one mesh" in warning for warning in report["warnings"]), report["warnings"])
        self.assertFalse(any("not rendered" in warning for warning in report["warnings"]))

    def test_a_declared_moving_part_that_did_not_come_out_is_retried(self):
        from slopforge.validation import apply_moving_parts
        report = _quality_report(component_count=1)
        report["measured"]["parts"] = [{"name": "slide", "kind": "slide"}]
        missing = apply_moving_parts(report, ["slide", "trigger"])
        self.assertEqual(missing["failure_codes"], ["part_missing"])
        self.assertTrue(candidate_quality_rejection(missing))
        report = _quality_report(component_count=1)
        report["measured"]["parts"] = [{"name": "slide", "kind": "slide"}, {"name": "trigger", "kind": "hinge"}]
        self.assertEqual(apply_moving_parts(report, ["slide", "trigger"]).get("failure_codes", []), [])

    def test_a_weapon_whose_length_runs_across_the_concept_view_is_retried(self):
        # Two crossed swords reconstructed at alignment 0.0 and stopped approval as a Blender crash (2026-10-24); it
        # is a quality rejection, so the next seed is tried. A three-quarter crossbow at 0.45 is oriented.
        from slopforge.validation import apply_weapon_orientation
        for alignment, codes in ((0.0, ["weapon_orientation"]), (0.45, [])):
            report = _quality_report(component_count=1)
            report["measured"]["concept_view"] = {"fit": 0.73, "theta": -90, "phi": 0, "tip_alignment": alignment}
            result = apply_weapon_orientation(report)
            self.assertEqual(result.get("failure_codes", []), codes)
            self.assertEqual(result["measured"]["weapon_tip_alignment"], alignment)
            self.assertEqual(candidate_quality_rejection(result), bool(codes))
        self.assertEqual(apply_weapon_orientation({"measured": {}}), {"measured": {}})  # not a held weapon
