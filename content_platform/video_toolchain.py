"""Automatic video workflow selection for channel-specific media jobs."""

from __future__ import annotations

from typing import Any

from .content_policy import SHORT_VIDEO_PLATFORMS
from .content_recipe import build_tool_invocation_manifest
from .tool_selection import build_tool_selection_evidence
from .video_recipe import build_visual_recipe
from .video_director import build_video_route


VIDEO_FORMS = {"short_video", "knowledge_card_video", "edited_short_video", "microcase_video", "article_explainer_video"}
MIXED_VIDEO_FORMS = {"image_text_knowledge_card_short_video_mix"}
VIDEO_ASSETS = {"short_video", "source_video", "human_voiceover", "background_music", "knowledge_cards"}
VIDEO_FORM_OPTIONS = (
    "real_footage_story", "screen_demo", "split_comparison", "data_story",
    "layered_checklist", "cinematic_explainer", "knowledge_card",
)


def build_video_toolchain_plan(strategy: dict[str, Any] | None, brief: dict[str, Any] | None = None) -> dict[str, Any]:
    """Select the video pipeline, template family, and required tools from strategy evidence.

    The plan is intentionally declarative. Renderers and uploaders consume it
    through ``VIDEO_TOOLCHAIN_PLAN_PATH`` instead of relying on an agent to
    remember which video tools to call.
    """
    strategy = strategy or {}
    brief = brief or {}
    platforms = [str(item).casefold() for item in strategy.get("primary_platforms") or brief.get("platforms") or []]
    content_form = str(strategy.get("content_form") or "").casefold()
    asset_plan = {str(item).casefold() for item in strategy.get("asset_plan") or []}
    needs_video = content_form in VIDEO_FORMS or content_form in MIXED_VIDEO_FORMS or bool(asset_plan & VIDEO_ASSETS)
    if not needs_video and not any(platform in SHORT_VIDEO_PLATFORMS for platform in platforms):
        return {
            "required": False,
            "reason": "content strategy does not require a video component",
            "content_form": content_form,
            "platforms": platforms,
        }

    legacy_pipeline = _select_pipeline(platforms, content_form, asset_plan, brief)
    legacy_template_family = _select_template_family(platforms, content_form, brief)
    available_assets = brief.get("available_video_assets") if isinstance(brief.get("available_video_assets"), dict) else {}
    if "agnes_video_available" not in available_assets:
        from .agnes_provider import probe_agnes

        available_assets = {**available_assets, "agnes_video_available": probe_agnes()["video_auto_enabled"]}
    viral_pattern_evidence = _viral_pattern_evidence(brief, platforms[0] if platforms else "")
    route_body = " ".join(
        [str(brief.get("body") or brief.get("summary") or ""), *viral_pattern_evidence["recommended_patterns"], *viral_pattern_evidence["generation_requirements"]]
    )
    route = build_video_route(
        platform=platforms[0] if platforms else "",
        title=str(brief.get("topic") or brief.get("title") or ""),
        body=route_body,
        content_form=content_form,
        available_assets=available_assets,
        recent_style_ids=list(brief.get("recent_video_style_ids") or []),
    )
    selected_form = str(route.get("presentation_mode") or route.get("renderer_id") or "cinematic_explainer")
    rejected_forms = [form for form in VIDEO_FORM_OPTIONS if form != selected_form]
    # Preserve the public pipeline contract. The renderer is selected once in
    # video_route and must not rewrite selected_pipeline downstream.
    selected_pipeline = legacy_pipeline
    template_family = legacy_template_family
    required_tools = _required_tools(selected_pipeline, content_form, asset_plan)
    plan = {
        "required": True,
        "content_form": content_form,
        "platforms": platforms,
        "selected_pipeline": selected_pipeline,
        "template_family": template_family,
        "selected_form": selected_form,
        "rejected_forms": rejected_forms,
        "form_selection_reason": _form_selection_reason(route, viral_pattern_evidence),
        "viral_pattern_evidence": viral_pattern_evidence,
        "video_route": route,
        "legacy_pipeline_hint": legacy_pipeline,
        "recent_cover_direction_ids": list(brief.get("recent_cover_direction_ids") or []),
        "required_tools": required_tools,
        "tool_refs": {
            "source_video_discovery": "hermes_tool:same_lane_hot_video_analysis",
            "repost_pipeline": "hermes_tool:cross_pipeline_v5",
            "knowledge_card_designer": "hermes_skill:content/knowledge-card-designer",
            "cinema_composition_designer": "script:scripts/cinema_composition.py",
            "shotcraft_motion_designer": "script:scripts/shotcraft_moves.py",
            "scene_manifest": "module:content_platform.scene_manifest",
            "video_toolchain_runner": "script:scripts/video_toolchain_runner.py",
            "kuaishou_render": "script:scripts/kuaishou_render.py",
            "card_renderer": "script:scripts/kuaishou_render.py::render_cards",
            "voiceover": "hermes_tool:voice_engine",
            "tts_renderer": "script:scripts/kuaishou_render.py::gen_tts",
            "segment_renderer": "script:scripts/kuaishou_render.py::render_segments",
            "concat_renderer": "script:scripts/kuaishou_render.py::concat_video",
            "audio_mixer": "script:scripts/mix_bgm_with_gate.py",
            "subtitle_renderer": "hermes_tool:lower_third_subtitle_renderer",
            "subtitle_burner": "script:scripts/kuaishou_render.py::encode_final",
            "final_encoder": "script:scripts/kuaishou_render.py::encode_final",
            "background_music": "script:scripts/kuaishou_render.py::download_bgm",
            "effect_template_renderer": "hermes_tool:short_video_renderer",
            "visual_gate": "script:scripts/visual_gate.py --cinema",
        },
        "renderer_steps": [
            "cinema_storyboard",
            "shotcraft_motion_plan",
            "scene_manifest",
            "build_cards",
            "render_cards",
            "gen_tts",
            "render_segments",
            "concat_video",
            "download_bgm",
            "mix_audio",
            "gen_subtitles",
            "encode_final",
            "generate_packet",
            "visual_gate_cinema",
        ],
        "effect_stack": list(route["modules"]) + ["audio_loudness_gate", "post_render_anti_template_gate"],
        "render_requirements": {
            "duration_seconds": [40, 100],
            "min_distinct_scenes": 8,
            "min_unique_source_assets": 4,
            "subtitle_position": "lower_third",
            "voiceover_required": True,
            "background_music_required": True,
            "scene_change_interval_seconds": [2, 4],
        },
        "quality_gates": [
            "source_asset_match",
            "scene_to_script_mapping",
            "audible_voiceover",
            "lower_third_subtitles",
            "licensed_background_music",
            "template_family_recorded",
            "visual_recipe_recorded",
            "visual_recipe_fingerprint_recorded",
            "scene_manifest",
            "scene_manifest_duration_policy",
            "no_static_single_template_loop",
            "cinema_storyboard_recorded",
            "shotcraft_motion_plan_recorded",
            "tool_invocation_manifest_recorded",
            "post_render_cinema_visual_gate",
            "audio_mix_probe_recorded",
            "renderer_steps_recorded",
            "form_selection_recorded",
            "non_uniform_visual_forms",
        ],
    }
    plan["visual_recipe"] = build_visual_recipe(plan, title=str(brief.get("topic") or brief.get("title") or ""))
    planned_tools = {name: plan["tool_refs"].get(name, "video_toolchain_internal") for name in required_tools}
    tool_manifest = build_tool_invocation_manifest(
        planned_tools=planned_tools,
        invocations={name: {"status": "planned_internal", "output": ref} for name, ref in planned_tools.items()},
    )
    plan["tool_invocation_manifest"] = tool_manifest
    plan.update(build_tool_selection_evidence(
        platform=platforms[0] if platforms else "video",
        content_type=content_form or "short_video",
        content_goal="increase retention with matched source assets, motion effects, voice, subtitles, and BGM",
        planned_manifest=tool_manifest,
    ))
    return plan


def _viral_pattern_evidence(brief: dict[str, Any], platform: str) -> dict[str, Any]:
    """Extract only audited viral mechanisms; never copy a source answer/title."""
    pack = brief.get("hot_work_parameter_pack") if isinstance(brief.get("hot_work_parameter_pack"), dict) else {}
    platform_pack = (pack.get("platforms") or {}).get(platform) if isinstance(pack.get("platforms"), dict) else {}
    same_lane = brief.get("same_lane_intelligence") if isinstance(brief.get("same_lane_intelligence"), dict) else {}
    patterns = list(platform_pack.get("recommended_patterns") or []) if isinstance(platform_pack, dict) else []
    requirements = list(platform_pack.get("generation_requirements") or []) if isinstance(platform_pack, dict) else []
    patterns.extend(str(item) for item in (same_lane.get("visual_patterns") or []) if str(item))
    return {
        "source": "same_platform_same_lane_parameter_pack" if platform_pack else "no_verified_viral_pack",
        "ready": bool(platform_pack.get("ready")) if isinstance(platform_pack, dict) else False,
        "recommended_patterns": list(dict.fromkeys(str(item) for item in patterns if str(item)))[:8],
        "generation_requirements": list(dict.fromkeys(str(item) for item in requirements if str(item)))[:8],
    }


def _form_selection_reason(route: dict[str, Any], evidence: dict[str, Any]) -> str:
    base = str(route.get("selection_reason") or "content and platform signals selected the visual form")
    patterns = evidence.get("recommended_patterns") or []
    return f"{base}; viral mechanisms referenced without copying source content: {', '.join(patterns[:4]) or 'none'}"


def _select_pipeline(platforms: list[str], content_form: str, asset_plan: set[str], brief: dict[str, Any]) -> str:
    line = str(brief.get("content_line") or brief.get("video_line") or "").casefold()
    if "repost" in line or "source_video" in asset_plan or "douyin" in platforms or "tiktok" in platforms:
        return "localized_repost_video"
    if content_form == "article_explainer_video":
        return "article_explainer_video"
    if "bilibili" in platforms or "youtube" in platforms:
        return "tutorial_video"
    if content_form == "image_text_knowledge_card_short_video_mix":
        return "mixed_note_short_video"
    return "knowledge_card_video"


def _select_template_family(platforms: list[str], content_form: str, brief: dict[str, Any]) -> str:
    lane = " ".join(str(brief.get(key, "")) for key in ("primary_track", "sub_track", "audience", "topic"))
    lane = lane.casefold()
    if "cat" in lane or "pet" in lane or "douyin" in platforms:
        return "pet_repost_real_behavior"
    if "shipinhao" in platforms:
        return "wechat_ecosystem_microcase"
    if content_form == "article_explainer_video":
        return "chaptered_explainer"
    if "bilibili" in platforms or "youtube" in platforms:
        return "chaptered_tutorial"
    if content_form == "image_text_knowledge_card_short_video_mix":
        return "social_note_motion_cards"
    return "knowledge_card_motion_case"


def _required_tools(selected_pipeline: str, content_form: str, asset_plan: set[str]) -> list[str]:
    tools = [
        "knowledge_card_designer",
        "cinema_composition_designer",
        "shotcraft_motion_designer",
        "voiceover",
        "lower_third_subtitles",
            "online_real_instrument_bgm_resolver",
        "effect_template_renderer",
        "card_renderer",
        "tts_renderer",
        "segment_renderer",
        "concat_renderer",
        "audio_mixer",
        "subtitle_burner",
        "final_encoder",
        "post_render_visual_gate",
    ]
    if selected_pipeline == "localized_repost_video" or "source_video" in asset_plan:
        tools.insert(0, "source_video_discovery")
        tools.insert(1, "source_asset_matcher")
    if selected_pipeline == "article_explainer_video":
        tools.insert(0, "article_explainer_planner")
    if content_form == "image_text_knowledge_card_short_video_mix":
        tools.append("manual_handoff_package_builder")
    return tools
