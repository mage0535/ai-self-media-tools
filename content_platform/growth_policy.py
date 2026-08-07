"""Growth-oriented strategy and validation helpers for channel packets."""

from __future__ import annotations

from typing import Any


GROWTH_POLICY_ID = "growth_quality_policy_v1"

VIDEO_CONTENT_HINTS = {"video", "short", "repost", "microcase"}

WECHAT_RECOVERY_PLAYBOOK: dict[str, Any] = {
    "diagnosis_date": "2026-08-08",
    "mode": "wechat_14_day_recovery",
    "account_status": {
        "certified": True,
        "comments_enabled": True,
        "advanced_data_api": "unavailable_or_unauthorized",
        "manual_backend_export_required": True,
    },
    "primary_goal": "recover_open_rate_and_finish_read_rate_before_increasing_publish_frequency",
    "publishing_frequency": {
        "recommended_articles_per_week": "2",
        "max_articles_per_week_recovery": 2,
        "max_articles_per_week_after_recovery": 3,
        "max_articles_per_day": 1,
        "min_gap_hours_between_articles": 48,
        "pause_days_before_next_publish": 2,
        "avoid_daily_updates": True,
        "avoid_three_articles_per_day_batching": True,
        "reason": "recent 17-day run produced 15 articles and repeated automation topics; recovery needs fewer, stronger, more differentiated pieces",
    },
    "content_mix": {
        "open_source_notes": 0.25,
        "personal_practice_story": 0.30,
        "opinion_or_trend_interpretation": 0.25,
        "interactive_qa_or_weekly_recap": 0.20,
    },
    "columns": [
        {"name": "马吉克开源笔记", "role": "open_source_notes", "recommended_day": "tuesday"},
        {"name": "我的 AI 工作台", "role": "personal_practice_story", "recommended_day": "friday"},
        {"name": "AI 说人话", "role": "opinion_or_trend_interpretation", "recommended_day": "alternate_tuesday"},
        {"name": "你问我答 / 工具箱回访", "role": "interactive_qa_or_weekly_recap", "recommended_day": "alternate_friday"},
    ],
    "recovery_topic_policy": {
        "duration_days": 14,
        "topic_dedup_window_days": 14,
        "title_frame_dedup_window_days": 14,
        "suspend_topics": ["自动化实测", "办公自动化实测", "重复劳动自动化", "WordPress SEO 自动化"],
        "fatigue_terms": ["实测", "自动化", "工具", "AI"],
        "max_fatigue_terms_per_title": 1,
        "same_topic_action": "block_and_reselect_topic",
        "same_title_frame_action": "rewrite_title_or_switch_column",
    },
    "github_selection_policy": {
        "default_mode": "weekly_or_biweekly_single_column",
        "bundle_rule": "one carefully tested open-source project per issue; bundle only when each project has a distinct reader payoff",
        "extra_issue_allowed_only_when": "current_ops_strategy_has_strong_trend_or_account_data_evidence",
        "avoid": "daily_repetitive_github_listing_without_case_or_reader_payoff",
    },
    "title_rules": {
        "ideal_chars": "12-22",
        "max_chars": 24,
        "keyword_first_chars": 15,
        "must_include_one": ["pain", "result", "loss_avoidance", "specific_scenario", "contrast"],
        "template_fatigue_limit": "same_title_frame_not_more_than_once_in_14_days",
        "avoid_repeated_frames": ["实测", "试了", "值得试试", "自动化", "AI工具"],
        "prepare_candidates": 3,
        "reject_if_fatigue_terms_exceed": 1,
    },
    "article_structure": {
        "first_200_chars": "state the reader pain, concrete payoff, and why this matters now",
        "retention_hook_interval_chars": 350,
        "structure_rotation_required": True,
        "avoid_reusing_standard_template_for_14_days": True,
        "allowed_structures": [
            "story_driven_case",
            "contrast_test",
            "contrarian_opinion",
            "reader_question_answer",
            "open_source_project_note",
        ],
        "must_include": [
            "real_case",
            "specific_steps",
            "failure_or_boundary",
            "saveable_checklist",
            "natural_follow_reason",
        ],
    },
    "seo_geo": {
        "primary_keywords": ["AI效率工具", "AI工作流", "开源项目", "GitHub精选", "AI实践复盘"],
        "placement": ["title_first_15_chars", "digest", "first_200_chars", "section_headings"],
        "search_footprint_goal": "improve_wechat_search_and_sogou_discoverability_without_keyword_stuffing",
    },
    "interaction_conversion": {
        "backend_reply_keywords": ["工具箱", "清单", "GitHub", "开源笔记", "提问"],
        "single_primary_cta_only": True,
        "comment_prompt": "ask one concrete experience question tied to the article scenario",
        "share_prompt": "state the colleague or operator who should read it",
        "cross_platform_funnel": "short_video_and_answer_channels_point_to_wechat_keyword_reply",
    },
    "post_publish_review": {
        "review_cadence": "weekly",
        "required_metrics": [
            "impressions",
            "open_rate",
            "finish_read_rate",
            "share_rate",
            "save_rate",
            "comment_rate",
            "new_follows",
            "read_to_follow_rate",
        ],
        "api_unavailable_policy": "record_48001_or_backend_unavailable_reason_and_use_manual_export",
        "recovery_exit_condition": "two consecutive weeks with improving open_rate and finish_read_rate",
    },
}


PLATFORM_GROWTH_RULES: dict[str, dict[str, Any]] = {
    "douyin": {
        "primary_metric": "completion_rate",
        "secondary_metrics": ["three_second_view_rate", "comment_rate", "follow_conversion_rate"],
        "rules": ["strong_first_motion", "lower_third_subtitles", "matched_real_footage", "single_best_candidate"],
        "target_action": "comment_or_follow",
    },
    "kuaishou": {
        "primary_metric": "completion_rate",
        "secondary_metrics": ["comment_rate", "follow_conversion_rate", "share_rate"],
        "rules": ["trust_first_microcase", "plainspoken_voice", "series_prompt", "private_domain_reply"],
        "target_action": "comment_or_follow",
    },
    "wechat": {
        "primary_metric": "click_through_rate",
        "secondary_metrics": ["finish_read_rate", "save_rate", "share_rate", "follow_conversion_rate"],
        "rules": [
            "wechat_14_day_recovery_frequency_control",
            "wechat_14_day_topic_dedup",
            "columnized_personal_ip_mix",
            "title_keyword_first_15_chars",
            "title_template_fatigue_limit_14_days",
            "first_200_chars_reader_payoff",
            "every_350_chars_retention_hook",
            "comment_backend_reply_and_share_cta",
            "single_primary_cta_only",
            "wechat_search_seo_layout",
            "cross_platform_follow_funnel",
            "manual_backend_metrics_review_when_api_unavailable",
        ],
        "target_action": "read_to_follow",
        "wechat_growth_playbook": WECHAT_RECOVERY_PLAYBOOK,
    },
    "bilibili": {
        "primary_metric": "average_watch_seconds",
        "secondary_metrics": ["completion_rate", "favorite_rate", "coin_or_like_rate"],
        "rules": ["tutorial_or_case_depth", "evidence_before_claim", "danmaku_prompt", "favorite_checkpoint"],
        "target_action": "favorite_or_comment",
    },
    "shipinhao": {
        "primary_metric": "three_second_view_rate",
        "secondary_metrics": ["completion_rate", "share_rate", "save_rate"],
        "rules": ["wechat_social_context", "shareable_first_screen", "trust_signal", "no_kuaishou_reuse"],
        "target_action": "share_or_save",
    },
    "xiaohongshu": {
        "primary_metric": "click_through_rate",
        "secondary_metrics": ["save_rate", "comment_rate", "follow_conversion_rate"],
        "rules": ["authentic_cover", "pain_point_title", "use_case_keywords", "early_comment_reply"],
        "target_action": "save_or_comment",
    },
    "zhihu": {
        "primary_metric": "normal_visibility_and_save_rate",
        "secondary_metrics": ["upvote_rate", "comment_rate", "follow_conversion_rate"],
        "rules": [
            "reasoned_article_or_answer_first",
            "pin_not_article_excerpt",
            "answer_article_pin_differentiation",
            "anti_spam_similarity_gate",
            "discussion_prompt_not_marketing_slogan",
        ],
        "target_action": "save_or_comment",
        "zhihu_growth_playbook": {
            "diagnosis_date": "2026-08-08",
            "mode": "zhihu_similarity_recovery",
            "primary_goal": "restore normal visibility by stopping high-similarity short-form promotions",
            "publishing_frequency": {
                "max_articles_per_day": 1,
                "max_pins_per_day": 1,
                "min_gap_hours_between_pins": 48,
                "auto_pin_publish_default": "review_only",
            },
            "anti_spam_similarity": {
                "lookback_days": 14,
                "max_pin_article_overlap": 0.22,
                "max_pin_title_overlap": 0.55,
                "block_if_platform_limited_visibility": True,
            },
            "form_mix": {
                "article": "deep reasoning with evidence and tradeoffs",
                "answer": "question-specific answer with direct answer first",
                "pin": "short original commentary plus discussion question, never article excerpt",
            },
        },
    },
    "juejin": {
        "primary_metric": "collection_rate",
        "secondary_metrics": ["comment_rate", "follow_conversion_rate", "read_depth"],
        "rules": [
            "engineering_implementation_depth",
            "code_or_architecture_specific_value",
            "not_duplicate_of_zhihu_or_wechat",
            "collectable_checklist_or_demo",
        ],
        "target_action": "save_or_comment",
    },
    "rednote": {
        "alias": "xiaohongshu",
    },
}


def _normalized_platform(platforms: list[str] | tuple[str, ...] | str | None) -> str:
    if isinstance(platforms, str):
        platform = platforms
    else:
        platform = next((str(item) for item in (platforms or []) if str(item).strip()), "wechat")
    platform = platform.casefold()
    alias = PLATFORM_GROWTH_RULES.get(platform, {}).get("alias")
    return str(alias or platform)


def _is_video(content_type: str) -> bool:
    content = str(content_type or "").casefold()
    return any(hint in content for hint in VIDEO_CONTENT_HINTS)


def _has_effective_historical_feedback(historical_feedback: dict[str, Any]) -> bool:
    if not isinstance(historical_feedback, dict) or not historical_feedback:
        return False
    platforms = historical_feedback.get("platforms")
    if isinstance(platforms, dict) and any(isinstance(item, dict) and item for item in platforms.values()):
        return True
    clusters = historical_feedback.get("clusters")
    if isinstance(clusters, list) and any(isinstance(item, dict) and item for item in clusters):
        return True
    return any(
        key not in {"platforms", "clusters"} and value not in ({}, [], None, "")
        for key, value in historical_feedback.items()
    )


def build_growth_strategy(
    platforms: list[str] | tuple[str, ...] | str | None,
    content_type: str,
    historical_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the minimum growth brief every generator must carry forward."""
    platform = _normalized_platform(platforms)
    rules = PLATFORM_GROWTH_RULES.get(platform, {})
    is_video = _is_video(content_type)
    historical_feedback = historical_feedback or {}
    has_feedback = _has_effective_historical_feedback(historical_feedback)
    strategy = {
        "policy_id": GROWTH_POLICY_ID,
        "platform": platform,
        "content_type": str(content_type or ""),
        "primary_metric": rules.get("primary_metric") or ("completion_rate" if is_video else "click_through_rate"),
        "secondary_metrics": list(rules.get("secondary_metrics") or ["save_rate", "comment_rate", "follow_conversion_rate"]),
        "target_user_action": rules.get("target_action") or ("save_or_comment" if not is_video else "comment_or_follow"),
        "hook_plan": {
            "type": "conflict_or_payoff",
            "first_screen_promise": "show a concrete result, conflict, or benefit before generic explanation",
            "curiosity_gap": "make the viewer want the missing step, evidence, or reason",
        },
        "retention_plan": {
            "first_3_seconds": "lead with result, mistake, proof, or emotional moment",
            "scene_change_interval_seconds": 3 if is_video else 0,
            "midpoint_payoff": "deliver a useful checklist, proof point, or story turn before the midpoint",
        },
        "interaction_plan": {
            "comment_prompt": "ask a specific low-friction question tied to the viewer's own situation",
            "save_reason": "make the content reusable as a checklist, reference, or decision aid",
            "share_reason": "state why another similar user would benefit from seeing it",
        },
        "packaging_plan": {
            "title_angle": "pain, result, contrast, or mistake; avoid neutral labels",
            "cover_angle": "one visual subject plus one benefit or conflict",
            "keyword_intent": "use channel-native search terms without keyword stuffing",
        },
        "platform_growth_rules": list(rules.get("rules") or []),
        "post_publish_review_plan": {
            "review_points_hours": [1, 24, 72],
            "diagnosis_dimensions": [
                "click_through_rate",
                "three_second_view_rate",
                "completion_rate",
                "save_rate",
                "comment_rate",
                "share_rate",
                "follow_conversion_rate",
            ],
        },
        "quality_targets": {
            "hook_score": 0.78,
            "first_frame_score": 0.76,
            "save_value_score": 0.72,
            "comment_prompt_score": 0.68,
            "template_fatigue_risk": 0.35,
        },
        "historical_feedback_status": "available" if has_feedback else "missing_or_empty",
        "historical_feedback_summary": historical_feedback,
    }
    if platform == "wechat" and isinstance(rules.get("wechat_growth_playbook"), dict):
        strategy["wechat_growth_playbook"] = rules["wechat_growth_playbook"]
    if platform == "zhihu" and isinstance(rules.get("zhihu_growth_playbook"), dict):
        strategy["zhihu_growth_playbook"] = rules["zhihu_growth_playbook"]
    return strategy


def validate_growth_strategy(plan: dict[str, Any], platform: str = "", content_type: str = "") -> dict[str, Any]:
    required_blocks = ["hook_plan", "retention_plan", "interaction_plan", "packaging_plan", "post_publish_review_plan", "quality_targets"]
    missing_blocks = [name for name in required_blocks if not isinstance(plan.get(name), dict) or not plan.get(name)]
    targets = plan.get("quality_targets") if isinstance(plan.get("quality_targets"), dict) else {}
    target_failures = [
        name
        for name in ["hook_score", "first_frame_score", "save_value_score", "comment_prompt_score", "template_fatigue_risk"]
        if name not in targets
    ]
    review = plan.get("post_publish_review_plan") if isinstance(plan.get("post_publish_review_plan"), dict) else {}
    diagnosis = review.get("diagnosis_dimensions") or []
    failures: list[str] = []
    if plan.get("policy_id") != GROWTH_POLICY_ID:
        failures.append("growth_strategy.policy_id_missing")
    if platform and str(plan.get("platform") or "").casefold() not in {str(platform).casefold(), _normalized_platform(platform)}:
        failures.append("growth_strategy.platform_mismatch")
    if content_type and not str(plan.get("content_type") or ""):
        failures.append("growth_strategy.content_type_missing")
    if not plan.get("primary_metric"):
        failures.append("growth_strategy.primary_metric_missing")
    if not plan.get("target_user_action"):
        failures.append("growth_strategy.target_user_action_missing")
    if missing_blocks:
        failures.append("growth_strategy.blocks_missing:" + ",".join(missing_blocks))
    if target_failures:
        failures.append("growth_quality_targets.missing:" + ",".join(target_failures))
    if len(diagnosis) < 5:
        failures.append("growth_review_plan.diagnosis_dimensions_incomplete")
    if _normalized_platform(platform) == "wechat":
        playbook = plan.get("wechat_growth_playbook") if isinstance(plan.get("wechat_growth_playbook"), dict) else {}
        recovery = playbook.get("recovery_topic_policy") if isinstance(playbook.get("recovery_topic_policy"), dict) else {}
        frequency = playbook.get("publishing_frequency") if isinstance(playbook.get("publishing_frequency"), dict) else {}
        if playbook.get("mode") != "wechat_14_day_recovery":
            failures.append("wechat_growth_playbook.recovery_mode_missing")
        if int(frequency.get("max_articles_per_week_recovery") or 0) > 2:
            failures.append("wechat_frequency.recovery_weekly_cap_too_high")
        if int(recovery.get("topic_dedup_window_days") or 0) < 14:
            failures.append("wechat_topic_dedup_window.too_short")
    if _normalized_platform(platform) == "zhihu":
        playbook = plan.get("zhihu_growth_playbook") if isinstance(plan.get("zhihu_growth_playbook"), dict) else {}
        anti_spam = playbook.get("anti_spam_similarity") if isinstance(playbook.get("anti_spam_similarity"), dict) else {}
        frequency = playbook.get("publishing_frequency") if isinstance(playbook.get("publishing_frequency"), dict) else {}
        if playbook.get("mode") != "zhihu_similarity_recovery":
            failures.append("zhihu_growth_playbook.similarity_recovery_mode_missing")
        if int(anti_spam.get("lookback_days") or 0) < 14:
            failures.append("zhihu_similarity_lookback.too_short")
        if float(anti_spam.get("max_pin_article_overlap") or 1) > 0.22:
            failures.append("zhihu_pin_overlap_threshold.too_loose")
        if str(frequency.get("auto_pin_publish_default") or "") != "review_only":
            failures.append("zhihu_pin_publish_default.not_review_only")
    return {
        "passed": not failures,
        "failures": failures,
        "policy_id": GROWTH_POLICY_ID,
    }
