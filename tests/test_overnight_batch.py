import json
from pathlib import Path

from content_platform.overnight_batch import (
    BatchEventJournal,
    build_due_tasks,
    build_batch_plan,
    execute_batch,
    normalize_delivery_boundary,
)


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
