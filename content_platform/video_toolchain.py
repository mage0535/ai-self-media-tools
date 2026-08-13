"""Automatic video workflow selection for channel-specific media jobs."""

from __future__ import annotations

from typing import Any

from .content_recipe import build_tool_invocation_manifest
from .tool_selection import build_tool_selection_evidence
from .video_recipe import build_visual_recipe


VIDEO_FORMS = {"short_video", "knowledge_card_video", "edited_short_video", "microcase_video", "article_explainer_video"}
MIXED_VIDEO_FORMS = {"image_text_knowledge_card_short_video_mix"}
VIDEO_ASSETS = {"short_video", "source_video", "human_voiceover", "background_music", "knowledge_cards"}
SHORT_VIDEO_PLATFORMS = {"douyin", "kuaishou", "shipinhao", "bilibili", "tiktok", "youtube"}


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

    selected_pipeline = _select_pipeline(platforms, content_form, asset_plan, brief)
    template_family = _select_template_family(platforms, content_form, brief)
    required_tools = _required_tools(selected_pipeline, content_form, asset_plan)
    plan = {
        "required": True,
        "content_form": content_form,
        "platforms": platforms,
        "selected_pipeline": selected_pipeline,
        "template_family": template_family,
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
        "effect_stack": [
            "template_theme",
            "cinema_color_css",
            "cinema_composition_layout",
            "shotcraft_motion_css",
            "motion_card_layouts",
            "lower_third_subtitles",
            "licensed_bgm_mix",
            "audio_loudness_gate",
            "post_render_anti_template_gate",
        ],
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
