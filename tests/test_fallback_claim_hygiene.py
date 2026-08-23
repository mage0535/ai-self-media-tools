from content_platform.generator import DraftGenerator


def test_fallback_draft_does_not_copy_internal_platform_thresholds():
    draft = DraftGenerator({"allow_fallback": True}).generate(
        "AI会议纪要证据链", {"platforms": ["douyin_ai"], "automated_workflow": False}
    )
    assert "5%" not in draft["body"]
    assert "平台规则:" not in draft["body"]
