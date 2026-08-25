"""Canonical cross-stage execution evidence without pipeline coupling."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable


EXECUTION_STAGES = ("generation", "assets", "render", "gate", "delivery")
_HASH_PATTERN = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")
_EVIDENCE_STATES = ("planned", "consulted", "executed", "artifact_verified")


def record_execution_stage(
    stage: str,
    *,
    manifest_hash: str,
    manifest_kind: str | None = None,
    planned: Iterable[dict[str, Any]] | None = None,
    consulted: Iterable[dict[str, Any]] | None = None,
    executed: Iterable[dict[str, Any]] | None = None,
    artifact_verified: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Record explicit stage facts while retaining only a manifest hash reference."""
    if stage not in EXECUTION_STAGES:
        raise ValueError(f"unsupported execution stage: {stage}")
    match = _HASH_PATTERN.fullmatch(str(manifest_hash or "").strip())
    if not match:
        raise ValueError("manifest_hash must be a sha256 digest")
    kind = str(manifest_kind or f"{stage}_manifest").strip()
    if not kind:
        raise ValueError("manifest_kind must not be empty")

    states = {
        "planned": _copy_evidence(planned, "planned"),
        "consulted": _copy_evidence(consulted, "consulted"),
        "executed": _copy_evidence(executed, "executed"),
        "artifact_verified": _copy_evidence(artifact_verified, "artifact_verified"),
    }
    return {
        "version": "execution_stage_record_v1",
        "stage": stage,
        "manifest_ref": {"kind": kind, "hash": f"sha256:{match.group(1).lower()}"},
        **states,
    }


def merge_execution_manifests(records: Iterable[dict[str, Any]], *, allow_incomplete: bool = False) -> dict[str, Any]:
    """Merge stage records into the deterministic canonical execution trace."""
    by_stage: dict[str, dict[str, Any]] = {}
    merge_failures: list[str] = []
    for raw in records:
        if not isinstance(raw, dict):
            merge_failures.append("invalid_stage_record")
            continue
        stage = str(raw.get("stage") or "")
        if stage in by_stage:
            merge_failures.append(f"duplicate_stage_record:{stage}")
            continue
        by_stage[stage] = _copy_stage_record(raw)

    ordered = [by_stage[stage] for stage in EXECUTION_STAGES if stage in by_stage]
    from .execution_dag import validate_execution_trace

    failures = _unique(merge_failures + validate_execution_trace(ordered))
    missing = [failure for failure in failures if failure.startswith("required_stage_missing:")]
    if allow_incomplete:
        failures = [failure for failure in failures if failure not in missing]
    trace: dict[str, Any] = {
        "version": "execution_trace_v1",
        "stages": ordered,
        "failures": failures,
        "passed": None if allow_incomplete and missing and not failures else not failures,
        "status": "pending_delivery" if allow_incomplete and missing and not failures else ("completed" if not failures else "failed"),
    }
    trace["trace_hash"] = _stable_hash(trace)
    return trace


def manifest_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_pre_delivery_trace(
    *, capability_execution: dict[str, Any], artifacts: list[dict[str, Any]], assets_required: bool,
    render_manifest: dict[str, Any], render_required: bool, quality_gate: dict[str, Any],
) -> dict[str, Any]:
    selected = capability_execution.get("selected") or capability_execution.get("planned") or []
    generation = record_execution_stage(
        "generation", manifest_hash=manifest_hash(capability_execution), manifest_kind="capability_execution",
        planned=[{**row, "node_id": row.get("capability_id"), "selected": True, "required": str(row.get("required_or_optional") or "required") != "optional"} for row in selected if isinstance(row, dict) and row.get("capability_id")],
        consulted=[{**row, "node_id": row.get("capability_id")} for row in capability_execution.get("consulted") or [] if isinstance(row, dict) and row.get("capability_id")],
        executed=[{**row, "node_id": row.get("capability_id")} for row in capability_execution.get("executed") or [] if isinstance(row, dict) and row.get("capability_id")],
    )
    asset_node = {"node_id": "media_assets", "selected": bool(assets_required or artifacts), "required": bool(assets_required), "artifact_required": bool(assets_required)}
    assets = record_execution_stage(
        "assets", manifest_hash=manifest_hash(artifacts), manifest_kind="artifact_manifest", planned=[asset_node],
        executed=[{"node_id": "media_assets", "artifacts": len(artifacts)}] if artifacts else [],
        artifact_verified=[{"node_id": "media_assets", "artifacts": len(artifacts)}] if artifacts else [],
    )
    render_node = {"node_id": "media_render", "selected": bool(render_required or render_manifest), "required": bool(render_required), "artifact_required": bool(render_required)}
    rendered_ok = bool(render_manifest) and (render_manifest.get("ok") is True or render_manifest.get("status") in {"rendered", "completed"})
    render = record_execution_stage(
        "render", manifest_hash=manifest_hash(render_manifest), manifest_kind="renderer_manifest", planned=[render_node],
        executed=[{"node_id": "media_render"}] if rendered_ok else [], artifact_verified=[{"node_id": "media_render"}] if rendered_ok else [],
    )
    gate_ok = quality_gate.get("passed") is True
    gate = record_execution_stage(
        "gate", manifest_hash=manifest_hash(quality_gate), manifest_kind="quality_report",
        planned=[{"node_id": "final_quality_gate", "selected": True, "required": True, "artifact_required": True}],
        executed=[{"node_id": "final_quality_gate"}] if quality_gate else [],
        artifact_verified=[{"node_id": "final_quality_gate"}] if gate_ok else [],
    )
    return merge_execution_manifests([generation, assets, render, gate], allow_incomplete=True)


def complete_delivery_trace(trace: dict[str, Any], *, platform: str, result: dict[str, Any]) -> dict[str, Any]:
    accepted = bool(result.get("ok")) and str(result.get("status") or "") in {"published", "drafted", "scheduled", "handoff_pending"}
    node_id = f"delivery:{platform}"
    delivery = record_execution_stage(
        "delivery", manifest_hash=manifest_hash(result), manifest_kind="delivery_receipt",
        planned=[{"node_id": node_id, "selected": True, "required": True, "artifact_required": True}],
        executed=[{"node_id": node_id, "status": result.get("status")}] if accepted else [],
        artifact_verified=[{"node_id": node_id, "external_id": result.get("external_id")}] if accepted else [],
    )
    records = [dict(row) for row in trace.get("stages") or [] if isinstance(row, dict)]
    existing = next((row for row in records if row.get("stage") == "delivery"), None)
    if existing is not None:
        records.remove(existing)
        combined_result = {
            "previous": existing.get("manifest_ref"),
            "platform": platform,
            "result": result,
        }
        delivery = record_execution_stage(
            "delivery", manifest_hash=manifest_hash(combined_result), manifest_kind="delivery_receipts",
            planned=[*(existing.get("planned") or []), *(delivery.get("planned") or [])],
            consulted=existing.get("consulted") or [],
            executed=[*(existing.get("executed") or []), *(delivery.get("executed") or [])],
            artifact_verified=[*(existing.get("artifact_verified") or []), *(delivery.get("artifact_verified") or [])],
        )
    return merge_execution_manifests([*records, delivery])


def _copy_evidence(
    values: Iterable[dict[str, Any]] | None,
    state: str,
) -> list[dict[str, Any]]:
    if state not in _EVIDENCE_STATES:
        raise ValueError(f"unsupported evidence state: {state}")
    copied: list[dict[str, Any]] = []
    for value in values or []:
        if not isinstance(value, dict):
            raise ValueError(f"{state} evidence must contain dictionaries")
        if not _node_id(value):
            raise ValueError(f"{state} evidence requires node_id, capability_id, or id")
        copied.append(dict(value))
    return copied


def _copy_stage_record(record: dict[str, Any]) -> dict[str, Any]:
    copied = dict(record)
    copied["manifest_ref"] = dict(record.get("manifest_ref") or {})
    for state in _EVIDENCE_STATES:
        copied[state] = [dict(item) for item in record.get(state) or [] if isinstance(item, dict)]
    return copied


def _node_id(record: dict[str, Any]) -> str:
    return str(record.get("node_id") or record.get("capability_id") or record.get("id") or "").strip()


def _stable_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))
