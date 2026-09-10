from datetime import datetime, timedelta, timezone

from content_platform.topic_selection_engine import decide_topic
from content_platform.overnight_batch import build_due_tasks


NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def _item(
    platform: str,
    title: str,
    evidence_type: str,
    *,
    metric: int | None = 1000,
    identity_role: str = "target_platform",
    lane_fit: float = 0.9,
    hours_old: int = 2,
) -> dict:
    row = {
        "platform": platform,
        "title": title,
        "evidence_type": evidence_type,
        "identity_role": identity_role,
        "url": f"https://{platform}.example/items/{abs(hash(title))}",
        "captured_at": (NOW - timedelta(hours=hours_old)).isoformat(),
        "collector": f"{platform}_collector",
        "lane_fit_score": lane_fit,
        "content_value_score": 0.8,
        "actionability_score": 0.8,
        "saturation_score": 0.2,
    }
    if metric is not None:
        row["views"] = metric
    return row


def test_same_platform_same_lane_work_outranks_hot_cross_platform_reference():
    native = _item("kuaishou", "AI工作流三步实测", "same_lane_hot_work", metric=1500)
    external = _item(
        "weibo",
        "AI工作流爆发",
        "native",
        metric=8_000_000,
        identity_role="cross_platform_reference",
    )

    result = decide_topic(
        "kuaishou",
        [external, native],
        lane_keywords=["AI", "工作流"],
        now=NOW,
    )

    assert result["status"] == "selected"
    assert result["selected"]["title"] == native["title"]
    assert result["selected"]["selection_layer"] == "same_platform_same_lane_work"
    assert result["coverage"]["cross_platform_reference"] == 1


def test_matching_official_activity_boosts_topic_without_becoming_native_hotspot():
    first = _item("kuaishou", "AI工作流效率实测", "same_lane_hot_work", metric=1400)
    second = _item("kuaishou", "AI办公效率清单", "same_lane_hot_work", metric=1500)
    official = _item("kuaishou", "AI工作流创作活动", "official_activity", metric=None)
    official.update({"official_reference_only": True, "native_verified": False})

    result = decide_topic(
        "kuaishou",
        [second, official, first],
        lane_keywords=["AI", "工作流", "效率"],
        now=NOW,
    )

    assert result["selected"]["title"] == first["title"]
    assert result["selected"]["official_support"][0]["title"] == official["title"]
    assert result["selected"]["native_verified"] is False
    assert result["selected"]["associated_hotspot"] is None


def test_empty_metrics_cannot_qualify_as_same_platform_viral_work():
    incomplete = _item("xiaohongshu", "AI效率工具", "same_lane_hot_work", metric=None)

    result = decide_topic(
        "xiaohongshu",
        [incomplete],
        lane_keywords=["AI", "效率"],
        now=NOW,
    )

    assert result["status"] == "insufficient"
    assert result["rejected"][0]["reason"] == "same_platform_work_metric_missing"


def test_official_keyword_can_be_selected_but_keeps_official_reference_identity():
    official = _item("wechat", "AI效率工具征集", "official_keyword", metric=None)
    official.update({"official_reference_only": True, "native_verified": False})

    result = decide_topic(
        "wechat",
        [official],
        lane_keywords=["AI", "效率"],
        now=NOW,
    )

    assert result["status"] == "selected"
    assert result["selected"]["selection_layer"] == "official_activity_or_keyword"
    assert result["selected"]["native_verified"] is False
    assert result["selected"]["associated_hotspot"] is None


def test_cross_platform_reference_alone_never_claims_target_platform_identity():
    reference = _item(
        "github",
        "AI Agent workflow",
        "native",
        metric=50_000,
        identity_role="cross_platform_reference",
    )

    result = decide_topic(
        "youtube",
        [reference],
        lane_keywords=["AI", "workflow"],
        now=NOW,
    )

    assert result["status"] == "reference_only"
    assert result["selected"] is None
    assert result["references"][0]["identity_role"] == "cross_platform_reference"


def test_overnight_due_task_persists_unified_topic_decision_before_generation():
    candidate = _item("kuaishou", "AI工作流三步实测", "same_lane_hot_work", metric=1500)
    candidate["source"] = "kuaishou:same_lane_hot_work"

    result = build_due_tasks(
        [{"platform": "kuaishou", "topic_keywords": ["AI", "工作流"]}],
        items=[candidate],
        source_report=[],
        rank_for_platform=lambda *_: [candidate],
        trend_evidence_mode="off",
    )

    task = result["tasks"][0]
    assert task["state"] == "ready_for_plan"
    assert task["topic_decision"]["version"] == "topic_decision_v1"
    assert task["topic_decision"]["selected"]["title"] == candidate["title"]
    assert task["brief"]["topic_decision"]["selection_layer"] == "same_platform_same_lane_work"
