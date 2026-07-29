"""Unified visual/template rules for human-facing content packets."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


KNOWLEDGE_CARD_SKILL = "hermes_skill:content/knowledge-card-designer"

TEXT_COMPOSITION_METHODS = [
    "horizontal",
    "vertical",
    "diagonal",
    "rotated",
    "staggered",
    "split_screen",
    "timeline",
    "card_stack",
    "magazine_cover",
    "visual_anchor",
]

CARD_TYPES = [
    "cover",
    "knowledge_summary",
    "carousel",
    "viewpoint",
    "step_tutorial",
    "emotional_companion",
    "commercial_information",
    "science_explainer",
]

ARTICLE_STRUCTURES = [
    "problem-cause-solution",
    "case-breakdown-method",
    "checklist-steps-cautions",
    "myth-correction-action",
    "story-conflict-turning_point-insight",
    "trend-background-impact-response",
]

VISUAL_FAMILIES = [
    "casebook",
    "process_walkthrough",
    "decision_framework",
    "checklist_board",
    "magazine_feature",
    "evidence_chain",
    "timeline_map",
    "contrast_before_after",
]

SELF_CHECKS = [
    "readability",
    "attraction",
    "information_density",
    "share_or_save_value",
    "visual_match",
    "mobile_safe_boundaries",
]

BASE_POLICY: dict[str, Any] = {
    "policy_id": "visual_content_design_policy_v1",
    "skill": KNOWLEDGE_CARD_SKILL,
    "scope": [
        "covers",
        "inline_knowledge_cards",
        "carousel_cards",
        "image_text_notes",
        "infographics",
        "posters",
        "knowledge_card_videos",
        "article_inline_images",
        "video_scene_cards",
    ],
    "generation_sequence": [
        "load_knowledge_card_designer_skill",
        "classify_content_type",
        "identify_platform_and_audience",
        "choose_article_or_card_structure",
        "select_visual_family",
        "plan_section_or_scene_mapping",
        "select_topic_matched_background_or_visual_subject",
        "generate_assets",
        "render_preview",
        "run_self_check",
    ],
    "tool_refs": {
        "image_generation_engine": "hermes_tool:image_gen_engine",
        "wechat_theme_renderer": "hermes_tool:wechat_theme_renderer",
        "wechat_publisher": "hermes_tool:wechat_publisher",
        "knowledge_card_designer": KNOWLEDGE_CARD_SKILL,
    },
    "card_types": CARD_TYPES,
    "article_structures": ARTICLE_STRUCTURES,
    "visual_families": VISUAL_FAMILIES,
    "text_composition_methods": TEXT_COMPOSITION_METHODS,
    "typography": {
        "hierarchy": "4:2:1",
        "title_px": [48, 72],
        "body_px": [18, 24],
        "label_px": [9, 12],
        "line_height": [1.6, 1.8],
        "min_padding_px": 30,
        "preferred_padding_px": 40,
    },
    "composition_rules": [
        "one_fixed_template_is_not_allowed_for_a_batch",
        "cover_is_not_title_pasted_on_background",
        "visual_subject_must_match_topic",
        "background_or_decoration_must_add_information_value",
        "images_must_explain_prove_compare_locate_or_emotionally_reinforce_adjacent_content",
        "bottom_stacked_gallery_does_not_satisfy_inline_mapping",
        "split_crowded_topics_into_carousel_or_card_video",
        "text_must_not_overflow_mobile_frame",
    ],
    "douyin_reference_patterns": [
        "hook_cover",
        "one_micro_point_per_page",
        "strong_visual_hierarchy",
        "changing_text_groups",
        "page_by_page_progression",
        "2_to_3_second_card_style_changes",
    ],
    "article_requirements": {
        "word_count": [1200, 3000],
        "minimum_inline_images": 3,
        "minimum_sections": 5,
        "requires_section_image_map": True,
        "requires_embedded_knowledge_cards_when_topic_supports": True,
    },
    "wechat_requirements": {
        "theme_count_required": 15,
        "theme_selection": "keyword_and_content_type_match",
        "css": "inline",
        "metadata": ["digest", "author", "geo_tag"],
        "postcheck": "draft_batchget_confirm",
    },
    "video_requirements": {
        "recommended_duration_seconds": [40, 100],
        "minimum_scenes": 8,
        "minimum_unique_source_assets": 4,
        "minimum_knowledge_cards": 3,
        "subtitle_default": "lower_third",
        "visual_change_interval_seconds": [2, 4],
    },
    "self_check": SELF_CHECKS,
}


PLATFORM_OVERRIDES: dict[str, dict[str, Any]] = {
    "wechat": {
        "content_uses": ["long_form_article", "image_text_article"],
        "must_include": ["cover", "article", "embedded_knowledge_cards", "section_image_map"],
        "postcheck": "wechat_draft_batchget_or_backend_draft_row",
    },
    "weixin": {
        "alias_of": "wechat",
        "content_uses": ["long_form_article", "image_text_article"],
        "must_include": ["cover", "article", "embedded_knowledge_cards", "section_image_map"],
        "postcheck": "wechat_draft_batchget_or_backend_draft_row",
    },
    "xiaohongshu": {
        "content_uses": ["image_text_note", "knowledge_cards", "short_video", "carousel"],
        "must_include": ["cover", "content_images", "knowledge_cards", "short_video", "authentic_source_evidence"],
        "main_visual_warning": "no_obvious_ai_generated_main_visual",
        "publish_mode": "hermes_generates_local_review_package_user_manual_publish",
    },
    "douyin": {
        "content_uses": ["edited_pet_short_video", "localized_repost", "knowledge_image_video"],
        "must_include": ["source_video_or_verified_behavior_visuals", "human_voiceover", "background_music"],
        "visual_rule": "real_or_verified_behavior_visuals_must_match_narration",
    },
    "kuaishou": {
        "content_uses": ["edited_short_video", "microcase_video", "knowledge_image_video"],
        "must_include": ["source_assets", "human_voiceover", "background_music", "lower_third_subtitles_or_readable_cards"],
        "template_rule": "no_single_static_template_batch",
    },
    "shipinhao": {
        "content_uses": ["wechat_ecosystem_short_video", "microcase_video"],
        "must_include": ["wechat_ecosystem_context", "source_assets", "human_voiceover", "background_music"],
        "template_rule": "must_differ_from_same_day_kuaishou_without_explicit_reason",
    },
}


def visual_content_policy(platforms: list[str] | tuple[str, ...] | None = None, content_form: str = "") -> dict[str, Any]:
    """Return the consolidated policy that generation and QA must cite."""
    policy = deepcopy(BASE_POLICY)
    policy["content_form"] = content_form
    selected: dict[str, Any] = {}
    for platform in platforms or []:
        key = str(platform).casefold()
        if key in PLATFORM_OVERRIDES:
            selected[key] = deepcopy(PLATFORM_OVERRIDES[key])
    policy["platform_overrides"] = selected
    return policy


def required_policy_id() -> str:
    return BASE_POLICY["policy_id"]


def packet_uses_current_policy(packet: dict[str, Any]) -> bool:
    policy = packet.get("visual_content_policy") or {}
    return policy.get("policy_id") == required_policy_id() and policy.get("skill") == KNOWLEDGE_CARD_SKILL
