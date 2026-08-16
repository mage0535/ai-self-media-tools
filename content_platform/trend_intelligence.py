"""Cached, evidence-preserving trend intelligence for topic selection."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .trends import normalize_topic


SUCCESS_STATUSES = {"ok", "success", "saved", "usable"}
SNAPSHOT_GLOB = "trend_snapshot_*.json"


def collect_daily_snapshot(
    collect: Callable[[], dict[str, Any]],
    *,
    cache_dir: str | Path,
    now: datetime | None = None,
    max_age_hours: float = 18,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Collect once per freshness window and keep source failures observable."""
    now = _utc_now(now)
    path = Path(cache_dir) / f"trend_snapshot_{now.date().isoformat()}.json"
    cached = _load_snapshot(path)
    if cached and not force_refresh and _is_fresh(cached, now, max_age_hours):
        return {**cached, "snapshot_path": str(path), "cache_status": "reused"}

    report = collect() or {}
    payload = {
        "version": "trend_snapshot_v1",
        "collected_at": now.isoformat(),
        "items": _copy_dict_rows(report.get("items")),
        "sources": _copy_dict_rows(report.get("sources")),
        "summary": dict(report.get("summary") or {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {**payload, "snapshot_path": str(path), "cache_status": "refreshed"}


def load_previous_snapshot(cache_dir: str | Path, *, current_path: str | Path = "") -> dict[str, Any]:
    """Return the newest earlier valid snapshot, or an empty baseline."""
    current = Path(current_path).resolve() if current_path else None
    paths = sorted(Path(cache_dir).glob(SNAPSHOT_GLOB), reverse=True)
    for path in paths:
        if current and path.resolve() == current:
            continue
        snapshot = _load_snapshot(path)
        if snapshot:
            return {**snapshot, "snapshot_path": str(path)}
    return {"items": [], "sources": [], "summary": {}, "snapshot_path": ""}


def detect_breakouts(
    current: dict[str, Any],
    previous: dict[str, Any] | None = None,
    *,
    minimum_delta: float = 20,
    minimum_ratio: float = 2.0,
) -> list[dict[str, Any]]:
    """Mark candidates whose observed source score rose materially since the last snapshot."""
    previous_points = {
        normalize_topic(row.get("title", "")): _number(row.get("points"))
        for row in _copy_dict_rows((previous or {}).get("items"))
        if normalize_topic(row.get("title", ""))
    }
    result = []
    for row in _copy_dict_rows(current.get("items")):
        key = normalize_topic(row.get("title", ""))
        points = _number(row.get("points"))
        baseline = previous_points.get(key)
        delta = points - baseline if baseline is not None else 0.0
        ratio = (points / baseline) if baseline and baseline > 0 else 0.0
        result.append(
            {
                **row,
                "breakout": bool(baseline is not None and delta >= minimum_delta and ratio >= minimum_ratio),
                "breakout_delta": _compact_number(delta),
                "breakout_ratio": round(ratio, 3),
            }
        )
    return result


def calibrate_candidates(items: list[dict[str, Any]], learned: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Apply existing account feedback without fabricating a score when history is absent."""
    learned = learned or {}
    source_weights = {str(key).casefold(): _number(value) for key, value in (learned.get("preferred_sources") or {}).items()}
    clusters = [row for row in learned.get("preferred_clusters", []) if isinstance(row, dict)]
    calibrated = []
    for row in _copy_dict_rows(items):
        title = str(row.get("title") or "").casefold()
        source_bonus = source_weights.get(str(row.get("source") or "").casefold(), 0.0)
        cluster_bonus = max(
            (
                _number(cluster.get("weight"))
                for cluster in clusters
                if _cluster_matches(title, cluster)
            ),
            default=0.0,
        )
        historical_fit = round(source_bonus + cluster_bonus, 3)
        score = _number(row.get("score"))
        calibrated.append(
            {
                **row,
                "historical_fit_score": historical_fit,
                "calibrated_score": round(score + historical_fit, 3),
                "historical_feedback_available": bool(source_weights or clusters),
            }
        )
    return sorted(calibrated, key=lambda row: (-_number(row.get("calibrated_score")), str(row.get("title") or "")))


def build_platform_matrix(
    platform: str,
    snapshot: dict[str, Any],
    candidate: dict[str, Any],
    *,
    platform_keywords: list[str] | None = None,
    strategy_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the existing matrix contract from live source outcomes for one platform."""
    normalized = str(platform or "").casefold()
    sources = _copy_dict_rows(snapshot.get("sources"))
    aliases = _platform_aliases(normalized)
    source_name = str(candidate.get("source") or "").casefold()
    collected_at = str(snapshot.get("collected_at") or "")
    for row in sources:
        if collected_at:
            row.setdefault("collected_at", collected_at)
    platform_sources = [
        row
        for row in sources
        if str(row.get("status") or "").casefold() in SUCCESS_STATUSES
        and bool(row.get("collected_at"))
        and any(alias in str(row.get("source") or "").casefold() for alias in aliases)
    ]
    candidate_platform_evidence = any(
        _source_matches(source_name, str(row.get("source") or ""))
        for row in platform_sources
    )
    candidate_source_url_native = _candidate_source_url_is_native(normalized, candidate)
    samples = []
    if candidate_platform_evidence and candidate_source_url_native and str(candidate.get("title") or "").strip():
        samples.append(
            {
                "source": str(candidate.get("source") or ""),
                "title": str(candidate["title"]),
                **({"url": str(candidate["url"])} if candidate.get("url") else {}),
            }
        )
    strategy_status = strategy_status or {}
    strategy_verified = str(strategy_status.get("status") or "").casefold() == "ok"
    successful = [row for row in sources if str(row.get("status") or "").casefold() in SUCCESS_STATUSES]
    verified = bool(platform_sources and samples)
    return {
        "version": "platform_source_matrix_v2",
        "platform": normalized,
        "attempted_sources": sources,
        "sources_attempted": len(sources),
        "sources_succeeded": len(successful),
        "successful_source_count": len(successful),
        "platform_internal_verified": verified,
        "real_platform_collection_verified": verified,
        "current_platform_specific_topic": verified,
        "platform_strategy_verified": strategy_verified,
        "shared_trend_only": not verified,
        "platform_fit_reason": _platform_fit_reason(normalized, candidate, platform_keywords or []),
        "candidate_source": str(candidate.get("source") or ""),
        "candidate_source_url_native": candidate_source_url_native,
        "candidate_breakout": bool(candidate.get("breakout")),
        "report_path": str(snapshot.get("snapshot_path") or "runtime:trend_snapshot"),
        "trend_evidence": {
            "source": str(candidate.get("source") or "") if verified else "",
            "collected_at": str(platform_sources[0].get("collected_at") or "") if verified else "",
            "samples": samples,
        },
    }


def _load_snapshot(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_fresh(snapshot: dict[str, Any], now: datetime, max_age_hours: float) -> bool:
    try:
        collected = datetime.fromisoformat(str(snapshot.get("collected_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    if collected.tzinfo is None:
        collected = collected.replace(tzinfo=timezone.utc)
    return now - collected.astimezone(timezone.utc) <= timedelta(hours=float(max_age_hours))


def _platform_aliases(platform: str) -> set[str]:
    aliases = {platform}
    aliases.update({"rednote"} if platform == "xiaohongshu" else set())
    aliases.update({"douyin"} if platform.startswith("douyin_") else set())
    aliases.update({"twitter"} if platform == "x" else set())
    return {item for item in aliases if item}


def _source_matches(candidate_source: str, collected_source: str) -> bool:
    """Preserve provenance while allowing a named collection transport suffix."""
    candidate = str(candidate_source or "").casefold()
    collected = str(collected_source or "").casefold()
    return bool(candidate and collected and (candidate == collected or candidate.startswith(collected + ":")))


def _candidate_source_url_is_native(platform: str, candidate: dict[str, Any]) -> bool:
    """A web-search transport qualifies only when its result URL is native."""
    source = str(candidate.get("source") or "").casefold()
    if not source.endswith(":web_search"):
        return True
    host = (urlparse(str(candidate.get("url") or "")).hostname or "").casefold()
    roots = {
        "douyin": ("douyin.com", "iesdouyin.com"),
        "tiktok": ("tiktok.com",),
        "youtube": ("youtube.com", "youtu.be"),
        "xiaohongshu": ("xiaohongshu.com", "xhslink.com"),
        "zhihu": ("zhihu.com",),
        "juejin": ("juejin.cn",),
        "bilibili": ("bilibili.com", "b23.tv"),
        "kuaishou": ("kuaishou.com", "gifshow.com"),
        "shipinhao": ("weixin.qq.com", "channels.weixin.qq.com"),
        "twitter": ("x.com", "twitter.com"),
    }
    target = "douyin" if platform.startswith("douyin_") else platform
    return any(host == root or host.endswith("." + root) for root in roots.get(target, ()))


def _platform_fit_reason(platform: str, candidate: dict[str, Any], keywords: list[str]) -> str:
    title = str(candidate.get("title") or "")
    matched = [str(word) for word in keywords if str(word).casefold() in title.casefold()]
    source = str(candidate.get("source") or "unknown")
    if matched:
        return f"{platform} lane keywords matched: {', '.join(matched[:3])}; source={source}"
    return f"{platform} candidate selected from source={source}; platform-specific evidence is recorded separately"


def _cluster_matches(title: str, cluster: dict[str, Any]) -> bool:
    terms = [cluster.get("label"), *list(cluster.get("topic_signals") or [])]
    return any(str(term).casefold() in title for term in terms if str(term).strip())


def _copy_dict_rows(rows: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in (rows or []) if isinstance(row, dict)]


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _compact_number(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 3)


def _utc_now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
