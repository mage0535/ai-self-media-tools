from content_platform.intelligence import _plain, collect_reference_posts


def test_plain_text_removes_script_and_style_payloads():
    result = _plain("<script>function () { var options = {bdms: true}</script><style>.x{}</style><p>真实正文</p>")
    assert result == "真实正文"
    assert "bdms" not in result


def test_plain_text_removes_juejin_navigation_prefix():
    result = _plain("稀土掘金 首页 沸点 课程 APP 搜索历史 清空 创作者中心 写文章 发沸点 写笔记 写代码 草稿 正文标题")
    assert result == "正文标题"


def test_reference_posts_are_cleaned_before_prompt_compilation():
    rows = collect_reference_posts({"reference_posts": [{"title": "标题", "body": "首页 沸点 课程 APP 搜索历史 清空 创作者中心 写文章 发沸点 写笔记 写代码 草稿 正文"}]})
    assert rows[0]["body"] == "正文"


def test_non_content_source_field_is_not_used_as_reference_post(tmp_path):
    import json
    cache = tmp_path / "trending_2026-01-01.json"
    cache.write_text(json.dumps({"trends": [{"title": "后台", "source": "https://juejin.cn/creator/content", "url": ""}]}, ensure_ascii=False), encoding="utf-8")
    rows = collect_reference_posts({"keywords": ["AI"], "trend_cache_dir": str(tmp_path)})
    assert rows == []
