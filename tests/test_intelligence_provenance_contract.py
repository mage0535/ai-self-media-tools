from datetime import datetime, timezone

from content_platform.intelligence_provenance import can_use, validate_envelope


def _envelope(source_class="public_web_observation", **overrides):
    base = {
        "version": "intelligence_provenance_v1",
        "evidence_id": "obs-001",
        "source_class": source_class,
        "origin_platform": "bilibili",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "collector_id": "test_collector_v1",
        "content_locator": "https://www.bilibili.com/video/BV1test",
        "integrity": {"sha256": "a" * 64},
        "use_policy": {},
    }
    return {**base, **overrides}


def test_public_observation_can_support_topic_planning_but_not_owned_strategy_or_generation_reference():
    result = validate_envelope(_envelope())
    assert result["passed"] is True
    assert can_use(result["envelope"], "topic_planning")["allowed"] is True
    assert can_use(result["envelope"], "owned_strategy")["allowed"] is False
    assert can_use(result["envelope"], "generation_reference")["allowed"] is False


def test_provenance_rejects_naive_timestamp_and_sensitive_key():
    result = validate_envelope(_envelope(observed_at="2026-09-15T12:00:00", cookie="must-not-enter"))
    assert result["passed"] is False
    assert "observed_at_timezone_invalid" in result["reason_codes"]
    assert "sensitive_field_forbidden" in result["reason_codes"]


def test_licensed_reference_requires_explicit_cleared_scope_for_generation_reference():
    pending = validate_envelope(_envelope(
        "licensed_vendor",
        license_status="pending_review",
        license_scope=["topic_planning"],
    ))
    cleared = validate_envelope(_envelope(
        "licensed_vendor",
        license_status="cleared",
        license_scope=["generation_reference"],
    ))
    assert can_use(pending["envelope"], "generation_reference")["allowed"] is False
    assert can_use(cleared["envelope"], "generation_reference")["allowed"] is True
