"""Shared failure vocabulary for SlopForge orchestration and workers.

Workers and backends import this module only (never orchestration).
Orchestration callers import from backends' StageFailure.
"""

from __future__ import annotations

import json
from typing import Any, Dict
import math

# ── Allowlisted candidate-quality codes (only these retry) ──────────────
_CANDIDATE_QUALITY_CODES = frozenset({
    "component_budget",
    "nonmanifold_budget",
    "boundary_budget",
    "concept_silhouette",
    "emitter_missing",
    "colour_hue_shift",
    "colour_desaturated",
    "colour_darkened",
    "thin_feature_missing",
    "glass_missing",
    "nonmetal_missing",
    "uv_area_budget",
    "concept_fit",
    "module_footprint",
    "module_taper",
    "weapon_orientation",
    "part_missing",
    "part_penetrates",
    "part_open",
    "colour_lost",
    "mesh_folded",
    "part_fit",
})

# ── Codes of candidates that are not meshes, by validation["artifact_kind"] ─
# A rig, a video clip or an extracted motion has no mesh metrics; its codes name their own metric and limit
# (code: (metric, limit); a min_ limit rejects below it, any other above it). AI motion sources plan, section 8.
_KIND_CODES: Dict[str, Dict[str, tuple[str, str]]] = {
    "rig": {"rig_limb_missing": ("rig_limbs_missing", "max_rig_limbs_missing"),
            "rig_asymmetric": ("rig_asymmetry", "max_rig_asymmetry"),
            "rig_bone_outside": ("rig_bones_outside", "max_rig_bones_outside")},
    # B5's intake (slopforge/video_intake.py), then video2rig's check of the two views (D7, exam v1's limits)
    "video": {"video_frame_rate": ("video_duplicate_share", "max_video_duplicate_share"),
              "video_frame0": ("video_frame0_difference", "max_video_frame0_difference"),
              "video_creature_missing": ("video_presence", "min_video_presence"),
              "video_backdrop_drift": ("video_backdrop_drift", "max_video_backdrop_drift"),
              "video_still": ("video_motion_share", "min_video_motion_share"),
              "video_turned": ("video_turn", "max_video_turn"),
              "video_views_disagree": ("video_view_disagreement", "max_video_view_disagreement"),
              "video_limbs_disagree": ("video_limb_disagreement", "max_video_limb_disagreement"),
              "video_check_failed": ("video_check_failures", "max_video_check_failures"),
              "video_refused": ("video_refusals", "max_video_refusals"),
              "video_cut": ("video_cuts", "max_video_cuts")},
    "motion": {"motion_joint_lost": ("motion_joints_lost", "max_motion_joints_lost"),
               "motion_limit_exceeded": ("motion_limit_violations", "max_motion_limit_violations"),
               "exam_failed": ("exam_bone_error_degrees", "max_exam_bone_error_degrees"),
               # B6's bake: a period needs two plants of every leg (slopforge/creature_gait.py)
               "motion_no_cycle": ("motion_min_plants", "min_motion_plants")},
}

# ── Retryable categories (subset of all categories) ───────────────────
_RETRYABLE_CATEGORIES = frozenset({"candidate_quality"})


class StageFailure(RuntimeError):
    """Typed failure describing a prop-stage stop or retry boundary.

    str(output) includes stage (when known), category, message, and remedy
    so existing CLI error paths remain readable.
    """

    def __init__(
        self,
        category: str,
        message: str,
        *,
        operation: str,
        remedy: str,
        stage: str | None = None,
        stage_id: str | None = None,
        evidence: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.operation = operation
        self.remedy = remedy
        self.stage = stage
        self.stage_id = stage_id
        self.evidence = evidence or {}

    def __str__(self) -> str:
        parts: list[str] = []
        if self.stage is not None:
            parts.append(self.stage)
        parts.append(f"({self.category})")
        parts.append(self.message)
        parts.append(f"remedy: {self.remedy}")
        return " — ".join(parts)


# ── Required fields for a complete failure_record ──────────────────────
_REQUIRED_RECORD_FIELDS = frozenset({
    "category", "stage", "stage_id", "attempt",
    "operation", "message", "remedy", "retryable",
    "exception_type", "evidence",
})


def failure_record(
    error: Exception | KeyboardInterrupt,
    *,
    stage: str,
    attempt: int | None,
    operation: str,
    stage_id: str | None = None,
) -> dict:
    """Return a JSON-safe failure record from any exception.

    An explicitly reported StageFailure takes precedence over the fallback.
    Untyped exceptions default to category "unknown".

    The ``stage`` field always stores the caller-supplied stage name.
    When an untyped exception is passed the caller's ``stage`` is used
    verbatim rather than falling through to the optional ``stage_id``.
    """
    # ── Default: classify as unknown for any unhandled exception ────────
    if not isinstance(error, StageFailure):
        # KeyboardInterrupt → interruption; untyped exceptions → unknown.
        if isinstance(error, KeyboardInterrupt):
            category = "interruption"
            remedy = "inspect retained state and explicitly resume; do not assume remote inference stopped"
        else:
            category = "unknown"
            remedy = "inspect the stage boundary and retry after a confirmed fix"
        msg = str(error)
        if not msg:
            msg = f"{category}: no message"
        return {
            "category": category,
            "stage": stage,                # ← always use caller's name
            "stage_id": stage_id,
            "attempt": attempt,
            "operation": operation,
            "message": msg,
            "remedy": remedy,
            "retryable": False,
            "exception_type": type(error).__name__,
            "evidence": {},
        }

    # ── StageFailure path ───────────────────────────────────────────────
    # Validate evidence: use strict JSON serialization.  Unsupported objects
    # reset evidence to safe-fallback so quality-retry never trusts bad data.
    safe_evidence: dict = {}
    if (isinstance(error.evidence, dict)):
        try:
            json.dumps(error.evidence, allow_nan=False)
            safe_evidence = dict(error.evidence)
        except (TypeError, ValueError):
            safe_evidence = {"_safe_evidence_fallback": True}

    # Derive retryable from validated quality evidence only.
    is_quality = (error.category == "candidate_quality")
    validated_evidence = safe_evidence.get("validation") if is_quality else None
    retryable = (False
                 if not is_quality or not isinstance(validated_evidence, dict)
                 else candidate_quality_rejection(validated_evidence))

    return {
        "category": error.category,
        "stage": error.stage if error.stage is not None else stage,
        "stage_id": error.stage_id if error.stage_id is not None else stage_id,
        "attempt": attempt,
        "operation": error.operation if error.operation else operation,
        "message": str(error) or f"{error.category}: no message",
        "remedy": error.remedy,
        "retryable": retryable,
        "exception_type": type(error).__name__,
        "evidence": safe_evidence,
    }


def should_retry(failure: dict, *, used: int, limit: int) -> bool:
    """Decide whether the failure record qualifies for automatic retry.

    * ``used`` and ``limit`` must be positive integers (not bools); retry only
      when ``used < limit``.
    * Only ``candidate_quality`` category records qualify within budget.
    * A ``candidate_quality`` record must carry a validated
      ``evidence["validation"]`` report; missing/incomplete/tampered evidence
      prevents retry (never trusts the boolean flag alone).
    * Invalid records (bad containers, negative counters, etc.) fail closed.
    * The record must contain all required failure_record fields.
    """
    # Validate container shapes early (fail closed).
    if not isinstance(failure, dict):
        return False

    # Validate required fields (Blocker 2).
    for field in _REQUIRED_RECORD_FIELDS:
        if field not in failure:
            return False

    category = failure.get("category")
    if not isinstance(category, str) or not category:
        return False

    # Validate field value types (not just presence).
    stage = failure.get("stage")
    if not isinstance(stage, str) or not stage:
        return False
    message = failure.get("message")
    if not isinstance(message, str) or not message:
        return False
    remedy = failure.get("remedy")
    if not isinstance(remedy, str) or not remedy:
        return False
    operation = failure.get("operation")
    if not isinstance(operation, str) or not operation:
        return False
    attempt = failure.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int):
        return False
    if attempt < 1:
        return False
    exception_type = failure.get("exception_type")
    if not isinstance(exception_type, str) or not exception_type:
        return False
    retryable = failure.get("retryable")
    if not isinstance(retryable, bool):
        return False

    # used/limit must be plain ints, not booleans (isinstance(True, int)!).
    if isinstance(used, bool) or isinstance(limit, bool):
        return False
    if not isinstance(used, int) or not isinstance(limit, int):
        return False
    if used <= 0 or limit <= 0:
        return False
    if category not in _RETRYABLE_CATEGORIES:
        return False

    # candidate_quality requires validated evidence; never trust retryable
    # from the record alone.  Tampered or absent evidence blocks retry.
    evidence = failure.get("evidence")
    if not isinstance(evidence, dict):
        return False
    validation = evidence.get("validation")
    if not isinstance(validation, dict):
        return False
    if not candidate_quality_rejection(validation):
        return False

    return used < limit


def candidate_quality_rejection(validation: dict) -> bool:
    """Return True only when a complete valid inspection rejects on
    allowlisted topology thresholds.

    Requirements for a True result:
    * ``status == "failed"`` and ``errors`` is a non-empty list of strings.
    * ``failure_codes`` is present and non-empty; every code is in the
      allowlist; there are no missing or legacy codes.
    * ``failure_codes`` is aligned with ``errors`` (same length).
    * For each rejection code the inspection has a finite non-negative
      numeric metric that meets or exceeds its declared non-negative
      threshold in the inspection's measured data.
    * Booleans are not treated as numeric metrics or thresholds.
    * A complete valid inspection is required (all mandatory metrics present
      and valid -- mirroring validate_model_outputs requirements).
    * All members of the validation dict must be validated before selecting
      any single threshold failure. One legitimate exceeded component limit
      cannot conceal invalid face or geometry data.

    Any violation returns False without raising. Handles overlarge integers
    without leaking numeric overflow.
    """
    # Fail closed on malformed containers.
    if not isinstance(validation, dict):
        return False

    status = validation.get("status")
    if status != "failed":
        return False

    errors = validation.get("errors")
    if not isinstance(errors, list) or not errors:
        return False

    codes = validation.get("failure_codes")
    if not isinstance(codes, list) or not codes:
        return False

    # Code list length must match errors (one-to-one alignment).
    if len(codes) != len(errors):
        return False

    # Every error member must be a string.
    for error_member in errors:
        if not isinstance(error_member, str):
            return False

    # The inspected artifact's kind selects the codes; a mesh by default (every inspection before kinds existed).
    kind = validation.get("artifact_kind", "mesh")
    if kind != "mesh":
        table = _KIND_CODES.get(kind) if isinstance(kind, str) else None
        if table is None or not all(isinstance(code, str) and code in table for code in codes):
            return False
        measured, limits = validation.get("measured"), validation.get("limits")
        if not isinstance(measured, dict) or not isinstance(limits, dict):
            return False
        return _codes_exceed_limits(codes, measured, limits, table)

    # Every code must be in the allowlist (no missing/legacy codes).
    for code in codes:
        if not isinstance(code, str) or code not in _CANDIDATE_QUALITY_CODES:
            return False

    # ── Complete-inspection check mirroring validate_model_outputs ──────
    measured = validation.get("measured")
    if not isinstance(measured, dict):
        return False

    # ── Complete-inspection check mirroring validate_model_outputs ──────
    # These checks are structural (presence/value-type). Additional
    # validity checks (non-zero geometry, positive bounds, empty texture
    # list, etc.) are done below.

    _STRUCT_METRICS = (
        "mesh_objects", "vertex_count", "face_count",
        "uv_layers", "material_count", "image_texture_count",
        "component_count", "nonmanifold_edge_count",
    )

    for m in _STRUCT_METRICS:
        if m not in measured:
            return False

    if "dimensions" not in measured or not isinstance(
            measured["dimensions"], (list, tuple)):
        return False
    if "transforms_applied" not in measured or measured["transforms_applied"] is not True:
        return False
    if "missing_textures" not in measured:
        return False

    # ── Value validity: geometry, bounds, texture completeness ────────

    # All count/gauge metrics must be > 0 (positive geometry exists)
    for m in ("mesh_objects", "face_count", "uv_layers", "material_count"):
        v = measured[m]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False
        try:
            if not math.isfinite(v) or v <= 0:
                return False
        except OverflowError:
            return False

    # vertex_count must be >= 3 (minimum triangle geometry)
    vc = measured["vertex_count"]
    if isinstance(vc, bool) or not isinstance(vc, (int, float)):
        return False
    try:
        if not math.isfinite(vc) or vc < 3:
            return False
    except OverflowError:
        return False

    # component_count / nonmanifold must be >= 0 (zero is valid)
    for m in ("component_count", "nonmanifold_edge_count"):
        v = measured[m]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False
        try:
            if not math.isfinite(v) or v < 0:
                return False
        except OverflowError:
            return False

    # dimensions: all three entries must be > 1e-5 (non-degenerate bounds)
    dims = measured["dimensions"]
    if len(dims) != 3:
        return False
    for d in dims:
        if isinstance(d, bool) or not isinstance(d, (int, float)):
            return False
        try:
            if not math.isfinite(d) or d <= 1e-5:
                return False
        except OverflowError:
            return False

    # missing_textures must be an empty list (no missing textures)
    mt = measured["missing_textures"]
    if not isinstance(mt, list) or mt:
        return False

    # image_texture_count must be a finite non-negative numeric
    itc = measured["image_texture_count"]
    if isinstance(itc, bool) or not isinstance(itc, (int, float)):
        return False
    try:
        if not math.isfinite(itc) or itc < 0:
            return False
    except OverflowError:
        return False

    limits = validation.get("limits")
    if not isinstance(limits, dict):
        return False

    # ── Check each rejection code exceeds its limit ─────────────────────
    _CODE_LIMIT: Dict[str, tuple[str, str]] = {
        "component_budget": ("component_count", "max_components"),
        "nonmanifold_budget": ("nonmanifold_edge_count", "max_nonmanifold_edges"),
        "boundary_budget": ("boundary_edge_count", "max_boundary_edges"),
        "concept_silhouette": ("concept_aspect_error", "max_concept_aspect_error"),
        "emitter_missing": ("emissive_fraction", "min_emissive_fraction"),
        "colour_hue_shift": ("concept_hue_difference", "max_concept_hue_difference"),
        "colour_desaturated": ("concept_chroma_ratio", "min_concept_chroma_ratio"),
        "colour_darkened": ("concept_darkened_share", "max_concept_darkened_share"),
        "colour_lost": ("concept_desaturated_share", "max_concept_desaturated_share"),
        "thin_feature_missing": ("concept_thin_recall", "min_concept_thin_recall"),
        "glass_missing": ("glass_fraction", "min_glass_fraction"),
        "nonmetal_missing": ("nonmetal_fraction", "min_nonmetal_fraction"),
        "uv_area_budget": ("uv_area_sum", "min_uv_area"),
        "concept_fit": ("concept_fit", "min_concept_fit"),
        "module_footprint": ("open_quadrant", "max_open_quadrant"),
        "module_taper": ("corner_taper", "max_arm_taper"),
        "weapon_orientation": ("weapon_tip_alignment", "min_weapon_tip_alignment"),
        "part_missing": ("moving_parts_missing", "max_moving_parts_missing"),
        "part_penetrates": ("moving_parts_penetrating", "max_moving_parts_penetrating"),
        "part_open": ("moving_parts_open", "max_moving_parts_open"),
        "mesh_folded": ("max_folded_edge_share", "max_folded_edge_share"),
        "part_fit": ("open_part_stretch", "max_open_part_stretch"),
    }

    return _codes_exceed_limits(codes, measured, limits, _CODE_LIMIT)


def _codes_exceed_limits(codes, measured, limits, table) -> bool:
    """Every code's metric is a finite number past its declared finite, non-negative limit."""
    for code in codes:
        metric_key, limit_key = table.get(code, (None, None))
        if metric_key is None:
            return False
        threshold = limits.get(limit_key)
        # Unspecified (null) limit means unbounded; missing limit here means
        # the validator did not emit the code and the report is inconsistent.
        if threshold is None:
            return False
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            return False
        try:
            if not math.isfinite(threshold) or threshold < 0:
                return False
        except OverflowError:
            return False
        metric_value = measured.get(metric_key)
        # Booleans are not numeric metrics.
        if isinstance(metric_value, bool) or not isinstance(metric_value, (int, float)):
            return False
        try:
            if not math.isfinite(metric_value):
                return False
            # A min_ limit rejects below it; every other limit is a maximum.
            if metric_value >= threshold if limit_key.startswith("min_") else metric_value <= threshold:
                return False
        except OverflowError:
            return False

    return True
