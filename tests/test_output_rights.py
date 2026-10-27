import pytest

from slopforge.providers import RIGHTS, combine_rights, validate_output_rights

CLEARED = {"status": "cleared", "terms": "MIT", "terms_version": "LICENSE at 55d51b3", "read_on": "2026-10-27"}
NOTICE = {"status": "attribution_required", "terms": "DINOv3 License", "terms_version": "2025-08-19",
          "read_on": "2026-10-27", "notice": "Built with DINOv3."}
UNKNOWN = {"status": "unknown", "reason": "API terms not read"}
RESTRICTED = {"status": "restricted", "terms": "FLUX.1 [dev] Non-Commercial License", "terms_version": "v1.1.1",
              "read_on": "2026-10-27", "reason": "non-commercial outputs"}


@pytest.mark.parametrize("record", [CLEARED, NOTICE, UNKNOWN, RESTRICTED])
def test_valid_records_pass_as_copies(record):
    result = validate_output_rights(record)
    assert result == record and result is not record


@pytest.mark.parametrize("record, message", [
    (None, "must be a mapping"),
    ({"status": "fine"}, "status"),
    ({**CLEARED, "terms": ""}, "terms"),
    ({key: value for key, value in CLEARED.items() if key != "terms_version"}, "terms_version"),
    ({**CLEARED, "read_on": "27/10/2026"}, "read_on"),
    ({**CLEARED, "read_on": 20261027}, "read_on"),
    ({key: value for key, value in NOTICE.items() if key != "notice"}, "notice"),
    ({"status": "unknown"}, "reason"),
    ({key: value for key, value in RESTRICTED.items() if key != "reason"}, "reason"),
    ({**CLEARED, "notes": "typo of notice"}, "notes"),
    ({**UNKNOWN, "terms": ["not", "text"]}, "terms"),
])
def test_malformed_records_are_refused_with_the_field_named(record, message):
    with pytest.raises(ValueError, match=message):
        validate_output_rights(record, "providers.video_cloud.output_rights")


def test_the_weakest_status_wins_and_notices_accumulate():
    assert RIGHTS == ("restricted", "unknown", "attribution_required", "cleared")
    combined = combine_rights([{"source": "trellis", **CLEARED}, {"source": "dinov3", **NOTICE},
                               {"source": "dinov3 again", **NOTICE},
                               {"source": "other", **NOTICE, "notice": "Built with X."}])
    assert combined["status"] == "attribution_required"
    assert combined["notices"] == ["Built with DINOv3.", "Built with X."]
    assert combined["reasons"] == []
    assert [item["source"] for item in combined["sources"]] == ["trellis", "dinov3", "dinov3 again", "other"]
    assert combine_rights([{"source": "a", **NOTICE}, {"source": "b", **UNKNOWN}])["status"] == "unknown"
    worst = combine_rights([{"source": "b", **UNKNOWN}, {"source": "c", **RESTRICTED}])
    assert worst["status"] == "restricted"
    assert worst["reasons"] == ["b: API terms not read", "c: non-commercial outputs"]
    assert combine_rights([]) == {"status": "cleared", "notices": [], "reasons": [], "sources": []}


def test_an_invalid_entry_is_unknown_not_an_exception():
    combined = combine_rights([{"source": "trellis", **CLEARED}, {"source": "broken", "status": "cleared"},
                               "not a record", {**CLEARED}])
    assert combined["status"] == "unknown"
    assert any(reason.startswith("broken: invalid output rights") for reason in combined["reasons"])
    assert sum("invalid output rights" in reason for reason in combined["reasons"]) == 3
