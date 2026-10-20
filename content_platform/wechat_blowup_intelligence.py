"""Auditable WeChat breakout-article intelligence.

This module accepts only legally exported, article-level records.  It separates
supplier hot-article evidence from public discovery and prevents search ranking
from becoming an article-performance claim.
"""
from __future__ import annotations

import hashlib
import json
from statistics import median
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "wechat_blowup_intelligence_v1"
GRADE_ORDER = {"G1": 1, "G2": 2, "G3": 3, "G4": 4}


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _artifact_hash(payload: dict[str, Any]) -> str:
    stable = dict(payload)
    stable.pop("artifact_sha256", None)
    return hashlib.sha256(_canonical_json(stable)).hexdigest()


def _text(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _has_identity(row: dict[str, Any]) -> bool:
    return bool(_text(row, "canonical_url") and _text(row, "title") and _text(row, "account_name") and _text(row, "published_at"))


def _has_snapshot(row: dict[str, Any]) -> bool:
    digest = _text(row, "raw_snapshot_sha256")
    return bool(_text(row, "raw_snapshot_ref") and len(digest) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in digest))


def _has_metric(row: dict[str, Any]) -> bool:
    return bool(_text(row, "metric_name") and _text(row, "metric_definition") and row.get("metric_value") not in (None, ""))


def classify_wechat_article(row: dict[str, Any]) -> tuple[str, str, list[str]]:
    """Return evidence grade, claim scope, and deterministic validation failures."""
    row = row if isinstance(row, dict) else {}
    source_kind = _text(row, "source_kind").casefold()
    failures: list[str] = []
    if str(row.get("platform") or "wechat").casefold() != "wechat":
        return "rejected", "invalid_platform", ["platform_must_be_wechat"]
    if not _has_identity(row):
        failures.append("article_identity_incomplete")
    if not _text(row, "observed_at"):
        failures.append("observed_at_missing")

    if source_kind in {"sogou_wechat_search", "public_search", "wechat_search"}:
        return ("G1", "public_discovery_only", failures)

    if source_kind == "public_10w_plus":
        if not _has_snapshot(row):
            failures.append("public_threshold_snapshot_missing")
        if _text(row, "metric_name") != "public_10w_plus":
            failures.append("public_threshold_marker_missing")
        return ("G2", "public_threshold_observed", failures)

    if source_kind == "authorized_vendor_export":
        if not _text(row, "source_vendor"):
            failures.append("source_vendor_missing")
        if not _has_snapshot(row):
            failures.append("vendor_snapshot_missing")
        if not _has_metric(row):
            failures.append("vendor_metric_definition_missing")
        return ("G3", "vendor_monitored_hot_article", failures)

    if source_kind == "authorized_backend_export":
        if not _has_snapshot(row):
            failures.append("backend_export_snapshot_missing")
        if not _has_metric(row):
            failures.append("backend_metric_definition_missing")
        raw_baseline = row.get("baseline")
        baseline = raw_baseline if isinstance(raw_baseline, dict) else {}
        if not (baseline.get("sample_n") and baseline.get("metric_window") and baseline.get("median")):
            failures.append("comparable_baseline_missing")
        return ("G4", "authorized_article_performance", failures)

    return ("rejected", "unsupported_source_kind", ["unsupported_source_kind"] + failures)


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    grade, scope, failures = classify_wechat_article(row)
    normalized = {str(key): value for key, value in row.items()}
    normalized["platform"] = "wechat"
    normalized["evidence_grade"] = grade
    normalized["claim_scope"] = scope
    normalized["validation_failures"] = failures
    normalized["strategy_eligible"] = grade in {"G3", "G4"} and not failures
    normalized["research_eligible"] = grade in {"G2", "G3", "G4"} and not failures
    return normalized


def build_wechat_blowup_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Create an immutable, evidence-gated WeChat breakout corpus report."""
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, dict):
            rejected.append({"validation_failures": ["row_not_object"]})
            continue
        row = _normalize_row(raw)
        key = _text(row, "canonical_url")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        if row["evidence_grade"] == "rejected" or row["validation_failures"]:
            rejected.append(row)
        else:
            normalized.append(row)

    counts = {grade: sum(1 for row in normalized if row["evidence_grade"] == grade) for grade in ("G1", "G2", "G3", "G4")}
    counts["rejected"] = len(rejected)
    strategy_samples = [row for row in normalized if row["strategy_eligible"]]
    research_samples = [row for row in normalized if row["research_eligible"]]
    if len(strategy_samples) >= 3:
        status = "strategy_ready"
        failures: list[str] = []
    elif len(research_samples) >= 3:
        status = "research_ready"
        failures = ["insufficient_g3_or_g4_samples"]
    else:
        status = "blocked_no_strategy_evidence"
        failures = ["insufficient_g3_or_g4_samples"]

    payload: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": "wechat",
        "status": status,
        "counts": counts,
        "gate_failures": failures,
        "strategy_samples": strategy_samples,
        "research_samples": research_samples,
        "rejected_samples": rejected,
        "evidence_contract": {
            "G1": "public discovery only; never article performance",
            "G2": "public threshold evidence; structure research only",
            "G3": "auditable vendor monitored hot article; strategy sample",
            "G4": "authorized backend article performance with comparable baseline",
        },
    }
    payload["artifact_sha256"] = _artifact_hash(payload)
    return payload


def load_wechat_blowup_rows(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        raise ValueError("WeChat breakout input must be a JSON list or object")
    for key in ("articles", "items", "rows", "samples", "article_observations"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    raise ValueError("WeChat breakout input needs articles/items/rows/samples list")


def _attach_authorized_backend_baselines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach same-account, same-metric baselines without retaining raw exports.

    An authorized backend observation becomes G4 only when this import contains
    at least three comparable article rows for the account and metric.  This is
    deliberately a performance baseline, not an assertion that every row is a
    breakout article.
    """
    groups: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        key = (_text(row, "account_name"), _text(row, "metric_name"))
        try:
            value = float(row.get("metric_value"))
        except (TypeError, ValueError):
            continue
        if all(key) and value >= 0:
            groups.setdefault(key, []).append(value)
    output: list[dict[str, Any]] = []
    for row in rows:
        normalized = dict(row)
        key = (_text(normalized, "account_name"), _text(normalized, "metric_name"))
        values = groups.get(key, [])
        if len(values) >= 3:
            normalized["baseline"] = {
                "metric_name": key[1],
                "metric_window": "same_authorized_export",
                "sample_n": len(values),
                "median": median(values),
            }
        output.append(normalized)
    return output


def ingest_authorized_backend_export(source: str | Path, output: str | Path) -> dict[str, Any]:
    """Convert one explicitly authorized backend export into a verified G4 artifact.

    The export is hashed in place and never copied.  Caller-provided source
    labels are overwritten so a public-search row cannot be promoted by mistake.
    """
    source_path = Path(source)
    raw_bytes = source_path.read_bytes()
    snapshot_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    imported = load_wechat_blowup_rows(source_path)
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for raw in imported:
        row = dict(raw)
        row["platform"] = "wechat"
        row["source_kind"] = "authorized_backend_export"
        row["observed_at"] = _text(row, "observed_at") or observed_at
        row["raw_snapshot_ref"] = f"authorized_backend_export:{source_path.name}"
        row["raw_snapshot_sha256"] = snapshot_sha256
        rows.append(row)
    report = build_wechat_blowup_report(_attach_authorized_backend_baselines(rows))
    report["source_audit"] = [{
        "name": source_path.name,
        "kind": "authorized_backend_export",
        "status": "collected",
        "row_count": len(rows),
        "raw_snapshot_sha256": snapshot_sha256,
    }]
    report["artifact_sha256"] = _artifact_hash(report)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output"] = str(target)
    return report


def write_wechat_blowup_report(rows: list[dict[str, Any]], output: str | Path) -> dict[str, Any]:
    report = build_wechat_blowup_report(rows)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output"] = str(path)
    return report


def collect_wechat_blowup_sources(config_path: str | Path) -> dict[str, Any]:
    """Ingest deliberately configured legal article-level exports without retaining raw data.

    Each source is an explicit local JSON export.  The report retains only its
    content hash and source name; sensitive original files remain at their
    configured location and are never copied into the intelligence directory.
    """
    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    sources = config.get("sources") if isinstance(config, dict) else None
    if not isinstance(sources, list):
        raise ValueError("WeChat blowup source config needs a sources list")

    rows: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for raw_source in sources:
        source = raw_source if isinstance(raw_source, dict) else {}
        name = _text(source, "name")
        kind = _text(source, "kind")
        export_path = Path(_text(source, "path"))
        if not name or kind not in {"authorized_vendor_export", "authorized_backend_export"} or not export_path.is_file():
            audit.append({"name": name or "unnamed", "status": "rejected", "reason": "invalid_or_unavailable_source"})
            continue
        raw_bytes = export_path.read_bytes()
        snapshot_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        try:
            exported_rows = load_wechat_blowup_rows(export_path)
        except (OSError, ValueError, json.JSONDecodeError):
            audit.append({"name": name, "status": "rejected", "reason": "export_unreadable", "raw_snapshot_sha256": snapshot_sha256})
            continue
        for raw_row in exported_rows:
            row = dict(raw_row)
            row.setdefault("platform", "wechat")
            row["source_kind"] = kind
            row["source_vendor"] = name if kind == "authorized_vendor_export" else row.get("source_vendor", "")
            row.setdefault("metric_definition", _text(source, "metric_definition"))
            row["observed_at"] = _text(row, "observed_at") or observed_at
            row["raw_snapshot_ref"] = f"source:{name}"
            row["raw_snapshot_sha256"] = snapshot_sha256
            rows.append(row)
        audit.append({"name": name, "kind": kind, "status": "collected", "row_count": len(exported_rows), "raw_snapshot_sha256": snapshot_sha256})

    report = build_wechat_blowup_report(rows)
    report["source_audit"] = audit
    report["artifact_sha256"] = _artifact_hash(report)
    return report


def load_wechat_blowup_compact(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        return {"version": SCHEMA_VERSION, "status": "missing", "samples": [], "failures": ["artifact_missing"]}
    try:
        report = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": SCHEMA_VERSION, "status": "blocked", "samples": [], "failures": ["artifact_unreadable"]}
    if not isinstance(report, dict) or report.get("version") != SCHEMA_VERSION:
        return {"version": SCHEMA_VERSION, "status": "blocked", "samples": [], "failures": ["artifact_schema_invalid"]}
    if _text(report, "artifact_sha256") != _artifact_hash(report):
        return {"version": SCHEMA_VERSION, "status": "blocked", "samples": [], "failures": ["artifact_sha256_mismatch"]}
    raw_samples = report.get("strategy_samples")
    samples = raw_samples if isinstance(raw_samples, list) else []
    return {
        "version": SCHEMA_VERSION,
        "status": report.get("status") if report.get("status") in {"strategy_ready", "research_ready"} else "blocked",
        "samples": samples[:12],
        "counts": report.get("counts") or {},
        "failures": report.get("gate_failures") or [],
        "artifact_path": str(target),
        "artifact_sha256": report.get("artifact_sha256"),
    }
