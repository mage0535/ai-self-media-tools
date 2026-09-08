from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any


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


def _freshness(value: Any, now: datetime) -> float:
    try:
        captured = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        days = max(0.0, (now - captured.astimezone(timezone.utc)).total_seconds() / 86400)
    except ValueError:
        return 0.0
    if days <= 1:
        return 1.0
    if days <= 7:
        return 0.75
    if days <= 30:
        return 0.4
    return 0.1


def _lane_fit(title: str, keywords: list[str]) -> float:
    value = str(title or "").casefold()
    wanted = [str(item).casefold().strip() for item in keywords if str(item).strip()]
    if not wanted:
        return 0.5
    matches = sum(1 for item in wanted if item in value)
    return min(1.0, matches / max(1, min(3, len(wanted))))


def score_intelligence_item(
    item: dict[str, Any],
    *,
    target_platform: str,
    lane_keywords: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    platform = str(item.get("platform") or "").casefold()
    target = str(target_platform or "").casefold()
    role = str(item.get("identity_role") or "")
    evidence = str(item.get("evidence_type") or item.get("evidence_strength") or "").casefold()
    same_platform = platform == target
    if same_platform and evidence in {"native", "official_activity", "official_keyword"}:
        identity = 1.0
    elif same_platform:
        identity = 0.85
    elif role == "cross_platform_reference":
        identity = 0.35
    else:
        identity = 0.1
    metric = max(_number(item.get(key)) for key in ("heat", "views", "likes", "engagement", "points"))
    heat = min(1.0, math.log10(metric + 1) / 7.0) if metric > 0 else 0.0
    freshness = _freshness(item.get("captured_at") or item.get("collected_at"), current)
    lane = _lane_fit(str(item.get("title") or ""), lane_keywords or [])
    analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}
    useful_structure = any(value and value != "结构待补" for value in analysis.get("structure_types") or [])
    content_value = float(item.get("content_value_score") or (0.75 if useful_structure else 0.5))
    saturation = min(1.0, max(0.0, float(item.get("saturation_score") or 0.35)))
    source_complete = bool(
        str(item.get("url") or "").startswith(("https://", "http://"))
        and item.get("captured_at")
        and item.get("collector")
    )
    source_quality = 1.0 if source_complete else 0.25
    total = (
        0.27 * identity + 0.16 * heat + 0.14 * freshness + 0.20 * lane
        + 0.12 * content_value + 0.07 * (1.0 - saturation) + 0.04 * source_quality
    )
    return {
        "platform": platform,
        "target_platform": target,
        "identity_role": role or ("target_platform" if same_platform else "unclassified"),
        "target_ready_eligible": bool(same_platform and role != "cross_platform_reference"),
        "score": round(total, 6),
        "dimensions": {
            "identity": round(identity, 4),
            "heat": round(heat, 4),
            "freshness": round(freshness, 4),
            "lane_fit": round(lane, 4),
            "content_value": round(content_value, 4),
            "saturation_penalty": round(saturation, 4),
            "source_quality": round(source_quality, 4),
        },
    }


def evaluate_intelligence_pool(
    items: list[dict[str, Any]],
    *,
    target_platform: str,
    lane_keywords: list[str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append({**item, "intelligence_score": score_intelligence_item(
            item, target_platform=target_platform, lane_keywords=lane_keywords, now=now,
        )})
    return sorted(rows, key=lambda row: row["intelligence_score"]["score"], reverse=True)


__all__ = ["evaluate_intelligence_pool", "score_intelligence_item"]
