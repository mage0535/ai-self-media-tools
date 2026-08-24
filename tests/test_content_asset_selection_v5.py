from content_platform.content_assets import select_content_asset_ids


def test_content_asset_selection_varies_by_topic_deterministically():
    assets = {
        "hooks": {"title": [{"id": "h1"}, {"id": "h2"}, {"id": "h3"}], "opening": [], "ending": []},
        "structures": {"structures": ["s1", "s2", "s3"]},
        "formulas": {"formulas": ["f1", "f2", "f3"]},
    }
    first = select_content_asset_ids({"content_format": "short_video", "platform": "kuaishou", "topic": "AI工具自动化"}, assets)
    second = select_content_asset_ids({"content_format": "short_video", "platform": "kuaishou", "topic": "会议纪要效率"}, assets)
    assert first["hook_ids"][0] in {"h1", "h2", "h3"}
    assert second["hook_ids"][0] in {"h1", "h2", "h3"}
    assert first != second
