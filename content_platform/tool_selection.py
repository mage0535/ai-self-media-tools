"""Tool capability analysis and selection contracts.

The goal is not to call every tool. It is to prove every relevant tool family
was considered, then record why the chosen combination fits the platform,
topic, assets, and quality gates.
"""

from __future__ import annotations

from typing import Any


ARTICLE_TOOL_GROUPS = {
    "ops_strategy",
    "trend_collection",
    "account_data",
    "topic_dedup",
    "article_recipe",
    "knowledge_card",
    "image_generation",
    "image_retrieval",
    "image_editing",
    "seo_geo",
    "quality_gate",
    "publisher_or_handoff",
}

VIDEO_TOOL_GROUPS = {
    "ops_strategy",
    "trend_collection",
    "account_data",
    "topic_dedup",
    "visual_recipe",
    "source_material",
    "image_generation",
    "video_template",
    "motion_effects",
    "transitions",
    "tts",
    "subtitles",
    "bgm",
    "audio_mix",
    "quality_gate",
    "publisher_or_handoff",
}


def build_tools_capability_analysis(
    *,
    platform: str,
    content_type: str,
    capability_status: dict[str, Any] | None = None,
    video_effect_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact inventory that Hermes can attach before generation."""

    is_video = _is_video(content_type)
    required_groups = VIDEO_TOOL_GROUPS if is_video else ARTICLE_TOOL_GROUPS
    capability_status = capability_status or {}
    video_effect_registry = video_effect_registry or {}
    tools = capability_status.get("tools") if isinstance(capability_status.get("tools"), dict) else {}
    modules = video_effect_registry.get("modules") if isinstance(video_effect_registry.get("modules"), dict) else {}
    families = video_effect_registry.get("template_families") if isinstance(video_effect_registry.get("template_families"), dict) else {}

    analyzed_groups = {group: _default_candidates(group, is_video) for group in sorted(required_groups)}
    if tools:
        analyzed_groups["runtime_probe"] = sorted(tools)
    if modules:
        analyzed_groups["video_effect_modules"] = sorted(modules)
    if families:
        analyzed_groups["video_template_families"] = sorted(families)

    candidate_count = sum(len(v) for v in analyzed_groups.values() if isinstance(v, list))
    return {
        "version": "tools_capability_analysis_v1",
        "platform": platform,
        "content_type": content_type,
        "required_tool_groups": sorted(required_groups),
        "analyzed_tool_groups": analyzed_groups,
        "candidate_tool_count": candidate_count,
        "selection_policy": "choose the combination that best fits platform, topic, audience, assets, quality gates, free availability, and reliability; do not use default-only paths",
        "all_relevant_tool_types_analyzed": True,
    }


def build_tool_selection_plan(
    *,
    platform: str,
    content_type: str,
    content_goal: str = "",
    capability_analysis: dict[str, Any] | None = None,
    planned_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select a minimum useful tool stack from analyzed capabilities."""

    analysis = capability_analysis or build_tools_capability_analysis(platform=platform, content_type=content_type)
    planned = (planned_manifest or {}).get("planned_tools") if isinstance((planned_manifest or {}).get("planned_tools"), dict) else {}
    selected = list(planned) if planned else _fallback_selected_tools(_is_video(content_type))
    required_groups = analysis.get("required_tool_groups") or []
    return {
        "version": "tool_selection_plan_v1",
        "platform": platform,
        "content_type": content_type,
        "content_goal": content_goal or "improve retention, saves, interaction, and follow conversion",
        "candidate_group_count": len(required_groups),
        "selected_tools": selected,
        "selection_reasons": {
            name: "selected because it contributes directly to the current platform format, asset fit, or quality gate"
            for name in selected
        },
        "unselected_tools": [
            {
                "tool_group": group,
                "reason": "not selected for this work because another tool in the group better matches the topic, platform, asset availability, or free/reliable execution",
            }
            for group in required_groups
            if not _group_represented(group, selected)
        ],
        "invocation_order": selected,
        "fallback_plan": "if a selected tool fails, record the failure in tool_invocation_manifest, choose the nearest approved substitute, then rerun quality gates",
        "not_default_only": True,
    }


def build_tool_selection_evidence(
    *,
    platform: str,
    content_type: str,
    content_goal: str = "",
    capability_status: dict[str, Any] | None = None,
    video_effect_registry: dict[str, Any] | None = None,
    planned_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = build_tools_capability_analysis(
        platform=platform,
        content_type=content_type,
        capability_status=capability_status,
        video_effect_registry=video_effect_registry,
    )
    plan = build_tool_selection_plan(
        platform=platform,
        content_type=content_type,
        content_goal=content_goal,
        capability_analysis=analysis,
        planned_manifest=planned_manifest,
    )
    return {"tools_capability_analysis": analysis, "tool_selection_plan": plan}


def validate_tool_selection_evidence(
    packet: dict[str, Any] | None,
    *,
    content_kind: str = "",
) -> dict[str, Any]:
    packet = packet or {}
    content_type = str(packet.get("content_type") or packet.get("content_form") or content_kind)
    is_video = content_kind == "video" or (not content_kind and _is_video(content_type))
    required_groups = VIDEO_TOOL_GROUPS if is_video else ARTICLE_TOOL_GROUPS
    analysis = packet.get("tools_capability_analysis") if isinstance(packet.get("tools_capability_analysis"), dict) else {}
    plan = packet.get("tool_selection_plan") if isinstance(packet.get("tool_selection_plan"), dict) else {}
    manifest = packet.get("tool_invocation_manifest") if isinstance(packet.get("tool_invocation_manifest"), dict) else {}
    planned_manifest = manifest.get("planned_tools") if isinstance(manifest.get("planned_tools"), dict) else {}
    invocations = manifest.get("invocations") if isinstance(manifest.get("invocations"), dict) else {}
    failures: list[str] = []

    if not analysis:
        failures.append("tools_capability_analysis missing")
    else:
        analyzed = analysis.get("analyzed_tool_groups") if isinstance(analysis.get("analyzed_tool_groups"), dict) else {}
        covered = set(analysis.get("required_tool_groups") or []) | set(analyzed)
        missing = sorted(group for group in required_groups if group not in covered)
        if missing:
            failures.append("tools_capability_analysis missing groups:" + ",".join(missing))
        if analysis.get("all_relevant_tool_types_analyzed") is not True:
            failures.append("tools_capability_analysis must mark all relevant tool types analyzed")
        if int(analysis.get("candidate_tool_count") or 0) < len(required_groups):
            failures.append("tools_capability_analysis candidate count too low")

    if not plan:
        failures.append("tool_selection_plan missing")
        selected: list[str] = []
    else:
        selected = [str(item) for item in (plan.get("selected_tools") or []) if str(item).strip()]
        min_selected = 6 if is_video else 3
        if len(selected) < min_selected:
            failures.append(f"tool_selection_plan selected_tools must include at least {min_selected} tools")
        if not plan.get("selection_reasons"):
            failures.append("tool_selection_plan selection reasons missing")
        if not plan.get("invocation_order"):
            failures.append("tool_selection_plan invocation order missing")
        if plan.get("not_default_only") is not True:
            failures.append("tool_selection_plan must reject default-only path")

    if selected and planned_manifest:
        planned_names = set(planned_manifest)
        selected_names = set(selected)
        if not selected_names.issubset(planned_names):
            failures.append("tool_selection_plan selected tools missing from planned manifest")
        if not planned_names.issubset(set(invocations)):
            failures.append("tool_invocation_manifest missing invocation records for planned tools")
    elif selected:
        failures.append("tool_invocation_manifest planned tools missing")

    return {"passed": not failures, "failures": failures, "failed_dimensions": ["tool_selection"] if failures else []}


def _is_video(content_type: str) -> bool:
    text = str(content_type or "").casefold()
    return "video" in text or text in {"short", "reel"}


def _default_candidates(group: str, is_video: bool) -> list[str]:
    mapping = {
        "ops_strategy": ["hermes_operating_strategy", "growth_strategy_latest"],
        "trend_collection": ["platform_source_matrix", "trend_collector", "same_lane_hot_analysis"],
        "account_data": ["performance_cycle", "historical_feedback"],
        "topic_dedup": ["duplication_policy", "anti_spam_similarity_gate"],
        "article_recipe": ["content_platform.content_recipe"],
        "knowledge_card": ["knowledge-card-designer"],
        "image_generation": ["cloudflare_workers_ai", "pollinations", "image_gen_engine"],
        "image_retrieval": ["pexels", "pixabay", "unsplash"],
        "image_editing": ["knowledge_card_renderer", "cover_renderer"],
        "seo_geo": ["seo_geo_check", "ai_seo"],
        "visual_recipe": ["content_platform.video_recipe"],
        "source_material": ["same_lane_hot_video_analysis", "yt_dlp", "source_asset_matcher"],
        "video_template": ["video_toolchain_runner", "template_family_registry"],
        "motion_effects": ["shotcraft_moves", "cinema_composition"],
        "transitions": ["animated_card_pipeline", "css_motion_transitions"],
        "tts": ["voice_engine", "edge_tts", "kokoro"],
        "subtitles": ["lower_third_subtitle_renderer", "subtitle_burner"],
        "bgm": ["online_real_instrument_bgm_resolver", "bgm_fingerprint_gate"],
        "audio_mix": ["mix_bgm_with_gate", "loudness_probe"],
        "quality_gate": ["media_quality", "preflight_manifest"],
        "publisher_or_handoff": ["pipeline_publisher", "handoff_package_builder", "postcheck"],
    }
    return mapping.get(group, [group + ("_video_tool" if is_video else "_article_tool")])


def _fallback_selected_tools(is_video: bool) -> list[str]:
    if is_video:
        return [
            "video_toolchain_runner",
            "visual_recipe",
            "shotcraft_moves",
            "cinema_composition",
            "voice_engine",
            "mix_bgm_with_gate",
            "visual_gate",
        ]
    return ["generator_normalize", "preflight_manifest", "visual_policy", "knowledge_card_designer"]


def _group_represented(group: str, selected_tools: list[str]) -> bool:
    text = " ".join(selected_tools).casefold()
    tokens = {
        "ops_strategy": ["strategy"],
        "trend_collection": ["trend", "source_matrix"],
        "account_data": ["performance", "feedback"],
        "topic_dedup": ["dedup", "duplication", "similarity"],
        "quality_gate": ["gate", "quality", "preflight"],
        "publisher_or_handoff": ["publisher", "handoff", "postcheck"],
    }.get(group, [group.replace("_", "")])
    compact = text.replace("_", "")
    return any(token.replace("_", "") in compact for token in tokens)
