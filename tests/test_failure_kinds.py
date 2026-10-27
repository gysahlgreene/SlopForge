"""Candidate-quality codes by artifact kind: a video, rig or motion candidate has no mesh metrics, and its quality
codes must still be able to retry, while a mesh code keeps its complete-inspection requirement."""
import copy

import pytest

from slopforge.failures import StageFailure, candidate_quality_rejection, failure_record, should_retry
from tests.test_failure_classification import _quality_report

VIDEO = {"status": "failed", "errors": ["the clip repeats frames: 12 distinct per second"],
         "failure_codes": ["video_frame_rate"], "artifact_kind": "video",
         "measured": {"video_distinct_fps": 12.0}, "limits": {"min_video_distinct_fps": 20}}


def test_a_video_code_without_mesh_metrics_can_retry():
    assert candidate_quality_rejection(VIDEO)
    failure = failure_record(StageFailure("candidate_quality", "frame rate", operation="video_intake",
                                          remedy="generate another clip", evidence={"validation": VIDEO}),
                             stage="video_intake", attempt=1, operation="video_intake")
    assert failure["retryable"] and should_retry(failure, used=1, limit=3)


@pytest.mark.parametrize("kind, code, metric, limit, value, bound", [
    ("rig", "rig_limb_missing", "rig_limbs_missing", "max_rig_limbs_missing", 1, 0),
    ("rig", "rig_asymmetric", "rig_asymmetry", "max_rig_asymmetry", 0.2, 0.1),
    ("rig", "rig_bone_outside", "rig_bones_outside", "max_rig_bones_outside", 2, 0),
    ("video", "video_views_disagree", "video_view_disagreement", "max_video_view_disagreement", 0.05, 0.02),
    ("video", "video_cut", "video_cuts", "max_video_cuts", 1, 0),
    ("motion", "motion_joint_lost", "motion_joints_lost", "max_motion_joints_lost", 3, 0),
    ("motion", "motion_limit_exceeded", "motion_limit_violations", "max_motion_limit_violations", 4, 0),
    ("motion", "exam_failed", "exam_bone_error_degrees", "max_exam_bone_error_degrees", 9.0, 5.0),
])
def test_every_new_code_retries_only_past_its_own_limit(kind, code, metric, limit, value, bound):
    validation = {"status": "failed", "errors": [code], "failure_codes": [code], "artifact_kind": kind,
                  "measured": {metric: value}, "limits": {limit: bound}}
    assert candidate_quality_rejection(validation)
    assert not candidate_quality_rejection({**validation, "measured": {metric: bound}})  # within the limit
    assert not candidate_quality_rejection({**validation, "measured": {}})  # the metric is missing


@pytest.mark.parametrize("change", [
    lambda v: v.pop("artifact_kind"),                     # a mesh inspection by default: mesh metrics missing
    lambda v: v.update(artifact_kind="audio"),            # an unknown kind
    lambda v: v.update(artifact_kind="rig"),              # the code belongs to another kind
    lambda v: v.update(failure_codes=["video_frame_rate", "component_budget"],
                       errors=["a", "b"]),                # a mesh code inside a video inspection
    lambda v: v.update(artifact_kind=["video"]),          # not a name
])
def test_a_mismatched_or_unknown_kind_fails_closed(change):
    validation = copy.deepcopy(VIDEO)
    change(validation)
    assert not candidate_quality_rejection(validation)


def test_a_mesh_code_still_needs_the_complete_mesh_inspection():
    report = _quality_report(60, 50)
    assert candidate_quality_rejection(report)
    assert candidate_quality_rejection({**report, "artifact_kind": "mesh"})
    assert not candidate_quality_rejection({**report, "measured": {"component_count": 60}})
    assert not candidate_quality_rejection({**report, "artifact_kind": "video"})
