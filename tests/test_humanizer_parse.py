from content_platform.humanizer import humanize_text

BODY = "此外，这一点至关重要。\n\n## 小节\n\n正文。"


def test_reply_with_raw_newlines_and_surrounding_text_is_parsed():
    reply = '好的，结果如下：\n{"title": "新标题", "body": "第一段\n\n## 小节\n\n正文。", "changes": [], "score": 40}\n以上。'
    result = humanize_text("标题", BODY, llm_call=lambda prompt, system: reply)
    assert result["ok"] is True
    assert result["body"] == "第一段\n\n## 小节\n\n正文。"


def test_unparseable_reply_reports_the_reason_and_keeps_the_original():
    result = humanize_text("标题", BODY, llm_call=lambda prompt, system: "not json")
    assert result["ok"] is False and result["body"] == BODY
    assert result["error"].startswith("failed to parse LLM response: ")


def test_failed_hermes_call_reports_exit_code_and_stderr(monkeypatch, tmp_path):
    fake = tmp_path / "hermes"
    fake.write_text("#!/bin/sh\necho 'provider unavailable' >&2\nexit 3\n")
    fake.chmod(0o755)
    monkeypatch.setenv("HERMES_COMMAND", str(fake))
    monkeypatch.delenv("CONTENT_PLATFORM_NO_MODEL_CALLS", raising=False)
    result = humanize_text("标题", BODY)
    assert result["ok"] is False
    assert "rc=3" in result["error"] and "provider unavailable" in result["error"]
