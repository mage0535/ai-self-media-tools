import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_platform.associated_hotspot import (
    build_associated_hotspot,
    persist_associated_hotspot,
)
from content_platform.official_reference_signals import build_reference_items
from content_platform.trend_intelligence import (
    SCHEDULED_PLATFORM_INTELLIGENCE_PLATFORMS,
    bounded_same_platform_recapture,
    expire_abandoned_reservations,
    rank_platform_candidates,
    reserve_topic_atomically,
    validate_platform_candidate,
)
from content_platform.overnight_batch import build_due_tasks


FIXTURE = Path(__file__).parent / "fixtures" / "platform_intelligence_task5.json"
NOW = datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc)


def _candidate(platform, evidence_type, title=None, **extra):
    return {
        "platform": platform,
        "title": title or f"{platform} practical topic",
        "source": platform,
        "url": f"https://{platform}.example/topic",
        "captured_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=6)).isoformat(),
        "evidence_type": evidence_type,
        "lane": next((row["lane"] for row in json.loads(FIXTURE.read_text(encoding="utf-8"))["platforms"] if row["platform"] == platform), "other_lane"),
        "lane_fit_score": 0.9,
        "semantic_fit_score": 0.85,
        "heat_score": 0.8,
        "rank": 1,
        "velocity_score": 0.7,
        "content_value_score": 0.9,
        "actionability_score": 0.85,
        "saturation_score": 0.1,
        "account_history_score": 0.4,
        **extra,
    }


def test_fixture_covers_all_scheduled_platforms_and_evidence_types():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = payload["platforms"]
    assert {row["platform"] for row in rows} == set(SCHEDULED_PLATFORM_INTELLIGENCE_PLATFORMS)
    assert {row["evidence_type"] for row in rows} >= {
        "native", "official_activity", "official_keyword", "same_lane_hot_work"
    }
    assert set(payload["negative_outcomes"]) == {"unavailable", "expired"}


@pytest.mark.parametrize("platform", SCHEDULED_PLATFORM_INTELLIGENCE_PLATFORMS)
def test_candidate_platform_is_exact_task_platform(platform):
    candidate = _candidate(platform, "native")
    assert validate_platform_candidate(candidate, platform, now=NOW)["passed"] is True
    mismatch = validate_platform_candidate({**candidate, "platform": "other"}, platform, now=NOW)
    assert mismatch["passed"] is False
    assert "candidate_platform_mismatch" in mismatch["failures"]


def test_official_reference_is_scoring_context_not_native_identity(tmp_path):
    matrix = {"platforms": [{
        "platform": "wechat",
        "status": "verified",
        "signal_type": "official_keyword",
        "signals": ["AI workflow keyword"],
        "official_url": "https://mp.weixin.qq.com/s/1",
        "captured_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=4)).isoformat(),
    }]}
    path = tmp_path / "overnight" / "2026-08-25" / "official-platform-signal-matrix-v3.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(matrix), encoding="utf-8")
    evidence, items = build_reference_items("wechat", data_dir=tmp_path)
    assert evidence["evidence_type"] == "official_keyword"
    assert items[0]["platform"] == "wechat"
    assert items[0]["official_reference_only"] is True
    assert items[0]["native_verified"] is False
    assert items[0]["evidence_type"] == "official_keyword"


def test_ranking_rejects_expired_and_cross_platform_candidates_and_records_breakdown():
    rows = [
        _candidate("wechat", "native", "Native useful workflow"),
        _candidate("kuaishou", "native", "Wrong platform identity"),
        _candidate("wechat", "official_activity", "Expired official", expires_at=(NOW - timedelta(minutes=1)).isoformat()),
    ]
    ranked = rank_platform_candidates(rows, "wechat", lane_keywords=["workflow"], now=NOW)
    assert [row["title"] for row in ranked] == ["Native useful workflow"]
    assert set(ranked[0]["score_breakdown"]) >= {"native_priority", "heat", "rank", "velocity", "validity", "lane_fit", "semantic_fit", "content_value", "actionability", "saturation", "account_history"}
    assert ranked[0]["evidence"]["url"]
    assert ranked[0]["evidence"]["captured_at"]
    assert ranked[0]["evidence"]["source"] == "wechat"
    assert ranked[0]["evidence"]["evidence_hash"]
    assert 0 <= ranked[0]["evidence"]["confidence"] <= 1


def test_unavailable_evidence_is_not_a_valid_candidate():
    result = validate_platform_candidate(_candidate("wechat", "unavailable"), "wechat", now=NOW)
    assert result["passed"] is False
    assert "candidate_unavailable" in result["failures"]


def test_bounded_recapture_records_attempts_and_never_returns_foreign_identity():
    calls = []

    def recapture(platform, attempt):
        calls.append((platform, attempt))
        return [_candidate("other", "native")] if attempt == 1 else [_candidate(platform, "same_lane_hot_work")]

    result = bounded_same_platform_recapture("wechat", recapture, max_attempts=3, now=NOW)
    assert calls == [("wechat", 1), ("wechat", 2)]
    assert result["attempts"] == [{"attempt": 1, "candidate_count": 0}, {"attempt": 2, "candidate_count": 1}]
    assert result["candidates"][0]["platform"] == "wechat"


def test_topic_reservation_is_global_semantic_and_expiration_is_explicit(tmp_path):
    ledger = tmp_path / "topic-reservations.json"
    first = reserve_topic_atomically(ledger, "AI workflow checklist", "wechat", "job-1", now=NOW)
    assert first["reserved"] is True
    duplicate = reserve_topic_atomically(ledger, "AI workflow checklists", "tiktok", "job-2", now=NOW)
    assert duplicate["reserved"] is False
    stale = reserve_topic_atomically(ledger, "Old topic", "twitter", "job-3", now=NOW - timedelta(days=8), ttl_hours=1)
    assert stale["reserved"] is True
    expired = expire_abandoned_reservations(ledger, now=NOW)
    assert expired[0]["status"] == "expired"


def test_hotspot_persistence_contains_identity_evidence_validity_lane_mode_and_postcheck(tmp_path):
    hotspot = build_associated_hotspot(
        _candidate("zhihu", "official_activity", "Reasoned answer hotspot"),
        platform="zhihu",
        association_mode="manual_handoff",
        now=NOW,
        postcheck_state="pending",
    )
    saved = persist_associated_hotspot(tmp_path / "hotspots.json", hotspot)
    assert saved["hotspot_id"]
    assert saved["platform"] == "zhihu"
    assert saved["evidence_type"] == "official_activity"
    assert saved["validity"] == "valid"
    assert saved["lane"]
    assert saved["semantic_fit_score"] == 0.85
    assert saved["association_mode"] == "manual_handoff"
    assert saved["postcheck_state"] == "pending"


def test_due_tasks_fallback_is_labeled_and_keeps_scheduled_platform():
    result = build_due_tasks(
        [{
            "platform": "tiktok",
            "editorial_fallback": {
                "topic": "A planned evergreen workflow guide",
                "strategy_source": "growth_strategy:tiktok:latest",
                "calendar_column": "evergreen",
                "planned_for": NOW.date().isoformat(),
                "dedupe_passed": True,
            },
        }],
        items=[],
        source_report=[],
        rank_for_platform=lambda *_: [],
        strict_trend_evidence=True,
    )
    task = result["tasks"][0]
    assert task["platform"] == "tiktok"
    assert task["state"] == "ready_for_plan"
    assert task["selection_mode"] == "editorial_calendar"
    assert task["brief"]["editorial_evidence"]["strategy_source"]
