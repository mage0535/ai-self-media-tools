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


def merge_execution_manifests(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
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
    trace: dict[str, Any] = {
        "version": "execution_trace_v1",
        "stages": ordered,
        "failures": failures,
        "passed": not failures,
    }
    trace["trace_hash"] = _stable_hash(trace)
    return trace


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
