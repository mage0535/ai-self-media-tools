"""Materialize review-only dual-lane plans from the latest public evidence bundle."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .dual_lane_work_planner import build_work_plan
from .real_world_ai_policy import load_real_world_ai_positioning

PLATFORMS = tuple(load_real_world_ai_positioning().get("platforms") or [])
_ALIASES = {"douyin": "douyin_ai"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_public_observation(item: Any) -> dict[str, Any] | None:
    """Convert only a public work snapshot; topic boards are intentionally ignored."""
    if not isinstance(item, dict):
        return None
    platform = _ALIASES.get(str(item.get("platform") or "").casefold(), str(item.get("platform") or "").casefold())
    content_id = str(item.get("content_id") or "").strip()
    url = str(item.get("canonical_url") or "").strip()
    observed_at = str(item.get("observed_at") or "").strip()
    raw_hash = str(item.get("raw_response_hash") or "").strip()
    signal_type = str(item.get("signal_type") or "").casefold()
    if not content_id or not url or "/hot" in url or signal_type == "topic_signal":
        return None
    return {
        "version": "intelligence_provenance_v1",
        "evidence_id": f"public:{platform}:{content_id}:{raw_hash[:12]}",
        "source_class": "public_web_observation",
        "origin_platform": platform,
        "observed_at": observed_at,
        "ingested_at": _now(),
        "collector_id": str(item.get("collector") or item.get("source") or "public_work_snapshot"),
        "content_locator": url,
        "integrity": {"sha256": raw_hash},
        "use_policy": {},
        "title": str(item.get("title") or ""),
        "excerpt": str(item.get("excerpt") or ""),
        "public_metrics": dict(item.get("metrics") or {}) if isinstance(item.get("metrics"), dict) else {},
    }


def build_dual_lane_work_plans(bundle: dict[str, Any] | None, *, lane: str) -> dict[str, Any]:
    """Create one plan per supported platform, with every decision review-only."""
    rows = list((bundle or {}).get("items") or []) if isinstance(bundle, dict) else []
    observations: dict[str, list[dict[str, Any]]] = {platform: [] for platform in PLATFORMS}
    for raw in rows:
        observation = _as_public_observation(raw)
        if observation and observation["origin_platform"] in observations:
            observations[observation["origin_platform"]].append(observation)
    plans = {
        platform: build_work_plan(platform=platform, lane=lane, public_observations=observations[platform], owned_rows=[])
        for platform in PLATFORMS
    }
    return {
        "version": "dual_lane_work_plans_snapshot_v1", "generated_at": _now(), "lane": lane,
        "generation_only": True,
        "permissions": {"allow_viral_claims": False, "allow_automated_learning": False},
        "plans": plans,
    }
