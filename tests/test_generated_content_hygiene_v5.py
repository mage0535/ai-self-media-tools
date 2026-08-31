from content_platform.content_hygiene import validate_generated_text


def test_generated_text_rejects_scraped_page_script():
    result = validate_generated_text("稀土掘金 (function () { var options = { bdms: { aid: 26 } }) 为什么工具好用")
    assert result["passed"] is False
    assert result["reason"] == "source_page_code_contamination"


def test_generated_text_allows_normal_markdown_code_tutorial():
    result = validate_generated_text(
        "# 教程\n\n这里的 `print(\"ok\")` 会输出一行文本。\n\n"
        "```python\nmessage = \"quoted value\"\nprint(message)\n```\n\n"
        "- 保留代码中的引号\n- 保留列表结构"
    )
    assert result["passed"] is True


def test_rejects_platform_navigation_contamination():
    result = validate_generated_text("稀土掘金 首页 沸点 课程 APP 搜索历史 清空 创作者中心 写文章 发沸点 写笔记 写代码 草稿\n\n正文")
    assert result["passed"] is False
    assert result["reason"] == "source_page_navigation_contamination"


def test_xhs_repeated_cta_is_rejected():
    result = validate_generated_text(
        "Check the topic and source evidence before generating. "
        "Please save and follow for more. Please save and follow for more."
    )
    assert result["passed"] is False
    assert "repeated_sentence" in result["reasons"]


def test_youtube_dangling_article_fragment_is_rejected():
    result = validate_generated_text(
        "The workflow can collect evidence and draft a weekly plan. "
        "It still needs a final content gate. If it cannot plan a."
    )

    assert result["passed"] is False
    assert "sentence_fragment" in result["reasons"]


def test_wechat_malformed_mixed_quotes_are_rejected():
    result = validate_generated_text("团队把这一步称为“最终验收\"，但正文仍然进入了发布队列。")

    assert result["passed"] is False
    assert "malformed_quotes" in result["reasons"]


def test_truncated_chinese_and_english_terminal_sentences_are_rejected():
    chinese = validate_generated_text("先验证素材来源，再检查成品是否满足发布要求")
    english = validate_generated_text("Validate the source evidence before the final automated release")

    assert "truncated_terminal_sentence" in chinese["reasons"]
    assert "truncated_terminal_sentence" in english["reasons"]


def test_repeated_paragraph_and_duplicated_conclusion_are_rejected():
    paragraph = "This concrete review step verifies the title, cover, and delivery evidence."
    repeated = validate_generated_text(f"{paragraph}\n\n{paragraph}\n\nA different conclusion follows.")
    conclusion = validate_generated_text(
        "The evidence must be checked before release.\n\n"
        "## Conclusion\n\nDo not automate the final release without verified evidence.\n\n"
        "## Final takeaway\n\nDo not automate the final release without verified evidence."
    )

    assert "repeated_paragraph" in repeated["reasons"]
    assert "duplicated_conclusion" in conclusion["reasons"]


def test_balanced_quotes_and_terminal_code_block_remain_valid():
    result = validate_generated_text(
        "# Review\n\nThe operator said \"verify first\", and the reviewer agreed.\n\n"
        "```json\n{\"status\": \"passed\", \"message\": \"keep quotes intact\"}\n```"
    )

    assert result["passed"] is True
