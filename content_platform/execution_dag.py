"""Deterministic capability execution with truthful state transitions."""

from __future__ import annotations

import time
import re
from typing import Any, Callable


_EXECUTION_STAGES = ("collection", "selection", "blueprint", "generation", "assets", "render", "gate", "delivery")
_MANIFEST_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_GENERIC_PLACEHOLDERS = frozenset({"media_assets", "media_render", "final_quality_gate", "delivery_receipt"})


def validate_execution_trace(records: list[dict[str, Any]]) -> list[str]:
    """Return canonical spine failures without promoting one evidence state to another."""
    failures: list[str] = []
    by_stage: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            failures.append("invalid_stage_record")
            continue
        stage = str(record.get("stage") or "")
        if stage not in _EXECUTION_STAGES:
            failures.append(f"unsupported_execution_stage:{stage}")
            continue
        if stage in by_stage:
            failures.append(f"duplicate_stage_record:{stage}")
            continue
        by_stage[stage] = record

    for stage in _EXECUTION_STAGES:
        record = by_stage.get(stage)
        if record is None:
            failures.append(f"required_stage_missing:{stage}")
            continue
        manifest_ref = record.get("manifest_ref") if isinstance(record.get("manifest_ref"), dict) else {}
        if not str(manifest_ref.get("kind") or "").strip():
            failures.append(f"manifest_kind_missing:{stage}")
        if not _MANIFEST_HASH_PATTERN.fullmatch(str(manifest_ref.get("hash") or "")):
            failures.append(f"manifest_hash_invalid:{stage}")

        executed_ids = _evidence_ids(record.get("executed"))
        verified_ids = _evidence_ids(record.get("artifact_verified"))
        skipped = {
            _node_id(item): item
            for item in record.get("skipped") or []
            if isinstance(item, dict) and _node_id(item)
        }
        for planned in record.get("planned") or []:
            if not isinstance(planned, dict) or not _node_id(planned):
                failures.append(f"planned_node_invalid:{stage}")
                continue
            if not _is_selected_required(planned):
                continue
            node_id = _node_id(planned)
            if node_id in _GENERIC_PLACEHOLDERS:
                failures.append(f"generic_placeholder_node_forbidden:{stage}:{node_id}")
            if node_id not in executed_ids:
                failures.append(f"required_node_not_executed:{stage}:{node_id}")
            if _artifact_required(planned) and node_id not in verified_ids:
                failures.append(f"required_artifact_not_verified:{stage}:{node_id}")
        for node_id, item in skipped.items():
            if not str(item.get("reason") or "").strip():
                failures.append(f"skipped_reason_missing:{stage}:{node_id}")
    return list(dict.fromkeys(failures))


def _evidence_ids(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {_node_id(item) for item in values if isinstance(item, dict) and _node_id(item)}


def _node_id(record: dict[str, Any]) -> str:
    return str(record.get("node_id") or record.get("capability_id") or record.get("id") or "").strip()


def _is_selected_required(record: dict[str, Any]) -> bool:
    selected = record.get("selected", True) is True
    required = record.get("required")
    if required is None:
        required = str(record.get("required_or_optional") or "required") != "optional"
    return selected and required is True


def _artifact_required(record: dict[str, Any]) -> bool:
    return record.get("artifact_required") is True or record.get("requires_artifact_verification") is True


def execute_capability_dag(
    plan: dict[str, Any],
    draft: dict[str, Any],
    brief: dict[str, Any],
    *,
    executor: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]],
    stages: set[str] | None = None,
) -> dict[str, Any]:
    active_stages = set(stages or _EXECUTION_STAGES)
    unknown_stages = active_stages.difference(_EXECUTION_STAGES)
    if unknown_stages:
        raise ValueError(f"unsupported execution stages: {sorted(unknown_stages)}")
    selected = []
    pending: list[dict[str, Any]] = []
    for raw in plan.get("candidates") or []:
        item = dict(raw)
        stage = str(item.get("stage") or "generation")
        if stage in active_stages:
            item["status"] = "planned"
        else:
            item.update(status="pending", reason=f"stage_pending:{stage}")
            pending.append(item)
        selected.append(item)
    consulted = [dict(item, status="consulted") for item in (plan.get("consulted") or [])]
    planned = list(selected)
    executed: list[dict[str, Any]] = []
    output_verified: list[dict[str, Any]] = []
    artifact_verified: list[dict[str, Any]] = []
    effect_verified: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failures: list[dict[str, Any] | str] = list(plan.get("selection_failures") or plan.get("failures") or [])
    optional_failures: list[dict[str, Any]] = []
    for item in selected:
        if item.get("status") == "pending":
            continue
        required = str(item.get("required_or_optional") or "required") != "optional"
        started = time.monotonic()
        try:
            result = executor(item, draft, brief) or {}
        except Exception as exc:
            result = {"status": "failed", "reason": f"executor_error:{type(exc).__name__}"}
        record: dict[str, Any] = {
            "capability_id": item.get("capability_id"),
            "stage": str(item.get("stage") or "generation"),
            "required": required,
            **result,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
        if record.get("status") == "executed":
            executed.append(record)
            if record.get("contract_valid") is True and record.get("output_hash"):
                stage = str(record.get("stage") or "generation")
                verified = {**record, "status": "output_verified"}
                if stage in {"assets", "render"}:
                    verified["status"] = "artifact_verified"
                    artifact_verified.append(verified)
                elif stage == "gate":
                    verified["status"] = "effect_verified"
                    effect_verified.append(verified)
                else:
                    output_verified.append(verified)
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
        "output_verified": output_verified,
        "artifact_verified": artifact_verified,
        "effect_verified": effect_verified,
        "skipped": skipped,
        "pending": pending,
        "completed_stages": [stage for stage in _EXECUTION_STAGES if stage in active_stages],
        "failures": failures,
        "optional_failures": optional_failures,
        "passed": not failures,
    }
