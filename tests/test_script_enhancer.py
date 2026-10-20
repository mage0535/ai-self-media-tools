from __future__ import annotations

import pytest


def test_enhance_screencast_call_keeps_legacy_fields_and_adds_prompt_receipt():
    from scripts.script_enhancer import enhance_screencast_call

    result = enhance_screencast_call("5个免费AI工具提升编码效率", "youtube_shorts")

    assert result["type"] in {"tutorial", "demo", "cicd"}
    assert result["title"]
    assert result["content"]
    assert result["prompt_bundle_fingerprint"]
    assert result["quality_contract"]["aspect_ratio"] == "9:16"
    assert result["quality_contract"]["duration_required"] is True


def test_enhance_screencast_call_fails_closed_for_unknown_platform():
    from scripts.script_enhancer import enhance_screencast_call

    with pytest.raises(ValueError, match="unsupported video platform"):
        enhance_screencast_call("AI workflow", "not-a-platform")
