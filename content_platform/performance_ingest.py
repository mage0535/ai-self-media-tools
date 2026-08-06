"""Import platform performance snapshots and produce strategy-facing reviews."""

from __future__ import annotations

import json
import csv
from pathlib import Path
from typing import Any, Iterable


NUMERIC_FIELDS = {
    "views": int,
    "likes": int,
    "comments": int,
    "shares": int,
    "saves": int,
    "follows": int,
    "completion_rate": float,
    "three_second_view_rate": float,
    "avg_watch_seconds": float,
}
RESERVED_FIELDS = set(NUMERIC_FIELDS) | {"job_id", "platform", "title", "work_title", "metrics", "extra_metrics"}

FIELD_ALIASES = {
    "view_count": "views",
    "read_count": "views",
    "play_count": "views",
    "plays": "views",
    "impressions": "views",
    "like_count": "likes",
    "comment_count": "comments",
    "share_count": "shares",
    "collect_count": "saves",
    "favorite_count": "saves",
    "save_count": "saves",
    "new_follows": "follows",
    "follower_gain": "follows",
    "finish_rate": "completion_rate",
    "completion": "completion_rate",
    "3s_rate": "three_second_view_rate",
    "three_second_rate": "three_second_view_rate",
    "avg_play_seconds": "avg_watch_seconds",
    "avg_play_duration": "avg_watch_seconds",
}

PLATFORM_ALIASES = {
    "kwai": "kuaishou",
    "kuaishou": "kuaishou",
    "wxSph": "shipinhao",
    "wxsph": "shipinhao",
    "shipinhao": "shipinhao",
    "xhs": "xiaohongshu",
    "xiaohongshu": "xiaohongshu",
    "wxGzh": "wechat",
    "wxgzh": "wechat",
    "wechat": "wechat",
}

DEFAULT_REVIEW_THRESHOLDS = {
    "min_samples_for_confident_review": 3,
    "low_engagement_rate": 0.04,
    "low_save_rate": 0.02,
    "low_follow_rate": 0.005,
    "low_completion_rate": 0.35,
    "low_three_second_view_rate": 0.45,
}


def _load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix.lower() == ".csv":
        return [dict(row) for row in csv.DictReader(text.splitlines())]
    if path.suffix.lower() == ".jsonl":
        records = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("jsonl records must be objects")
                records.append(payload)
        return records
    payload = json.loads(text)
    if isinstance(payload, dict):
        if isinstance(payload.get("records"), list):
            return payload["records"]
        return [payload]
    if isinstance(payload, list):
        return payload
    raise ValueError("metrics file must be a JSON object, JSON array, or JSONL")


def _coerce_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("metric record must be an object")
    record = _normalize_record_keys(record)
    job_id = str(record.get("job_id") or "").strip()
    platform = _normalize_platform(record.get("platform"))
    if not job_id:
        raise ValueError("job_id is required")
    if not platform:
        raise ValueError("platform is required")
    normalized: dict[str, Any] = {"job_id": job_id, "platform": platform}
    for key, caster in NUMERIC_FIELDS.items():
        value = record.get(key, 0)
        normalized[key] = caster(value or 0)
    metrics = dict(record.get("metrics", record.get("extra_metrics", {})) or {})
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be an object")
    for key, value in record.items():
        if key in RESERVED_FIELDS or value in (None, ""):
            continue
        try:
            metrics[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    normalized["metrics"] = metrics
    return normalized


def _normalize_record_keys(record: dict[str, Any]) -> dict[str, Any]:
    normalized = {}
    for key, value in record.items():
        canonical = FIELD_ALIASES.get(str(key).strip(), str(key).strip())
        normalized[canonical] = value
    return normalized


def _normalize_platform(platform: Any) -> str:
    raw = str(platform or "").strip()
    return PLATFORM_ALIASES.get(raw, PLATFORM_ALIASES.get(raw.casefold(), raw))


def _resolve_job_id(store: Any, record: dict[str, Any]) -> str:
    job_id = str(record.get("job_id") or "").strip()
    if job_id:
        return job_id
    platform = _normalize_platform(record.get("platform"))
    title = str(record.get("title") or record.get("work_title") or "").strip()
    if not platform or not title:
        return ""
    needle = title.casefold()
    candidates = []
    for job in store.list_jobs(500):
        if platform not in (job.get("platforms") or []):
            continue
        haystacks = [str(job.get("title") or ""), str(job.get("topic") or ""), str(job.get("body") or "")[:500]]
        if any(needle == value.casefold() for value in haystacks if value):
            return str(job.get("id") or "")
        if any(needle in value.casefold() or value.casefold() in needle for value in haystacks if value):
            candidates.append(str(job.get("id") or ""))
    return candidates[0] if len(candidates) == 1 else ""


def _snapshot_job_for_unknown_import(store: Any, record: dict[str, Any]) -> str:
    platform = _normalize_platform(record.get("platform")) or "unknown"
    external_id = str(record.get("job_id") or "").strip()
    title = str(record.get("title") or record.get("work_title") or "").strip()
    fingerprint = f"performance-import:{platform}:{external_id or title or 'snapshot'}"
    for job in store.list_jobs(500):
        if job.get("topic_fingerprint") == fingerprint:
            return str(job.get("id") or "")
    job = store.create_job(
        title or f"Imported performance snapshot {platform}",
        [platform],
        {
            "source": "performance_import",
            "analytics_only": True,
            "external_job_id": external_id,
        },
        topic_fingerprint=fingerprint,
    )
    return str(job["id"])


def import_performance_records(store: Any, records: Iterable[dict[str, Any]], *, allow_unknown_job: bool = False) -> dict[str, Any]:
    imported = 0
    errors = []
    for index, raw in enumerate(records, start=1):
        try:
            if not raw.get("job_id"):
                resolved = _resolve_job_id(store, raw)
                if resolved:
                    raw = {**raw, "job_id": resolved}
            record = _coerce_record(raw)
            if not allow_unknown_job:
                store.get_job(record["job_id"])
            else:
                try:
                    store.get_job(record["job_id"])
                except Exception:
                    record["job_id"] = _snapshot_job_for_unknown_import(store, raw)
            store.record_performance(
                record["job_id"],
                record["platform"],
                views=record["views"],
                likes=record["likes"],
                comments=record["comments"],
                shares=record["shares"],
                saves=record["saves"],
                follows=record["follows"],
                completion_rate=record["completion_rate"],
                three_second_view_rate=record["three_second_view_rate"],
                avg_watch_seconds=record["avg_watch_seconds"],
                extra_metrics=record["metrics"],
            )
            imported += 1
        except Exception as exc:
            errors.append({"index": index, "error": str(exc)})
    return {"imported": imported, "failed": len(errors), "errors": errors}


def import_performance_file(store: Any, path: str | Path, *, allow_unknown_job: bool = False) -> dict[str, Any]:
    source = Path(path)
    return import_performance_records(store, _load_records(source), allow_unknown_job=allow_unknown_job)


def _rate(numerator: float, denominator: float) -> float:
    return round(float(numerator) / max(1.0, float(denominator)), 4)


def review_performance(store: Any, thresholds: dict[str, Any] | None = None, expected_platforms: Iterable[str] | None = None) -> dict[str, Any]:
    cfg = {**DEFAULT_REVIEW_THRESHOLDS, **(thresholds or {})}
    summary = store.feedback_summary()
    report = {"platforms": {}, "totals": summary.get("totals", {}), "thresholds": cfg}
    expected = {str(platform).strip() for platform in (expected_platforms or []) if str(platform).strip()}
    for platform, row in (summary.get("platforms") or {}).items():
        expected.discard(platform)
        views = int(row.get("views", 0) or 0)
        sample_count = int(row.get("sample_count", 0) or 0)
        engagement_rate = _rate(row.get("engagement", 0), views)
        save_rate = _rate(row.get("saves", 0), views)
        follow_rate = _rate(row.get("follows", 0), views)
        findings = []
        if sample_count < int(cfg["min_samples_for_confident_review"]):
            findings.append("insufficient_samples")
        if engagement_rate < float(cfg["low_engagement_rate"]):
            findings.append("low_engagement_rate")
        if save_rate < float(cfg["low_save_rate"]):
            findings.append("low_save_rate")
        if follow_rate < float(cfg["low_follow_rate"]):
            findings.append("low_follow_conversion")
        if float(row.get("completion_rate", 0) or 0) and float(row.get("completion_rate", 0)) < float(cfg["low_completion_rate"]):
            findings.append("low_completion_rate")
        if float(row.get("three_second_view_rate", 0) or 0) and float(row.get("three_second_view_rate", 0)) < float(cfg["low_three_second_view_rate"]):
            findings.append("low_three_second_view_rate")
        report["platforms"][platform] = {
            **row,
            "sample_count": sample_count,
            "engagement_rate": engagement_rate,
            "save_rate": save_rate,
            "follow_rate": follow_rate,
            "confidence": "low" if "insufficient_samples" in findings else "normal",
            "findings": findings,
            "recommended_focus": _recommended_focus(findings),
        }
    for platform in sorted(expected):
        report["platforms"][platform] = {
            "views": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "saves": 0,
            "follows": 0,
            "engagement": 0,
            "completion_rate": 0.0,
            "three_second_view_rate": 0.0,
            "avg_watch_seconds": 0.0,
            "extra_metrics": {},
            "sample_count": 0,
            "engagement_rate": 0.0,
            "save_rate": 0.0,
            "follow_rate": 0.0,
            "confidence": "none",
            "findings": ["metrics_missing"],
            "recommended_focus": _recommended_focus(["metrics_missing"]),
        }
    return report


def _recommended_focus(findings: list[str]) -> list[str]:
    mapping = {
        "insufficient_samples": "collect_1h_24h_72h_metrics_before_trusting_strategy",
        "low_engagement_rate": "rebuild_title_cover_hook_and_comment_prompt",
        "low_save_rate": "increase_checklist_density_examples_and_embedded_knowledge_cards",
        "low_follow_conversion": "make_series_promise_and_profile_follow_reason_explicit",
        "low_completion_rate": "tighten_pacing_scene_changes_and_payoff_density",
        "low_three_second_view_rate": "rewrite_first_second_motion_and_opening_sentence",
        "metrics_missing": "collect_platform_backend_metrics",
    }
    return [mapping[item] for item in findings if item in mapping]
