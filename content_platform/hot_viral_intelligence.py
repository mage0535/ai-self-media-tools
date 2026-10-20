"""Evidence-first fusion of native and cross-platform viral works."""

from __future__ import annotations

from datetime import datetime
from typing import Any


BREAKDOWN_DIMENSIONS = (
    "copy",
    "hook",
    "writing_style",
    "illustration",
    "cover",
    "video_structure",
    "motion",
    "transition",
    "CTA",
)

ADJACENT_PLATFORMS = {
    "douyin": {"kuaishou", "tiktok", "xiaohongshu", "shipinhao", "youtube"},
    "douyin_ai": {"douyin", "kuaishou", "tiktok", "xiaohongshu", "shipinhao", "youtube", "bilibili", "zhihu"},
    "douyin_pet": {"douyin", "kuaishou", "tiktok", "xiaohongshu", "shipinhao", "youtube", "bilibili"},
    "kuaishou": {"douyin", "tiktok", "xiaohongshu", "shipinhao", "youtube"},
    "tiktok": {"douyin", "kuaishou", "xiaohongshu", "youtube"},
    "xiaohongshu": {"douyin", "kuaishou", "tiktok", "bilibili", "wechat"},
    "shipinhao": {"douyin", "kuaishou", "xiaohongshu", "youtube"},
    "youtube": {"tiktok", "douyin", "kuaishou", "bilibili", "shipinhao"},
    "bilibili": {"youtube", "xiaohongshu", "douyin"},
    "wechat": {"juejin", "zhihu", "xiaohongshu"},
    "juejin": {"wechat", "zhihu"},
    "zhihu": {"wechat", "juejin", "xiaohongshu"},
}
VALID_SOURCE_STATUSES = {"ready", "partial", "blocked", "fresh_empty"}
USABLE_SOURCE_STATUSES = {"ready", "partial"}
NATIVE_SIGNAL_FIELDS = {
    "rank",
    "hot_rank",
    "viral_rank",
    "views",
    "view_count",
    "plays",
    "play_count",
    "likes",
    "like_count",
    "comments",
    "comment_count",
    "shares",
    "share_count",
    "reposts",
    "repost_count",
    "favorites",
    "favorite_count",
    "saves",
    "save_count",
    "danmaku",
    "engagement",
}


def _present(value: Any) -> bool:
    return bool(value) if isinstance(value, (str, list, tuple, dict)) else value is not None


def _aware_timestamp(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _native_signal_present(sample: dict[str, Any]) -> bool:
    metrics = sample.get("metrics")
    if isinstance(metrics, dict) and any(field in metrics and _present(metrics[field]) for field in NATIVE_SIGNAL_FIELDS):
        return True
    return any(_present(sample.get(field)) for field in NATIVE_SIGNAL_FIELDS)


def _sample_failures(sample: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if not (str(sample.get("canonical_url") or "").strip() or str(sample.get("content_id") or "").strip()):
        failures.append("identity_missing")
    if not str(sample.get("author") or "").strip():
        failures.append("author_missing")
    if not _aware_timestamp(sample.get("published_at")):
        failures.append("published_at_missing_or_invalid")
    if not _aware_timestamp(sample.get("observed_at")):
        failures.append("observed_at_missing_or_invalid")
    if not _native_signal_present(sample):
        failures.append("native_signal_missing")
    if not _present(sample.get("content_evidence")):
        failures.append("content_evidence_missing")
    breakdown = sample.get("breakdown")
    if not isinstance(breakdown, dict):
        failures.append("breakdown_missing")
    else:
        failures.extend(f"breakdown_{dimension}_missing" for dimension in BREAKDOWN_DIMENSIONS if not _present(breakdown.get(dimension)))
    return failures


def _normalized_statuses(statuses: dict[str, str] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for source, status in (statuses or {}).items():
        value = str(status or "").casefold().strip()
        normalized[str(source)] = value if value in VALID_SOURCE_STATUSES else "blocked"
    return normalized


def _source_is_usable(sample: dict[str, Any], statuses: dict[str, str]) -> bool:
    source = str(sample.get("source") or "").strip()
    return bool(source) and statuses.get(source) in USABLE_SOURCE_STATUSES


def _breakdown_context(samples: list[dict[str, Any]]) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = {}
    for dimension in BREAKDOWN_DIMENSIONS:
        values: list[Any] = []
        for sample in samples:
            value = sample["breakdown"][dimension]
            if value not in values:
                values.append(value)
        result[dimension] = values
    return result


def _evidence_ref(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": str(sample.get("platform") or "").casefold().strip(),
        "source": str(sample.get("source") or ""),
        "canonical_url": str(sample.get("canonical_url") or ""),
        "content_id": str(sample.get("content_id") or ""),
        "author": str(sample.get("author") or ""),
        "published_at": sample.get("published_at"),
        "observed_at": sample.get("observed_at"),
        "metrics": dict(sample.get("metrics") or {}),
    }


def build_hot_viral_intelligence(
    *,
    target_platform: str,
    lane: str,
    samples: list[dict[str, Any]],
    source_statuses: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a machine-readable strategy context from audited viral works."""
    target = str(target_platform or "").casefold().strip()
    normalized_statuses = _normalized_statuses(source_statuses)
    topic_signal_count = sum(
        1
        for sample in samples
        if str(sample.get("lane") or "").strip() == str(lane or "").strip()
        and str(sample.get("signal_type") or "").casefold().strip() == "topic_signal"
    )
    native_candidates = [
        sample
        for sample in samples
        if str(sample.get("platform") or "").casefold().strip() == target
        and str(sample.get("lane") or "").strip() == str(lane or "").strip()
        and str(sample.get("signal_type") or "").casefold().strip() != "topic_signal"
    ]
    native = next(
        (sample for sample in native_candidates if not _sample_failures(sample) and _source_is_usable(sample, normalized_statuses)),
        None,
    )
    if native is not None:
        return {
            "version": "hot_viral_intelligence_v1",
            "target_platform": target,
            "lane": lane,
            "required_breakdown_dimensions": list(BREAKDOWN_DIMENSIONS),
            "status": "native_ready",
            "native_ready": True,
            "native_verified": True,
            "evidence_grade": "A_native_content",
            "topic_signal_count": topic_signal_count,
            "strategy_context": {
                "mode": "target_platform_native",
                "breakdown": dict(native["breakdown"]),
                "evidence_refs": [_evidence_ref(native)],
            },
            "source_statuses": normalized_statuses,
        }

    adjacent = ADJACENT_PLATFORMS.get(target, set())
    fallback_samples = [
        sample
        for sample in samples
        if str(sample.get("platform") or "").casefold().strip() in adjacent
        and str(sample.get("lane") or "").strip() == str(lane or "").strip()
        and str(sample.get("signal_type") or "").casefold().strip() != "topic_signal"
        and not _sample_failures(sample)
        and _source_is_usable(sample, normalized_statuses)
    ]
    fallback_sources = {str(sample.get("source") or "") for sample in fallback_samples}
    if len(fallback_sources) >= 2:
        source_platforms = sorted({str(sample.get("platform") or "").casefold().strip() for sample in fallback_samples})
        return {
            "version": "hot_viral_intelligence_v1",
            "target_platform": target,
            "lane": lane,
            "required_breakdown_dimensions": list(BREAKDOWN_DIMENSIONS),
            "status": "fallback_ready",
            "native_ready": False,
            "native_verified": False,
            "evidence_grade": "B_cross_platform_content",
            "topic_signal_count": topic_signal_count,
            "blocking_reasons": ["target_platform_native_evidence_unavailable"],
            "source_statuses": normalized_statuses,
            "strategy_context": {
                "mode": "fallback_generation_context",
                "claim_scope": "cross_platform_same_lane_reference_only",
                "not_target_platform_viral_proof": True,
                "source_platforms": source_platforms,
                "breakdown": _breakdown_context(fallback_samples),
                "evidence_refs": [_evidence_ref(sample) for sample in fallback_samples],
            },
        }

    failures = [failure for sample in native_candidates for failure in _sample_failures(sample)]
    if not native_candidates:
        failures.append("target_platform_same_lane_sample_missing")
    return {
        "version": "hot_viral_intelligence_v1",
        "target_platform": target,
        "lane": lane,
        "required_breakdown_dimensions": list(BREAKDOWN_DIMENSIONS),
        "status": "blocked",
        "native_ready": False,
        "native_verified": False,
        "evidence_grade": "C_topic_signal_only" if topic_signal_count else "D_insufficient",
        "topic_signal_count": topic_signal_count,
        "source_statuses": normalized_statuses,
        "blocking_reasons": list(dict.fromkeys(failures)),
        "strategy_context": {"mode": "unavailable", "breakdown": {}},
    }
