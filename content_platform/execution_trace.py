"""Canonical cross-stage execution evidence without pipeline coupling."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable


EXECUTION_STAGES = ("collection", "selection", "blueprint", "generation", "assets", "render", "gate", "delivery")
_HASH_PATTERN = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")
_EVIDENCE_STATES = ("planned", "consulted", "executed", "artifact_verified", "skipped")


def record_execution_stage(
    stage: str,
    *,
    manifest_hash: str,
    manifest_kind: str | None = None,
    planned: Iterable[dict[str, Any]] | None = None,
    consulted: Iterable[dict[str, Any]] | None = None,
    executed: Iterable[dict[str, Any]] | None = None,
    artifact_verified: Iterable[dict[str, Any]] | None = None,
    skipped: Iterable[dict[str, Any]] | None = None,
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
        "skipped": _copy_evidence(skipped, "skipped"),
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
    del assets_required, render_required  # Requiredness belongs to selected registry nodes.
    selected = [row for row in (capability_execution.get("selected") or capability_execution.get("planned") or []) if isinstance(row, dict)]
    consulted = [row for row in capability_execution.get("consulted") or [] if isinstance(row, dict)]
    executed = [row for row in capability_execution.get("executed") or [] if isinstance(row, dict)]
    verified = [row for row in capability_execution.get("artifact_verified") or [] if isinstance(row, dict)]
    skipped = [row for row in capability_execution.get("skipped") or [] if isinstance(row, dict)]

    asset_evidence = _artifact_capability_evidence(artifacts)
    render_evidence = _manifest_capability_evidence(render_manifest)
    gate_evidence = _manifest_capability_evidence(quality_gate)
    executed.extend(asset_evidence["executed"] + render_evidence["executed"] + gate_evidence["executed"])
    verified.extend(asset_evidence["artifact_verified"] + render_evidence["artifact_verified"] + gate_evidence["artifact_verified"])
    skipped.extend(asset_evidence["skipped"] + render_evidence["skipped"] + gate_evidence["skipped"])

    manifests = {
        "collection": capability_execution,
        "selection": capability_execution,
        "blueprint": capability_execution,
        "generation": capability_execution,
        "assets": artifacts,
        "render": render_manifest,
        "gate": quality_gate,
    }
    kinds = {
        "collection": "capability_execution",
        "selection": "capability_execution",
        "blueprint": "capability_execution",
        "generation": "capability_execution",
        "assets": "artifact_manifest",
        "render": "renderer_manifest",
        "gate": "quality_report",
    }
    records = []
    for stage in EXECUTION_STAGES[:-1]:
        records.append(
            record_execution_stage(
                stage,
                manifest_hash=manifest_hash(manifests[stage]),
                manifest_kind=kinds[stage],
                planned=[_planned_evidence(row) for row in selected if _stage(row) == stage],
                consulted=[_node_evidence(row) for row in consulted if _stage(row, "blueprint") == stage],
                executed=[_node_evidence(row) for row in executed if _stage(row) == stage],
                artifact_verified=[_node_evidence(row) for row in verified if _stage(row) == stage],
                skipped=[_node_evidence(row) for row in skipped if _stage(row) == stage],
            )
        )
    return merge_execution_manifests(records, allow_incomplete=True)


def complete_delivery_trace(trace: dict[str, Any], *, platform: str, result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("status") or "")
    accepted = bool(result.get("ok")) and status in {"published", "drafted", "scheduled", "handoff_pending", "dry_run"}
    node_id = (
        "delivery_boundary_probe" if status == "dry_run"
        else "handoff_package_builder" if status == "handoff_pending"
        else "pipeline_publisher"
    )
    delivery = record_execution_stage(
        "delivery", manifest_hash=manifest_hash(result), manifest_kind="delivery_receipt",
        planned=[{"node_id": node_id, "selected": True, "required": True, "artifact_required": True}],
        executed=[{"node_id": node_id, "platform": platform, "status": result.get("status")}] if accepted else [],
        artifact_verified=[{"node_id": node_id, "platform": platform, "external_id": result.get("external_id")}] if accepted and result.get("external_id") else [],
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
            planned=_dedupe_evidence([*(existing.get("planned") or []), *(delivery.get("planned") or [])]),
            consulted=existing.get("consulted") or [],
            executed=_dedupe_evidence([*(existing.get("executed") or []), *(delivery.get("executed") or [])]),
            artifact_verified=_dedupe_evidence([*(existing.get("artifact_verified") or []), *(delivery.get("artifact_verified") or [])]),
            skipped=_dedupe_evidence([*(existing.get("skipped") or []), *(delivery.get("skipped") or [])]),
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


def _stage(record: dict[str, Any], default: str = "generation") -> str:
    return str(record.get("stage") or default)


def _node_evidence(record: dict[str, Any]) -> dict[str, Any]:
    return {**record, "node_id": _node_id(record)}


def _planned_evidence(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **_node_evidence(record),
        "selected": True,
        "required": str(record.get("required_or_optional") or "required") != "optional",
    }


def _artifact_capability_evidence(artifacts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    evidence = {"executed": [], "artifact_verified": [], "skipped": []}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        capability_ids = artifact.get("capability_ids") or [artifact.get("capability_id")]
        for capability_id in capability_ids:
            if not capability_id:
                continue
            row = {"capability_id": str(capability_id), "stage": "assets", "artifact": dict(artifact)}
            evidence["executed"].append(row)
            if artifact.get("artifact_verified") is True or artifact.get("checksum") or artifact.get("receipt"):
                evidence["artifact_verified"].append(row)
    return evidence


def _manifest_capability_evidence(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    evidence = {"executed": [], "artifact_verified": [], "skipped": []}
    stage = "gate" if "passed" in manifest and "status" not in manifest else "render"
    for raw in manifest.get("capability_evidence") or []:
        if not isinstance(raw, dict) or not raw.get("capability_id"):
            continue
        row = {**raw, "stage": str(raw.get("stage") or stage)}
        status = str(raw.get("status") or "")
        if status == "executed":
            evidence["executed"].append(row)
            if raw.get("artifact_verified") is True:
                evidence["artifact_verified"].append(row)
        elif status == "skipped":
            evidence["skipped"].append(row)
    return evidence


def _dedupe_evidence(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for value in values:
        key = (_node_id(value), str(value.get("platform") or ""))
        deduped[key] = dict(value)
    return list(deduped.values())


def _stable_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))
