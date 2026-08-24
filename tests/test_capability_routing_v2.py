from content_platform.capability_router import load_registry, match_capabilities
from content_platform.content_profile import classify_content_profile


def test_profile_keeps_tech_domain_when_visual_treatment_is_cinematic():
    profile = classify_content_profile("电影感 AI 工具教程，展示真实效率提升", "douyin_ai", "short_video")
    assert profile["content_domain"] == "tech"
    assert profile["visual_treatment"] == "cinematic"
    assert profile["content_format"] == "short_video"


def test_router_separates_consulted_and_executed_and_rejects_unverified():
    profile = classify_content_profile("电影感 AI 工具教程", "douyin_ai", "short_video")
    result = match_capabilities(profile, load_registry())
    assert all(item["status"] == "consulted" for item in result["consulted"])
    assert all(item.get("license") != "unverified" for item in result["executed"])
    assert all(item.get("status") != "executed" for item in result["skipped"])


def test_runtime_enabled_mcp_namespaces_are_inventoryable(monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_MCP_SERVERS", "gbrain,anysearch")
    registry = load_registry("douyin_ai")
    ids = {item["id"] for item in registry["capabilities"]}
    assert "mcp:gbrain" in ids
    assert "mcp:anysearch" in ids
