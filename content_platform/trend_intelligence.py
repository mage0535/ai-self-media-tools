"""Cached, evidence-preserving trend intelligence for topic selection."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
import hashlib
import os
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .trends import normalize_topic


SUCCESS_STATUSES = {"ok", "success", "saved", "usable"}
SNAPSHOT_GLOB = "trend_snapshot_*.json"
SCHEDULED_PLATFORM_INTELLIGENCE_PLATFORMS = (
    "wechat", "xiaohongshu", "douyin_ai", "douyin_pet", "kuaishou", "bilibili",
    "shipinhao", "zhihu", "juejin", "youtube", "tiktok", "twitter",
)


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


def validate_platform_candidate(candidate: dict[str, Any] | None, platform: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Validate identity and freshness before a platform can select a topic."""
    now = _utc_now(now)
    target = str(platform or "").casefold().strip()
    row = dict(candidate or {})
    failures = []
    candidate_platform = str(row.get("platform") or "").casefold().strip()
    if candidate_platform and candidate_platform != target:
        failures.append("candidate_platform_mismatch")
    if not target:
        failures.append("task_platform_missing")
    if not str(row.get("title") or "").strip():
        failures.append("candidate_title_missing")
    expiry = _parse_candidate_time(row.get("expires_at") or row.get("valid_until"))
    if expiry and expiry <= now:
        failures.append("candidate_expired")
    if str(row.get("validity") or "").casefold() in {"expired", "invalid"}:
        failures.append("candidate_invalidity")
    evidence = str(row.get("evidence_type") or "native").casefold()
    if evidence not in {"native", "official_activity", "official_keyword", "same_lane_hot_work", "unavailable"}:
        failures.append("evidence_type_invalid")
    if evidence == "unavailable" or row.get("source_unavailable") is True:
        failures.append("candidate_unavailable")
    if evidence in {"official_activity", "official_keyword", "official_reference"}:
        row["native_verified"] = False
        row["native_evidence"] = False
    if row.get("official_reference_only") and row.get("native_verified") is True:
        failures.append("official_reference_marked_native")
    if not failures:
        row["platform"] = target
    return {"passed": not failures, "failures": sorted(set(failures)), "candidate": row}


def rank_platform_candidates(candidates: list[dict[str, Any]], platform: str, *, lane_keywords: list[str] | tuple[str, ...] = (), account_history: dict[str, Any] | None = None, used_topics: set[str] | None = None, now: datetime | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Rank valid same-platform evidence with an inspectable score breakdown."""
    now = _utc_now(now)
    used = {normalize_topic(value) for value in (used_topics or set())}
    ranked = []
    for candidate in candidates or []:
        checked = validate_platform_candidate(candidate, platform, now=now)
        if not checked["passed"]:
            continue
        row = checked["candidate"]
        if normalize_topic(row.get("title")) in used:
            continue
        if row.get("lane_match") is False or _bounded(row.get("semantic_fit_score"), 0.0) < 0.45:
            continue
        text = str(row.get("title") or "").casefold()
        keyword_fit = min(1.0, sum(str(word).casefold() in text for word in lane_keywords) / max(1, len(lane_keywords)))
        breakdown = {
            "native_priority": 1.0 if row.get("evidence_type", "native") == "native" and not row.get("official_reference_only") else 0.65,
            "heat": _bounded(row.get("heat_score"), _heat(row)), "rank": _rank_score(row.get("rank")),
            "velocity": _bounded(row.get("velocity_score"), 0.0), "validity": 1.0,
            "lane_fit": max(_bounded(row.get("lane_fit_score"), 0.0), keyword_fit),
            "semantic_fit": _bounded(row.get("semantic_fit_score"), 0.0), "content_value": _bounded(row.get("content_value_score"), 0.0),
            "actionability": _bounded(row.get("actionability_score"), 0.0), "saturation": _bounded(row.get("saturation_score"), 0.0),
            "account_history": _bounded(row.get("account_history_score"), _bounded((account_history or {}).get(platform), 0.0)),
        }
        score = sum(breakdown[key] * weight for key, weight in {
            "native_priority": .18, "heat": .14, "rank": .07, "velocity": .10, "validity": .10,
            "lane_fit": .12, "semantic_fit": .10, "content_value": .07, "actionability": .06,
            "saturation": -.05, "account_history": .06,
        }.items())
        ranked.append({**row, "platform": platform.casefold(), "score": round(score, 6), "score_breakdown": breakdown, "evidence": _evidence_record(row, platform)})
    return sorted(ranked, key=lambda row: (-row["score"], str(row.get("title") or "")))[: int(limit)]


def bounded_same_platform_recapture(platform: str, recapture: Callable[[str, int], list[dict[str, Any]]], *, max_attempts: int = 3, now: datetime | None = None) -> dict[str, Any]:
    attempts = []
    evidence = []
    for attempt in range(1, max(0, int(max_attempts)) + 1):
        rows = []
        for candidate in recapture(platform, attempt) or []:
            checked = validate_platform_candidate(candidate, platform, now=now)
            if checked["passed"]:
                rows.append(checked["candidate"])
        attempts.append({"attempt": attempt, "candidate_count": len(rows)})
        evidence.append({"attempt": attempt, "sources": sorted({str(row.get("source") or "") for row in rows if row.get("source")})})
        if rows:
            return {"platform": str(platform).casefold(), "candidates": rows, "attempts": attempts, "attempt_evidence": evidence, "exhausted": False}
    return {"platform": str(platform).casefold(), "candidates": [], "attempts": attempts, "attempt_evidence": evidence, "exhausted": True}


def reserve_topic_atomically(path: str | Path, topic: str, platform: str, job_id: str, *, now: datetime | None = None, ttl_hours: float = 6, lookback_days: int = 7, copy_text: str = "", follow_up_to: str = "", difference_angle: str = "", recap_reason: str = "") -> dict[str, Any]:
    now = _utc_now(now)
    fingerprint = normalize_topic(topic)
    if not fingerprint:
        return {"reserved": False, "reason": "topic_missing", "fingerprint": ""}
    if any((follow_up_to, difference_angle, recap_reason)) and not all((follow_up_to, difference_angle, recap_reason)):
        return {"reserved": False, "reason": "follow_up_metadata_incomplete", "fingerprint": fingerprint}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name(target.name + ".lock")
    for _ in range(50):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            time.sleep(0.01)
    else:
        return {"reserved": False, "reason": "reservation_lock_busy", "fingerprint": fingerprint}
    try:
        payload = {"version": "topic_reservations_v2", "reservations": []}
        if target.is_file():
            try:
                loaded = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass
        active = []
        for row in payload.get("reservations") or []:
            expiry = _parse_candidate_time(row.get("expires_at")) if isinstance(row, dict) else None
            used_at = _parse_candidate_time(row.get("used_at")) if isinstance(row, dict) else None
            recent_used = used_at and used_at >= now - timedelta(days=max(0, int(lookback_days)))
            if isinstance(row, dict) and ((row.get("status") == "reserved" and expiry and expiry > now) or (row.get("status") == "consumed" and recent_used)):
                active.append(row)
        copy_fingerprint = normalize_topic(copy_text)
        duplicates = [row for row in active if _semantic_duplicate(fingerprint, row.get("fingerprint", "")) or (copy_fingerprint and _semantic_duplicate(copy_fingerprint, row.get("copy_fingerprint", "")))]
        if duplicates:
            permitted_follow_up = all((follow_up_to, difference_angle, recap_reason)) and any(_semantic_duplicate(normalize_topic(follow_up_to), row.get("fingerprint", "")) for row in duplicates)
            if not permitted_follow_up:
                return {"reserved": False, "reason": "semantic_topic_duplicate", "fingerprint": fingerprint}
        reservation = {
            "fingerprint": fingerprint, "topic": str(topic).strip(), "platform": str(platform).casefold(), "job_id": str(job_id),
            "status": "reserved", "reserved_at": now.isoformat(), "expires_at": (now + timedelta(hours=float(ttl_hours))).isoformat(),
            "copy_fingerprint": copy_fingerprint, "follow_up_to": str(follow_up_to), "difference_angle": str(difference_angle), "recap_reason": str(recap_reason),
        }
        payload["reservations"] = active + [reservation]
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(target)
        return {"reserved": True, **reservation}
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def expire_abandoned_reservations(path: str | Path, *, now: datetime | None = None) -> list[dict[str, Any]]:
    now = _utc_now(now)
    target = Path(path)
    if not target.is_file():
        return []
    payload = json.loads(target.read_text(encoding="utf-8"))
    expired = []
    for row in payload.get("reservations", []):
        expiry = _parse_candidate_time(row.get("expires_at"))
        if row.get("status") == "reserved" and expiry and expiry <= now:
            row["status"] = "expired"; row["expired_at"] = now.isoformat(); row["expiration_reason"] = "abandoned_reservation_ttl"; expired.append(dict(row))
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return expired


def complete_topic_reservation(path: str | Path, fingerprint: str, *, now: datetime | None = None) -> bool:
    """Move a reservation to consumed so it remains in the seven-day ledger."""
    target = Path(path)
    if not target.is_file():
        return False
    payload = json.loads(target.read_text(encoding="utf-8"))
    for row in payload.get("reservations", []):
        if row.get("fingerprint") == normalize_topic(fingerprint) and row.get("status") == "reserved":
            row["status"] = "consumed"; row["used_at"] = _utc_now(now).isoformat()
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            return True
    return False


def _evidence_record(row: dict[str, Any], platform: str) -> dict[str, Any]:
    raw = json.dumps({key: row.get(key) for key in ("platform", "title", "source", "url", "captured_at", "evidence_type")}, ensure_ascii=False, sort_keys=True)
    return {"platform": platform, "url": str(row.get("url") or ""), "captured_at": str(row.get("captured_at") or ""), "source": str(row.get("source") or ""), "evidence_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "confidence": round(_bounded(row.get("confidence"), 0.8), 3)}


def _parse_candidate_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _bounded(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _heat(row: dict[str, Any]) -> float:
    import math
    return min(1.0, math.log1p(max(0.0, _number(row.get("points")))) / 12.0)


def _rank_score(value: Any) -> float:
    try:
        rank = float(value)
        return 1.0 if rank <= 1 else max(0.0, 1.0 - (rank - 1) / 20.0)
    except (TypeError, ValueError):
        return 0.0


def _semantic_duplicate(left: str, right: str) -> bool:
    left_tokens = {_semantic_token(token) for token in left.split()}
    right_tokens = {_semantic_token(token) for token in str(right).split()}
    return bool(left_tokens and right_tokens and len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens)) >= 0.8)


def _semantic_token(token: str) -> str:
    token = str(token).strip()
    return token[:-1] if len(token) > 4 and token.endswith("s") else token


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
        "wechat": ("mp.weixin.qq.com", "weixin.qq.com"),
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
