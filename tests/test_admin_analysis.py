from unittest.mock import patch

from content_platform.admin_analysis import platform_llm_analysis


def test_platform_llm_analysis_uses_fallback_unless_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-that-must-not-be-used")
    payload = {"bindings": [], "latest_works": [], "stats": {}}

    with patch("content_platform.admin_analysis.urllib.request.urlopen") as call:
        result = platform_llm_analysis({}, payload)

    assert result["provider"] == "fallback"
    call.assert_not_called()
