from datetime import datetime, timedelta, timezone

from content_platform.intelligence_scoring import evaluate_intelligence_pool, score_intelligence_item


NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)


def _row(platform, role, *, hours=1, heat=1000, title="AI 工作流实战"):
    return {
        "platform": platform,
        "identity_role": role,
        "title": title,
        "url": f"https://{platform}.example/item",
        "captured_at": (NOW - timedelta(hours=hours)).isoformat(),
        "collector": f"{platform}_collector",
        "heat": heat,
        "analysis": {"structure_types": ["步骤/清单"]},
    }


def test_target_platform_evidence_outranks_hotter_cross_platform_reference():
    native = _row("wechat", "target_platform", heat=1000)
    reference = _row("weibo", "cross_platform_reference", heat=1_000_000)

    ranked = evaluate_intelligence_pool(
        [reference, native], target_platform="wechat", lane_keywords=["AI", "工作流"], now=NOW,
    )

    assert ranked[0]["platform"] == "wechat"
    assert ranked[0]["intelligence_score"]["target_ready_eligible"] is True
    assert ranked[1]["intelligence_score"]["target_ready_eligible"] is False


def test_scoring_exposes_freshness_lane_value_and_saturation_dimensions():
    fresh = score_intelligence_item(
        _row("github", "cross_platform_reference", hours=2, title="AI workflow checklist"),
        target_platform="youtube", lane_keywords=["AI", "workflow"], now=NOW,
    )
    stale = score_intelligence_item(
        _row("medium", "cross_platform_reference", hours=24 * 60, title="unrelated travel note"),
        target_platform="youtube", lane_keywords=["AI", "workflow"], now=NOW,
    )

    assert fresh["score"] > stale["score"]
    assert set(fresh["dimensions"]) == {
        "identity", "heat", "freshness", "lane_fit", "content_value", "saturation_penalty", "source_quality",
    }
