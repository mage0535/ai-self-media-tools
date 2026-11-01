"""Automatic video workflow selection for channel-specific media jobs."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from .content_policy import SHORT_VIDEO_PLATFORMS
from .content_recipe import build_tool_invocation_manifest
from .run_contract import validate_audio_plan
from .tool_selection import build_tool_selection_evidence
from .video_recipe import build_visual_recipe


VIDEO_FORMS = {"short_video", "knowledge_card_video", "edited_short_video", "microcase_video", "article_explainer_video"}
MIXED_VIDEO_FORMS = {"image_text_knowledge_card_short_video_mix"}
VIDEO_ASSETS = {"short_video", "source_video", "human_voiceover", "background_music", "knowledge_cards"}


def _generation_contract_fields(
    strategy: dict[str, Any], brief: dict[str, Any], platforms: list[str], content_form: str,
    *, require_bgm: bool,
) -> dict[str, Any]:
    """Bridge existing planning evidence into the trusted generation schema."""
    def value(name: str, default: Any) -> Any:
        strategy_value = strategy.get(name)
        brief_value = brief.get(name)
        if strategy_value not in (None, "", [], {}):
            return strategy_value
        if brief_value not in (None, "", [], {}):
            return brief_value
        if strategy_value is not None:
            return strategy_value
        if brief_value is not None:
            return brief_value
        return default

    lane = str(
        value("lane", "")
        or brief.get("primary_track")
        or brief.get("content_line")
        or brief.get("video_line")
        or "general_video"
    ).strip()
    content_type = str(value("content_type", "") or "workflow").strip()
    evidence_shapes = value("evidence_shapes", []) or ["document", "annotations"]
    viewer_job = str(value("viewer_job", "") or "follow a workflow").strip()
    samples = value("hot_viral_samples", [])
    statuses = value("hot_viral_source_statuses", {})
    canonical_output_name = str(value("canonical_output_name", "final.mp4"))
    supplied_audio_plan = value("audio_plan", None)
    # Bound stage payloads carry an unresolved plan as {}; treat it like an absent plan.
    audio_plan = deepcopy(supplied_audio_plan) if isinstance(supplied_audio_plan, dict) and supplied_audio_plan else None
    if audio_plan is None:
        audio_plan = {
            "status": "resolution_required",
            "route": "resolution_required",
            "route_reason": "planner must resolve real audio rights and fingerprint before generation",
            "source_audio_action": "pending_resolution",
            "fallback_route": None,
        }
    else:
        audio_validation = validate_audio_plan(audio_plan, require_bgm=require_bgm)
        if not audio_validation["passed"]:
            raise ValueError("invalid audio_plan: " + ", ".join(audio_validation["failures"]))
    identity_basis = {
        "platforms": platforms,
        "topic": str(brief.get("topic") or brief.get("title") or ""),
        "lane": lane,
        "content_form": content_form,
        "content_type": content_type,
        "evidence_shapes": evidence_shapes,
        "viewer_job": viewer_job,
        "hot_viral_samples": samples if isinstance(samples, list) else [],
        "hot_viral_source_statuses": statuses if isinstance(statuses, dict) else {},
        "canonical_output_name": canonical_output_name,
        "audio_plan": audio_plan,
        **({"content_mode": "original_knowledge", "original_knowledge_ref": deepcopy(brief["original_knowledge_ref"])}
           if brief.get("content_mode") == "original_knowledge" and brief.get("original_knowledge_ref") else {}),
    }
    identity_digest = hashlib.sha256(
        json.dumps(
            identity_basis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    platform = platforms[0] if platforms else "video"
    return {
        "run_id": str(value("run_id", "") or f"video-{platform}-{identity_digest[:16]}"),
        "run_id_basis_sha256": identity_digest,
        "revision": int(value("revision", 1)),
        "attempt_id": str(value("attempt_id", "attempt-1")),
        "lane": lane,
        **{key: str(value(key, "")) for key in ("account_key", "content_line") if value(key, "")},
        "content_type": content_type,
        "evidence_shapes": deepcopy(evidence_shapes),
        "viewer_job": viewer_job,
        "hot_viral_samples": deepcopy(samples) if isinstance(samples, list) else [],
        "hot_viral_source_statuses": deepcopy(statuses) if isinstance(statuses, dict) else {},
        "canonical_output_name": canonical_output_name,
        "audio_plan": audio_plan,
        **({"content_mode": "original_knowledge", "original_knowledge_ref": deepcopy(brief["original_knowledge_ref"])}
           if brief.get("content_mode") == "original_knowledge" and brief.get("original_knowledge_ref") else {}),
    }


def _build_scene_contract(platform: str, brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Create executable, platform-aware visual decisions before rendering."""
    platform = str(platform or "video").casefold()
    if platform == "douyin_pet":
        return _build_pet_scene_contract(brief)
    if platform in {"bilibili", "youtube", "youtube_long"}:
        modes = ["terminal_evidence", "before_after_split", "prompt_typewriter", "annotation_callout", "error_fix_compare", "timeline_reveal", "checklist_stamp", "result_hold"]
    elif platform in {"douyin", "douyin_ai", "kuaishou", "shipinhao", "tiktok", "youtube_shorts"}:
        modes = ["before_after_split", "prompt_typewriter", "annotation_callout", "location_selector", "light_split_compare", "composition_push_in", "error_fix_compare", "checklist_stamp"]
    else:
        modes = ["result_reveal", "before_after_split", "prompt_typewriter", "annotation_callout", "timeline_reveal", "error_fix_compare", "checklist_stamp", "result_hold"]
    jobs = ["结果对比", "字段拆解", "主体关系", "场景选择", "参数影响", "构图解释", "错误修正", "总结行动"]
    motions = ["wipe_reveal", "type_in", "callout_draw", "focus_shift", "split_reveal", "frame_draw", "fix_reveal", "stamp_lock"]
    topic = str(brief.get("topic") or brief.get("title") or "当前任务")
    return [{
        "beat_id": f"s{i:02d}",
        "content_job": jobs[i - 1],
        "visual_hook": f"{jobs[i - 1]}：画面先揭示一个新变化",
        "visual_mode": modes[i - 1],
        "template_id": f"{modes[i - 1]}_v1",
        "evidence_asset": f"pending:evidence_asset:{platform}:s{i:02d}",
        "group_motion": [motions[i - 1]],
        "platform_reason": f"{platform}平台适配：{jobs[i - 1]}服务于{topic}",
        "reading_hold_seconds": 2.0 if i < 8 else 3.0,
    } for i in range(1, 9)]


PET_SCENE_MODES = ("pet_hook", "pet_moment", "pet_behavior", "pet_cause",
                   "pet_care_step", "pet_home_setup", "pet_watch_signal", "pet_save_cta")


def _build_pet_scene_contract(brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Pet beats illustrate the narration itself; never reuse AI-tutorial screen layouts."""
    jobs = ["开场提问", "真实瞬间", "行为表现", "背后原因", "照护做法", "家居布置", "观察信号", "收藏行动"]
    motions = ["push_in", "focus_shift", "callout_draw", "split_reveal", "check_each", "frame_draw", "local_highlight", "stamp_lock"]
    topic = str(brief.get("topic") or brief.get("title") or "当前宠物话题")
    return [{
        "beat_id": f"s{i:02d}",
        "content_job": jobs[i - 1],
        "visual_hook": f"{jobs[i - 1]}：画面呈现这句旁白里的宠物",
        "visual_mode": PET_SCENE_MODES[i - 1],
        "template_id": f"{PET_SCENE_MODES[i - 1]}_v1",
        "evidence_asset": f"pending:evidence_asset:douyin_pet:s{i:02d}",
        "group_motion": [motions[i - 1]],
        "platform_reason": f"douyin_pet平台适配：{jobs[i - 1]}服务于{topic}",
        "reading_hold_seconds": 2.0 if i < 8 else 3.0,
    } for i in range(1, 9)]


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
    generation_fields = _generation_contract_fields(
        strategy,
        brief,
        platforms,
        content_form,
        require_bgm=selected_pipeline != "localized_repost_video",
    )
    audio_plan = generation_fields["audio_plan"]
    required_tools = _required_tools(selected_pipeline, content_form, asset_plan, audio_plan)
    embedded_bgm = audio_plan["route"] == "embedded_licensed_bgm"
    renderer_steps = [
        "cinema_storyboard", "shotcraft_motion_plan", "scene_manifest", "build_cards",
        "render_cards", "gen_tts", "render_segments", "concat_video",
    ]
    if embedded_bgm:
        renderer_steps.append("download_bgm")
        renderer_steps.append("mix_audio")
    elif audio_plan["route"] == "resolution_required":
        renderer_steps.append("resolve_audio_plan")
    renderer_steps.extend(["gen_subtitles", "encode_final", "generate_packet", "visual_gate_cinema"])
    effect_stack = [
        "template_theme", "cinema_color_css", "cinema_composition_layout",
        "shotcraft_motion_css", "motion_card_layouts", "lower_third_subtitles",
    ]
    if embedded_bgm:
        effect_stack.append("licensed_bgm_mix")
    effect_stack.extend(["audio_loudness_gate", "post_render_anti_template_gate"])
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
            "online_real_instrument_bgm_resolver": "script:scripts/kuaishou_render.py::download_bgm",
            "platform_native_track_applicator": "platform_publish:native_track",
            "effect_template_renderer": "hermes_tool:short_video_renderer",
            "visual_gate": "script:scripts/visual_gate.py --cinema",
        },
        "renderer_steps": renderer_steps,
        "effect_stack": effect_stack,
        "render_requirements": {
            "duration_seconds": [40, 100],
            "min_distinct_scenes": 8,
            "min_unique_source_assets": 4,
            "subtitle_position": "lower_third",
            "voiceover_required": True,
            "background_music_required": audio_plan["route"] == "embedded_licensed_bgm",
            "scene_change_interval_seconds": [2, 4],
        },
        "quality_gates": [
            "source_asset_match",
            "scene_to_script_mapping",
            "audible_voiceover",
            "lower_third_subtitles",
            "audio_route_consistency",
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
    if embedded_bgm:
        plan["quality_gates"].append("licensed_background_music")
    plan.update(generation_fields)
    if brief.get('user_visual_materials_source') is not None:
        from .native_visual_inputs import read_user_visual_materials_inputs
        read_user_visual_materials_inputs(brief['user_visual_materials_source'])
        plan['user_visual_materials_source']=deepcopy(brief['user_visual_materials_source'])
    plan["visual_contract"] = _build_scene_contract(platforms[0] if platforms else "video", brief)
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
    if "repost" in line or "source_video" in asset_plan:
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
    if "douyin_pet" in platforms or "cat" in lane or "pet" in lane:
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


def _required_tools(
    selected_pipeline: str,
    content_form: str,
    asset_plan: set[str],
    audio_plan: dict[str, Any],
) -> list[str]:
    tools = [
        "knowledge_card_designer",
        "cinema_composition_designer",
        "shotcraft_motion_designer",
        "voiceover",
        "lower_third_subtitles",
        "effect_template_renderer",
        "card_renderer",
        "tts_renderer",
        "segment_renderer",
        "concat_renderer",
        "subtitle_burner",
        "final_encoder",
        "post_render_visual_gate",
    ]
    if audio_plan.get("route") == "embedded_licensed_bgm":
        tools.insert(5, "online_real_instrument_bgm_resolver")
        tools.insert(6, "audio_mixer")
    elif audio_plan.get("route") == "resolution_required":
        tools.insert(5, "audio_plan_resolver")
        tools.insert(6, "audio_mixer")
    elif audio_plan.get("route") == "platform_native_track":
        tools.insert(5, "platform_native_track_applicator")
    if selected_pipeline == "localized_repost_video" or "source_video" in asset_plan:
        tools.insert(0, "source_video_discovery")
        tools.insert(1, "source_asset_matcher")
    if selected_pipeline == "article_explainer_video":
        tools.insert(0, "article_explainer_planner")
    if content_form == "image_text_knowledge_card_short_video_mix":
        tools.append("manual_handoff_package_builder")
    return tools
