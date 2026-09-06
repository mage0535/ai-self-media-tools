from content_platform.illustrator import GuizangIllustrator


def test_illustration_labels_exclude_file_extensions_and_ordinal_fragments() -> None:
    illustrator = GuizangIllustrator()

    labels = illustrator._extract_labels(
        "第一：创建 SKILL.md。第二：把 Agent Skills 操作手册接入标准操作流程。",
        "pipeline",
    )

    assert "md" not in {label.casefold() for label in labels}
    assert "第一" not in labels
    assert "第二" not in labels
    assert any(label in labels for label in ("操作手册", "标准操作流程"))
