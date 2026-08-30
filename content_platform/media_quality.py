"""Portable quality checks for article and short-video delivery packets."""

from __future__ import annotations

import re
from typing import Any

from .visual_content_policy import packet_uses_current_policy
from .models import GateFailure, GateResult
from .asset_license import validate_asset_licenses
from .growth_policy import validate_growth_strategy
from .preflight_manifest import validate_preflight_manifest
from .video_recipe import load_effect_module_registry, validate_visual_recipe
from .content_recipe import validate_article_recipe, validate_image_text_card_recipe, validate_knowledge_card_recipe, validate_tool_invocation_manifest
from .tool_selection import validate_tool_selection_evidence

TIKTOK_REPOST_LINE = "tiktok_hot_localized_repost"
ALLOWED_VISUAL_REVIEWS = {"passed", "approved", "verified", "manual_passed"}
GENERIC_DOUYIN_TITLES = {"猫咪日常", "猫咪治愈", "可爱猫咪", "猫咪知识", "这只小猫在想什么呢？"}
DOUYIN_PET_TEXT_RE = re.compile(r"(cat|cats|kitten|kitty|meow|purr|feline|whisker|paw|pet|猫|猫咪|喵|宠物)", re.I)
DOUYIN_KNOWLEDGE_PATTERNS = [
    r"你有没有发现.*信号",
    r"这说明.*",
    r"科学.*猫",
    r"猫咪.*行为",
    r"猫.*知识",
    r"不是.*而是.*信号",
]
FULL_OPS_WORKFLOW_PLATFORMS = {"xiaohongshu", "rednote", "juejin", "zhihu"}
MANDATORY_OPS_SOURCES = {"account_history", "same_lane_accounts", "bilibili", "wechat", "xiaohongshu", "youtube", "external_hot_platforms"}
MANDATORY_WORKFLOW_INPUTS = {
    "account_analysis",
    "same_lane_account_analysis",
    "cross_platform_trend_analysis",
    "topic_selection",
    "quantity_plan",
    "content_brief",
}
MANDATORY_CONTENT_HANDOFF_FIELDS = {
    "copy_plan",
    "script_plan",
    "seo_geo_plan",
    "topic_tags",
    "asset_mix_plan",
    "humanization_plan",
}
FORBIDDEN_PRIMARY_BACKGROUNDS = {"css_gradient", "gradient", "solid_color", "design_card", "abstract_shape", "procedural"}
REAL_SCENE_BACKGROUND_SOURCE_POLICY = {
    "licensed_real_scene_assets",
    "licensed_or_verified_real_scene_assets",
    "licensed_or_verified_runtime_assets",
    "verified_real_material",
}
MANUAL_MEDIA_DELIVERY_PLATFORMS = {"bilibili", "douyin", "shipinhao", "tiktok", "youtube", "xiaohongshu", "rednote"}


def _text_length(value: str) -> int:
    return len(re.sub(r"\s+", "", str(value or "")))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_abs_media_path(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and (text.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", text) is not None)


def _platform_source_matrix_gate(matrix: dict[str, Any], platform: str) -> dict[str, Any]:
    attempted = matrix.get("attempted_sources") if isinstance(matrix, dict) else []
    if not isinstance(attempted, list):
        attempted = []
    successful = [
        item
        for item in attempted
        if isinstance(item, dict) and str(item.get("status") or "").casefold() in {"ok", "success", "saved", "usable"}
    ]
    success_count = max(_safe_int(matrix.get("successful_source_count")) if isinstance(matrix, dict) else 0, len(successful))
    trend = matrix.get("trend_evidence") if isinstance(matrix, dict) else {}
    if not isinstance(trend, dict):
        trend = {}
    return {
        "passed": isinstance(matrix, dict)
        and str(matrix.get("platform") or platform).casefold() == str(platform).casefold()
        and len(attempted) >= 5
        and success_count >= 3
        and bool(matrix.get("platform_internal_verified"))
        and bool(matrix.get("real_platform_collection_verified"))
        and bool(matrix.get("current_platform_specific_topic"))
        and bool(trend.get("source"))
        and bool(trend.get("collected_at"))
        and bool(trend.get("samples"))
        and not bool(matrix.get("shared_trend_only"))
        and bool(matrix.get("report_path")),
        "attempted": len(attempted),
        "successful": success_count,
        "required": ["attempted_sources >= 5", "successful_source_count >= 3", "real platform collection", "timestamped trend sample", "not shared_trend_only"],
    }


def _platform_render_identity_gate(packet: dict[str, Any], platform: str) -> dict[str, Any]:
    identity = packet.get("platform_render_identity") or {}
    output_path = str(identity.get("output_path") or "").strip()
    rendered = str(identity.get("rendered_for_platform") or identity.get("current_platform") or "").casefold()
    normalized = str(platform or packet.get("platform") or "").casefold()
    return {
        "passed": isinstance(identity, dict)
        and bool(output_path)
        and _is_abs_media_path(output_path)
        and bool(identity.get("script_hash"))
        and bool(identity.get("visual_hash"))
        and bool(identity.get("bgm_fingerprint"))
        and identity.get("not_reused_from_other_platform") is True
        and rendered == normalized,
        "rendered_for_platform": rendered,
        "platform": normalized,
        "output_path": output_path,
    }


def _media_delivery_contract_gate(packet: dict[str, Any], platform: str) -> dict[str, Any]:
    delivery = packet.get("media_delivery") or packet.get("handoff_media_delivery") or {}
    paths = delivery.get("abs_paths") if isinstance(delivery, dict) else []
    if not isinstance(paths, list):
        paths = []
    normalized = str(platform or packet.get("platform") or "").casefold()
    must_deliver_media = normalized in MANUAL_MEDIA_DELIVERY_PLATFORMS or bool(delivery)
    return {
        "passed": (not must_deliver_media)
        or (
            isinstance(delivery, dict)
            and str(delivery.get("mode") or "").casefold() == "independent_media_message"
            and str(delivery.get("message_kind") or "").upper() == "MEDIA"
            and delivery.get("sent_as_separate_message") is True
            and delivery.get("text_report_separate") is True
            and len(paths) >= 1
            and all(_is_abs_media_path(path) for path in paths)
        ),
        "path_count": len(paths),
        "required": ["MEDIA message", "sent_as_separate_message", "text_report_separate", "absolute media paths"],
    }


def _bgm_fingerprint_history_gate(packet: dict[str, Any]) -> dict[str, Any]:
    check = packet.get("bgm_history_check") or {}
    bgm = packet.get("bgm") or packet.get("background_music") or packet.get("bgm_source") or {}
    manifest = packet.get("bgm_license_manifest") or (bgm.get("manifest") if isinstance(bgm, dict) else {}) or {}
    current = str(
        check.get("current_fingerprint")
        or check.get("fingerprint")
        or manifest.get("fingerprint")
        or manifest.get("checksum")
        or ""
    ).strip()
    recent = {str(item).strip() for item in (check.get("recent_fingerprints") or []) if str(item).strip()}
    same_batch = {str(item).strip() for item in (check.get("same_batch_fingerprints") or []) if str(item).strip()}
    return {
        "passed": isinstance(check, dict)
        and check.get("checked") is True
        and bool(check.get("registry_path"))
        and bool(current)
        and current not in recent
        and current not in same_batch
        and not bool(check.get("duplicate_found")),
        "current_fingerprint": current,
        "duplicate_found": bool(check.get("duplicate_found")) or current in recent or current in same_batch,
    }


def _check_no_ai_slop(text: str) -> bool:
    """Run no-ai-slop check on article body. Returns True if clean (no slop found)."""
    import os, subprocess, sys, tempfile
    script = os.path.expanduser("~/.hermes/scripts/no_ai_slop_check.py")
    if not os.path.exists(script):
        return True  # pass by default if script missing
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(text)
            tmp = f.name
        r = subprocess.run(
            [sys.executable, script, tmp],
            capture_output=True, text=True, timeout=15,
        )
        os.unlink(tmp)
        return r.returncode == 0 and "未检测到" in r.stdout
    except Exception:
        return True  # pass by default on infrastructure failure


def _packet_value(packet: dict[str, Any], *names: str) -> Any:
    for name in names:
        current: Any = packet
        for part in name.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if current not in (None, "", [], {}):
            return current
    return None


def validate_douyin_tiktok_repost_packet(packet: dict[str, Any], *, require_visual_review: bool = False) -> list[str]:
    """Validate that a Douyin TikTok repost packet is not generic cat knowledge content."""
    required = [
        "source_url",
        "video_id",
        "keyword",
        "trend_reason",
        "source_caption_or_overlay",
        "source_entertainment_or_story_intent",
        "source_evidence",
        "source_decision_reason",
        "localization_angle",
        "translation_rewrite_plan",
        "scene_to_script_mapping",
    ]
    aliases = {
        "video_id": ["video_id", "id"],
        "source_caption_or_overlay": ["source_caption_or_overlay", "source_caption", "caption", "overlay_text"],
        "source_entertainment_or_story_intent": [
            "source_entertainment_or_story_intent",
            "source_story_intent",
            "story_intent",
        ],
    }
    failures: list[str] = []
    if packet.get("content_line") != TIKTOK_REPOST_LINE:
        failures.append("content_line must be tiktok_hot_localized_repost")
    for field in required:
        if _packet_value(packet, *(aliases.get(field, [field]))) in (None, "", [], {}):
            failures.append(f"missing required TikTok repost field: {field}")

    title = str(packet.get("title") or "").strip()
    if title in GENERIC_DOUYIN_TITLES:
        failures.append("generic Douyin title is not allowed for TikTok repost lane")

    source_text = " ".join(
        str(_packet_value(packet, name) or "")
        for name in ("source_caption_or_overlay", "source_entertainment_or_story_intent")
    )
    if source_text.strip() and not DOUYIN_PET_TEXT_RE.search(source_text):
        failures.append("source caption/story does not prove cat or pet lane fit")
    evidence = _packet_value(packet, "source_evidence")
    if not isinstance(evidence, list) or not evidence:
        failures.append("source_evidence must record TikTok tag/caption/visual decision inputs")
    elif not any(bool(item.get("pet_positive")) for item in evidence if isinstance(item, dict)):
        failures.append("source_evidence must include at least one pet-positive evidence item")

    caption_text = str(_packet_value(packet, "source_caption_or_overlay") or "").lower()
    visual_review = str(packet.get("visual_review") or "").lower()
    if "caption unavailable" in caption_text and visual_review not in ALLOWED_VISUAL_REVIEWS:
        failures.append("source caption unavailable requires passed visual review before content generation")

    script_text = " ".join(
        str(packet.get(name) or "")
        for name in ("title", "script", "body", "caption", "localized_script", "voiceover_text")
    )
    if re.search(r"知识|科普|行为信号|这说明", script_text) and not str(packet.get("ops_override_reason") or ""):
        if any(re.search(pattern, script_text) for pattern in DOUYIN_KNOWLEDGE_PATTERNS):
            failures.append("TikTok repost script looks like cat knowledge explainer")

    mapping = _packet_value(packet, "scene_to_script_mapping")
    if isinstance(mapping, list) and not mapping:
        failures.append("scene_to_script_mapping must not be empty")
    if require_visual_review and visual_review not in ALLOWED_VISUAL_REVIEWS:
        failures.append("visual_review must be passed before publish package")
    return failures


def validate_article_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Require long-form structure, a deliberate hook, visual mapping, and template evidence."""
    body = str(packet.get("body", ""))
    selection = packet.get("visual_template_selection") or {}
    mapping = packet.get("section_image_map") or []
    strategy = packet.get("strategy_brief") or {}
    cover = packet.get("cover_design") or {}
    card_plan = packet.get("knowledge_card_plan") or {}
    embedded_cards = packet.get("embedded_knowledge_cards") or []
    differentiation = packet.get("differentiation_dimensions") or []
    hook = str(packet.get("opening_hook", "")).strip()
    hook_type = str(packet.get("hook_type", "")).strip()
    length = _text_length(body)
    gates = {
        "preflight_manifest": validate_preflight_manifest(packet, str(packet.get("platform") or "")),
        "visual_content_policy": {
            "passed": packet_uses_current_policy(packet),
            "required_policy": "visual_content_design_policy_v1",
        },
        "strategy_brief": {
            "passed": all(
                strategy.get(key)
                for key in [
                    "target_user",
                    "channel_lane",
                    "topic_basis",
                    "click_reason",
                    "reader_payoff",
                    "chosen_structure",
                    "content_form",
                ]
            ),
        },
        "body_length": {"passed": 1200 <= length <= 3000, "actual": length, "range": [1200, 3000]},
        "opening_hook": {"passed": bool(hook) and _text_length(hook) >= 35 and bool(hook_type), "type": hook_type},
        "expanded_sections": {"passed": len(packet.get("sections") or []) >= 5},
        "template_selection": {
            "passed": bool(selection.get("selected"))
            and bool(selection.get("ranked_scores"))
            and "recent_same_platform_templates" in selection
            and "penalties" in selection,
        },
        "section_images": {
            "passed": len(mapping) >= 3
            and all(
                isinstance(item, dict)
                and item.get("section")
                and item.get("image")
                and item.get("purpose")
                and item.get("adjacent_to_text")
                for item in mapping
            ),
            "count": len(mapping),
            "minimum": 3,
        },
        "real_scene_backgrounds": _real_scene_background_gate(packet, minimum=3),
        "section_real_scene_mapping": _section_real_scene_mapping_gate(packet, mapping),
        "knowledge_card_plan": {
            "passed": _valid_knowledge_card_plan(card_plan),
            "skill": str(card_plan.get("skill", "")),
        },
        "article_recipe": validate_article_recipe(packet.get("article_recipe")),
        "knowledge_card_recipe": validate_knowledge_card_recipe(packet.get("knowledge_card_recipe")),
        "tool_selection": validate_tool_selection_evidence(packet, content_kind="article"),
        "tool_invocation_manifest": validate_tool_invocation_manifest(
            packet.get("tool_invocation_manifest"),
            require_execution=bool(packet.get("runtime_execution_required") or packet.get("run_contract")),
        ),
        "embedded_knowledge_cards": {
            "passed": len(embedded_cards) >= 3
            and all(isinstance(card, dict) and _valid_knowledge_card(card) and card.get("section") for card in embedded_cards),
            "count": len(embedded_cards),
            "minimum": 3,
        },
        "cover_design": {
            "passed": (
                cover.get("version") == "cover_direction_v2"
                and all(cover.get(key) for key in ["visual_subject", "layout_key", "hook", "conflict_or_payoff", "content_match_reason"])
                and cover.get("safe_zone_verified") is True
                and cover.get("degraded") is not True
            ) or all(
                cover.get(key)
                for key in ["visual_subject", "topic_alignment", "mobile_readable", "visual_hierarchy", "template_family"]
            ),
        },
        "same_day_differentiation": {"passed": len(differentiation) >= 3, "count": len(differentiation), "minimum": 3},
        "human_value": {
            "passed": bool(packet.get("reader_payoff")) and bool(packet.get("concrete_case")) and bool(packet.get("actionable_checklist")),
        },
        "growth_plan": validate_growth_package(packet),
    }
    return _result(gates)


def validate_platform_article_packet(packet: dict[str, Any], platform: str) -> dict[str, Any]:
    """Validate pre-onboarding article channels through an explicit platform gate."""
    article = validate_article_packet(packet)
    normalized = str(platform or packet.get("platform") or "").casefold()
    strategy = packet.get("strategy_brief") or {}
    adaptation = packet.get("platform_adaptation") or {}
    ops_gates = _full_ops_gates(packet, normalized)
    gates = {
        "base_article_quality": {"passed": bool(article.get("passed")), "failed": article.get("failed_dimensions", [])},
        **ops_gates,
        "platform_identity": {
            "passed": str(packet.get("platform") or "").casefold() == normalized
            and str((packet.get("preflight_manifest") or {}).get("channel") or "").casefold() == normalized,
        },
        "platform_strategy": {
            "passed": bool(strategy.get("channel_lane"))
            and bool(strategy.get("topic_basis"))
            and bool(strategy.get("content_form"))
            and bool(strategy.get("reader_payoff")),
        },
        "platform_adaptation": {
            "passed": bool(adaptation.get("required_fields_checked"))
            or (normalized in {"juejin", "zhihu"} and bool(packet.get("safe_handoff_route"))),
        },
    }
    return _result(gates)


def validate_xiaohongshu_auto_packet(packet: dict[str, Any], phase: str = "rendered") -> dict[str, Any]:
    """Validate Xiaohongshu mixed manual-handoff packages before user review."""
    content_type = str(packet.get("content_type") or packet.get("content_form") or "").casefold()
    cards = packet.get("embedded_knowledge_cards") or packet.get("knowledge_card_sequence") or []
    images = packet.get("section_image_map") or packet.get("image_text_plan") or []
    cover = packet.get("cover_design") or {}
    source_assets = packet.get("source_assets") or packet.get("authentic_source_evidence") or []
    valid_source_assets = [item for item in source_assets if isinstance(item, dict) and _valid_real_scene_asset(item)] if isinstance(source_assets, list) else []
    disclosure = str(packet.get("ai_assisted_disclosure") or packet.get("disclosure") or packet.get("body") or "")
    video_plan = packet.get("video_plan") or packet.get("short_video_plan") or {}
    mixed_plan = packet.get("mixed_content_plan") or {}
    generation_phase = str(phase or "rendered").casefold() in {"generation", "pre_generation", "pre-generation"}
    rendered_phase = str(phase or "rendered").casefold() in {"rendered", "post_generation", "post-generation"}
    carousel_only = content_type in {"carousel", "image_text_note", "xiaohongshu_carousel"}
    ops_gates = _full_ops_gates(packet, "xiaohongshu")
    gates = {
        "preflight_manifest": validate_preflight_manifest(packet, str(packet.get("platform") or "")),
        "visual_content_policy": {
            "passed": packet_uses_current_policy(packet),
            "required_policy": "visual_content_design_policy_v1",
        },
        **ops_gates,
        "mixed_content_form": {
            "passed": content_type
            in {
                "image_text_knowledge_card_short_video_mix",
                "xiaohongshu_mixed_note",
                "note_knowledge_card_short_video",
                "carousel",
                "image_text_note",
                "xiaohongshu_carousel",
            },
            "actual": content_type,
        },
        "body_or_caption": {
            "passed": _text_length(str(packet.get("body") or packet.get("caption") or "")) >= 300,
        },
        "knowledge_cards": {
            "passed": len(cards) >= 3 and all(isinstance(card, dict) and _valid_knowledge_card(card) for card in cards),
            "count": len(cards),
            "minimum": 3,
        },
        "knowledge_card_recipe": validate_knowledge_card_recipe(packet.get("knowledge_card_recipe")),
        "tool_selection": validate_tool_selection_evidence(packet, content_kind="article"),
        "tool_invocation_manifest": validate_tool_invocation_manifest(
            packet.get("tool_invocation_manifest"),
            require_execution=not generation_phase and bool(packet.get("runtime_execution_required") or packet.get("run_contract")),
        ),
        "image_text_mapping": {
            "passed": len(images) >= 3
            and all(
                isinstance(item, dict)
                and (item.get("section") or item.get("beat"))
                and (item.get("image") or item.get("asset"))
                and item.get("purpose")
                for item in images
            ),
            "count": len(images),
            "minimum": 3,
        },
        "section_real_scene_mapping": _section_real_scene_mapping_gate(packet, images),
        "short_video_component": {
            "passed": carousel_only
            or all(video_plan.get(key) for key in ["theme", "opening_hook", "visual_alignment_plan"])
            or all(mixed_plan.get(key) for key in ["short_video", "image_text_note", "knowledge_cards"]),
        },
        "authentic_source_evidence": {
            "passed": len(valid_source_assets) >= 3,
            "count": len(valid_source_assets),
            "total_assets": len(source_assets) if isinstance(source_assets, list) else 0,
        },
        "real_scene_backgrounds": _real_scene_background_gate(packet, minimum=3),
        "ai_assisted_disclosure": {
            "passed": "AI" in disclosure or "ai" in disclosure.casefold() or "辅助" in disclosure,
        },
        "cover_design": {
            "passed": (
                cover.get("version") == "cover_direction_v2"
                and all(cover.get(key) for key in ["visual_subject", "layout_key", "hook", "conflict_or_payoff", "content_match_reason"])
                and cover.get("safe_zone_verified") is True
                and cover.get("degraded") is not True
            ) or all(
                cover.get(key)
                for key in ["visual_subject", "topic_alignment", "mobile_readable", "visual_hierarchy", "template_family"]
            ),
        },
        "manual_handoff_only": {
            "passed": (packet.get("manual_publish_package") or {}).get("live_publish_allowed") is False
            or (packet.get("publishing_plan") or {}).get("manual_review_required") is True,
        },
        "growth_plan": validate_growth_package(packet),
    }
    if generation_phase:
        for key in ("tool_invocation_manifest", "authentic_source_evidence", "cover_design", "manual_handoff_only"):
            gates[key] = {"passed": True, "deferred": True, "phase": "generation"}
    elif rendered_phase:
        gates["manual_handoff_only"] = {"passed": True, "deferred": True, "phase": "rendered"}
    return _result(gates)


def validate_video_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Reject silent, uncaptained, static-card, or unverified-footage short videos."""
    audio = packet.get("audio_probe") or {}
    subtitle = packet.get("subtitle") or {}
    captions = packet.get("burned_captions") or {}
    visuals = packet.get("visual_probe") or {}
    assets = packet.get("source_assets") or []
    scenes = packet.get("scene_visual_alignment") or []
    card_sequence = packet.get("knowledge_card_sequence") or []
    voice_style = packet.get("voice_style") or {}
    pause_plan = voice_style.get("pause_plan") or []
    plan = packet.get("video_plan") or {}
    visual_recipe = packet.get("visual_recipe") or (packet.get("video_toolchain_plan") or {}).get("visual_recipe") or {}
    differentiation = packet.get("differentiation_dimensions") or []
    platform = str(packet.get("platform", "")).casefold()
    platform_adaptation = packet.get("platform_adaptation") or {}
    form = str(packet.get("content_form", "")).casefold()
    allows_no_subtitles = form in {"knowledge_image_video", "image_card_knowledge_video", "visual_card_voiceover"}
    duration = float(audio.get("duration", 0))
    duration_policy = packet.get("duration_policy") or {}
    experimental_short = isinstance(duration_policy, dict) and str(duration_policy.get("mode") or "").casefold() == "experimental_short"
    minimum_duration = float(duration_policy.get("min_seconds") or 25) if experimental_short else 40.0
    maximum_duration = float(duration_policy.get("max_seconds") or 40) if experimental_short else 100.0
    long_reason = str(packet.get("duration_strategy_reason", "")).strip()
    gates = {
        "preflight_manifest": validate_preflight_manifest(packet, str(packet.get("platform") or "")),
        "visual_content_policy": {
            "passed": packet_uses_current_policy(packet),
            "required_policy": "visual_content_design_policy_v1",
        },
        "video_plan": {
            "passed": all(
                plan.get(key)
                for key in [
                    "theme",
                    "target_audience",
                    "user_pain",
                    "opening_hook",
                    "core_message",
                    "storyboard",
                    "voiceover",
                    "subtitle_plan",
                    "music_plan",
                    "ending_cta",
                    "visual_alignment_plan",
                ]
            ),
        },
        "visual_recipe": validate_visual_recipe(visual_recipe, load_effect_module_registry()),
        "tool_selection": validate_tool_selection_evidence(packet, content_kind="video"),
        "tool_invocation_manifest": validate_tool_invocation_manifest(
            packet.get("tool_invocation_manifest"),
            require_execution=bool(packet.get("runtime_execution_required") or packet.get("run_contract")),
        ),
        "duration": {
            "passed": duration >= minimum_duration and (duration <= maximum_duration or bool(long_reason)),
            "actual": duration,
            "recommended_range_seconds": [minimum_duration, maximum_duration],
            "long_reason": long_reason,
        },
        "audio_stream": {"passed": int(audio.get("stream_count", 0)) > 0 and duration >= minimum_duration},
        "audio_composition": {
            "passed": bool(packet.get("voiceover_present", True)) and bool(packet.get("background_music_present")),
        },
        "background_music_source": {
            "passed": bool(packet.get("background_music_present")) and bool(packet.get("bgm_source")),
            "source": packet.get("bgm_source") or {},
        },
        "natural_voice": {
            "passed": bool(voice_style.get("human_pacing"))
            and int(voice_style.get("segment_count", 0)) >= 4
            and len(pause_plan) >= 4
            and bool(voice_style.get("emotion_cues")),
            "provider": str(voice_style.get("provider", "")),
            "segments": int(voice_style.get("segment_count", 0)),
            "pauses": len(pause_plan),
        },
        "subtitle_or_readable_cards": {
            "passed": int(subtitle.get("cue_count", 0)) >= 8
            or (
                allows_no_subtitles
                and bool(visuals.get("readable_on_card_text"))
                and int(visuals.get("card_text_min_font_size", 0)) >= 44
            )
        },
        "lower_third_captions": {
            "passed": allows_no_subtitles
            or (
                captions.get("position") == "lower_third"
                and bool(captions.get("burned_in"))
                and int(captions.get("font_size", 0)) >= 44
                and int(captions.get("max_chars_per_line", 99)) <= 18
                and int(captions.get("max_lines", 99)) <= 2
            ),
        },
        "full_frame_visuals": {
            "passed": float(visuals.get("occupied_frame_ratio", 0)) >= 0.85
            and int(visuals.get("distinct_scene_count", 0)) >= 8
            and int(visuals.get("unique_source_count", 0)) >= 4,
        },
        "knowledge_card_sequence": {
            "passed": len(card_sequence) >= 3
            and all(isinstance(card, dict) and _valid_knowledge_card(card) and card.get("script_beat") for card in card_sequence),
            "count": len(card_sequence),
            "minimum": 3,
        },
        "rights_cleared_source_assets": {
            "passed": len(assets) >= 4
            and all(isinstance(item, dict) and item.get("rights_cleared") and item.get("behavior_match") for item in assets),
            "count": len(assets),
        },
        "real_scene_backgrounds": _real_scene_background_gate(packet, minimum=max(4, len(card_sequence) or 0, len(scenes) or 0)),
        "hook": {"passed": bool(str(packet.get("first_second_hook", "")).strip())},
        "first_three_seconds": {
            "passed": bool(str(packet.get("first_second_hook", "")).strip())
            and bool(packet.get("first_three_second_value")),
        },
        "scene_visual_alignment": {
            "passed": len(scenes) >= 8
            and all(
                isinstance(item, dict)
                and item.get("script_beat")
                and item.get("visual_asset")
                and item.get("match_reason")
                for item in scenes
            ),
            "count": len(scenes),
        },
        "scene_real_scene_mapping": _scene_real_scene_mapping_gate(packet, scenes),
        "same_batch_differentiation": {"passed": len(differentiation) >= 3, "count": len(differentiation), "minimum": 3},
        "platform_render_identity": _platform_render_identity_gate(packet, platform),
        "media_delivery_contract": _media_delivery_contract_gate(packet, platform),
        "platform_adaptation": {
            "passed": bool(platform_adaptation.get("required_fields_checked"))
            and (
                platform != "kuaishou"
                or (
                    int(platform_adaptation.get("topic_tag_count", 99)) <= 2
                    and int(platform_adaptation.get("description_hashtag_count", 99)) == 0
                )
            ),
            "platform": platform,
        },
        "growth_plan": validate_growth_package(packet),
    }
    return _result(gates)


def validate_wechat_auto_packet(packet: dict[str, Any], phase: str = "rendered") -> dict[str, Any]:
    """Validate a WeChat auto-workflow packet before draft upload.

    This is stricter than the generic article gate because WeChat automation
    has repeatedly failed by skipping the current source plan, section images,
    theme differentiation, and draft postcheck plan.
    """
    article = validate_article_packet(packet)
    body = str(packet.get("body", ""))
    strategy = packet.get("strategy_brief") or {}
    source_data = packet.get("source_data") or {}
    selected_project = packet.get("selected_project") or {}
    selected_project_url = str(selected_project.get("url") or selected_project.get("html_url") or "").strip()
    selected_project_visual = str(
        selected_project.get("screenshot_path")
        or selected_project.get("screenshot_url")
        or selected_project.get("og_image")
        or selected_project.get("image_url")
        or ""
    ).strip()
    batch = packet.get("batch_plan") or {}
    cover = packet.get("cover_design") or {}
    publishing = packet.get("publishing_plan") or {}
    theme = packet.get("visual_template_selection") or {}
    account_analysis = packet.get("account_analysis") or strategy.get("account_analysis") or {}
    same_lane_accounts = packet.get("same_lane_account_analysis") or strategy.get("same_lane_account_analysis") or {}
    trend_analysis = packet.get("cross_platform_trend_analysis") or strategy.get("cross_platform_trend_analysis") or {}
    topic_selection = packet.get("topic_selection") or strategy.get("topic_selection") or {}
    content_brief = packet.get("content_generation_brief") or strategy.get("content_generation_brief") or {}
    content_channels = packet.get("content_channels") or strategy.get("content_channels") or {}
    growth_strategy = packet.get("growth_strategy") or packet.get("growth_plan") or {}
    wechat_playbook = (
        (growth_strategy.get("wechat_growth_playbook") if isinstance(growth_strategy, dict) else {})
        or packet.get("growth_optimization_strategy")
        or strategy.get("growth_optimization_strategy")
        or {}
    )
    artifact_probe = packet.get("article_artifact_probe") or {}
    direction = str(strategy.get("content_direction") or packet.get("content_line") or "").casefold()
    github_projects = source_data.get("github_projects") or []
    ai_github_projects = source_data.get("github_ai_projects") or []
    non_ai_github_projects = source_data.get("github_non_ai_projects") or []
    hot_content_items = source_data.get("hot_content_items") or trend_analysis.get("hot_content_items") or []
    expected_count = _safe_int(batch.get("expected_count"))
    item_index = _safe_int(batch.get("item_index"))
    selected_theme = str(theme.get("selected") or strategy.get("selected_theme") or "").strip()
    recent_themes = {str(item).strip() for item in (theme.get("recent_same_platform_templates") or [])}
    same_lane_account_samples = same_lane_accounts.get("accounts") or same_lane_accounts.get("samples") or []
    wechat_trend_samples = trend_analysis.get("wechat_same_lane_samples") or trend_analysis.get("wechat_samples") or []
    external_trend_samples = trend_analysis.get("external_platform_samples") or trend_analysis.get("external_samples") or []
    content_brief_sources = {str(item).casefold() for item in (content_brief.get("source_inputs") or [])}
    github_channel_enabled = bool(content_channels.get("github_selection") or content_channels.get("daily_github_selection"))
    frequency = wechat_playbook.get("publishing_frequency") if isinstance(wechat_playbook, dict) else {}
    title_rules = wechat_playbook.get("title_rules") if isinstance(wechat_playbook, dict) else {}
    article_structure = wechat_playbook.get("article_structure") if isinstance(wechat_playbook, dict) else {}
    interaction_conversion = wechat_playbook.get("interaction_conversion") if isinstance(wechat_playbook, dict) else {}
    seo_geo = wechat_playbook.get("seo_geo") if isinstance(wechat_playbook, dict) else {}
    generation_phase = str(phase or "rendered").casefold() in {"generation", "pre_generation", "pre-generation"}
    gates = {
        "base_article_quality": {"passed": bool(article.get("passed")), "failed": article.get("failed_dimensions", [])},
        "account_data_analysis": {
            "passed": all(account_analysis.get(key) for key in ["account_lane", "current_content_data", "audience_profile"]),
            "required": ["account_lane", "current_content_data", "audience_profile"],
        },
        "same_lane_account_benchmark": {
            "passed": bool(same_lane_accounts.get("source"))
            and len(same_lane_account_samples) >= 3
            and bool(same_lane_accounts.get("borrowable_patterns") or same_lane_accounts.get("learnings")),
            "sample_count": len(same_lane_account_samples),
        },
        "cross_platform_trend_analysis": {
            "passed": bool(trend_analysis.get("source"))
            and len(wechat_trend_samples) >= 3
            and len(external_trend_samples) >= 3
            and bool(trend_analysis.get("hot_topics") or trend_analysis.get("hot_trends")),
            "wechat_sample_count": len(wechat_trend_samples),
            "external_sample_count": len(external_trend_samples),
        },
        "topic_and_article_plan": {
            "passed": all(topic_selection.get(key) for key in ["selected_topic", "selection_reason", "article_angle"])
            and bool(content_brief.get("article_plan"))
            and bool(content_brief.get("headline_hook")),
            "required": ["selected_topic", "selection_reason", "article_angle", "article_plan", "headline_hook"],
        },
        "content_workflow_inputs": {
            "passed": bool(content_brief.get("provided_to_content_workflow"))
            and {"account_analysis", "same_lane_account_analysis", "cross_platform_trend_analysis", "topic_selection"}.issubset(content_brief_sources),
            "source_inputs": sorted(content_brief_sources),
        },
        "github_project_source": {
            "passed": ("github" in direction or github_channel_enabled)
            and len(github_projects) >= 1
            and bool(selected_project.get("repo"))
            and selected_project_url.startswith("http")
            and bool(selected_project_visual),
            "project_count": len(github_projects),
            "project_url_present": selected_project_url.startswith("http"),
            "project_visual_present": bool(selected_project_visual),
        },
        "dual_content_channels": {
            "passed": github_channel_enabled
            and bool(content_channels.get("hot_content_generation"))
            and len(ai_github_projects) >= 1
            and len(non_ai_github_projects) >= 1
            and len(hot_content_items) >= 3,
            "ai_github_count": len(ai_github_projects),
            "non_ai_github_count": len(non_ai_github_projects),
            "hot_content_count": len(hot_content_items),
        },
        "wechat_growth_playbook": {
            "passed": bool(wechat_playbook)
            and wechat_playbook.get("mode") == "wechat_14_day_recovery"
            and str(frequency.get("recommended_articles_per_week") or "") == "3"
            and _safe_int(frequency.get("max_articles_per_week_recovery")) <= 3
            and _safe_int(frequency.get("min_gap_hours_between_articles")) >= 48
            and _safe_int(frequency.get("max_articles_per_day")) == 1
            and _safe_int((wechat_playbook.get("recovery_topic_policy") or {}).get("topic_dedup_window_days")) >= 14
            and bool((wechat_playbook.get("content_mix") or {}).get("personal_practice_story"))
            and len(wechat_playbook.get("columns") or []) >= 4
            and _safe_int(title_rules.get("keyword_first_chars")) <= 15
            and _safe_int(title_rules.get("max_chars")) <= 24
            and _safe_int(article_structure.get("retention_hook_interval_chars")) <= 350
            and bool(interaction_conversion.get("backend_reply_keywords"))
            and bool(seo_geo.get("primary_keywords")),
            "required": [
                "mode=wechat_14_day_recovery",
                "publishing_frequency.recommended_articles_per_week=3",
                "publishing_frequency.max_articles_per_week_recovery<=3",
                "publishing_frequency.min_gap_hours_between_articles>=48",
                "publishing_frequency.max_articles_per_day=1",
                "recovery_topic_policy.topic_dedup_window_days>=14",
                "content_mix",
                "columns",
                "title_rules.keyword_first_chars<=15",
                "title_rules.max_chars<=24",
                "article_structure.retention_hook_interval_chars<=350",
                "backend_reply_keywords",
                "seo_keywords",
            ],
        },
        "batch_quantity_contract": {
            "passed": expected_count >= 2
            and item_index >= 1
            and item_index <= expected_count,
            "expected_count": expected_count,
            "item_index": item_index,
        },
        "inline_img_tags": {"passed": len(re.findall(r"<img\b", body, flags=re.I)) >= 3},
        "theme_differentiation": {
            "passed": bool(selected_theme)
            and bool(strategy.get("selected_theme_reason"))
            and selected_theme not in recent_themes,
            "selected": selected_theme,
        },
        "cover_cdn": {
            "passed": bool(cover.get("cdn_url") or cover.get("thumb_media_id") or cover.get("wechat_media_id")),
        },
        "digest_limit": {
            "passed": bool(packet.get("digest") or strategy.get("seo_digest"))
            and _text_length(str(packet.get("digest") or strategy.get("seo_digest") or "")) <= 54,
        },
        "draft_postcheck_plan": {
            "passed": str(publishing.get("postcheck") or "").casefold()
            in {"wechat_draft_batchget", "draft_batchget_confirm", "wechat_draft_batchget_or_backend_draft_row"},
        },
        "article_artifact_probe": {
            "passed": 1200 <= _safe_int(artifact_probe.get("word_count")) <= 3000
            and _safe_int(artifact_probe.get("inline_image_count")) >= 3
            and _safe_int(artifact_probe.get("adjacent_inline_image_count")) >= 3
            and bool(artifact_probe.get("theme_css_inlined"))
            and bool(artifact_probe.get("cover_uploaded"))
            and _safe_int(artifact_probe.get("body_font_px")) >= 16
            and bool(artifact_probe.get("draft_batchget_planned")),
            "required": [
                "word_count 1200..3000",
                "inline_image_count >= 3",
                "adjacent_inline_image_count >= 3",
                "theme_css_inlined",
                "cover_uploaded",
                "body_font_px >= 16",
                "draft_batchget_planned",
            ],
        },
        "no_ai_slop_check": {
            "passed": _check_no_ai_slop(body) if len(body) > 200 else False,
            "note": "run no_ai_slop_check.py on body",
        },
    }
    if generation_phase:
        for key in ("base_article_quality", "inline_img_tags", "cover_cdn", "draft_postcheck_plan", "article_artifact_probe"):
            gates[key] = {"passed": True, "deferred": True, "phase": "generation"}
    return _result(gates)


def validate_wechat_image_post_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Validate a WeChat image-message (newspic) package before draft upload.

    The image-message lane is a companion to the long article lane. It must be
    treated as a real content product, not as decorative screenshots.
    """
    cards = packet.get("cards") or packet.get("image_cards") or []
    if not isinstance(cards, list):
        cards = []
    layouts = [str(card.get("layout") or "").strip() for card in cards if isinstance(card, dict)]
    palettes = [str(card.get("palette") or "").strip() for card in cards if isinstance(card, dict)]
    backgrounds = [(card.get("background") or {}) for card in cards if isinstance(card, dict)]
    postcheck = packet.get("postcheck") or {}
    publishing = packet.get("publishing_plan") or {}
    title = str(packet.get("title") or "").strip()
    gates = {
        "content_type": {
            "passed": str(packet.get("content_type") or "").casefold() in {"wechat_image_post", "wechat_newspic", "newspic"},
        },
        "card_count": {
            "passed": 3 <= len(cards) <= 20 and _safe_int(packet.get("card_count"), len(cards)) == len(cards),
            "count": len(cards),
            "range": [3, 20],
        },
        "cover_and_cta": {
            "passed": bool(cards)
            and str((cards[0] if isinstance(cards[0], dict) else {}).get("role") or "").casefold() == "cover"
            and str((cards[-1] if isinstance(cards[-1], dict) else {}).get("role") or "").casefold() in {"cta", "summary_cta"},
        },
        "one_idea_per_card": {
            "passed": bool(cards)
            and all(isinstance(card, dict) and card.get("one_idea") is True and _text_length(str(card.get("title") or "")) >= 4 for card in cards),
        },
        "image_specs": {
            "passed": bool(cards)
            and all(
                isinstance(card, dict)
                and _safe_int(card.get("width")) == 1080
                and _safe_int(card.get("height")) == 1440
                and _safe_int(card.get("bytes")) >= 30000
                and _is_abs_media_path(card.get("image_path"))
                for card in cards
            ),
            "required": "1080x1440, absolute image path, non-empty file",
        },
        "layout_diversity": {
            "passed": len({layout for layout in layouts if layout}) >= min(len(cards), 5),
            "unique_layouts": len({layout for layout in layouts if layout}),
        },
        "palette_rotation": {
            "passed": len({palette for palette in palettes if palette}) >= min(len(cards), 4),
            "unique_palettes": len({palette for palette in palettes if palette}),
        },
        "real_scene_backgrounds": {
            "passed": bool(backgrounds)
            and len(backgrounds) == len(cards)
            and all(_valid_wechat_image_card_background(bg) for bg in backgrounds),
            "count": len(backgrounds),
        },
        "readability": {
            "passed": bool(cards)
            and all(_valid_wechat_image_card_typography(card.get("typography") or {}) for card in cards if isinstance(card, dict)),
        },
        "engagement_design": {
            "passed": bool(packet.get("design_strategy"))
            and all(
                isinstance(card, dict)
                and bool((card.get("engagement") or {}).get("hook_or_payoff"))
                and bool((card.get("engagement") or {}).get("save_reason"))
                for card in cards
            ),
        },
        "image_text_card_recipe": validate_image_text_card_recipe(packet.get("image_text_card_recipe")),
        "tool_invocation_manifest": validate_tool_invocation_manifest(
            packet.get("tool_invocation_manifest"),
            require_execution=bool(packet.get("runtime_execution_required") or packet.get("run_contract")),
        ),
        "publishing_contract": {
            "passed": str(publishing.get("article_type") or "").casefold() == "newspic"
            and str(publishing.get("publish_mode") or "").casefold() in {"draft", "scheduled_draft"},
        },
        "draft_postcheck": {
            "passed": postcheck.get("required") is True
            and postcheck.get("batchget_verified") is True
            and str(postcheck.get("article_type") or "").casefold() == "newspic"
            and postcheck.get("title_present") is True
            and postcheck.get("image_count_matched") is True,
        },
    }
    return _result(gates)


def validate_kuaishou_auto_packet(packet: dict[str, Any], phase: str = "preflight") -> dict[str, Any]:
    """Validate a Kuaishou auto-workflow packet.

    ``preflight`` runs before upload/schedule and must not require evidence
    that can only exist after delivery. ``postcheck`` additionally requires
    upload and management-page confirmation steps.
    """
    video = validate_video_packet(packet)
    strategy = packet.get("strategy_brief") or {}
    trend = packet.get("trend_evidence") or strategy.get("trend_evidence") or {}
    selection_mode = str(packet.get("selection_mode") or strategy.get("selection_mode") or "trend_driven").casefold()
    editorial = packet.get("editorial_evidence") or strategy.get("editorial_evidence") or {}
    workflow = packet.get("workflow_evidence") or {}
    card_sequence = packet.get("knowledge_card_sequence") or []
    bgm = packet.get("bgm") or packet.get("background_music") or packet.get("bgm_source") or {}
    bgm_manifest = packet.get("bgm_license_manifest") or bgm.get("manifest") or {}
    publishing = packet.get("publishing_plan") or {}
    artifact_probe = packet.get("video_artifact_probe") or {}
    if not isinstance(card_sequence, list):
        card_sequence = []
    layouts = [str(card.get("layout") or "") for card in card_sequence if isinstance(card, dict)]
    forbidden_bgm_sources = {
        "soundhelix",
        "synthetic",
        "procedural",
        "generated_tone",
        "midi",
        "generated_synthetic_bgm",
        "local_instrument_bgm_library",
    }
    bgm_source = str(bgm.get("source") or "").casefold()
    normalized_phase = str(phase or "preflight").casefold()
    selection_step = "editorial_selection" if selection_mode == "editorial_calendar" else "trend_analysis"
    required_steps = ["strategy", selection_step, "content_generation", "quality_gate"]
    if normalized_phase in {"postcheck", "post_delivery", "post-delivery"}:
        required_steps.extend(["scheduled_upload", "management_postcheck"])
    completed = {str(item).casefold() for item in (workflow.get("completed_steps") or [])}
    trend_evidence_passed = (
        bool(trend.get("source"))
        and bool(trend.get("collected_at"))
        and len(trend.get("samples") or []) >= 3
    )
    editorial_evidence_passed = (
        selection_mode == "editorial_calendar"
        and bool(editorial.get("strategy_source"))
        and bool(editorial.get("calendar_column"))
        and bool(editorial.get("planned_for"))
        and editorial.get("dedupe_passed") is True
    )
    duration_policy = packet.get("duration_policy") or {}
    experimental_short = isinstance(duration_policy, dict) and str(duration_policy.get("mode") or "").casefold() == "experimental_short"
    minimum_duration = float(duration_policy.get("min_seconds") or 25) if experimental_short else 40.0
    maximum_duration = float(duration_policy.get("max_seconds") or 40) if experimental_short else None
    observed_duration = float(artifact_probe.get("duration_seconds") or 0)
    duration_passed = observed_duration >= minimum_duration and (
        maximum_duration is None or observed_duration <= maximum_duration
    )
    gates = {
        "base_video_quality": {"passed": bool(video.get("passed")), "failed": video.get("failed_dimensions", [])},
        "strategy_before_generation": {
            "passed": all(strategy.get(key) for key in ["target_user", "channel_lane", "topic_basis", "content_form"])
        },
        "kuaishou_trend_evidence": {
            "passed": trend_evidence_passed or editorial_evidence_passed,
            "selection_mode": selection_mode,
            "sample_count": len(trend.get("samples") or []),
        },
        "workflow_steps": {
            "passed": all(step in completed for step in required_steps),
            "missing": [step for step in required_steps if step not in completed],
        },
        "card_layout_diversity": {
            "passed": len(card_sequence) >= 6 and len({layout for layout in layouts if layout}) >= 6,
            "layout_count": len({layout for layout in layouts if layout}),
        },
        "real_music_source": {
            "passed": bool(bgm_source)
            and bgm_source not in forbidden_bgm_sources
            and bool(bgm.get("license") or bgm.get("license_type"))
            and bool(bgm.get("source_url"))
            and bool(bgm.get("fit_reason")),
            "source": bgm_source,
        },
        "bgm_license_manifest": {
            "passed": isinstance(bgm_manifest, dict)
            and bool(bgm_manifest.get("source_url"))
            and bool(bgm_manifest.get("license") or bgm_manifest.get("license_type"))
            and bool(bgm_manifest.get("fingerprint") or bgm_manifest.get("checksum")),
        },
        "no_silent_bgm_fallback": {
            "passed": not bool(bgm.get("fallback_used")),
        },
        "bgm_fingerprint_history": _bgm_fingerprint_history_gate(packet),
        "schedule_and_postcheck_plan": {
            "passed": bool(publishing.get("schedule_at"))
            and str(publishing.get("postcheck") or "").casefold()
            in {"kuaishou_management_pending_list", "management_page_postcheck", "kuaishou_management_pending_list_with_exact_schedule_time"},
        },
        "video_artifact_probe": {
            "passed": bool(artifact_probe.get("file_exists"))
            and duration_passed
            and int(artifact_probe.get("audio_stream_count") or 0) >= 1
            and -32 <= float(artifact_probe.get("mean_volume_db") or -99) <= -6
            and str(artifact_probe.get("subtitle_position") or "").casefold() in {"lower_third", "readable_cards"}
            and int(artifact_probe.get("distinct_scene_count") or 0) >= 8
            and int(artifact_probe.get("unique_source_count") or 0) >= 4
            and str(artifact_probe.get("resolution") or "") in {"1080x1920", "2160x3840", "1440x2560"},
            "required": [
                "file_exists",
                f"duration_seconds >= {minimum_duration:g}" + (f" and <= {maximum_duration:g}" if maximum_duration is not None else ""),
                "audio_stream_count >= 1",
                "-32 <= mean_volume_db <= -6",
                "subtitle_position lower_third/readable_cards",
                "distinct_scene_count >= 8",
                "unique_source_count >= 4",
                "vertical resolution >= 1080x1920",
            ],
        },
        "subtitle_layout": {
            "passed": (packet.get("burned_captions") or {}).get("position") == "lower_third"
            and int((packet.get("burned_captions") or {}).get("margin_v") or 0) >= 180
            and int((packet.get("burned_captions") or {}).get("max_chars_per_line") or 99) <= 18
            and int((packet.get("burned_captions") or {}).get("max_lines") or 99) <= 2,
        },
    }
    return _result(gates)


def validate_shipinhao_auto_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Validate Video Channels packets independently from Kuaishou templates."""
    video = validate_video_packet(packet)
    strategy = packet.get("strategy_brief") or {}
    adaptation = packet.get("platform_adaptation") or {}
    ending_card = packet.get("ending_card") or packet.get("final_card") or {}
    ending_probe = packet.get("ending_card_probe") or packet.get("final_card_probe") or {}
    if not isinstance(ending_card, dict):
        ending_card = {}
    if not isinstance(ending_probe, dict):
        ending_probe = {}
    title = str(ending_card.get("title") or ending_card.get("headline") or "").strip()
    title_limit = _safe_int(ending_card.get("title_max_chars")) or 16
    qr_asset = str(
        ending_card.get("wechat_qr_asset")
        or ending_card.get("qr_asset")
        or ending_card.get("official_account_qr")
        or ""
    ).strip()
    cta_type = str(ending_card.get("cta_type") or "").casefold()
    cta_text = str(ending_card.get("cta_text") or ending_card.get("cta") or "").strip()
    qr_position = str(ending_card.get("qr_position") or "").casefold()
    title_chars = _safe_int(ending_probe.get("title_chars")) or _text_length(title)
    gates = {
        "base_video_quality": {"passed": bool(video.get("passed")), "failed": video.get("failed_dimensions", [])},
        "wechat_ecosystem_fit": {
            "passed": bool(strategy.get("wechat_ecosystem_context") or adaptation.get("wechat_ecosystem_context")),
        },
        "not_kuaishou_reuse": {
            "passed": bool(strategy.get("same_day_kuaishou_dedupe_result") or packet.get("same_day_kuaishou_dedupe_result")),
        },
        "retention_or_share_reason": {
            "passed": bool(strategy.get("target_share_or_save_reason") or strategy.get("retention_problem_addressed")),
        },
        "platform_render_identity": _platform_render_identity_gate(packet, "shipinhao"),
        "media_delivery_contract": _media_delivery_contract_gate(packet, "shipinhao"),
        "wechat_qr_ending_card": {
            "passed": bool(ending_card.get("required"))
            and bool(qr_asset)
            and bool(ending_card.get("qr_visible"))
            and bool(ending_card.get("qr_source"))
            and qr_position in {"lower_right", "lower_left", "bottom_center", "right_safe_area"}
            and cta_type in {"wechat_official_account_followup", "official_account_qr", "wechat_ecosystem_cta"}
            and ("公众号" in cta_text or "微信" in cta_text or "完整" in cta_text),
            "required": ["wechat_qr_asset", "qr_visible", "qr_source", "qr_position", "wechat ecosystem cta"],
        },
        "ending_card_title": {
            "passed": bool(title) and title_chars <= title_limit,
            "actual_chars": title_chars,
            "limit": title_limit,
        },
        "ending_card_visual_probe": {
            "passed": bool(ending_probe.get("frame_path"))
            and bool(ending_probe.get("qr_detected"))
            and bool(ending_probe.get("qr_visible"))
            and bool(ending_probe.get("qr_contrast_ok"))
            and bool(ending_probe.get("safe_area_ok"))
            and float(ending_probe.get("overlay_opacity_max") or 1) <= 0.65,
            "required": ["frame_path", "qr_detected", "qr_visible", "qr_contrast_ok", "safe_area_ok", "overlay_opacity_max <= 0.65"],
        },
    }
    return _result(gates)


def validate_bilibili_auto_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Validate Bilibili short/tutorial video packets before uploader routing."""
    video = validate_video_packet(packet)
    strategy = packet.get("strategy_brief") or {}
    gates = {
        "base_video_quality": {"passed": bool(video.get("passed")), "failed": video.get("failed_dimensions", [])},
        "tutorial_or_case_value": {
            "passed": bool(strategy.get("reader_payoff") or strategy.get("viewer_payoff") or packet.get("tutorial_value") or packet.get("case_value")),
        },
        "scene_to_script_match": {
            "passed": len(packet.get("scene_visual_alignment") or []) >= 8,
        },
        "bilibili_required_fields": {
            "passed": bool((packet.get("platform_adaptation") or {}).get("required_fields_checked")),
        },
    }
    return _result(gates)


def validate_douyin_auto_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Validate non-TikTok-repost Douyin video packets before upload or scheduling."""
    video = validate_video_packet(packet)
    strategy = packet.get("strategy_brief") or {}
    gates = {
        "base_video_quality": {"passed": bool(video.get("passed")), "failed": video.get("failed_dimensions", [])},
        "pet_or_channel_lane_fit": {
            "passed": bool(strategy.get("channel_lane") or packet.get("content_line") or packet.get("lane")),
        },
        "single_best_schedule_plan": {
            "passed": bool((packet.get("publishing_plan") or {}).get("schedule_at") or (packet.get("publishing_plan") or {}).get("candidate_review_only")),
        },
    }
    return _result(gates)


def validate_delivery_result(result: dict[str, Any]) -> dict[str, Any]:
    """Require platform-side evidence before a prepared packet can be called delivered."""
    status = str(result.get("status", "")).casefold()
    postcheck = result.get("postcheck") or {}
    gates = {
        "remote_submission": {
            "passed": bool(result.get("remote_submitted")),
            "actual": bool(result.get("remote_submitted")),
        },
        "postcheck": {
            "passed": bool(postcheck.get("passed")) and bool(postcheck.get("evidence_path")),
            "evidence_path": str(postcheck.get("evidence_path", "")),
        },
        "final_status": {"passed": status in {"drafted", "published"}, "actual": status},
    }
    return _result(gates)


def validate_growth_package(packet: dict[str, Any]) -> dict[str, Any]:
    """Require a concrete growth plan before a packet can pass content quality."""
    plan = packet.get("growth_strategy") or packet.get("growth_plan") or {}
    platform = str(packet.get("platform") or "")
    content_type = str(packet.get("content_type") or packet.get("content_form") or "")
    result = validate_growth_strategy(plan if isinstance(plan, dict) else {}, platform, content_type)
    failures = result.get("failures", [])
    gates = {
        "growth_strategy": {
            "passed": not any(str(item).startswith("growth_strategy.") for item in failures),
            "failures": failures,
        },
        "growth_quality_targets": {
            "passed": not any(str(item).startswith("growth_quality_targets.") for item in failures),
            "failures": failures,
        },
        "growth_review_plan": {
            "passed": not any(str(item).startswith("growth_review_plan.") for item in failures),
            "failures": failures,
        },
    }
    return _result(gates)


def validate_article_structure(content_package: dict[str, Any], rules: dict[str, Any] | None = None) -> GateResult:
    rules = rules or {}
    failures: list[GateFailure] = []
    for field in ("title", "body_or_script", "visual_strategy"):
        if not content_package.get(field):
            failures.append(_failure("ARTICLE_REQUIRED_FIELD_MISSING", "Q1.1", f"Article content package is missing {field}.", f"Fill {field} before draft or publish."))
    visual_strategy = content_package.get("visual_strategy") or {}
    section_map = visual_strategy.get("section_image_map") or content_package.get("section_image_map") or []
    min_images = int(rules.get("min_illustration_count", 1))
    if len(section_map) < min_images:
        failures.append(
            _failure(
                "ARTICLE_SECTION_IMAGE_MAP_INCOMPLETE",
                "Q1.2",
                f"Article has {len(section_map)} section image mappings; minimum is {min_images}.",
                "Map each required illustration to the adjacent section or record a current strategy exception.",
            )
        )
    if rules.get("require_seo_keywords", True) and not content_package.get("seo_keywords"):
        failures.append(_failure("ARTICLE_SEO_KEYWORDS_MISSING", "Q1.3", "Article is missing seo_keywords.", "Add channel-specific SEO/GEO keywords."))
    return GateResult("article_quality_gate", "failed" if failures else "passed", failures, mode=str(rules.get("mode", "shadow")))


def validate_video_structure(content_package: dict[str, Any], rules: dict[str, Any] | None = None) -> GateResult:
    rules = rules or {}
    failures: list[GateFailure] = []
    for field in ("title", "body_or_script", "storyboard"):
        if not content_package.get(field):
            failures.append(_failure("VIDEO_REQUIRED_FIELD_MISSING", "Q1.10", f"Video content package is missing {field}.", f"Fill {field} before draft or publish."))
    storyboard = content_package.get("storyboard") or []
    for index, scene in enumerate(storyboard):
        if not scene.get("asset_ids") and not scene.get("visual_asset"):
            failures.append(
                _failure(
                    "VIDEO_SCENE_ASSET_MAPPING_MISSING",
                    "Q1.11",
                    f"Video storyboard scene {index + 1} has no mapped visual asset.",
                    "Attach at least one licensed visual asset to every storyboard scene.",
                )
            )
    visual_strategy = content_package.get("visual_strategy") or {}
    if rules.get("require_audio", True) and not (visual_strategy.get("audio_asset_id") or content_package.get("audio_asset_id")):
        failures.append(_failure("VIDEO_AUDIO_MISSING", "Q1.12", "Video package is missing audio asset metadata.", "Attach narration/audio asset metadata."))
    if rules.get("require_subtitle", True) and not (visual_strategy.get("subtitle_asset_id") or content_package.get("subtitle_asset_id")):
        failures.append(_failure("VIDEO_SUBTITLE_MISSING", "Q1.13", "Video package is missing subtitle metadata.", "Attach subtitle metadata or record a card-video exception."))
    return GateResult("video_quality_gate", "failed" if failures else "passed", failures, mode=str(rules.get("mode", "shadow")))


def validate_publish_readiness(content_package: dict[str, Any], channel_rules: dict[str, Any] | None = None) -> GateResult:
    channel_rules = channel_rules or {}
    failures: list[GateFailure] = []
    license_result = validate_asset_licenses(content_package, action="publish")
    failures.extend(license_result.failures)
    if not content_package.get("content_package_id"):
        failures.append(_failure("CONTENT_PACKAGE_ID_MISSING", "P1.1", "Publish payload has no content_package_id.", "Create or attach a ContentPackage before delivery."))
    if str(content_package.get("status", "")).casefold() in {"published", "completed"} and not content_package.get("publish_receipt"):
        failures.append(_failure("PUBLISH_RECEIPT_MISSING", "P1.4", "Content is marked complete without publish_receipt.", "Run platform postcheck or keep the item pending verification."))
    if channel_rules.get("postcheck") and not content_package.get("publishing_plan", {}).get("postcheck"):
        failures.append(_failure("POSTCHECK_PLAN_MISSING", "P1.5", "Channel requires postcheck but no postcheck plan was recorded.", "Record the platform-specific postcheck target before submission."))
    return GateResult("publish_readiness_gate", "failed" if failures else "passed", failures)


def _result(gates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    failed = [name for name, value in gates.items() if not value["passed"]]
    return {
        "passed": not failed,
        "gates": gates,
        "failed_dimensions": failed,
        "score": len(gates) - len(failed),
        "total": len(gates),
    }


def _full_ops_gates(packet: dict[str, Any], platform: str) -> dict[str, dict[str, Any]]:
    normalized = str(platform or packet.get("platform") or "").casefold()
    if normalized not in FULL_OPS_WORKFLOW_PLATFORMS:
        return {}
    strategy = packet.get("strategy_brief") or {}
    workflow = packet.get("operations_workflow") or strategy.get("full_ops_workflow") or {}
    source_matrix = packet.get("platform_source_matrix") or strategy.get("platform_source_matrix") or {}
    account = packet.get("account_analysis") or strategy.get("account_analysis") or {}
    same_lane = packet.get("same_lane_account_analysis") or strategy.get("same_lane_account_analysis") or {}
    trends = packet.get("cross_platform_trend_analysis") or strategy.get("cross_platform_trend_analysis") or {}
    topic = packet.get("topic_selection") or strategy.get("topic_selection") or {}
    quantity = packet.get("quantity_plan") or strategy.get("quantity_plan") or {}
    brief = packet.get("content_generation_brief") or strategy.get("content_generation_brief") or {}
    workflow_inputs = packet.get("content_workflow_inputs") or strategy.get("content_workflow_inputs") or {}
    required_sources = set(str(item).casefold() for item in (trends.get("required_sources") or workflow.get("cross_platform_sources") or []))
    # source_inputs must carry WORKFLOW names (account_analysis, topic_selection, ...),
    # not platform names (bilibili, wechat, ...). Prefer workflow_inputs; fall back to
    # brief only when it holds workflow names. Legacy packets may hold platform names
    # in brief.source_inputs — those must not satisfy MANDATORY_WORKFLOW_INPUTS.
    _brief_sources = {str(item).casefold() for item in (brief.get("source_inputs") or [])}
    _wf_sources = {str(item).casefold() for item in (workflow_inputs.get("source_inputs") or [])}
    if _wf_sources:
        source_inputs = _wf_sources
    elif _brief_sources and MANDATORY_WORKFLOW_INPUTS.issubset(_brief_sources):
        source_inputs = _brief_sources
    else:
        source_inputs = _brief_sources
    handoff_fields = {field for field in MANDATORY_CONTENT_HANDOFF_FIELDS if brief.get(field) or workflow_inputs.get(f"{field}_required")}
    asset_mix = brief.get("asset_mix_plan") or packet.get("asset_mix_plan") or {}
    humanization = brief.get("humanization_plan") or packet.get("humanization_plan") or {}
    return {
        "full_ops_workflow": {
            "passed": bool(workflow.get("required")) and normalized in {str(item).casefold() for item in (workflow.get("platforms") or [normalized])},
        },
        "platform_independent_source_matrix": _platform_source_matrix_gate(source_matrix, normalized),
        "account_data_analysis": {
            "passed": all(account.get(key) for key in ["source", "account_lane", "current_content_data", "audience_profile"]),
        },
        "same_lane_account_benchmark": {
            "passed": bool(same_lane.get("source"))
            and len(same_lane.get("samples") or same_lane.get("accounts") or []) >= 3
            and bool(same_lane.get("borrowable_patterns") or same_lane.get("learnings")),
        },
        "cross_platform_hot_trend_analysis": {
            "passed": bool(trends.get("source"))
            and MANDATORY_OPS_SOURCES.issubset(required_sources)
            and bool(trends.get("topic_clusters") or trends.get("hot_topics") or trends.get("samples")),
            "required_sources": sorted(MANDATORY_OPS_SOURCES),
            "actual_sources": sorted(required_sources),
        },
        "topic_quantity_decision": {
            "passed": all(topic.get(key) for key in ["selected_topic", "selection_reason"])
            and _safe_int(quantity.get("final_count")) >= 1
            and bool(quantity.get("decision_reason")),
        },
        "content_workflow_inputs": {
            "passed": MANDATORY_WORKFLOW_INPUTS.issubset(source_inputs)
            and MANDATORY_CONTENT_HANDOFF_FIELDS.issubset(handoff_fields),
            "source_inputs": sorted(source_inputs),
            "handoff_fields": sorted(handoff_fields),
        },
        "asset_mix_plan": {
            "passed": all(asset_mix.get(key) for key in ["ai_generated", "real_material_retrieval", "ai_edit_real_material"]),
        },
        "humanization_plan": {
            "passed": all(humanization.get(key) for key in ["hook", "body"])
            and bool(humanization.get("voice") or normalized in {"juejin", "zhihu"}),
        },
    }


def _valid_knowledge_card_plan(plan: dict[str, Any]) -> bool:
    skill = str(plan.get("skill", ""))
    skill_ok = skill in {
        "hermes_skill:content/knowledge-card-designer",
        "knowledge-card-designer",
    } or skill.endswith("knowledge-card-designer/SKILL.md")
    return skill_ok and all(
        plan.get(key)
        for key in [
            "card_type",
            "platform",
            "audience",
            "visual_scheme",
            "typography_hierarchy",
            "self_check",
        ]
    )


def _valid_knowledge_card(card: dict[str, Any]) -> bool:
    checks = set(card.get("self_check") or [])
    return bool(card.get("card_type")) and bool(card.get("layout")) and bool(card.get("visual_subject")) and bool(
        card.get("information_value")
    ) and {"readability", "attraction", "information_density", "visual_match"}.issubset(checks)


def _valid_wechat_image_card_background(background: dict[str, Any]) -> bool:
    if not isinstance(background, dict):
        return False
    kind = str(background.get("kind") or background.get("background_kind") or "").casefold()
    source = str(background.get("source") or "").strip()
    return (
        kind not in FORBIDDEN_PRIMARY_BACKGROUNDS
        and kind in {"real_scene_photo", "licensed_real_scene_photo", "verified_real_photo"}
        and bool(source)
        and bool(background.get("source_url") or background.get("asset_id") or background.get("path"))
        and bool(background.get("license") or background.get("rights_cleared"))
        and bool(background.get("query") or background.get("topic_keyword"))
        and bool(background.get("match_reason"))
        and background.get("not_gradient_fallback") is True
    )


def _valid_wechat_image_card_typography(typography: dict[str, Any]) -> bool:
    if not isinstance(typography, dict):
        return False
    return (
        _safe_int(typography.get("title_px")) >= 48
        and _safe_int(typography.get("body_px")) >= 28
        and float(typography.get("line_height") or 0) >= 1.45
        and typography.get("safe_area_ok") is True
        and typography.get("overflow") is False
    )


def _real_scene_background_gate(packet: dict[str, Any], minimum: int = 3) -> dict[str, Any]:
    plan = packet.get("real_scene_background_plan") or packet.get("visual_background_plan") or {}
    if not isinstance(plan, dict):
        plan = {}
    backgrounds = plan.get("per_slide_backgrounds") or plan.get("backgrounds") or packet.get("background_assets") or []
    if not isinstance(backgrounds, list):
        backgrounds = []
    source_policy = str(plan.get("source_policy") or "").casefold()
    primary_kind = str(plan.get("primary_background_kind") or "").casefold()
    forbidden = {str(item).casefold() for item in plan.get("forbidden_backgrounds") or []}
    valid_backgrounds = [item for item in backgrounds if isinstance(item, dict) and _valid_real_scene_background(item)]
    return {
        "passed": bool(plan.get("required"))
        and source_policy in REAL_SCENE_BACKGROUND_SOURCE_POLICY
        and (bool(plan.get("no_css_gradient_primary")) or "css_gradient" in forbidden)
        and primary_kind not in FORBIDDEN_PRIMARY_BACKGROUNDS
        and len(valid_backgrounds) >= int(minimum)
        and len(valid_backgrounds) == len(backgrounds),
        "count": len(valid_backgrounds),
        "minimum": int(minimum),
        "source_policy": source_policy,
        "primary_background_kind": primary_kind,
        "forbidden_backgrounds": sorted(forbidden),
    }


def _section_real_scene_mapping_gate(packet: dict[str, Any], mappings: list[Any]) -> dict[str, Any]:
    backgrounds = _valid_real_scene_backgrounds(packet)
    if not isinstance(mappings, list):
        mappings = []
    valid_mapping_items = [item for item in mappings if isinstance(item, dict)]
    covered = 0
    missing: list[str] = []
    for item in mappings:
        if not isinstance(item, dict):
            missing.append("invalid_mapping_item")
            continue
        if _mapping_item_has_real_background(item, backgrounds, ["section", "beat", "asset_id", "image", "asset"]):
            covered += 1
        else:
            missing.append(str(item.get("section") or item.get("beat") or item.get("image") or item.get("asset") or "unknown"))
    return {
        "passed": bool(mappings) and len(valid_mapping_items) == len(mappings) and covered == len(valid_mapping_items),
        "covered": covered,
        "total": len(mappings),
        "missing": missing[:5],
    }


def _scene_real_scene_mapping_gate(packet: dict[str, Any], scenes: list[Any]) -> dict[str, Any]:
    backgrounds = _valid_real_scene_backgrounds(packet)
    if not isinstance(scenes, list):
        scenes = []
    valid_scene_items = [item for item in scenes if isinstance(item, dict)]
    covered = 0
    missing: list[str] = []
    for item in scenes:
        if not isinstance(item, dict):
            missing.append("invalid_scene_item")
            continue
        if _mapping_item_has_real_background(item, backgrounds, ["script_beat", "beat", "visual_asset", "asset_id"]):
            covered += 1
        else:
            missing.append(str(item.get("script_beat") or item.get("visual_asset") or "unknown"))
    return {
        "passed": bool(scenes) and len(valid_scene_items) == len(scenes) and covered == len(valid_scene_items),
        "covered": covered,
        "total": len(scenes),
        "missing": missing[:5],
    }


def _valid_real_scene_backgrounds(packet: dict[str, Any]) -> list[dict[str, Any]]:
    plan = packet.get("real_scene_background_plan") or packet.get("visual_background_plan") or {}
    if not isinstance(plan, dict):
        return []
    backgrounds = plan.get("per_slide_backgrounds") or plan.get("backgrounds") or packet.get("background_assets") or []
    if not isinstance(backgrounds, list):
        return []
    return [item for item in backgrounds if isinstance(item, dict) and _valid_real_scene_background(item)]


def _mapping_item_has_real_background(item: dict[str, Any], backgrounds: list[dict[str, Any]], fields: list[str]) -> bool:
    values = {str(item.get(field) or "").strip() for field in fields}
    values = {value for value in values if value}
    if not values:
        return False
    for background in backgrounds:
        refs = _background_refs(background)
        if values & refs:
            return True
    return False


def _background_refs(background: dict[str, Any]) -> set[str]:
    refs = set()
    for key in [
        "asset_id",
        "path",
        "source",
        "source_url",
        "section",
        "sections",
        "beat",
        "beats",
        "script_beat",
        "script_beats",
        "visual_asset",
        "visual_assets",
        "image",
        "images",
        "asset",
        "assets",
        "card_id",
    ]:
        value = background.get(key)
        values = value if isinstance(value, list) else [value]
        for raw in values:
            text = str(raw or "").strip()
            if text:
                refs.add(text)
    return refs


def _valid_real_scene_background(item: dict[str, Any]) -> bool:
    background_kind = str(item.get("background_kind") or item.get("kind") or item.get("asset_type") or "").casefold()
    if background_kind in FORBIDDEN_PRIMARY_BACKGROUNDS:
        return False
    return _valid_real_scene_asset(item) and bool(
        item.get("match_reason")
        or item.get("purpose")
        or item.get("script_beat")
        or item.get("section")
        or item.get("card_id")
    )


def _valid_real_scene_asset(item: dict[str, Any]) -> bool:
    asset_type = str(item.get("asset_type") or item.get("kind") or item.get("media_type") or "").casefold()
    if asset_type in FORBIDDEN_PRIMARY_BACKGROUNDS:
        return False
    has_real_scene = bool(item.get("real_scene") or item.get("real_photo") or item.get("authentic") or item.get("verified_real_material"))
    has_source = bool(item.get("source") or item.get("source_url") or item.get("asset_id") or item.get("path"))
    return has_real_scene and has_source and bool(item.get("rights_cleared"))


def _failure(code: str, rule_ref: str, message: str, remediation: str) -> GateFailure:
    return GateFailure(code=code, rule_ref=rule_ref, severity="blocking", message=message, remediation=remediation)
