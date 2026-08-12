"""Recoverable, serial overnight execution planning and event reporting."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .risk import redact_secrets


MANUAL_HANDOFF_PLATFORMS = {
    "bilibili",
    "douyin",
    "douyin_ai",
    "douyin_pet",
    "shipinhao",
    "xiaohongshu",
    "youtube",
    "tiktok",
}


def normalize_delivery_boundary(platform: str, requested_state: str) -> str:
    """Keep manual channels out of a published/drafted success state."""
    if str(platform or "").casefold() in MANUAL_HANDOFF_PLATFORMS:
        return "handoff_ready"
    return str(requested_state or "blocked")


def build_batch_plan(
    tasks: list[dict[str, Any]],
    *,
    start_minute: int = 0,
    deadline_minute: int = 280,
    finalization_minutes: int = 20,
) -> dict[str, Any]:
    """Create a serial schedule which fails closed before the morning window.

    ``deadline_minute`` is measured from the batch start.  The finalization
    reserve is intentionally unavailable to content work so 05:00 reporting
    cannot be starved by rendering, browser, or upload retries.
    """
    available_until = int(deadline_minute) - max(int(finalization_minutes), 0)
    cursor = int(start_minute)
    rows: list[dict[str, Any]] = []
    blocked = False
    for raw in tasks:
        estimate = max(1, int(raw.get("estimate_minutes") or 1))
        row = {**raw, "estimate_minutes": estimate, "starts_at_minute": cursor, "ends_at_minute": cursor + estimate}
        upstream_state = str(raw.get("state") or "").casefold()
        if upstream_state in {"blocked", "deferred"}:
            row["state"] = upstream_state
            if upstream_state == "blocked":
                row.setdefault("reason", "upstream planning blocked this channel")
                blocked = True
        elif cursor + estimate > available_until:
            row.update({"state": "blocked", "reason": "estimated work exceeds overnight deadline reserve"})
            blocked = True
        else:
            row["state"] = "queued"
            cursor += estimate
        rows.append(row)
    queued_count = sum(1 for row in rows if row.get("state") == "queued")
    return {
        "version": "overnight_batch_plan_v1",
        "status": "partial_capacity" if blocked and queued_count else "capacity_blocked" if blocked else "scheduled",
        "start_minute": int(start_minute),
        "deadline_minute": int(deadline_minute),
        "finalization_minutes": int(finalization_minutes),
        "work_deadline_minute": available_until,
        "remaining_minutes": max(0, available_until - cursor),
        "tasks": rows,
    }


def build_due_tasks(
    slots: list[dict[str, Any]],
    *,
    items: list[dict[str, Any]],
    source_report: list[dict[str, Any]],
    rank_for_platform: Any,
    weekday: int | None = None,
) -> dict[str, Any]:
    """Turn due-channel slots into independent, source-evidenced work rows."""
    tasks: list[dict[str, Any]] = []
    weekday = datetime.now().weekday() if weekday is None else int(weekday)
    for raw in slots:
        platform = str(raw.get("platform") or "").casefold()
        row = {**raw, "platform": platform}
        due_days = raw.get("weekdays")
        if isinstance(due_days, list) and due_days and weekday not in {int(day) for day in due_days}:
            row.update({"state": "deferred", "reason": "not scheduled for this weekday"})
            tasks.append(row)
            continue
        candidates = list(rank_for_platform(platform, items, raw) or [])
        if not platform:
            row.update({"state": "blocked", "reason": "slot has no platform"})
        elif not candidates:
            row.update({"state": "blocked", "reason": "no independently ranked topic candidate"})
        else:
            selected = candidates[0]
            matrix = {
                "platform": platform,
                "attempted_sources": [
                    {"source": item.get("source"), "status": item.get("status", "unknown"), **({"error": item["error"]} if item.get("error") else {})}
                    for item in source_report
                    if item.get("source")
                ],
                "report_path": "runtime:overnight_trend_collection",
            }
            row.update({
                "topic": selected["title"],
                "topic_fingerprint": selected.get("fingerprint", ""),
                "brief": {
                    "source": selected.get("source"),
                    "sources": [selected["url"]] if selected.get("url") else [],
                    "platform_source_matrix": matrix,
                    "topic_decision": {
                        "score": selected.get("score", 0),
                        "growth_signals": ["timeliness", "user_benefit"],
                    },
                },
                "action": raw.get("action") or ("handoff" if platform in MANUAL_HANDOFF_PLATFORMS else "stage"),
                "state": "ready_for_plan",
            })
        tasks.append(row)
    return {"version": "overnight_due_tasks_v1", "tasks": tasks, "source_report": source_report}


TERMINAL_TASK_STATES = {"staged", "handoff_ready", "published", "blocked", "failed", "deferred"}


def execute_batch(
    pipeline: Any,
    plan: dict[str, Any],
    *,
    state_path: str | Path,
    journal: "BatchEventJournal",
) -> dict[str, Any]:
    """Run one planned platform at a time and checkpoint after every result.

    The caller may restart this function after an agent, browser, or model
    process exits.  Completed platform rows are retained and never recreated.
    Publishing is deliberately not implicit: this worker can stage automatic
    channels and prepares manual channels for handoff only.
    """
    state_file = Path(state_path)
    state = _load_state(state_file, plan)
    if state.get("status") == "capacity_blocked":
        _write_state(state_file, state)
        return state

    state["status"] = "running"
    _write_state(state_file, state)
    for task in state.get("tasks", []):
        platform = str(task.get("platform") or "")
        if not platform or task.get("state") in TERMINAL_TASK_STATES:
            continue
        if task.get("state") == "blocked":
            continue

        journal.append("platform_started", platform, {"stage": task.get("stage"), "action": task.get("action", "handoff")})
        task["state"] = "running"
        _write_state(state_file, state)
        try:
            job = pipeline.create(
                str(task.get("topic") or ""),
                [platform],
                dict(task.get("brief") or {}),
                str(task.get("profile") or "default"),
            )
            task["job_id"] = str(job["id"])
            result = pipeline.run(task["job_id"])
            result_state = str(result.get("state") or "failed")
            task["pipeline_state"] = result_state

            if result_state in {"blocked", "failed", "rejected"}:
                task["state"] = result_state
                task["reason"] = str(result.get("last_error") or "pipeline did not produce a reviewable artifact")
                journal.append("platform_blocked", platform, {"job_id": task["job_id"], "state": result_state, "reason": task["reason"]})
            elif platform.casefold() in MANUAL_HANDOFF_PLATFORMS:
                task["state"] = "handoff_ready"
                journal.append("handoff_ready", platform, {"job_id": task["job_id"], "pipeline_state": result_state})
            elif str(task.get("action") or "stage") == "stage":
                staged = pipeline.stage_drafts(task["job_id"])
                task["pipeline_state"] = str(staged.get("state") or result_state)
                # ``partial`` is Pipeline's aggregate delivery result.  In a
                # single-platform overnight task it means a draft was staged,
                # not that the task should be retried indefinitely.
                delivered_state = "staged" if task["pipeline_state"] in {"partial", "drafted"} else task["pipeline_state"]
                task["state"] = normalize_delivery_boundary(platform, delivered_state)
                journal.append("platform_finished", platform, {"job_id": task["job_id"], "state": task["state"]})
            else:
                # Approval and live publication are separate, auditable actions.
                task["state"] = "review_required"
                task["reason"] = "live publication requires an explicit approved workflow"
                journal.append("platform_review_required", platform, {"job_id": task["job_id"], "state": result_state})
        except Exception as exc:  # Keep unrelated channels recoverable.
            task["state"] = "failed"
            task["reason"] = redact_secrets(str(exc))
            journal.append("platform_failed", platform, {"reason": task["reason"]})
        finally:
            _write_state(state_file, state)

    unfinished = [task for task in state.get("tasks", []) if task.get("state") not in TERMINAL_TASK_STATES]
    state["status"] = "completed" if not unfinished else "partial"
    _write_state(state_file, state)
    return state


def _load_state(path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return copy.deepcopy(plan)


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(_redact(state), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


class BatchEventJournal:
    """Append-only JSONL events that survive an agent or process restart."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: str, platform: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        row = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": str(event),
            "platform": str(platform),
            "detail": _redact(detail or {}),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row

    def latest_by_platform(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        if not self.path.is_file():
            return result
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            platform = str(row.get("platform") or "")
            if platform:
                result[platform] = row
        return result


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            name = str(key)
            if any(marker in name.casefold() for marker in ("token", "secret", "cookie", "password", "api_key")):
                result[name] = "[REDACTED]"
            else:
                result[name] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value
