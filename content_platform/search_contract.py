"""Offline search request and media-candidate contracts."""

from __future__ import annotations

import re
from typing import Any

VERSION = "search_spec_v1"
_PLATFORM_QUERY = {
    "douyin_ai": "抖音 AI效率",
    "kuaishou": "快手 AI效率",
    "shipinhao": "视频号 AI效率",
    "bilibili": "B站 AI工具教程",
    "zhihu": "知乎 AI效率问题解决",
    "juejin": "掘金 开发者工具实战",
    "youtube": "YouTube AI productivity",
    "tiktok": "TikTok AI productivity",
}


def _tokens(value: str) -> set[str]:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(value or "").lower())
    return {token for token in normalized.split() if len(token) > 1}


def build_search_spec(
    topic: str,
    platform: str,
    visual_style: str,
    aspect_ratio: str | None = None,
    language: str = "zh-CN",
) -> dict[str, Any]:
    topic = str(topic or "").strip()
    visual_style = str(visual_style or "").strip()
    platform_query = _PLATFORM_QUERY.get(platform, platform.replace("_", " "))
    semantic = f"{topic}，{visual_style}，真实工作场景，可用于内容配图或视频素材"
    tags = [item for item in [topic, visual_style, "真实场景", "工作流"] if item]
    return {
        "version": VERSION,
        "original_query": topic,
        "platform": platform,
        "language": language,
        "queries": {
            "semantic": semantic,
            "tags": tags,
            "platform": f"{platform_query} {topic}".strip(),
        },
        "filters": {
            "aspect_ratio": aspect_ratio,
            "min_width": 512,
            "min_height": 512,
            "license_required": True,
            "downloadable_required": True,
        },
        "evidence_required": [
            "canonical_url",
            "source_id",
            "retrieved_at",
            "license_url",
            "media_hash",
        ],
    }


def _aspect_ratio(value: str | None) -> float | None:
    if not value or ":" not in value:
        return None
    left, right = value.split(":", 1)
    try:
        return float(left) / float(right)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def score_candidate(candidate: dict[str, Any], search: dict[str, Any]) -> dict[str, Any]:
    """Apply hard gates first, then return an explainable soft score."""
    hard_failures: list[str] = []
    if not candidate.get("license_verified"):
        hard_failures.append("license_unverified")
    if not candidate.get("downloadable"):
        hard_failures.append("not_downloadable")
    width = candidate.get("width")
    height = candidate.get("height")
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        hard_failures.append("dimensions_missing")
    else:
        filters = search.get("filters", {})
        if width < filters.get("min_width", 0) or height < filters.get("min_height", 0):
            hard_failures.append("dimensions_too_small")

    query_tokens = _tokens(" ".join(search.get("queries", {}).get("tags", [])))
    candidate_tokens = _tokens(f"{candidate.get('title', '')} {' '.join(candidate.get('tags', []))}")
    overlap = query_tokens & candidate_tokens
    semantic_match = min(1.0, len(overlap) / max(1, min(4, len(query_tokens))))
    technical_fit = 1.0 if not hard_failures else 0.0
    score = round(semantic_match * 0.65 + technical_fit * 0.35, 4)
    reasons = []
    if overlap:
        reasons.append(f"keyword_overlap:{','.join(sorted(overlap))}")
    if technical_fit:
        reasons.append("technical_constraints_passed")
    return {
        "candidate_id": candidate.get("id", ""),
        "passed": not hard_failures,
        "score": score if not hard_failures else 0.0,
        "hard_failures": hard_failures,
        "reasons": reasons,
        "signals": {
            "semantic_match": round(semantic_match, 4),
            "technical_fit": technical_fit,
        },
    }
