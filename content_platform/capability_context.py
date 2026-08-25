"""Build generation-time capability context before any model call."""

from __future__ import annotations

from pathlib import Path

from .capability_router import build_capability_plan
from .content_profile import classify_content_profile
from .tool_selection import build_tool_selection_evidence
from .skill_rule_compiler import compile_skill_rules, default_skill_paths, select_platform_rules
from .content_assets import load_compiled_assets, select_content_asset_ids


def build_generation_capability_context(platform: str, content_blueprint: dict) -> dict:
    topic = str(content_blueprint.get("topic") or content_blueprint.get("title") or "")
    profile = classify_content_profile(
        topic,
        platform=platform,
        content_format=str(content_blueprint.get("content_form") or ""),
    )
    full_plan = build_capability_plan(profile)
    project_root = Path(__file__).resolve().parents[1]
    compiled_skill_rules = compile_skill_rules(default_skill_paths(platform, root=project_root), root=project_root, platform=platform)
    # Keep full provenance local while fitting bounded provider input.
    compiled_skill_rules["sources"] = [
        {"id": source["id"], "sha256": source["sha256"]}
        for source in compiled_skill_rules.get("sources", [])
    ]
    compiled_skill_rules["rules"] = [
        {"id": rule["id"], "source": rule["source"], "section": rule["section"], "text": str(rule.get("text") or "")[:160]}
        for rule in select_platform_rules(compiled_skill_rules.get("rules", []), platform)[:32]
    ]
    assets = load_compiled_assets(project_root / "config" / "content_assets")
    selected_assets = select_content_asset_ids(profile, assets)
    compiled_skill_rules["content_assets"] = {
        "selected": selected_assets,
    }
    consulted = list(full_plan.get("consulted", []))
    consultation = compiled_skill_rules.get("consultation") or {}
    for item in consulted:
        if item.get("capability_id") == "skill_reference_compiler":
            item.update({
                "rules_applied": (consultation.get("output") or {}).get("rules_applied", []),
                "source_hashes": (consultation.get("output") or {}).get("source_hashes", {}),
                "affected_outputs": (consultation.get("output") or {}).get("affected_outputs", []),
                "consultation_status": consultation.get("status", "consulted"),
                "output_hash": consultation.get("output_hash", ""),
            })
    plan = {
        "version": full_plan["version"],
        "profile": full_plan["profile"],
        "tool_group_count": len(full_plan.get("tool_groups", {})),
        "tool_group_names": sorted(full_plan.get("tool_groups", {})),
        "consulted": consulted,
        "candidates": full_plan.get("candidates", []),
        "executed": full_plan.get("executed", []),
        "skipped": full_plan.get("skipped", []),
        "inventory_count": len(full_plan.get("inventory", [])),
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
            "analyzed_tool_groups": full_tool_selection["tools_capability_analysis"].get("analyzed_tool_groups", {}),
            "all_relevant_tool_types_analyzed": full_tool_selection["tools_capability_analysis"].get("all_relevant_tool_types_analyzed", False),
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
        "compiled_skill_rules": compiled_skill_rules,
        "selected_capability": list(full_plan.get("executed", [])),
        "ready_for_generation": not bool(plan.get("skipped")),
    }
