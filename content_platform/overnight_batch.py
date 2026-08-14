"""Recoverable, serial overnight execution planning and event reporting."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .risk import redact_secrets
from .trends import normalize_topic
from .trend_candidate import build_trend_candidate, validate_trend_candidate


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

# Publishing keeps the historical ``twitter`` identifier, while analytics and
# strategy snapshots use the canonical X key.  Keep the two concerns aligned
# without changing the publisher-facing platform name.
STRATEGY_PLATFORM_ALIASES = {"twitter": "x"}

# A source's popularity is not enough to make it a channel topic.  These
# defaults prevent a general-news item from being turned into an AI or pet
# account post when a private slot does not provide narrower keywords.
PLATFORM_TOPIC_KEYWORDS = {
    "douyin_pet": ("pet", "cat", "dog", "animal", "宠物", "猫", "狗", "动物"),
    "douyin_ai": ("ai", "agent", "automation", "人工智能", "智能体", "自动化"),
}
DEFAULT_AI_TOPIC_KEYWORDS = ("ai", "agent", "automation", "llm", "model", "人工智能", "智能体", "自动化", "大模型")


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
    candidate_filter: Any | None = None,
    growth_strategy_status: dict[str, dict[str, Any]] | None = None,
    weekday: int | None = None,
    strict_trend_evidence: bool = False,
) -> dict[str, Any]:
    """Turn due-channel slots into independent, source-evidenced work rows."""
    tasks: list[dict[str, Any]] = []
    selected_topics: dict[str, dict[str, str]] = {}
    growth_strategy_status = growth_strategy_status or {}
    weekday = datetime.now().weekday() if weekday is None else int(weekday)
    for raw in slots:
        platform = str(raw.get("platform") or "").casefold()
        row = {**raw, "platform": platform}
        strategy = growth_strategy_status.get(platform) or {}
        due_days = raw.get("weekdays")
        if isinstance(due_days, list) and due_days and weekday not in {int(day) for day in due_days}:
            row.update({"state": "deferred", "reason": "not scheduled for this weekday"})
            tasks.append(row)
            continue
        if strategy.get("status") in {"missing", "stale"}:
            row.update({"state": "blocked", "reason": f"growth strategy snapshot {strategy['status']}", "growth_strategy_key": strategy.get("key", "")})
            tasks.append(row)
            continue
        candidates = list(rank_for_platform(platform, items, raw) or [])
        if candidate_filter is not None:
            candidates = [candidate for candidate in candidates if candidate_filter(platform, candidate, raw)]
        if not platform:
            row.update({"state": "blocked", "reason": "slot has no platform"})
        elif not candidates:
            row.update({"state": "blocked", "reason": "no independently ranked topic candidate"})
        else:
            selected = None
            for candidate in candidates:
                identity = _topic_identity(candidate)
                previous = selected_topics.get(identity)
                if previous is None or _allows_evidenced_overlap(platform, candidate, raw, previous, source_report, strategy):
                    selected = candidate
                    break
            if not selected:
                row.update({
                    "state": "blocked",
                    "reason": "no independently evidenced cross-platform topic candidate",
                })
                tasks.append(row)
                continue
            adaptation = str(raw.get("platform_adaptation_reason") or f"adapt {selected['title']} to {platform} with a platform-specific format and CTA")
            signal = str(raw.get("platform_signal") or f"{platform} source matrix contains current platform and cross-platform evidence")
            trend_candidate = build_trend_candidate(
                platform=platform,
                topic=selected["title"],
                direction=str(selected.get("direction") or raw.get("direction") or normalize_topic(selected["title"])),
                source_report=source_report,
                platform_signal=signal,
                platform_adaptation_reason=adaptation,
                heat_score=float(selected.get("score") or 0),
                freshness_score=float(selected.get("freshness_score") or 0),
                platform_fit_score=float(selected.get("platform_fit_score") or selected.get("score") or 0),
            )
            trend_gate = validate_trend_candidate(trend_candidate)
            matrix = _platform_evidence_matrix(platform, selected, source_report, strategy)
            selected_topics.setdefault(
                _topic_identity(selected),
                {"platform": platform, "adaptation": adaptation, "signal": signal},
            )
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
                    "trend_candidate": trend_candidate,
                },
                "trend_candidate": trend_candidate,
                "trend_candidate_gate": trend_gate,
                "action": raw.get("action") or ("handoff" if platform in MANUAL_HANDOFF_PLATFORMS else "stage"),
                "state": "ready_for_plan",
            })
            if strict_trend_evidence and not trend_gate.get("passed"):
                row.update({"state": "blocked", "reason": "trend candidate evidence below 8-attempt/5-success threshold"})
            elif strict_trend_evidence and not matrix["platform_internal_verified"]:
                row.update({"state": "blocked", "reason": "platform-specific trend evidence missing"})
        tasks.append(row)
    return {"version": "overnight_due_tasks_v1", "tasks": tasks, "source_report": source_report}


def _allows_evidenced_overlap(
    platform: str,
    candidate: dict[str, Any],
    slot: dict[str, Any],
    previous: dict[str, str],
    source_report: list[dict[str, Any]],
    strategy: dict[str, Any],
) -> bool:
    """Allow natural resonance only when both platform executions are evidenced."""
    adaptation = str(slot.get("platform_adaptation_reason") or "").strip()
    signal = str(slot.get("platform_signal") or "").strip()
    matrix = _platform_evidence_matrix(platform, candidate, source_report, strategy)
    return bool(
        adaptation
        and signal
        and adaptation != previous.get("adaptation")
        and platform != previous.get("platform")
        and matrix["platform_internal_verified"]
        and matrix["sources_attempted"] >= 8
        and matrix["sources_succeeded"] >= 5
    )


def _platform_evidence_matrix(platform: str, candidate: dict[str, Any], source_report: list[dict[str, Any]], strategy: dict[str, Any]) -> dict[str, Any]:
    attempted = [
        {"source": item.get("source"), "status": item.get("status", "unknown"), **({"error": item["error"]} if item.get("error") else {})}
        for item in source_report
        if item.get("source")
    ]
    aliases = {platform, "twitter" if platform == "x" else platform}
    if platform.startswith("douyin"):
        aliases.add("douyin")
    candidate_source = str(candidate.get("source") or "").casefold()
    platform_source_ok = any(
        str(item.get("status") or "").casefold() in {"ok", "success", "saved", "usable"}
        and any(alias in str(item.get("source") or "").casefold() for alias in aliases)
        for item in attempted
    )
    candidate_source_ok = any(alias in candidate_source for alias in aliases)
    strategy_ok = str(strategy.get("status") or "").casefold() == "ok"
    # A fresh strategy is required context, but it does not prove that this
    # particular topic was observed on the platform. Keep those facts apart.
    verified = platform_source_ok or candidate_source_ok
    return {
        "platform": platform,
        "attempted_sources": attempted,
        "sources_attempted": len(attempted),
        "sources_succeeded": sum(str(item.get("status") or "").casefold() in {"ok", "success", "saved", "usable"} for item in attempted),
        "platform_internal_verified": verified,
        "current_platform_specific_topic": platform_source_ok or candidate_source_ok,
        "platform_strategy_verified": strategy_ok,
        "shared_trend_only": not verified,
        "candidate_source": str(candidate.get("source") or ""),
        "platform_fit_reason": str(candidate.get("platform_fit_reason") or "") if verified else "",
        "report_path": "runtime:overnight_trend_collection",
    }


def sync_batch_state(state: dict[str, Any], store: Any, *, summary_path: str | Path = "") -> dict[str, Any]:
    """Reconcile batch rows with the job and delivery records without inventing a publish state."""
    platforms = []
    for task in state.get("tasks") or []:
        job_id = str(task.get("job_id") or "")
        if not job_id:
            continue
        try:
            job = store.get_job(job_id)
        except KeyError:
            task["state"] = "blocked"
            task["reason"] = "job_record_missing"
            continue
        deliveries = store.deliveries(job_id)
        delivery_states = [str(row.get("status") or "") for row in deliveries]
        acceptance = dict(job.get("acceptance") or {})
        observed = "blocked" if acceptance and not acceptance.get("passed") else "published" if "published" in delivery_states else "handoff_ready" if "handoff_pending" in delivery_states else "drafted" if "drafted" in delivery_states else str(job.get("state") or "blocked")
        task.update({
            "state": observed,
            "job_state": str(job.get("state") or ""),
            "delivery_states": delivery_states,
            "acceptance": acceptance,
            "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        platforms.append({"platform": task.get("platform", ""), "job_id": job_id, "state": observed, "acceptance": task["acceptance"]})
    observed_states = {str(task.get("state") or "") for task in state.get("tasks") or []}
    if "failed" in observed_states:
        state["status"] = "failed"
    elif observed_states & {"blocked", "deferred"}:
        state["status"] = "partial"
    elif observed_states and observed_states <= {"published", "drafted", "handoff_ready", "staged"}:
        state["status"] = "completed"
    report = {"version": "overnight_acceptance_summary_v1", "batch_status": state.get("status", ""), "platforms": platforms}
    if summary_path:
        path = Path(summary_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_redact(report), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _topic_identity(candidate: dict[str, Any]) -> str:
    """Return a stable batch-wide topic identity, even for incomplete feeds."""
    return str(candidate.get("fingerprint") or normalize_topic(candidate.get("title", ""))).strip()


def topic_keywords_for_slot(platform: str, slot: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    """Resolve explicit slot keywords before safe platform/profile defaults."""
    configured = slot.get("topic_keywords")
    if isinstance(configured, list) and configured:
        return [str(word).casefold() for word in configured if str(word).strip()]
    resolved = [
        str(word).casefold()
        for word in PLATFORM_TOPIC_KEYWORDS.get(str(platform).casefold(), profile.get("keywords", []))
        if str(word).strip()
    ]
    return resolved or list(DEFAULT_AI_TOPIC_KEYWORDS)


def candidate_matches_topic_keywords(candidate: dict[str, Any], keywords: list[str]) -> bool:
    """Require topical fit when a channel has an explicit operating lane."""
    if candidate.get("source_unavailable"):
        return False
    if not keywords:
        return True
    text = str(candidate.get("title") or "").casefold()
    return any(
        re.search(rf"\b{re.escape(word)}\b", text) is not None if word.isascii() and word.isalnum() else word in text
        for word in keywords
    )


def candidate_matches_platform_language(platform: str, candidate: dict[str, Any]) -> bool:
    """Prevent Chinese domestic headlines from being routed into English lanes."""
    if str(platform).casefold() not in {"twitter", "youtube", "tiktok"}:
        return True
    title = str(candidate.get("title") or "")
    return bool(re.search(r"[A-Za-z]", title)) and not bool(re.search(r"[\u4e00-\u9fff]", title))


def growth_strategy_snapshot_status(store: Any, platforms: list[str], *, max_age_hours: int = 30) -> dict[str, dict[str, Any]]:
    """Return per-platform strategy freshness for overnight fail-closed checks."""
    result: dict[str, dict[str, Any]] = {}
    for platform in platforms:
        normalized = str(platform or "").casefold()
        if not normalized:
            continue
        strategy_platform = STRATEGY_PLATFORM_ALIASES.get(normalized, normalized)
        key = f"growth_strategy:{strategy_platform}:latest"
        row = store.latest_tool_inventory(key)
        if not row:
            result[normalized] = {"status": "missing", "key": key}
            continue
        age_hours = _age_hours(row.get("created_at"))
        if age_hours is not None and age_hours > max_age_hours:
            result[normalized] = {"status": "stale", "key": key, "age_hours": round(age_hours, 2)}
        else:
            result[normalized] = {"status": "ok", "key": key, "age_hours": round(age_hours, 2) if age_hours is not None else None}
    return result


def _age_hours(value: str | None) -> float | None:
    if not value:
        return None
    try:
        created = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds() / 3600


TERMINAL_TASK_STATES = {"staged", "handoff_ready", "published", "blocked", "failed", "deferred", "review_required"}


def execute_batch(
    pipeline: Any,
    plan: dict[str, Any],
    *,
    state_path: str | Path,
    journal: "BatchEventJournal",
    store: Any | None = None,
    require_acceptance: bool = False,
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

            if require_acceptance and result_state not in {"blocked", "failed", "rejected"}:
                from .workflow_acceptance import evaluate_job_acceptance

                acceptance = evaluate_job_acceptance(store, task["job_id"], platform)
                task["acceptance"] = acceptance
                if not acceptance["passed"]:
                    task["state"] = "blocked"
                    task["reason"] = "workflow acceptance failed: " + ",".join(acceptance["failures"])
                    journal.append("platform_blocked", platform, {"job_id": task["job_id"], "reason": task["reason"]})
                    continue

            if result_state in {"blocked", "failed", "rejected"}:
                task["state"] = result_state
                task["reason"] = str(result.get("last_error") or "pipeline did not produce a reviewable artifact")
                journal.append("platform_blocked", platform, {"job_id": task["job_id"], "state": result_state, "reason": task["reason"]})
            elif platform.casefold() in MANUAL_HANDOFF_PLATFORMS:
                handoff_problem = _handoff_media_problem(platform, result)
                if handoff_problem:
                    task["state"] = "blocked"
                    task["reason"] = handoff_problem
                    journal.append("platform_blocked", platform, {"job_id": task["job_id"], "reason": handoff_problem})
                else:
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

    tasks = state.get("tasks", [])
    failed = [task for task in tasks if task.get("state") == "failed"]
    unfinished = [task for task in tasks if task.get("state") not in TERMINAL_TASK_STATES]
    blocked = [task for task in tasks if task.get("state") == "blocked"]
    # Failed rows remain terminal so a resumed batch cannot silently rerun
    # them. Aggregate status still exposes failure to systemd and Hermes.
    if failed:
        state["status"] = "failed"
    elif unfinished or blocked:
        state["status"] = "partial"
    else:
        state["status"] = "completed"
    _write_state(state_file, state)
    if store is not None:
        sync_batch_state(state, store, summary_path=state_file.parent / "acceptance_summary.json")
        _write_state(state_file, state)
    return state


def _handoff_media_problem(platform: str, result: dict[str, Any]) -> str:
    """Reject text-only manual handoffs; delivery evidence must be usable."""
    readable: list[tuple[str, Path]] = []
    for artifact in result.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        path = Path(str(artifact.get("path") or ""))
        if path.is_file() and path.stat().st_size > 0:
            readable.append((str(artifact.get("kind") or "").casefold(), path))
    normalized = str(platform or "").casefold()
    videos = [path for kind, path in readable if kind == "video"]
    cover = any(kind == "cover" or path.stem.casefold().startswith("cover") for kind, path in readable)
    if normalized in {"xiaohongshu", "rednote"}:
        images = [path for kind, _path in readable if kind in {"image", "cover"}]
        if not cover:
            return "handoff_cover_missing"
        return "" if len(images) >= 3 else "handoff_image_set_missing"
    if not videos:
        return "handoff_media_missing"
    return "" if cover else "handoff_cover_missing"


def _load_state(path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("status") == "running":
                interrupted = False
                for task in state.get("tasks") or []:
                    if task.get("state") == "running":
                        task["state"] = "blocked"
                        task["reason"] = "interrupted_batch_requires_recovery"
                        interrupted = True
                if interrupted:
                    state["status"] = "partial"
            return state
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
