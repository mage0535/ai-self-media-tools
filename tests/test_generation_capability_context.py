from content_platform.capability_context import build_generation_capability_context


def test_capability_context_is_ready_before_model_generation():
    result = build_generation_capability_context(
        "douyin_ai",
        {"content_form": "short_video", "topic": "电影感 AI 工具教程"},
    )
    assert result["profile"]["content_domain"] == "tech"
    assert result["profile"]["visual_treatment"] == "cinematic"
    assert result["capability_plan"]["version"] == "capability_plan_v1"
    assert result["ready_for_generation"] is True
