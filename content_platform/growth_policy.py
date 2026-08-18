"""Growth-oriented strategy and validation helpers for channel packets."""

from __future__ import annotations

from typing import Any


GROWTH_POLICY_ID = "growth_quality_policy_v1"
GROWTH_POLICY_VERSION = "2026-08-17"

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
        "recommended_articles_per_week": "3",
        "max_articles_per_week_recovery": 3,
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
        "direction_dedup_required": True,
        "direction_register_key": "data/ops_runs/<YYYYMMDD>/run_manifest.json",
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
        "manual_backend_export_required": True,
        "manual_export_cadence": "weekly",
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


XIAOHONGSHU_RECOVERY_PLAYBOOK: dict[str, Any] = {
    "diagnosis_date": "2026-08-14",
    "mode": "xiaohongshu_manual_recovery",
    "primary_goal": "restore stable distribution and save-driven follow conversion without automated publishing",
    "publish_boundary": "manual_handoff_only_hard_gate_no_automation_ever",
    "publishing_frequency": {
        "max_posts_first_7_days": 4,
        "min_gap_hours_between_posts": 36,
        "increase_cadence_only_after": "three completed 1h_24h_72h reviews without an account-health warning",
    },
    "content_lane": {
        "primary": "ai_efficiency_workflow_system",
        "formats": ["six_page_carousel", "checklist_note", "workflow_case"],
        "must_include": [
            "specific first-image payoff",
            "concrete example",
            "saveable checklist",
            "one natural discussion question",
        ],
        "forbidden": [
            "generic tool roundup",
            "pure decorative AI image as primary visual",
            "external traffic diversion",
        ],
    },
    "manual_post_publish_review": {
        "review_points_hours": [1, 24, 72],
        "metrics": [
            "impressions",
            "cover_click_through_rate",
            "average_view_seconds",
            "save_rate",
            "comment_rate",
            "profile_to_follow_conversion",
        ],
        "missing_data_policy": "record_unavailable_reason_and_do_not_increase_cadence",
    },
}


PLATFORM_GROWTH_RULES: dict[str, dict[str, Any]] = {
    "douyin": {
        # 2026-08-16 更新：收藏率取代完播率成 TOP1（196篇公众号文章提炼，platform_rules_2026.md）
        "primary_metric": "save_rate",
        "secondary_metrics": ["revisit_rate", "loyal_fan_interaction_rate", "three_second_view_rate", "quality_comment_rate", "completion_rate"],
        "rules": [
            "strong_first_motion",
            "lower_third_subtitles",
            "matched_real_footage",
            "single_best_candidate",
            "save_value_content_checklist",  # 收藏型干货（步骤/清单/模板/避坑）
            "save_guide_cta",               # 结尾"建议收藏"
            "original_declaration_check",   # 原创声明勾选 +20-40% 流量
            "open_comment_prompt",          # 有效评论引导（10字以上观点），禁封闭问答
            "seven_day_longtail_retention", # 7天长尾赛马，勿首日删视频
            "loyal_fan_first_hour_reply",   # 发布1小时黄金窗口回评
        ],
        "target_action": "save_or_comment",
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
            # 2026-08-16 更新（platform_rules_2026.md）
            "ai_generated_label_required",       # 用AI必须打AI标注，否则影响推荐权重
            "no_pure_ai_auto_creation",          # 非真人自动化创作违规（运营规范3.27）
            "tietu_500_char_condense",           # 贴图红利：长文浓缩500字+卡片图
            "tietu_emotional_resonance_topic",   # 贴图选题：现实共鸣话题
            "publish_peak_slots",                # 发布高峰早7-9/中12-14/晚20-23
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
        # 2026-08-16 更新：星云5.0 + 8月新规（AI内容2设置/同质化严查，platform_rules_2026.md）
        "primary_metric": "save_rate",
        "secondary_metrics": ["avg_stay_seconds", "comment_rate", "follow_conversion_rate", "click_through_rate"],
        "rules": [
            "authentic_cover",
            "pain_point_title",
            "use_case_keywords",
            "early_comment_reply",
            "manual_handoff_only_hard_gate",
            "first_image_specific_payoff",
            "saveable_checklist_required",
            "manual_1h_24h_72h_review",
            "ai_creator_identity_setting",   # 8月新规：职业身份设「AI创作者」
            "ai_content_secondary_creation", # AI内容必须二次创作（剪辑/配音/字幕/特效）
            "ai_content_declaration",        # AI内容必须声明
            "homogenization_semantic_dedup", # 同质化严查：语义去重禁批量洗稿
            "single_primary_keyword",        # 每篇只定一个主词
        ],
        "target_action": "save_or_comment",
        "xiaohongshu_growth_playbook": XIAOHONGSHU_RECOVERY_PLAYBOOK,
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
    "youtube": {
        "primary_metric": "average_watch_seconds",
        "secondary_metrics": ["completion_rate", "comment_rate", "follow_conversion_rate"],
        "rules": [
            "english_first_five_second_payoff",
            "one_clear_tutorial_or_demo_promise",
            "retention_chapters_or_pattern_interrupts",
            "manual_handoff_no_aitoearn",
            "unique_render_not_cross_platform_final_reuse",
        ],
        "target_action": "subscribe_or_comment",
    },
    "tiktok": {
        "primary_metric": "three_second_view_rate",
        "secondary_metrics": ["completion_rate", "comment_rate", "follow_conversion_rate"],
        "rules": [
            "native_english_short_hook",
            "single_micro_payoff",
            "platform_native_caption_and_tags",
            "manual_handoff_no_aitoearn",
            "unique_render_not_youtube_or_douyin_reuse",
        ],
        "target_action": "comment_or_follow",
    },
    "twitter": {
        "primary_metric": "engagement_rate",
        "secondary_metrics": ["reply_rate", "profile_click_rate", "follow_conversion_rate"],
        "rules": [
            "one_point_under_280",
            "specific_observation_not_link_dump",
            "one_question_or_clear_reply_prompt",
            "no_thread_spam_or_repeated_hooks",
        ],
        "target_action": "reply_or_profile_click",
    },
    "x": {
        "alias": "twitter",
    },
    "rednote": {
        "alias": "xiaohongshu",
    },
    # 2026-08-16：douyin 双账号变体映射到 douyin 规则（收藏率 TOP1 等 2026 规则自动生效）
    "douyin_ai": {
        "alias": "douyin",
    },
    "douyin_pet": {
        # 猫咪号专属：赞粉比 174:1 → 转粉是 P0，但收藏率/原创声明等 2026 规则仍生效
        "primary_metric": "follow_conversion_rate",
        "secondary_metrics": ["save_rate", "loyal_fan_interaction_rate", "three_second_view_rate", "completion_rate"],
        "rules": [
            "strong_first_motion",
            "lower_third_subtitles",
            "matched_real_footage",
            "single_best_candidate",
            "follow_reason_cta",            # 关注理由（系列化/每天一只猫）
            "series_collection_build",     # 合集功能（EP系列/追更动力）
            "save_value_content_checklist", # 科普内容收藏型干货
            "save_guide_cta",
            "original_declaration_check",
            "open_comment_prompt",
            "seven_day_longtail_retention",
            "loyal_fan_first_hour_reply",
        ],
        "target_action": "follow_or_save",
    },
    "wechat_official": {
        "alias": "wechat",
    },
    "weixin": {
        "alias": "wechat",
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


def _rate(numerator: float, denominator: float) -> float:
    return round(float(numerator or 0) / max(1.0, float(denominator or 0)), 4)


def _feedback_row(historical_feedback: dict[str, Any], platform: str) -> dict[str, Any]:
    platforms = historical_feedback.get("platforms") if isinstance(historical_feedback, dict) else {}
    if not isinstance(platforms, dict):
        return {}
    row = platforms.get(platform) or platforms.get("x" if platform == "twitter" else platform) or {}
    return row if isinstance(row, dict) else {}


def _data_driven_improvement_plan(platform: str, historical_feedback: dict[str, Any], is_video: bool) -> dict[str, Any]:
    row = _feedback_row(historical_feedback, platform)
    if not row:
        return {
            "status": "needs_metrics",
            "diagnosis": ["metrics_missing_or_untrusted"],
            "required_actions": ["collect_1h_24h_72h_metrics_before_confidence_boost"],
        }
    views = float(row.get("views", 0) or 0)
    engagement = float(row.get("engagement", 0) or 0)
    saves = float(row.get("saves", 0) or 0)
    follows = float(row.get("follows", 0) or 0)
    completion = float(row.get("completion_rate", 0) or 0)
    three_second = float(row.get("three_second_view_rate", 0) or 0)
    engagement_rate = _rate(engagement, views)
    save_rate = _rate(saves, views)
    follow_rate = _rate(follows, views)
    diagnosis: list[str] = []
    actions: list[str] = []
    if views > 0 and engagement_rate < 0.04:
        diagnosis.append("low_engagement_rate")
        actions.append("rebuild_title_cover_hook_and_comment_prompt")
    if views > 0 and save_rate < 0.02:
        diagnosis.append("low_save_rate")
        actions.append("increase_checklist_density_examples_and_embedded_knowledge_cards")
    if views > 0 and follow_rate < 0.005:
        diagnosis.append("low_follow_conversion")
        actions.append("make_series_promise_profile_follow_reason_and_next_episode_explicit")
    if is_video and completion and completion < 0.35:
        diagnosis.append("low_completion_rate")
        actions.append("tighten_pacing_scene_changes_and_midpoint_payoff_density")
    if is_video and three_second and three_second < 0.45:
        diagnosis.append("low_three_second_view_rate")
        actions.append("rewrite_first_second_motion_and_opening_sentence")
    if not diagnosis:
        diagnosis.append("no_major_growth_alarm")
        actions.append("keep_current_lane_and_test_one_variable_only")
    return {
        "status": "active",
        "diagnosis": diagnosis,
        "required_actions": list(dict.fromkeys(actions)),
        "metrics": {
            "views": views,
            "engagement_rate": engagement_rate,
            "save_rate": save_rate,
            "follow_rate": follow_rate,
            "completion_rate": completion,
            "three_second_view_rate": three_second,
        },
    }


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
        "data_driven_improvement_plan": _data_driven_improvement_plan(platform, historical_feedback, is_video),
    }
    if platform == "wechat" and isinstance(rules.get("wechat_growth_playbook"), dict):
        strategy["wechat_growth_playbook"] = rules["wechat_growth_playbook"]
    if platform == "xiaohongshu" and isinstance(rules.get("xiaohongshu_growth_playbook"), dict):
        strategy["xiaohongshu_growth_playbook"] = rules["xiaohongshu_growth_playbook"]
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
        if int(frequency.get("max_articles_per_week_recovery") or 0) > 3:
            failures.append("wechat_frequency.recovery_weekly_cap_too_high")
        if int(recovery.get("topic_dedup_window_days") or 0) < 14:
            failures.append("wechat_topic_dedup_window.too_short")
        if recovery.get("direction_dedup_required") is not True:
            failures.append("wechat_direction_dedup.required")
        post_review = playbook.get("post_publish_review") if isinstance(playbook.get("post_publish_review"), dict) else {}
        if post_review.get("manual_backend_export_required") is not True:
            failures.append("wechat_manual_backend_export.required")
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
    if _normalized_platform(platform) == "xiaohongshu":
        playbook = plan.get("xiaohongshu_growth_playbook") if isinstance(plan.get("xiaohongshu_growth_playbook"), dict) else {}
        frequency = playbook.get("publishing_frequency") if isinstance(playbook.get("publishing_frequency"), dict) else {}
        review = playbook.get("manual_post_publish_review") if isinstance(playbook.get("manual_post_publish_review"), dict) else {}
        if playbook.get("mode") != "xiaohongshu_manual_recovery":
            failures.append("xiaohongshu_growth_playbook.recovery_mode_missing")
        if playbook.get("publish_boundary") != "manual_handoff_only_hard_gate_no_automation_ever":
            failures.append("xiaohongshu_publish_boundary.not_manual_handoff_only")
        if int(frequency.get("max_posts_first_7_days") or 0) > 4:
            failures.append("xiaohongshu_frequency.recovery_cap_too_high")
        if int(frequency.get("min_gap_hours_between_posts") or 0) < 36:
            failures.append("xiaohongshu_frequency.min_gap_too_short")
        if review.get("review_points_hours") != [1, 24, 72]:
            failures.append("xiaohongshu_review_schedule.invalid")
    return {
        "passed": not failures,
        "failures": failures,
        "policy_id": GROWTH_POLICY_ID,
    }
