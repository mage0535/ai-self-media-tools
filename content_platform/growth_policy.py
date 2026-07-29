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
        "secondary_metrics": ["finish_read_rate", "save_rate", "share_rate"],
        "rules": ["title_open_rate", "first_screen_payoff", "section_value_density", "search_keyword_fit"],
        "target_action": "open_and_save",
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
    return {
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
        "historical_feedback_status": "available" if historical_feedback else "missing_or_empty",
        "historical_feedback_summary": historical_feedback,
    }


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

