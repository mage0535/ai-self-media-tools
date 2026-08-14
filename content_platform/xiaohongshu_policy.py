"""Executable recovery contract for Xiaohongshu manual handoff packages."""

from __future__ import annotations


STRATEGY_ID = "xiaohongshu_recovery_v1"
CONTENT_PILLAR = "ai_efficiency_workflow_system"
MIN_PUBLISH_INTERVAL_HOURS = 36
POST_PUBLISH_REVIEW_HOURS = [1, 24, 72]


def build_recovery_strategy(job: dict, formatted: dict) -> dict:
    """Attach the evidence an operator needs before a manual publication."""
    meta = job.get("draft_meta") if isinstance(job.get("draft_meta"), dict) else {}
    depth = meta.get("content_depth_plan") if isinstance(meta.get("content_depth_plan"), dict) else {}
    strategy = meta.get("strategy_brief") if isinstance(meta.get("strategy_brief"), dict) else {}
    title = str(formatted.get("title") or job.get("title") or "").strip()
    first_image_promise = str(meta.get("first_image_promise") or strategy.get("reader_payoff") or title).strip()
    save_value = str(depth.get("takeaway") or meta.get("reader_payoff") or strategy.get("reader_payoff") or "").strip()
    return {
        "strategy_id": STRATEGY_ID,
        "content_pillar": str(meta.get("xhs_content_pillar") or CONTENT_PILLAR),
        "first_image_promise": first_image_promise,
        "save_value": save_value,
        "min_publish_interval_hours": MIN_PUBLISH_INTERVAL_HOURS,
        "post_publish_review_hours": POST_PUBLISH_REVIEW_HOURS,
        "publish_boundary": "manual_handoff_only",
    }


def validate_recovery_strategy(strategy: object) -> list[str]:
    """Return stable failure codes for the fail-closed handoff gate."""
    if not isinstance(strategy, dict):
        return ["growth_strategy_missing"]
    failures = []
    if strategy.get("strategy_id") != STRATEGY_ID:
        failures.append("growth_strategy_id_invalid")
    if strategy.get("content_pillar") != CONTENT_PILLAR:
        failures.append("growth_strategy_content_pillar_invalid")
    if not str(strategy.get("first_image_promise") or "").strip():
        failures.append("growth_strategy_first_image_promise_missing")
    if not str(strategy.get("save_value") or "").strip():
        failures.append("growth_strategy_save_value_missing")
    if strategy.get("min_publish_interval_hours") != MIN_PUBLISH_INTERVAL_HOURS:
        failures.append("growth_strategy_publish_interval_invalid")
    if strategy.get("post_publish_review_hours") != POST_PUBLISH_REVIEW_HOURS:
        failures.append("growth_strategy_review_schedule_invalid")
    if strategy.get("publish_boundary") != "manual_handoff_only":
        failures.append("growth_strategy_publish_boundary_invalid")
    return failures
