from datetime import datetime, timezone
import json
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from content_platform.trend_intelligence import (
    build_platform_matrix,
    calibrate_candidates,
    collect_daily_snapshot,
    detect_breakouts,
)
from content_platform.trends import rank_trends


FIXED_NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


def test_collect_daily_snapshot_reuses_a_fresh_cache(tmp_path):
    calls = []

    def collect():
        calls.append(True)
        return {
            "items": [{"title": "Agent workflow", "source": "github", "points": 12}],
            "sources": [{"source": "github", "status": "ok", "count": 1}],
        }

    first = collect_daily_snapshot(collect, cache_dir=tmp_path, now=FIXED_NOW)
    second = collect_daily_snapshot(collect, cache_dir=tmp_path, now=FIXED_NOW)

    assert len(calls) == 1
    assert first["cache_status"] == "refreshed"
    assert second["cache_status"] == "reused"
    assert first["items"] == second["items"]


def test_collect_daily_snapshot_honors_force_refresh(tmp_path):
    calls = []

    def collect():
        calls.append(True)
        return {"items": [{"title": f"Agent workflow {len(calls)}", "source": "github"}], "sources": []}

    collect_daily_snapshot(collect, cache_dir=tmp_path, now=FIXED_NOW)
    refreshed = collect_daily_snapshot(collect, cache_dir=tmp_path, now=FIXED_NOW, force_refresh=True)

    assert len(calls) == 2
    assert refreshed["cache_status"] == "refreshed"
    assert refreshed["items"][0]["title"] == "Agent workflow 2"


def test_platform_matrix_preserves_failures_and_platform_reason():
    snapshot = {
        "collected_at": "2026-08-16T00:00:00+00:00",
        "items": [{"title": "Agent workflow guide", "source": "zhihu_hot", "points": 16}],
        "sources": [
            {"source": "zhihu_hot", "status": "ok", "count": 1},
            {"source": "github", "status": "ok", "count": 1},
            {"source": "search", "status": "failed", "count": 0, "error": "timeout"},
        ],
    }

    matrix = build_platform_matrix(
        "zhihu",
        snapshot,
        snapshot["items"][0],
        platform_keywords=["agent", "workflow"],
    )

    assert matrix["sources_attempted"] == 3
    assert matrix["sources_succeeded"] == 2
    assert matrix["platform_internal_verified"] is True
    assert matrix["platform_fit_reason"]
    assert matrix["attempted_sources"][2]["status"] == "failed"


def test_platform_matrix_does_not_use_fresh_account_strategy_as_trend_evidence():
    snapshot = {
        "items": [{"title": "Agent workflow guide", "source": "hackernews", "points": 16}],
        "sources": [
            {"source": "hackernews", "status": "ok", "count": 1},
            {"source": "zhihu", "status": "ok", "count": 1},
            {"source": "bilibili", "status": "ok", "count": 1},
        ],
    }

    matrix = build_platform_matrix(
        "twitter",
        snapshot,
        snapshot["items"][0],
        platform_keywords=["agent", "workflow"],
        strategy_status={"status": "ok", "key": "growth_strategy:twitter:latest", "age_hours": 0.2},
    )

    assert matrix["platform_internal_verified"] is False
    assert matrix["platform_strategy_verified"] is True
    assert matrix["current_platform_specific_topic"] is False
    assert matrix["real_platform_collection_verified"] is False
    assert matrix["shared_trend_only"] is True
    assert matrix["trend_evidence"]["samples"] == []


def test_platform_matrix_accepts_a_real_source_transport_suffix_for_douyin_ai():
    snapshot = {
        "collected_at": "2026-08-16T00:00:00+00:00",
        "items": [{"title": "AI short video workflow", "source": "douyin:web_search", "url": "https://www.douyin.com/search/ai", "points": 16}],
        "sources": [{"source": "douyin", "status": "ok", "count": 1}],
    }

    matrix = build_platform_matrix("douyin_ai", snapshot, snapshot["items"][0], platform_keywords=["ai"])

    assert matrix["real_platform_collection_verified"] is True
    assert matrix["trend_evidence"]["source"] == "douyin:web_search"


def test_platform_matrix_rejects_external_url_for_platform_web_search_transport():
    snapshot = {
        "collected_at": "2026-08-16T00:00:00+00:00",
        "items": [{"title": "AI short video workflow", "source": "douyin:web_search", "url": "https://zhuanlan.zhihu.com/p/42", "points": 16}],
        "sources": [{"source": "douyin", "status": "ok", "count": 1}],
    }

    matrix = build_platform_matrix("douyin_ai", snapshot, snapshot["items"][0], platform_keywords=["ai"])

    assert matrix["real_platform_collection_verified"] is False
    assert matrix["trend_evidence"]["samples"] == []
    assert matrix["candidate_source_url_native"] is False


def test_calibrate_candidates_rewards_proven_history_without_hiding_missing_history():
    ranked = calibrate_candidates(
        [
            {"title": "Agent workflow", "source": "github", "score": 1.2},
            {"title": "Other topic", "source": "other", "score": 1.2},
        ],
        {"preferred_sources": {"github": 0.4}, "preferred_clusters": [{"label": "agent", "weight": 0.3}]},
    )

    assert ranked[0]["title"] == "Agent workflow"
    assert ranked[0]["historical_fit_score"] > 0
    assert ranked[0]["calibrated_score"] > ranked[0]["score"]
    assert ranked[1]["historical_fit_score"] == 0


def test_detect_breakouts_marks_material_score_growth():
    previous = {"items": [{"title": "Agent workflow", "points": 10}]}
    current = {"items": [{"title": "Agent workflow", "points": 50}]}

    items = detect_breakouts(current, previous)

    assert items[0]["breakout"] is True
    assert items[0]["breakout_delta"] == 40


def test_rank_trends_excludes_unavailable_source_fallbacks():
    ranked = rank_trends(
        [
            {"title": "Real agent workflow", "source": "github", "points": 3},
            {"title": "Unavailable agent hypothesis", "source": "douyin:source_fallback", "points": 99, "source_unavailable": True},
        ],
        {"keywords": ["agent"], "source_weights": {"github": 1, "douyin:source_fallback": 10}},
    )

    assert [row["title"] for row in ranked] == ["Real agent workflow"]


def test_overnight_prepare_uses_snapshot_and_platform_specific_matrix(tmp_path, monkeypatch):
    from content_platform.cli import main
    from content_platform.store import Store

    monkeypatch.setenv("CONTENT_PLATFORM_TREND_CACHE_DIR", str(tmp_path / "trend-cache"))
    store = Store(tmp_path / "state.db")
    store.save_tool_inventory("growth_strategy:zhihu:latest", {"policy_id": "test"})
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"profiles": {"default": {"keywords": ["agent"], "source_weights": {"zhihu_hot": 3}}}}),
        encoding="utf-8",
    )
    slots = tmp_path / "slots.json"
    slots.write_text(json.dumps({"slots": [{"platform": "zhihu", "topic_keywords": ["agent"]}]}), encoding="utf-8")
    output = tmp_path / "prepared.json"
    report = {
        "items": [{"title": "Agent workflow guide", "source": "zhihu_hot", "points": 50}],
        "sources": [
            {"source": "zhihu_hot", "status": "ok", "count": 1},
            {"source": "github", "status": "ok", "count": 1},
            {"source": "bilibili", "status": "ok", "count": 1},
            {"source": "hackernews", "status": "ok", "count": 1},
            {"source": "account_history", "status": "ok", "count": 1},
        ],
    }

    with patch("content_platform.cli.TrendCollector.collect_with_report", return_value=report):
        with redirect_stdout(StringIO()):
            assert main(["--db", str(tmp_path / "state.db"), "--config", str(config), "overnight-prepare", "--slots", str(slots), "--output", str(output), "--weekday", "2"]) == 0

    prepared = json.loads(output.read_text(encoding="utf-8"))
    matrix = prepared["tasks"][0]["brief"]["platform_source_matrix"]
    assert matrix["platform"] == "zhihu"
    assert matrix["platform_internal_verified"] is True
    assert matrix["sources_succeeded"] == 5
    assert matrix["platform_fit_reason"]
    assert matrix["real_platform_collection_verified"] is True
    assert matrix["trend_evidence"]["collected_at"]
    assert "trend_snapshot_" in matrix["report_path"]
