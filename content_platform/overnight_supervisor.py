"""Read-only health assessment for recoverable overnight batches."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def inspect_batch_health(
    state_path: str | Path,
    heartbeat_path: str | Path,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 1800,
    pid_checker=None,
) -> dict[str, Any]:
    """Report whether a batch has stopped advancing without mutating it."""
    state = _read_json(state_path)
    heartbeat = _read_json(heartbeat_path)
    status = str(state.get("status") or "missing")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if status != "running":
        return {
            "status": "terminal" if status in {"completed", "partial", "failed", "blocked", "no_run"} else "missing",
            "batch_status": status,
            "recovery_required": False,
            "recovery_authorized": False,
            "platform": str(heartbeat.get("platform") or ""),
        }
    heartbeat_at = _parse_time(heartbeat.get("at"))
    if heartbeat_at is None:
        return {
            "status": "stale",
            "batch_status": status,
            "recovery_required": True,
            "recovery_authorized": False,
            "reason": "heartbeat_missing_owner_proof_required",
            "platform": _running_platform(state),
            "age_seconds": None,
        }
    age_seconds = max(0, int((now.astimezone(timezone.utc) - heartbeat_at).total_seconds()))
    if age_seconds > int(stale_after_seconds):
        proof = _owner_proof(state, heartbeat, now, pid_checker)
        return {
            "status": "stale",
            "batch_status": status,
            "recovery_required": True,
            "recovery_authorized": proof["authorized"],
            "reason": "heartbeat_stale" if proof["authorized"] else "heartbeat_stale_owner_proof_required",
            "platform": str(heartbeat.get("platform") or _running_platform(state)),
            "age_seconds": age_seconds,
            "proof": proof,
        }
    return {
        "status": "healthy",
        "batch_status": status,
        "recovery_required": False,
        "recovery_authorized": False,
        "platform": str(heartbeat.get("platform") or _running_platform(state)),
        "age_seconds": age_seconds,
    }


def _read_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _running_platform(state: dict[str, Any]) -> str:
    return next((str(task.get("platform") or "") for task in state.get("tasks") or [] if task.get("state") == "running"), "")


def _owner_proof(state: dict[str, Any], heartbeat: dict[str, Any], now: datetime, pid_checker=None) -> dict[str, Any]:
    worker = state.get("worker") if isinstance(state.get("worker"), dict) else {}
    if not worker and isinstance(heartbeat.get("worker"), dict):
        worker = heartbeat["worker"]
    try:
        pid = int(worker.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    checker = pid_checker or _pid_is_alive
    pid_alive = bool(pid) and bool(checker(pid))
    lease = _parse_time(worker.get("lease_expires_at"))
    lease_expired = bool(lease and lease <= now.astimezone(timezone.utc))
    owner_present = bool(str(worker.get("owner") or "").strip())
    return {
        "owner_present": owner_present,
        "pid_present": bool(pid),
        "pid_dead": bool(pid) and not pid_alive,
        "lease_present": bool(lease),
        "lease_expired": lease_expired,
        "authorized": owner_present and bool(pid) and not pid_alive and lease_expired,
    }


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, ProcessLookupError):
        return False
    return True
