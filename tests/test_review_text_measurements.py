import json

from content_platform.native_quality_runner import TEXT_MEASURED_PARTS, _text_measurements


def test_review_gets_code_measured_counts_of_the_reader_facing_text():
    # MED90 (owner 11-13): length/table/image evidence comes from code, so the verdict does not depend on the model.
    markdown = "## 标题\n\n正文共八个字啊。\n\n| a | b |\n| — | — |\n| 1 | 2 |\n\n![图](x.png)\n"
    row = _text_measurements(json.dumps({"kind": "article", "title": "t", "markdown": markdown}, ensure_ascii=False).encode())
    assert row["measured_field"] == "markdown"
    assert row["cjk_characters"] == 10
    assert row["markdown_table_separator_rows"] == 1 and row["nonstandard_table_separator_rows"] == 1
    assert row["markdown_image_links"] == 1
    assert _text_measurements("plain 文本".encode())["measured_field"] == "raw_text"
    assert {"publication_copy", "body", "title"} <= TEXT_MEASURED_PARTS
