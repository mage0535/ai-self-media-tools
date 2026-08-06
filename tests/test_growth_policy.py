from content_platform.growth_policy import build_growth_strategy


def test_empty_historical_feedback_is_not_marked_available():
    strategy = build_growth_strategy(
        ["tiktok"],
        "short_video",
        {"platforms": {}, "clusters": []},
    )

    assert strategy["historical_feedback_status"] == "missing_or_empty"


def test_non_empty_historical_feedback_is_marked_available():
    strategy = build_growth_strategy(
        ["tiktok"],
        "short_video",
        {"platforms": {"tiktok": {"views": 120, "likes": 8}}, "clusters": []},
    )

    assert strategy["historical_feedback_status"] == "available"
