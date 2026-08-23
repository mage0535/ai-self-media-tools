from datetime import datetime, timedelta, timezone

from content_platform.associated_hotspot import hotspot_mode_for_platform, score_topic_with_hotspot, validate_associated_hotspot


def _hotspot(**overrides):
    value = {
        "platform": "douyin_ai",
        "hotspot_id": "hot-123",
        "title": "AI效率工具",
        "canonical_url": "https://example.test/hot-123",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        "heat_rank": 12,
        "heat_score": 0.82,
        "native_verified": True,
        "association_mode": "manual_handoff",
        "lane_fit_score": 0.86,
        "semantic_fit_score": 0.91,
    }
    value.update(overrides)
    return value


def test_hotspot_requires_native_identity_and_freshness():
    assert validate_associated_hotspot(_hotspot())["passed"] is True
    result = validate_associated_hotspot(_hotspot(native_verified=False))
    assert result["passed"] is False
    assert "native_verification_required" in result["failures"]


def test_auto_association_cannot_pass_without_native_verification():
    result = validate_associated_hotspot(_hotspot(association_mode="auto_api", native_verified=False))
    assert result["passed"] is False
    assert "auto_association_requires_native_verification" in result["failures"]


def test_topic_score_uses_hotspot_as_bounded_bonus_not_a_quality_bypass():
    result = score_topic_with_hotspot(
        {"platform_fit": 0.9, "utility": 0.8, "novelty": 0.7},
        _hotspot(),
    )
    assert 0.0 <= result["score"] <= 1.0
    assert result["hotspot_bonus"] > 0
    bad = score_topic_with_hotspot({"platform_fit": 0.1, "utility": 0.1, "novelty": 0.1}, _hotspot())
    assert bad["eligible"] is False


def test_unverified_platform_defaults_to_safe_manual_boundary():
    assert hotspot_mode_for_platform("douyin_ai") == "unsupported_or_unverified"
