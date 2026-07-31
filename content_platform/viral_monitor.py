"""Viral monitoring helpers for account growth decisions."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any


TIER_BASELINES = {
    "C": 0.30,
    "B": 0.15,
    "A": 0.08,
    "S": 0.04,
}


def account_tier(followers: int | float) -> str:
    followers = max(0, int(followers or 0))
    if followers >= 1_000_000:
        return "S"
    if followers >= 100_000:
        return "A"
    if followers >= 10_000:
        return "B"
    return "C"


def median_baseline(values: list[int | float], fallback: float = 1.0) -> float:
    cleaned = [float(item) for item in values if float(item or 0) > 0]
    if not cleaned:
        return float(fallback)
    return max(1.0, float(statistics.median(cleaned)))


def score_work(post: dict[str, Any], recent_metrics: list[int | float] | None = None) -> dict[str, Any]:
    """Score a single work with R/M/T-style growth signals.

    R compares the current work with the account's recent median.
    M compares engagement against a tier-adjusted follower baseline.
    """

    recent_metrics = recent_metrics or []
    views = float(post.get("views") or post.get("plays") or post.get("impressions") or 0)
    likes = float(post.get("likes") or 0)
    comments = float(post.get("comments") or 0)
    shares = float(post.get("shares") or post.get("reposts") or 0)
    saves = float(post.get("saves") or post.get("favorites") or 0)
    followers = float(post.get("followers") or post.get("account_followers") or 0)
    baseline = median_baseline(recent_metrics, fallback=max(1.0, views))
    tier = account_tier(followers)
    engagement = likes + comments * 2 + shares * 3 + saves * 2
    r_value = views / baseline if baseline else 0.0
    follower_base = max(1.0, followers * TIER_BASELINES[tier])
    m_value = engagement / follower_base
    grade = _grade(r_value, m_value)
    return {
        "platform": post.get("platform", ""),
        "title": post.get("title", ""),
        "url": post.get("url", ""),
        "tier": tier,
        "baseline": round(baseline, 3),
        "views": int(views),
        "engagement": int(engagement),
        "r_value": round(r_value, 3),
        "m_value": round(m_value, 3),
        "grade": grade,
        "recommendation": _recommendation(grade),
    }


def build_viral_report(posts: list[dict[str, Any]], recent_by_account: dict[str, list[int | float]] | None = None) -> dict[str, Any]:
    recent_by_account = recent_by_account or {}
    scored = []
    for post in posts:
        key = str(post.get("account") or post.get("account_handle") or post.get("author") or "default")
        scored.append(score_work(post, recent_by_account.get(key, [])))
    scored.sort(key=lambda row: (-row["r_value"], -row["m_value"], row["title"]))
    return {
        "ok": True,
        "count": len(scored),
        "viral_candidates": [row for row in scored if row["grade"] in {"T1", "T2"}],
        "items": scored,
        "topic_ammo": _topic_ammo(scored),
    }


def score_posts_file(input_path: str | Path, output_path: str | Path = "") -> dict[str, Any]:
    payload = json.loads(Path(input_path).read_text(encoding="utf-8-sig"))
    posts = payload.get("posts", payload if isinstance(payload, list) else [])
    recent = payload.get("recent_by_account", {}) if isinstance(payload, dict) else {}
    report = build_viral_report(posts, recent)
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output"] = str(output_path)
    return report


def _grade(r_value: float, m_value: float) -> str:
    if r_value >= 5.0 and m_value >= 1.2:
        return "T1"
    if r_value >= 3.0 or m_value >= 1.0:
        return "T2"
    if r_value >= 1.5 or m_value >= 0.6:
        return "T3"
    if r_value < 0.35 and m_value < 0.25:
        return "low_quality"
    return "normal"


def _recommendation(grade: str) -> str:
    return {
        "T1": "scale_this_angle",
        "T2": "adapt_with_platform_specific_hook",
        "T3": "test_small_batch",
        "low_quality": "avoid_repeating",
    }.get(grade, "observe")


def _topic_ammo(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ammo = []
    for item in scored[:10]:
        if item["grade"] in {"T1", "T2", "T3"}:
            ammo.append(
                {
                    "title": item["title"],
                    "platform": item["platform"],
                    "reason": f"{item['grade']} r={item['r_value']} m={item['m_value']}",
                    "recommended_use": item["recommendation"],
                }
            )
    return ammo
