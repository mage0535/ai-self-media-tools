"""Build generation-time capability context before any model call."""

from __future__ import annotations

from .capability_router import build_capability_plan
from .content_profile import classify_content_profile
from .tool_selection import build_tool_selection_evidence


def build_generation_capability_context(platform: str, content_blueprint: dict) -> dict:
    topic = str(content_blueprint.get("topic") or content_blueprint.get("title") or "")
    profile = classify_content_profile(
        topic,
        platform=platform,
        content_format=str(content_blueprint.get("content_form") or ""),
    )
    full_plan = build_capability_plan(profile)
    plan = {
        "version": full_plan["version"],
        "profile": full_plan["profile"],
        "tool_group_count": len(full_plan.get("tool_groups", {})),
        "tool_group_names": sorted(full_plan.get("tool_groups", {})),
        "consulted": full_plan.get("consulted", []),
        "candidates": full_plan.get("candidates", []),
        "executed": full_plan.get("executed", []),
        "skipped": full_plan.get("skipped", []),
    }
    full_tool_selection = build_tool_selection_evidence(
        platform=platform,
        content_type=str(content_blueprint.get("content_form") or profile["content_format"]),
        content_goal="select the executable tool stack for this generation stage",
    )
    tool_selection = {
        "version": "tool_selection_compact_v1",
        "tools_capability_analysis": {
            "version": full_tool_selection["tools_capability_analysis"].get("version"),
            "required_tool_groups": full_tool_selection["tools_capability_analysis"].get("required_tool_groups", []),
            "candidate_tool_count": full_tool_selection["tools_capability_analysis"].get("candidate_tool_count", 0),
        },
        "tool_selection_plan": {
            "version": full_tool_selection["tool_selection_plan"].get("version"),
            "selected_tools": full_tool_selection["tool_selection_plan"].get("selected_tools", []),
            "selection_reasons": full_tool_selection["tool_selection_plan"].get("selection_reasons", {}),
            "invocation_order": full_tool_selection["tool_selection_plan"].get("invocation_order", []),
            "not_default_only": full_tool_selection["tool_selection_plan"].get("not_default_only", False),
        },
    }
    return {
        "profile": profile,
        "capability_plan": plan,
        "tool_selection": tool_selection,
        "ready_for_generation": not bool(plan.get("skipped")),
    }
