"""Cross-platform publish-boundary and growth-policy regression tests."""

from content_platform.content_policy import is_manual_handoff_platform
from content_platform.growth_policy import build_growth_strategy, validate_growth_strategy


def test_manual_handoff_platforms_include_current_video_handoff_channels():
    for platform in ["bilibili", "douyin", "shipinhao", "tiktok", "youtube", "xiaohongshu"]:
        assert is_manual_handoff_platform(platform), platform


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
