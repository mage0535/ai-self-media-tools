from content_platform.capability_context import build_generation_capability_context


def test_capability_context_is_ready_before_model_generation():
    result = build_generation_capability_context(
        "douyin_ai",
        {"content_form": "short_video", "topic": "电影感 AI 工具教程"},
    )
    assert result["profile"]["content_domain"] == "tech"
    assert result["profile"]["visual_treatment"] == "cinematic"
    assert result["capability_plan"]["version"] == "capability_plan_v2"
    assert "tts" in result["capability_plan"]["tool_group_names"]
    assert result["tool_selection"]["tool_selection_plan"]["selected_tools"]
    assert result["compiled_skill_rules"]["version"] == "compiled_skill_rules_v1"
    assert all("/" not in item["source"] or not item["source"].startswith("/") for item in result["compiled_skill_rules"]["rules"])
    assert result["compiled_skill_rules"]["content_assets"]["selected"]["structure_id"]
    assert result["compiled_skill_rules"]["content_assets"]["selected"]["formula_id"]
    assert result["ready_for_generation"] is True
