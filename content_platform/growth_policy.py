"""Growth-oriented strategy and validation helpers for channel packets."""

from __future__ import annotations

from typing import Any


GROWTH_POLICY_ID = "growth_quality_policy_v1"

VIDEO_CONTENT_HINTS = {"video", "short", "repost", "microcase"}

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
            "wechat_editorial_frequency_control",
            "columnized_personal_ip_mix",
            "title_keyword_first_15_chars",
            "title_template_fatigue_limit",
            "first_200_chars_reader_payoff",
            "every_300_chars_retention_hook",
            "comment_backend_reply_and_share_cta",
            "wechat_search_seo_layout",
            "cross_platform_follow_funnel",
            "manual_backend_metrics_review_when_api_unavailable",
        ],
        "target_action": "read_to_follow",
        "wechat_growth_playbook": {
            "diagnosis_date": "2026-08-04",
            "account_status": {
                "certified": True,
                "comments_enabled": True,
                "advanced_data_api": "unavailable_or_unauthorized",
                "manual_backend_export_required": True,
            },
            "primary_goal": "increase_read_to_follow_rate_without_sacrificing_finish_read_or_save_rate",
            "publishing_frequency": {
                "recommended_articles_per_week": "3-4",
                "max_articles_per_day": 1,
                "avoid_three_articles_per_day_batching": True,
            },
            "content_mix": {
                "personal_practice_story": 0.30,
                "opinion_or_trend_interpretation": 0.25,
                "github_or_tool_selection": 0.30,
                "interactive_qa_or_weekly_recap": 0.15,
            },
            "columns": [
                {"name": "AI说人话", "role": "opinion_or_trend_interpretation", "recommended_day": "monday"},
                {"name": "我的AI工作台", "role": "personal_practice_story", "recommended_day": "wednesday"},
                {"name": "GitHub/工具精选", "role": "github_or_tool_selection", "recommended_day": "friday"},
                {"name": "马吉克周记/你问我答", "role": "interactive_qa_or_weekly_recap", "recommended_day": "sunday_or_month_end"},
            ],
            "github_selection_policy": {
                "default_mode": "weekly_bundle",
                "bundle_rule": "one_ai_project_plus_one_non_ai_project_per_week",
                "extra_issue_allowed_only_when": "current_ops_strategy_has_strong_trend_or_account_data_evidence",
            },
            "title_rules": {
                "max_chars": 28,
                "keyword_first_chars": 15,
                "must_include_one": ["pain", "result", "loss_avoidance", "specific_scenario", "contrast"],
                "template_fatigue_limit": "same_title_frame_not_more_than_once_in_7_days",
                "avoid_repeated_frames": ["实测", "试了", "值得试试"],
            },
            "article_structure": {
                "first_200_chars": "state the reader pain, result promise, and why this matters now",
                "retention_hook_interval_chars": 300,
                "must_include": ["real_case", "specific_steps", "failure_or_boundary", "saveable_checklist", "natural_follow_reason"],
            },
            "seo_geo": {
                "primary_keywords": ["AI效率工具", "AI自动化", "开源项目", "GitHub精选", "AI工作流"],
                "placement": ["title_first_15_chars", "digest", "first_200_chars", "section_headings"],
            },
            "interaction_conversion": {
                "backend_reply_keywords": ["工具箱", "清单", "GitHub", "自动化"],
                "comment_prompt": "ask one concrete experience question tied to the article scenario",
                "share_prompt": "state the colleague or operator who should read it",
                "cross_platform_funnel": "short_video_and_answer_channels_point_to_wechat_keyword_reply",
            },
            "post_publish_review": {
                "review_cadence": "weekly",
                "required_metrics": ["impressions", "open_rate", "finish_read_rate", "share_rate", "save_rate", "comment_rate", "new_follows", "read_to_follow_rate"],
                "api_unavailable_policy": "record_48001_or_backend_unavailable_reason_and_use_manual_export",
            },
        },
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
    return {
        "passed": not failures,
        "failures": failures,
        "policy_id": GROWTH_POLICY_ID,
    }
