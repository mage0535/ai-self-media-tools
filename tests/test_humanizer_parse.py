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
