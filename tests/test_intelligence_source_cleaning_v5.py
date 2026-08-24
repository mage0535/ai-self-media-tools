from content_platform.intelligence import _plain


def test_plain_text_removes_script_and_style_payloads():
    result = _plain("<script>function () { var options = {bdms: true}</script><style>.x{}</style><p>真实正文</p>")
    assert result == "真实正文"
    assert "bdms" not in result
