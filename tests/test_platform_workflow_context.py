from pathlib import Path

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
        assert context["selected_tools"]
