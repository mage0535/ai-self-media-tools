"""Cross-platform publish-boundary and growth-policy regression tests."""

from content_platform.content_policy import (
    AUTO_PUBLISH_PLATFORMS,
    delivery_mode,
    is_auto_publish_platform,
    is_douyin_platform,
    is_manual_handoff_platform,
    is_short_video_platform,
    platform_region,
)
from content_platform.growth_policy import build_growth_strategy, validate_growth_strategy


def test_manual_handoff_platforms_include_current_video_handoff_channels():
    for platform in ["bilibili", "douyin", "douyin_pet", "douyin_ai", "shipinhao", "tiktok", "youtube", "xiaohongshu"]:
        assert is_manual_handoff_platform(platform), platform


def test_douyin_account_variants_normalize_to_douyin_boundaries():
    for platform in ["douyin_pet", "douyin_ai"]:
        assert platform_region(platform) == "domestic"
        assert is_short_video_platform(platform)
        assert is_douyin_platform(platform)
        assert is_manual_handoff_platform(platform)


def test_only_configured_five_channel_family_can_auto_publish():
    expected = {
        "kuaishou": "automatic_scheduled",
        "zhihu": "draft_box",
        "juejin": "draft_box",
        "wechat": "draft_box",
        "twitter": "direct_publish",
        "x": "direct_publish",
    }
    for platform, mode in expected.items():
        assert is_auto_publish_platform(platform), platform
        assert delivery_mode(platform) == mode
    assert AUTO_PUBLISH_PLATFORMS == {
        "kuaishou", "zhihu", "juejin", "wechat", "wechat_official", "weixin", "twitter", "x"
    }


def test_all_ai_restricted_channels_are_manual_handoff_only():
    for platform in ["bilibili", "douyin", "douyin_ai", "douyin_pet", "shipinhao", "xiaohongshu", "youtube", "tiktok"]:
        assert delivery_mode(platform) == "manual_handoff", platform
        assert not is_auto_publish_platform(platform)


def test_unknown_channel_is_not_implicitly_publishable():
    assert delivery_mode("new_platform") == "unsupported"
    assert not is_auto_publish_platform("new_platform")


def test_international_video_growth_rules_are_platform_specific():
    youtube = build_growth_strategy(["youtube"], "short_video", {"platforms": {"youtube": {"views": 100}}})
    tiktok = build_growth_strategy(["tiktok"], "short_video", {"platforms": {"tiktok": {"views": 100}}})

    assert youtube["platform"] == "youtube"
    assert tiktok["platform"] == "tiktok"
    assert "manual_handoff_no_aitoearn" in youtube["platform_growth_rules"]
    assert "manual_handoff_no_aitoearn" in tiktok["platform_growth_rules"]
    assert youtube["primary_metric"] == "average_watch_seconds"
    assert tiktok["primary_metric"] == "three_second_view_rate"


def test_x_alias_uses_twitter_growth_policy():
    plan = build_growth_strategy(["x"], "short_post", {"platforms": {"twitter": {"views": 100}}})

    assert plan["platform"] == "twitter"
    assert "specific_observation_not_link_dump" in plan["platform_growth_rules"]
    assert validate_growth_strategy(plan, "twitter", "short_post")["passed"] is True


def test_growth_strategy_turns_low_rates_into_required_actions():
    plan = build_growth_strategy(
        ["youtube"],
        "short_video",
        {"platforms": {"youtube": {"views": 10000, "engagement": 0, "saves": 0, "follows": 1}}},
    )

    improvement = plan["data_driven_improvement_plan"]
    assert "low_engagement_rate" in improvement["diagnosis"]
    assert "low_save_rate" in improvement["diagnosis"]
    assert "low_follow_conversion" in improvement["diagnosis"]
    assert "rebuild_title_cover_hook_and_comment_prompt" in improvement["required_actions"]
    assert "increase_checklist_density_examples_and_embedded_knowledge_cards" in improvement["required_actions"]


def test_growth_strategy_requires_metrics_when_history_is_missing():
    plan = build_growth_strategy(["twitter"], "short_post", {})

    improvement = plan["data_driven_improvement_plan"]
    assert improvement["status"] == "needs_metrics"
    assert "collect_1h_24h_72h_metrics_before_confidence_boost" in improvement["required_actions"]
