import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from content_platform.chinese_reporter import ChineseReporter
from content_platform.overnight_batch import (
    BatchEventJournal,
    build_batch_plan,
    execute_batch,
    exclusive_batch_owner,
)
from content_platform.overnight_supervisor import inspect_batch_health
from content_platform.workflow_runtime import WORKFLOW_STAGES, WorkflowStateMachine


def test_workflow_state_machine_enforces_explicit_order_and_one_active_platform():
    machine = WorkflowStateMachine()

    machine.begin_platform("wechat")
    with pytest.raises(RuntimeError, match="one active platform"):
        machine.begin_platform("xiaohongshu")
    for stage in WORKFLOW_STAGES[1:]:
        machine.complete_stage(stage)

    assert machine.platform_state("wechat")["state"] == "completed"
    machine.begin_platform("xiaohongshu")
    assert machine.active_platform == "xiaohongshu"


def test_execute_batch_stops_after_same_platform_repair_limit(tmp_path: Path):
    class Pipeline:
        def __init__(self):
            self.created = []
            self.runs = []

        def create(self, topic, platforms, brief, profile="default"):
            self.created.append(platforms)
            return {"id": "job-wechat"}

        def run(self, job_id):
            self.runs.append(job_id)
            raise RuntimeError("provider timeout")

    pipeline = Pipeline()
    plan = build_batch_plan(
        [
            {"platform": "wechat", "topic": "topic-a", "brief": {}, "estimate_minutes": 10},
            {"platform": "youtube", "topic": "topic-b", "brief": {}, "estimate_minutes": 10},
        ],
        deadline_minute=280,
        finalization_minutes=20,
    )

    result = execute_batch(
        pipeline,
        plan,
        state_path=tmp_path / "state.json",
        journal=BatchEventJournal(tmp_path / "events.jsonl"),
    )

    assert result["status"] == "failed"
    assert result["tasks"][0]["state"] == "failed"
    assert result["tasks"][0]["repair_rounds"] == 2
    assert result["tasks"][1]["state"] == "queued"
    assert pipeline.created == [["wechat"]]
    assert pipeline.runs == ["job-wechat"] * 3


def test_recovery_and_runtime_retry_share_one_persisted_repair_counter(tmp_path: Path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "status": "running",
                "tasks": [
                    {
                        "platform": "wechat",
                        "state": "running",
                        "topic": "topic-a",
                        "repair_attempts": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class Pipeline:
        def create(self, *_args, **_kwargs):
            return {"id": "job-wechat"}

        def run(self, _job_id):
            raise RuntimeError("provider timeout")

    result = execute_batch(
        Pipeline(),
        build_batch_plan([{"platform": "wechat", "topic": "topic-a", "brief": {}, "estimate_minutes": 10}]),
        state_path=state_path,
        journal=BatchEventJournal(tmp_path / "events.jsonl"),
    )

    assert result["status"] == "failed"
    assert result["tasks"][0]["repair_attempts"] == 2
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["tasks"][0]["repair_attempts"] == 2
    assert "retry_count" not in persisted["tasks"][0]
    assert "recovery_count" not in persisted["tasks"][0]


def test_batch_owner_lease_rejects_a_second_live_worker(tmp_path: Path):
    lock_path = tmp_path / "overnight.owner.lock"
    with exclusive_batch_owner(lock_path):
        with pytest.raises(RuntimeError, match="another overnight worker"):
            with exclusive_batch_owner(lock_path):
                pass


def test_execute_batch_persists_job_and_stage_before_next_runtime_call(tmp_path: Path):
    state_path = tmp_path / "state.json"
    observed = []

    class Pipeline:
        def create(self, *_args, **_kwargs):
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            observed.append((saved["tasks"][0].get("job_id"), saved["tasks"][0]["workflow"]["completed_stages"]))
            return {"id": "job-wechat"}

        def run(self, job_id):
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            observed.append((job_id, saved["tasks"][0].get("job_id"), saved["tasks"][0]["workflow"]["completed_stages"]))
            return {"id": job_id, "state": "review_required", "artifacts": []}

        def stage_drafts(self, _job_id):
            return {"state": "partial"}

    result = execute_batch(
        Pipeline(),
        build_batch_plan([{"platform": "wechat", "topic": "topic-a", "brief": {}, "action": "stage", "estimate_minutes": 10}]),
        state_path=state_path,
        journal=BatchEventJournal(tmp_path / "events.jsonl"),
    )

    assert result["status"] == "completed"
    assert observed[0][0] is None
    assert observed[0][1] == ["planned", "collecting", "selecting"]
    assert observed[1][0:2] == ("job-wechat", "job-wechat")
    assert "generating" not in observed[1][2]


def test_resume_uses_persisted_job_and_completed_stages_without_repeating_them(tmp_path: Path):
    state_path = tmp_path / "state.json"
    workflow = {
        "state": "rendering",
        "completed_stages": ["planned", "collecting", "selecting", "generating", "rendering"],
        "stage_outputs": {},
        "repair_attempts": 0,
    }
    state_path.write_text(
        json.dumps(
            {
                "status": "partial",
                "tasks": [
                    {
                        "platform": "wechat",
                        "state": "retry_pending",
                        "topic": "topic-a",
                        "action": "stage",
                        "job_id": "job-existing",
                        "pipeline_result": {"id": "job-existing", "state": "review_required", "artifacts": []},
                        "workflow": workflow,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class Pipeline:
        def create(self, *_args, **_kwargs):
            raise AssertionError("resume must not recreate an existing job")

        def run(self, _job_id):
            raise AssertionError("resume must not rerun a completed generation stage")

        def stage_drafts(self, job_id):
            return {"id": job_id, "state": "partial"}

    result = execute_batch(
        Pipeline(),
        build_batch_plan([{"platform": "wechat", "topic": "topic-a", "brief": {}, "action": "stage", "estimate_minutes": 10}]),
        state_path=state_path,
        journal=BatchEventJournal(tmp_path / "events.jsonl"),
    )

    assert result["status"] == "completed"
    assert result["tasks"][0]["job_id"] == "job-existing"


def test_workflow_checkpoint_skips_completed_collection_tts_assets_and_render():
    machine = WorkflowStateMachine()
    machine.begin_platform("wechat")
    calls = []
    for stage in ("collecting", "selecting", "generating", "rendering"):
        machine.run_checkpointed(stage, lambda stage=stage: calls.append(stage) or stage)

    machine2 = WorkflowStateMachine(machine.to_dict())
    for stage in ("collecting", "selecting", "generating", "rendering"):
        machine2.run_checkpointed(stage, lambda: calls.append("repeated"))

    assert calls == ["collecting", "selecting", "generating", "rendering"]
    assert machine2.platform_state("wechat")["completed_stages"] == [
        "planned", "collecting", "selecting", "generating", "rendering"
    ]


def test_supervisor_authorizes_stale_recovery_only_with_dead_pid_and_expired_lease(tmp_path: Path):
    now = datetime(2026, 8, 25, 1, 0, tzinfo=timezone.utc)
    state = tmp_path / "state.json"
    heartbeat = tmp_path / "heartbeat.json"
    state.write_text(
        json.dumps(
            {
                "status": "running",
                "worker": {"pid": 4321, "owner": "worker-a", "lease_expires_at": (now - timedelta(minutes=5)).isoformat()},
                "tasks": [{"platform": "wechat", "state": "generating"}],
            }
        ),
        encoding="utf-8",
    )
    heartbeat.write_text(json.dumps({"at": (now - timedelta(minutes=31)).isoformat(), "platform": "wechat"}), encoding="utf-8")

    report = inspect_batch_health(
        state,
        heartbeat,
        now=now,
        stale_after_seconds=1800,
        pid_checker=lambda _pid: False,
    )

    assert report["status"] == "stale"
    assert report["recovery_authorized"] is True
    assert report["proof"]["pid_dead"] is True
    assert report["proof"]["lease_expired"] is True


def test_supervisor_does_not_authorize_or_mutate_a_living_owner(tmp_path: Path):
    now = datetime(2026, 8, 25, 1, 0, tzinfo=timezone.utc)
    state = tmp_path / "state.json"
    heartbeat = tmp_path / "heartbeat.json"
    original = {
        "status": "running",
        "worker": {"pid": 4321, "owner": "worker-a", "lease_expires_at": (now - timedelta(minutes=5)).isoformat()},
        "tasks": [{"platform": "wechat", "state": "generating"}],
    }
    state.write_text(json.dumps(original), encoding="utf-8")
    heartbeat.write_text(json.dumps({"at": (now - timedelta(minutes=31)).isoformat(), "platform": "wechat"}), encoding="utf-8")

    report = inspect_batch_health(state, heartbeat, now=now, pid_checker=lambda _pid: True)

    assert report["recovery_authorized"] is False
    assert json.loads(state.read_text(encoding="utf-8")) == original


def test_chinese_reporter_describes_business_fields_without_raw_event_syntax_or_secrets(tmp_path: Path):
    events = tmp_path / "events.jsonl"
    cursor = tmp_path / "reporter.cursor.json"
    journal = BatchEventJournal(events)
    journal.append(
        "platform_stage_progress",
        "wechat",
        {
            "stage": "selecting",
            "action": "查询平台原生热点",
            "query": "AI 工作流",
            "candidate_count": 6,
            "selected_topic": "团队自动化复盘",
            "selection_reason": "来源强且与账号赛道匹配",
            "tool_calls": ["native_search"],
            "token": "secret-value",
        },
    )
    journal.append(
        "platform_completed",
        "wechat",
        {
            "stage": "postchecking",
            "delivery_receipt": "receipt-123",
            "gate": {"passed": True},
        },
    )

    messages = ChineseReporter(events, cursor).consume()
    joined = "\n".join(messages)
    assert "微信" in joined
    assert "查询平台原生热点" in joined
    assert "候选 6" in joined
    assert "团队自动化复盘" in joined
    assert "来源强且与账号赛道匹配" in joined
    assert "native_search" in joined
    assert "receipt-123" in joined
    assert "secret-value" not in joined
    assert "platform_stage_progress" not in joined
    assert "{\"" not in joined


def test_chinese_reporter_distinguishes_progress_stale_completed_and_terminal(tmp_path: Path):
    events = tmp_path / "events.jsonl"
    cursor = tmp_path / "cursor.json"
    rows = [
        {"event": "stage_progress", "platform": "wechat", "detail": {"stage": "rendering", "progress": "已完成 2/3 个镜头", "heartbeat_age_seconds": 20}},
        {"event": "stage_heartbeat_stale", "platform": "wechat", "detail": {"stage": "rendering", "heartbeat_age_seconds": 1900}},
        {"event": "platform_completed", "platform": "wechat", "detail": {"stage": "completed"}},
        {"event": "platform_failed", "platform": "youtube", "detail": {"stage": "gating", "root_cause": "质量门禁未通过", "repair_round": 2}},
    ]
    events.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")

    messages = ChineseReporter(events, cursor).consume()
    joined = "\n".join(messages)
    assert "正在推进" in joined
    assert "心跳已超时" in joined
    assert "已完成" in joined
    assert "已终止" in joined
    assert "质量门禁未通过" in joined


def test_chinese_reporter_restart_is_idempotent_and_handles_appended_events(tmp_path: Path):
    events = tmp_path / "events.jsonl"
    cursor = tmp_path / "cursor.json"
    events.write_text(json.dumps({"event": "platform_started", "platform": "wechat", "detail": {"stage": "collecting"}}) + "\n", encoding="utf-8")
    reporter = ChineseReporter(events, cursor)

    first = reporter.consume()
    assert first
    assert reporter.consume() == []

    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "platform_finished", "platform": "wechat", "detail": {"stage": "completed"}}) + "\n")
    second = ChineseReporter(events, cursor).consume()

    assert len(second) == 1
    assert "已完成" in second[0]
