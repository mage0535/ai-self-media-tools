"""Deterministic capability execution with truthful required/optional states."""

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
    selected = list(plan.get("candidates") or [])
    consulted = [dict(item, status="consulted") for item in (plan.get("consulted") or [])]
    executed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    optional_failures: list[dict[str, Any]] = []
    for item in selected:
        required = str(item.get("required_or_optional") or "required") != "optional"
        started = time.monotonic()
        try:
            result = executor(item, draft, brief) or {}
        except Exception as exc:
            result = {"status": "failed", "reason": f"executor_error:{type(exc).__name__}"}
        record = {
            "capability_id": item.get("capability_id"),
            "required": required,
            **result,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
        if record.get("status") == "executed" and record.get("output_hash"):
            executed.append(record)
        elif required:
            failures.append(record)
        else:
            optional_failures.append(record)
    return {
        "version": "capability_execution_dag_v1",
        "selected": selected,
        "consulted": consulted,
        "executed": executed,
        "failures": failures,
        "optional_failures": optional_failures,
        "passed": not failures,
    }
