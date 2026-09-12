from content_platform.content_hygiene import complete_known_terminal_cta, normalize_generated_markdown, validate_generated_text


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


def test_markdown_normalizer_repairs_model_damaged_fences_and_identifiers():
    damaged = (
        "先看结构： ```yaml\n,\nname: api-review\n,\n``` 接着创建目录：\n"
        "├── .\nagent/\n└── packageon。\n"
    )

    repaired = normalize_generated_markdown(damaged)

    assert "：\n```yaml" in repaired
    assert "\n,\n" not in repaired
    assert ".agent/" in repaired
    assert "package.json" in repaired
    assert validate_generated_text(repaired)["passed"] is True


def test_markdown_normalizer_repairs_filename_after_chinese_text():
    repaired = normalize_generated_markdown("目录里至少包含一个SKILL.\nmd文件。")

    assert "SKILL.md文件" in repaired
    assert "SKILL.\nmd" not in repaired


def test_markdown_normalizer_repairs_unicode_yaml_delimiters_and_split_list_numbers():
    damaged = "```yaml\n—\nname: demo\n— # 说明\n1.\n查看文件\n2.\n核对结果\n```"

    repaired = normalize_generated_markdown(damaged)

    assert "```yaml\n---\nname: demo\n---\n# 说明" in repaired
    assert "1. 查看文件" in repaired
    assert "2. 核对结果" in repaired


def test_markdown_normalizer_splits_h2_heading_from_attached_opening_sentence():
    damaged = (
        "## 什么是 Agent Skill：一个目录，一份说明 先建立一个最朴素的认知。\n"
        "## 为什么要渐进式加载：需要时才展开细节 很多人担心能力写多了会让 Agent 变笨。"
    )

    repaired = normalize_generated_markdown(damaged)

    assert "## 什么是 Agent Skill：一个目录，一份说明\n先建立一个最朴素的认知。" in repaired
    assert "## 为什么要渐进式加载：需要时才展开细节\n很多人担心能力写多了会让 Agent 变笨。" in repaired


def test_markdown_normalizer_removes_only_unmatched_straight_quote_from_prose():
    damaged = '## 原理\n先读取 description"，再按需加载正文。\n\n```python\nprint("keep me")\n```'

    repaired = normalize_generated_markdown(damaged)

    assert 'description"' not in repaired
    assert 'print("keep me")' in repaired
    assert validate_generated_text(repaired)["passed"] is True


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


def test_chinese_classifier_ellipsis_is_not_confused_with_a_fragment():
    valid = validate_generated_text("先跑顺一个，再做下一个。")
    invalid = validate_generated_text("这只是一个。")

    assert valid["passed"] is True
    assert "sentence_fragment" in invalid["reasons"]


def test_wechat_malformed_mixed_quotes_are_rejected():
    result = validate_generated_text("团队把这一步称为“最终验收\"，但正文仍然进入了发布队列。")

    assert result["passed"] is False
    assert "malformed_quotes" in result["reasons"]


def test_truncated_chinese_and_english_terminal_sentences_are_rejected():
    chinese = validate_generated_text("先验证素材来源，再检查成品是否满足发布要求")
    english = validate_generated_text("Validate the source evidence before the final automated release")

    assert "truncated_terminal_sentence" in chinese["reasons"]
    assert "truncated_terminal_sentence" in english["reasons"]


def test_known_terminal_cta_is_completed_without_masking_arbitrary_truncation():
    repaired = complete_known_terminal_cta("Check the result.\n\nSave this")
    untouched = complete_known_terminal_cta("Check the result.\n\nThis explanation still needs")

    assert repaired.endswith("Save this.")
    assert validate_generated_text(repaired)["passed"] is True
    assert untouched.endswith("still needs")
    assert validate_generated_text(untouched)["passed"] is False


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


def test_normalize_generated_markdown_repairs_split_technical_filenames() -> None:
    text = "先检查 CLAUDE.\nmd，再把 SKILL.\n\nmd 放进项目；不要改普通句子。"

    normalized = normalize_generated_markdown(text)

    assert "CLAUDE.md" in normalized
    assert "SKILL.md" in normalized
    assert "不要改普通句子" in normalized


def test_normalize_generated_markdown_closes_one_unclosed_code_fence() -> None:
    normalized = normalize_generated_markdown("步骤如下：\n```yaml\nname: my-skill")

    assert normalized.count("```") == 2
    assert normalized.endswith("```")


def test_normalize_generated_markdown_removes_empty_media_and_repairs_common_damage() -> None:
    text = (
        "!\n[]()\n\n![]()\n\n"
        "| 维度 | Prompt | Skill |\n|:, |:, |:, |\n"
        "skill_registry.\nfind(user_request)"
    )

    normalized = normalize_generated_markdown(text)

    assert "![]()" not in normalized
    assert "[]()" not in normalized
    assert "\n!\n" not in f"\n{normalized}\n"
    assert "|---|---|---|" in normalized.replace(" ", "")
    assert "skill_registry.find(user_request)" in normalized
