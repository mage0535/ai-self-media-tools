"""Deterministic capability execution with truthful state transitions."""

from __future__ import annotations

import time
from typing import Any, Callable


def execute_capability_dag(
    plan: dict[str, Any],
    draft: dict[str, Any],
    brief: dict[str, Any],
    *,
    executor: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    selected = [dict(item, status="planned") for item in (plan.get("candidates") or [])]
    consulted = [dict(item, status="consulted") for item in (plan.get("consulted") or [])]
    planned = list(selected)
    executed: list[dict[str, Any]] = []
    artifact_verified: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failures: list[dict[str, Any] | str] = list(plan.get("selection_failures") or plan.get("failures") or [])
    optional_failures: list[dict[str, Any]] = []
    for item in selected:
        required = str(item.get("required_or_optional") or "required") != "optional"
        started = time.monotonic()
        try:
            result = executor(item, draft, brief) or {}
        except Exception as exc:
            result = {"status": "failed", "reason": f"executor_error:{type(exc).__name__}"}
        record: dict[str, Any] = {
            "capability_id": item.get("capability_id"),
            "required": required,
            **result,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
        if record.get("status") == "executed":
            executed.append(record)
            if record.get("contract_valid") is True and record.get("output_hash"):
                artifact_verified.append({**record, "status": "artifact_verified"})
            else:
                record["reason"] = "artifact_verification_failed"
                if required:
                    failures.append(record)
                else:
                    optional_failures.append(record)
        elif record.get("status") == "skipped":
            skipped.append(record)
            if required:
                failures.append(record)
            else:
                optional_failures.append(record)
        elif required:
            failures.append(record)
        else:
            optional_failures.append(record)
    return {
        "version": "capability_execution_dag_v2",
        "selection_status": plan.get("selection_status", "ready"),
        "selected": selected,
        "planned": planned,
        "consulted": consulted,
        "executed": executed,
        "artifact_verified": artifact_verified,
        "skipped": skipped,
        "failures": failures,
        "optional_failures": optional_failures,
        "passed": not failures,
    }
