from datetime import datetime, timezone

from content_platform.platform_intelligence_status import build_platform_intelligence_runtime_snapshot


def _registry():
    return {"version": "test", "policy_profile": "real_world_ai_implementation_v1",
            "policy_revision": "2026-09-16-universal-ai-lane-r2", "platforms": {"bilibili": {"capabilities": {
        "topic_discovery": {"enabled": True}, "work_level_metrics": {"enabled": False},
        "deep_content_analysis": {"enabled": False}, "automated_learning": {"enabled": False},
    }}, "douyin_ai": {"capabilities": {
        "topic_discovery": {"enabled": True}, "work_level_metrics": {"enabled": False},
        "deep_content_analysis": {"enabled": False}, "automated_learning": {"enabled": False},
    }}}}


def test_runtime_snapshot_distinguishes_source_health_from_capability_and_signal_count():
    bundle = {"version": "platform_hot_evidence_bundle_v1",
              "policy_profile": "real_world_ai_implementation_v1",
              "policy_revision": "2026-09-16-universal-ai-lane-r2",
              "observed_at": "2026-09-15T07:15:35+00:00", "sources": [
        {"platform": "bilibili", "source": "bilibili_popular_api", "status": "ok", "count": 0},
        {"platform": "douyin", "source": "douyin_public_hot_page", "status": "ok", "count": 0},
    ], "items": [{"platform": "bilibili"}]}
    result = build_platform_intelligence_runtime_snapshot(
        registry=_registry(), bundle=bundle, now=datetime.fromisoformat("2026-09-15T07:15:36+00:00")
    )
    assert result["platforms"]["bilibili"]["runtime_collection"]["state"] == "fresh_usable"
    assert result["platforms"]["bilibili"]["runtime_collection"]["accepted_item_count"] == 1
    assert result["platforms"]["douyin_ai"]["runtime_collection"]["state"] == "fresh_empty"


def test_runtime_snapshot_rejects_naive_stale_and_future_timestamps():
    now = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    source = [{"platform": "bilibili", "source": "x", "status": "ok", "count": 1}]
    for observed_at, expected in [
        ("2026-09-15T10:00:00", "invalid_snapshot"),
        ("2026-09-13T10:00:00+00:00", "stale"),
        ("2026-09-16T10:00:00+00:00", "future_timestamp"),
    ]:
        result = build_platform_intelligence_runtime_snapshot(
            registry=_registry(), bundle={"version": "platform_hot_evidence_bundle_v1",
                "policy_profile": "real_world_ai_implementation_v1",
                "policy_revision": "2026-09-16-universal-ai-lane-r2",
                "observed_at": observed_at, "sources": source, "items": [{"platform": "bilibili"}]}, now=now
        )
        assert result["platforms"]["bilibili"]["runtime_collection"]["state"] == expected
        assert result["platforms"]["bilibili"]["runtime_collection"]["usable_for_generation_context"] is False


def test_runtime_snapshot_blocks_policy_or_revision_mismatch():
    now = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)
    base = {
        "version": "platform_hot_evidence_bundle_v1",
        "policy_profile": "real_world_ai_implementation_v1",
        "policy_revision": "2026-09-16-universal-ai-lane-r2",
        "observed_at": "2026-09-15T11:00:00+00:00",
        "sources": [{"platform": "bilibili", "source": "x", "status": "ok", "count": 1}],
        "items": [{"platform": "bilibili"}],
    }
    for field, bad_value in (("policy_profile", "old_profile"), ("policy_revision", "old_revision"), ("version", "old_bundle")):
        bundle = {**base, field: bad_value}
        result = build_platform_intelligence_runtime_snapshot(registry=_registry(), bundle=bundle, now=now)
        runtime = result["platforms"]["bilibili"]["runtime_collection"]
        assert runtime["state"] == "version_mismatch"
        assert runtime["usable_for_generation_context"] is False
