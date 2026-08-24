from content_platform.content_hygiene import validate_generated_text


def test_generated_text_rejects_scraped_page_script():
    result = validate_generated_text("稀土掘金 (function () { var options = { bdms: { aid: 26 } }) 为什么工具好用")
    assert result["passed"] is False
    assert result["reason"] == "source_page_code_contamination"


def test_generated_text_allows_normal_markdown_code_tutorial():
    result = validate_generated_text("# 教程\n\n```python\nprint('ok')\n```\n解释这段代码的作用。")
    assert result["passed"] is True


def test_rejects_platform_navigation_contamination():
    result = validate_generated_text("稀土掘金 首页 沸点 课程 APP 搜索历史 清空 创作者中心 写文章 发沸点 写笔记 写代码 草稿\n\n正文")
    assert result["passed"] is False
    assert result["reason"] == "source_page_navigation_contamination"
