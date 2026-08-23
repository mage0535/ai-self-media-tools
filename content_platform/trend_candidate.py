"""Platform-specific trend evidence used before a content slot is selected."""

from __future__ import annotations

from typing import Any

from .associated_hotspot import validate_associated_hotspot


def build_trend_candidate(
    *,
    platform: str,
    topic: str,
    direction: str,
    source_report: list[dict[str, Any]],
    platform_signal: str,
    platform_adaptation_reason: str,
    heat_score: float = 0.0,
    freshness_score: float = 0.0,
    platform_fit_score: float = 0.0,
    associated_hotspot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = [
        {"source": str(row.get("source") or ""), "status": str(row.get("status") or "unknown")}
        for row in source_report
        if isinstance(row, dict) and str(row.get("source") or "").strip()
    ]
    succeeded = [row for row in evidence if row["status"] in {"ok", "success"}]
    return {
        "version": "trend_candidate_v1",
        "platform": str(platform).casefold(),
        "topic": str(topic).strip(),
        "direction": str(direction).strip(),
        "sources_attempted": len(evidence),
        "sources_succeeded": len(succeeded),
        "heat_score": round(float(heat_score), 3),
        "freshness_score": round(float(freshness_score), 3),
        "platform_fit_score": round(float(platform_fit_score), 3),
        "platform_signal": str(platform_signal).strip(),
        "platform_adaptation_reason": str(platform_adaptation_reason).strip(),
        "evidence": evidence,
        "associated_hotspot": associated_hotspot or {},
    }


def validate_trend_candidate(candidate: dict[str, Any] | None) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(candidate, dict) or not candidate:
        failures.append("trend_candidate_missing")
    else:
        for field in ("platform", "topic", "direction", "platform_signal", "platform_adaptation_reason"):
            if not str(candidate.get(field) or "").strip():
                failures.append(f"{field}_missing")
        if int(candidate.get("sources_attempted") or 0) < 8:
            failures.append("sources_attempted_lt_8")
        if int(candidate.get("sources_succeeded") or 0) < 5:
            failures.append("sources_succeeded_lt_5")
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), list) else []
        if len(evidence) != int(candidate.get("sources_attempted") or 0):
            failures.append("source_evidence_count_mismatch")
        hotspot = candidate.get("associated_hotspot")
        if hotspot:
            hotspot_gate = validate_associated_hotspot(hotspot)
            failures.extend(f"associated_hotspot.{item}" for item in hotspot_gate["failures"])
    return {"passed": not failures, "failures": failures, "failed_dimensions": ["trend_candidate"] if failures else []}
