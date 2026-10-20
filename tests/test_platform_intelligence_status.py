from content_platform.platform_intelligence_status import (
    load_platform_intelligence_status,
    platform_intelligence_generation_constraints,
)


def test_all_real_world_ai_platforms_have_a_fail_closed_status_contract():
    status = load_platform_intelligence_status()
    assert set(status["platforms"]) == {
        "douyin_ai", "kuaishou", "shipinhao", "wechat", "juejin", "zhihu",
        "bilibili", "tiktok", "youtube", "twitter", "threads", "bluesky",
        "mastodon", "nostr", "devto", "telegraph", "writeas", "buttondown",
    }
    assert status["policy_revision"] == "2026-09-16-universal-ai-lane-r2"
    for platform, entry in status["platforms"].items():
        assert entry["capabilities"].keys() == {
            "topic_discovery", "work_level_metrics", "deep_content_analysis", "automated_learning"
        }
        assert entry["capabilities"]["automated_learning"]["enabled"] is False


def test_zhihu_constraints_forbid_body_level_and_viral_claims_without_verified_body():
    constraints = platform_intelligence_generation_constraints("zhihu")
    assert constraints["allow_viral_claims"] is False
    assert constraints["allow_visual_cta_pattern_claims"] is False
    assert "body_or_native_page_verification_missing" in constraints["required_disclaimers"]


def test_unknown_platform_is_fail_closed():
    constraints = platform_intelligence_generation_constraints("unknown_platform")
    assert constraints["generation_only"] is True
    assert constraints["allow_topic_signals"] is False
    assert constraints["allow_viral_claims"] is False
