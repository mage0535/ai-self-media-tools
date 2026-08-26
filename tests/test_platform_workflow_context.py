from pathlib import Path

from content_platform.content_policy import delivery_mode
from content_platform.platform_workflow_context import load_platform_workflow_context


def test_platform_workflow_context_loads_rules_strategy_skills_and_publish_mode():
    platforms = ["kuaishou", "tiktok", "youtube", "douyin_ai", "xiaohongshu", "wechat", "bilibili", "shipinhao", "x"]
    for platform in platforms:
        context = load_platform_workflow_context(platform)
        assert context["loaded"] is True
        assert context["platform"] == platform
        assert context["rulebook"]["entry_loaded"] is True
        assert context["platform_rules_2026"]["matched"] is True
        assert Path(context["strategy"]["path"]).is_file()
        assert all(item["exists"] for item in context["skills"])
        assert context["content_quality_reference_pack"]["loaded"] is True
        assert context["content_quality_reference_pack"]["sha256"]
        assert context["content_quality_reference_pack"]["hook_title_gate"]
        assert context["runtime_capabilities"]["version"] == "runtime_capabilities_v1"
        assert "tools" in context["runtime_capabilities"]
        assert "content_quality_reference_pack" in context["selected_tools"]
        assert context["selected_tools"]
        assert context["publish_mode"] == delivery_mode(platform)


def test_existing_content_skills_are_routed_by_format_instead_of_orphaned():
    from content_platform.preflight_manifest import required_workflow_skills

    article = set(required_workflow_skills("juejin"))
    video = set(required_workflow_skills("douyin_ai"))

    assert {"content/content-copywriting-style", "content/content-seo-toolset", "content/content-open-notebook", "content/content-github-star-explorer"} <= article
    assert {"content/content-copywriting-style", "content/content-voice-engine", "content/content-ai-autoclip", "content/content-github-star-explorer"} <= video
