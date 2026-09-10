from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


SAME_PLATFORM_WORK = "same_platform_same_lane_work"
OFFICIAL_REFERENCE = "official_activity_or_keyword"
CROSS_PLATFORM_REFERENCE = "cross_platform_reference"

_WORK_EVIDENCE = {"same_lane_hot_work", "native"}
_OFFICIAL_EVIDENCE = {"official_activity", "official_keyword", "official_reference"}


def _number(value: Any) -> float:
    text = str(value or "").replace(",", "").strip().casefold()
    factor = 1.0
    if text.endswith("k"):
        text, factor = text[:-1], 1_000.0
    elif text.endswith("m"):
        text, factor = text[:-1], 1_000_000.0
    elif "万" in text:
        text, factor = text.replace("万", ""), 10_000.0
    try:
        return float(text) * factor
    except ValueError:
        return 0.0


def _metric(item: dict[str, Any]) -> float:
    return max(_number(item.get(key)) for key in ("heat", "views", "likes", "engagement", "points", "favorites"))


def _freshness(item: dict[str, Any], now: datetime) -> float:
    raw = item.get("captured_at") or item.get("collected_at")
    try:
        captured = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - captured.astimezone(timezone.utc)).total_seconds() / 86400)
    except ValueError:
        return 0.0
    if age_days <= 1:
        return 1.0
    if age_days <= 7:
        return 0.75
    if age_days <= 30:
        return 0.4
    return 0.0


def _source_complete(item: dict[str, Any]) -> bool:
    return bool(
        str(item.get("title") or "").strip()
        and str(item.get("url") or "").startswith(("https://", "http://"))
        and item.get("captured_at")
        and item.get("collector")
    )


def _terms(item: dict[str, Any], lane_keywords: list[str]) -> set[str]:
    title = str(item.get("title") or "").casefold()
    return {str(word).casefold().strip() for word in lane_keywords if str(word).strip() and str(word).casefold().strip() in title}


def _related(left: dict[str, Any], right: dict[str, Any], lane_keywords: list[str]) -> bool:
    left_terms = _terms(left, lane_keywords)
    right_terms = _terms(right, lane_keywords)
    shared = left_terms & right_terms
    return len(shared) >= 2 or (len(lane_keywords) == 1 and bool(shared))


def _layer(item: dict[str, Any], target_platform: str) -> str:
    role = str(item.get("identity_role") or "").casefold()
    platform = str(item.get("platform") or "").casefold()
    evidence = str(item.get("evidence_type") or "").casefold()
    if role == CROSS_PLATFORM_REFERENCE:
        return CROSS_PLATFORM_REFERENCE
    if platform != target_platform:
        return "invalid_cross_platform_identity"
    if evidence in _OFFICIAL_EVIDENCE or item.get("official_reference_only") is True:
        return OFFICIAL_REFERENCE
    if evidence in _WORK_EVIDENCE:
        return SAME_PLATFORM_WORK
    return "unsupported"


def decide_topic(
    target_platform: str,
    items: list[dict[str, Any]],
    *,
    lane_keywords: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    target = str(target_platform or "").casefold().strip()
    keywords = [str(value).strip() for value in (lane_keywords or []) if str(value).strip()]
    current = now or datetime.now(timezone.utc)
    works: list[dict[str, Any]] = []
    official: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        layer = _layer(item, target)
        if not _source_complete(item):
            rejected.append({**item, "reason": "source_contract_incomplete"})
            continue
        if keywords and not _terms(item, keywords):
            rejected.append({**item, "reason": "account_lane_mismatch"})
            continue
        if layer == SAME_PLATFORM_WORK:
            if _metric(item) <= 0:
                rejected.append({**item, "reason": "same_platform_work_metric_missing"})
                continue
            works.append(item)
        elif layer == OFFICIAL_REFERENCE:
            official.append(item)
        elif layer == CROSS_PLATFORM_REFERENCE:
            references.append({**item, "identity_role": CROSS_PLATFORM_REFERENCE})
        else:
            rejected.append({**item, "reason": layer})

    candidates = works or official
    max_metric = max((_metric(item) for item in works), default=0.0)
    ranked: list[dict[str, Any]] = []
    for item in candidates:
        layer = SAME_PLATFORM_WORK if item in works else OFFICIAL_REFERENCE
        lane_fit = min(1.0, max(0.0, float(item.get("lane_fit_score") or 0.0)))
        value = min(1.0, max(0.0, float(item.get("content_value_score") or 0.5)))
        saturation = min(1.0, max(0.0, float(item.get("saturation_score") or 0.0)))
        performance = math.log1p(_metric(item)) / math.log1p(max_metric) if max_metric and item in works else 0.0
        supports = [row for row in official if row is not item and _related(item, row, keywords)]
        references_for_topic = [row for row in references if _related(item, row, keywords)]
        official_score = 1.0 if supports or layer == OFFICIAL_REFERENCE else 0.0
        reference_score = 1.0 if references_for_topic else 0.0
        score = (
            0.45 * performance
            + 0.20 * official_score
            + 0.10 * _freshness(item, current)
            + 0.10 * lane_fit
            + 0.10 * value
            + 0.05 * reference_score
            - 0.15 * saturation
        )
        verified_hotspot = item.get("associated_hotspot") if isinstance(item.get("associated_hotspot"), dict) else None
        if not (verified_hotspot and verified_hotspot.get("native_verified") is True):
            verified_hotspot = None
        ranked.append({
            **item,
            "selection_layer": layer,
            "decision_score": round(score, 6),
            "official_support": supports,
            "cross_platform_support": references_for_topic,
            "native_verified": bool(verified_hotspot),
            "associated_hotspot": verified_hotspot,
        })

    ranked.sort(key=lambda row: row["decision_score"], reverse=True)
    status = "selected" if ranked else "reference_only" if references else "insufficient"
    return {
        "version": "topic_decision_v1",
        "platform": target,
        "status": status,
        "selected": ranked[0] if ranked else None,
        "ranked": ranked,
        "references": references,
        "rejected": rejected,
        "coverage": {
            SAME_PLATFORM_WORK: len(works),
            OFFICIAL_REFERENCE: len(official),
            CROSS_PLATFORM_REFERENCE: len(references),
        },
    }


__all__ = ["decide_topic"]
