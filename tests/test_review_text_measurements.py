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


def test_review_is_told_where_the_publisher_puts_each_section_image(tmp_path):
    # MED90: pictures are inserted at draft creation, so the reviewed copy has none; code states the layout.
    from content_platform.native_quality_runner import _delivery_image_layout

    for name in ("section-01.png", "section-02.png"):
        (tmp_path / name).write_bytes(name.encode())
    (tmp_path / "section_image_map.json").write_text(json.dumps([
        {"section": "先看证据", "image": str(tmp_path / "section-01.png")},
        {"section": "不存在的标题", "image": str(tmp_path / "section-02.png")}], ensure_ascii=False), encoding="utf-8")
    copy = tmp_path / "copy.txt"
    copy.write_text(json.dumps({"markdown": "## 先看证据\n\n正文"}, ensure_ascii=False), encoding="utf-8")
    parts = {"publication_copy": [{"path": str(copy), "sha256": "c"}],
             "images": [{"path": str(tmp_path / "section-01.png"), "sha256": "s1"},
                        {"path": str(tmp_path / "section-02.png"), "sha256": "s2"}]}
    layout = _delivery_image_layout(parts)
    assert [row["heading_found_in_publication_copy"] for row in layout["placements"]] == [True, False]
    assert [row["image_sha256"] for row in layout["placements"]] == ["s1", "s2"]
    assert layout["all_placeable"] is False
    assert _delivery_image_layout({"publication_copy": parts["publication_copy"]}) is None
