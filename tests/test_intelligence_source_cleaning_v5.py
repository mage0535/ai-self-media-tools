from content_platform.intelligence import _plain


def test_plain_text_removes_script_and_style_payloads():
    result = _plain("<script>function () { var options = {bdms: true}</script><style>.x{}</style><p>真实正文</p>")
    assert result == "真实正文"
    assert "bdms" not in result


def test_plain_text_removes_juejin_navigation_prefix():
    result = _plain("稀土掘金 首页 沸点 课程 APP 搜索历史 清空 创作者中心 写文章 发沸点 写笔记 写代码 草稿 正文标题")
    assert result == "正文标题"
