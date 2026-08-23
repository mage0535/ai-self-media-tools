"""Build generation-time capability context before any model call."""

from __future__ import annotations

from .capability_router import build_capability_plan
from .content_profile import classify_content_profile


def build_generation_capability_context(platform: str, content_blueprint: dict) -> dict:
    topic = str(content_blueprint.get("topic") or content_blueprint.get("title") or "")
    profile = classify_content_profile(
        topic,
        platform=platform,
        content_format=str(content_blueprint.get("content_form") or ""),
    )
    plan = build_capability_plan(profile)
    return {
        "profile": profile,
        "capability_plan": plan,
        "ready_for_generation": not bool(plan.get("skipped")),
    }
