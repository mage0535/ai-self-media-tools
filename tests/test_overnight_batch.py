import json
from pathlib import Path

from content_platform.overnight_batch import (
    BatchEventJournal,
    build_due_tasks,
    build_batch_plan,
    execute_batch,
    growth_strategy_snapshot_status,
    normalize_delivery_boundary,
    candidate_matches_topic_keywords,
    candidate_matches_platform_language,
    topic_keywords_for_slot,
)
from content_platform.store import Store


def test_batch_plan_schedules_all_due_work_before_morning_window():
    plan = build_batch_plan(
        [
            {"platform": "wechat", "stage": "article", "estimate_minutes": 25},
            {"platform": "kuaishou", "stage": "video", "estimate_minutes": 70},
            {"platform": "youtube", "stage": "handoff_video", "estimate_minutes": 70},
        ],
        start_minute=0,
        deadline_minute=280,
        finalization_minutes=20,
    )

    assert plan["status"] == "scheduled"
    assert plan["remaining_minutes"] >= 0
    assert [row["platform"] for row in plan["tasks"]] == ["wechat", "kuaishou", "youtube"]
    assert all(row["state"] == "queued" for row in plan["tasks"])


def test_batch_plan_fails_closed_when_all_due_work_cannot_finish_before_morning():
    plan = build_batch_plan(
        [{"platform": "kuaishou", "stage": "video", "estimate_minutes": 300}],
        start_minute=0,
        deadline_minute=280,
        finalization_minutes=20,
    )

    assert plan["status"] == "capacity_blocked"
    assert plan["tasks"][0]["state"] == "blocked"
    assert "deadline" in plan["tasks"][0]["reason"]


def test_batch_plan_runs_admitted_rows_even_when_later_rows_exceed_capacity():
    plan = build_batch_plan(
        [
            {"platform": "wechat", "estimate_minutes": 10},
            {"platform": "youtube", "estimate_minutes": 300},
        ],
        deadline_minute=280,
        finalization_minutes=20,
    )

    assert plan["status"] == "partial_capacity"
    assert plan["tasks"][0]["state"] == "queued"
    assert plan["tasks"][1]["state"] == "blocked"


def test_batch_plan_preserves_an_upstream_blocked_topic_selection():
    plan = build_batch_plan(
        [{"platform": "zhihu", "estimate_minutes": 10, "state": "blocked", "reason": "no source evidence"}],
        deadline_minute=280,
        finalization_minutes=20,
    )

    assert plan["status"] == "capacity_blocked"
    assert plan["tasks"][0]["reason"] == "no source evidence"


def test_batch_event_journal_persists_recoverable_redacted_events(tmp_path: Path):
    journal = BatchEventJournal(tmp_path / "events.jsonl")
    journal.append("platform_started", "wechat", {"token": "abc123-secret", "stage": "analysis"})
    journal.append("platform_finished", "wechat", {"state": "handoff_ready"})

    rows = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["event"] == "platform_started"
    assert "abc123-secret" not in json.dumps(rows[0])
    assert journal.latest_by_platform()["wechat"]["event"] == "platform_finished"


def test_manual_handoff_platform_cannot_be_normalized_to_published():
    assert normalize_delivery_boundary("youtube", "published") == "handoff_ready"
    assert normalize_delivery_boundary("douyin", "drafted") == "handoff_ready"
    assert normalize_delivery_boundary("kuaishou", "published") == "published"


def test_due_task_builder_selects_a_distinct_topic_for_each_due_platform():
    def rank(platform, _items, _slot):
        return [{"title": f"{platform} topic", "source": platform, "score": 3, "fingerprint": platform}]

    prepared = build_due_tasks(
        [{"platform": "wechat", "estimate_minutes": 20}, {"platform": "youtube", "estimate_minutes": 50}],
        items=[],
        source_report=[{"source": "github", "status": "ok"}],
        rank_for_platform=rank,
    )

    assert [task["topic"] for task in prepared["tasks"]] == ["wechat topic", "youtube topic"]
    assert prepared["tasks"][0]["action"] == "stage"
    assert prepared["tasks"][1]["action"] == "handoff"


def test_due_task_builder_uses_the_next_candidate_when_the_top_topic_is_already_reserved():
    def rank(_platform, _items, _slot):
        return [
            {"title": "Shared topic", "source": "github", "score": 5, "fingerprint": "shared-topic"},
            {"title": "Distinct topic", "source": "github", "score": 4, "fingerprint": "distinct-topic"},
        ]

    prepared = build_due_tasks(
        [{"platform": "wechat"}, {"platform": "kuaishou"}],
        items=[],
        source_report=[{"source": "github", "status": "ok"}],
        rank_for_platform=rank,
    )

    assert [task["topic"] for task in prepared["tasks"]] == ["Shared topic", "Distinct topic"]


def test_due_task_builder_blocks_a_duplicate_only_candidate_instead_of_reusing_it():
    def rank(_platform, _items, _slot):
        return [{"title": "Shared topic", "source": "github", "score": 5, "fingerprint": "shared-topic"}]

    prepared = build_due_tasks(
        [{"platform": "wechat"}, {"platform": "kuaishou"}],
        items=[],
        source_report=[{"source": "github", "status": "ok"}],
        rank_for_platform=rank,
    )

    assert prepared["tasks"][1]["state"] == "blocked"
    assert prepared["tasks"][1]["reason"] == "no unique cross-platform topic candidate"


def test_due_task_builder_applies_a_final_platform_candidate_filter():
    prepared = build_due_tasks(
        [{"platform": "wechat"}],
        items=[],
        source_report=[],
        rank_for_platform=lambda *_args: [{"title": "irrelevant", "fingerprint": "irrelevant"}],
        candidate_filter=lambda *_args: False,
    )

    assert prepared["tasks"][0]["state"] == "blocked"


def test_due_task_builder_blocks_when_growth_strategy_snapshot_is_missing():
    def rank(platform, _items, _slot):
        return [{"title": f"{platform} topic", "source": platform, "score": 3, "fingerprint": platform}]

    prepared = build_due_tasks(
        [{"platform": "zhihu", "estimate_minutes": 20}],
        items=[],
        source_report=[{"source": "github", "status": "ok"}],
        rank_for_platform=rank,
        growth_strategy_status={"zhihu": {"status": "missing", "key": "growth_strategy:zhihu:latest"}},
    )

    assert prepared["tasks"][0]["state"] == "blocked"
    assert prepared["tasks"][0]["reason"] == "growth strategy snapshot missing"


def test_growth_strategy_snapshot_status_reads_store_inventory(tmp_path: Path):
    store = Store(tmp_path / "state.db")
    store.save_tool_inventory("growth_strategy:wechat:latest", {"policy_id": "growth_quality_policy_v1"})

    status = growth_strategy_snapshot_status(store, ["wechat", "zhihu"])

    assert status["wechat"]["status"] == "ok"
    assert status["zhihu"] == {"status": "missing", "key": "growth_strategy:zhihu:latest"}


def test_growth_strategy_snapshot_status_maps_twitter_to_the_x_strategy_snapshot(tmp_path: Path):
    store = Store(tmp_path / "state.db")
    store.save_tool_inventory("growth_strategy:x:latest", {"policy_id": "growth_quality_policy_v1"})

    status = growth_strategy_snapshot_status(store, ["twitter"])

    assert status["twitter"]["status"] == "ok"
    assert status["twitter"]["key"] == "growth_strategy:x:latest"


def test_pet_lane_rejects_an_unrelated_general_news_candidate():
    keywords = topic_keywords_for_slot("douyin_pet", {}, {"keywords": ["AI"]})

    assert candidate_matches_topic_keywords({"title": "Facebook pays controversial rage-bait creators"}, keywords) is False
    assert candidate_matches_topic_keywords({"title": "Three signs your cat is stressed"}, keywords) is True


def test_ai_keyword_does_not_match_a_substring_inside_an_unrelated_word():
    assert candidate_matches_topic_keywords({"title": "Facebook pays rage-bait creators"}, ["ai"]) is False
    assert candidate_matches_topic_keywords({"title": "AI agents change workflows"}, ["ai"]) is True


def test_english_platform_rejects_a_chinese_headline_even_when_it_mentions_ai():
    assert candidate_matches_platform_language("twitter", {"title": "如何看待 AIGC 工具"}) is False
    assert candidate_matches_platform_language("twitter", {"title": "AI agents change team workflows"}) is True


def test_execute_batch_runs_each_platform_independently_and_persists_resume_state(tmp_path: Path):
    class Pipeline:
        def __init__(self):
            self.created = []

        def create(self, topic, platforms, brief, profile="default"):
            self.created.append((topic, platforms, brief, profile))
            return {"id": f"job-{len(self.created)}"}

        def run(self, job_id):
            return {"id": job_id, "state": "review_required"}

        def stage_drafts(self, job_id):
            return {"id": job_id, "state": "partial"}

    plan = build_batch_plan(
        [
            {"platform": "wechat", "topic": "WeChat topic", "brief": {}, "stage": "article", "estimate_minutes": 10, "action": "stage"},
            {"platform": "youtube", "topic": "YouTube topic", "brief": {}, "stage": "handoff_video", "estimate_minutes": 10},
        ],
        deadline_minute=280,
        finalization_minutes=20,
    )
    pipeline = Pipeline()
    state_path = tmp_path / "state.json"
    summary = execute_batch(pipeline, plan, state_path=state_path, journal=BatchEventJournal(tmp_path / "events.jsonl"))

    assert summary["status"] == "completed"
    assert [item[1] for item in pipeline.created] == [["wechat"], ["youtube"]]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["tasks"][0]["state"] == "staged"
    assert state["tasks"][1]["state"] == "handoff_ready"
