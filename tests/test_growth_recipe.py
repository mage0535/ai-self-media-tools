from content_platform.growth_recipe import build_growth_recipe, derive_topic_growth_signals, validate_growth_recipe


def test_tool_demo_recipe_requires_real_process_evidence():
    recipe = build_growth_recipe(
        platform="douyin",
        content_form="tool_demo_video",
        source_matrix={"attempted_sources": [{"source": "douyin", "status": "success"}]},
        topic_decision={"growth_signals": ["conflict", "user_benefit"], "score": 0.84},
        tool_selection_plan={"selected_tools": ["screencast", "shotcraft_moves"]},
    )

    result = validate_growth_recipe(recipe)
    assert not result["passed"]
    assert "process_evidence" in result["failures"]


def test_tool_demo_recipe_passes_with_real_process_evidence_and_concrete_cta():
    recipe = build_growth_recipe(
        platform="tiktok",
        content_form="tool_demo_video",
        source_matrix={"attempted_sources": [{"source": "tiktok", "status": "success"}]},
        topic_decision={"growth_signals": ["conflict", "user_benefit", "interaction"], "score": 0.9},
        tool_selection_plan={"selected_tools": ["screencast", "shotcraft_moves"]},
        process_evidence={"screenshots": ["step-1.png"], "tool_names": ["Example Tool"], "limitations": ["requires sign in"]},
        cta={"deliverable": "comment keyword for the tool list", "question": "Which workflow wastes the most time?"},
    )

    assert validate_growth_recipe(recipe)["passed"]


def test_recipe_accepts_unavailable_sources_without_turning_them_into_fake_success():
    recipe = build_growth_recipe(
        platform="xiaohongshu",
        content_form="carousel",
        source_matrix={"attempted_sources": [{"source": "xiaohongshu", "status": "unavailable", "error": "blocked"}]},
        topic_decision={"growth_signals": ["conflict", "user_benefit"], "score": 0.8},
        tool_selection_plan={"selected_tools": ["theme_registry", "image_generation"]},
    )

    assert recipe["source_status"] == "unavailable"
    assert validate_growth_recipe(recipe)["passed"]


def test_growth_recipe_accepts_legacy_signals_alias_from_the_auto_path():
    recipe = build_growth_recipe(
        platform="wechat",
        content_form="article",
        source_matrix={"attempted_sources": [{"source": "wechat", "status": "ok"}]},
        topic_decision={"score": 2, "signals": ["timeliness", "user_benefit"]},
        tool_selection_plan={"selected_tools": ["article_recipe"]},
    )

    assert recipe["topic_decision"]["growth_signals"] == ["timeliness", "user_benefit"]
    assert validate_growth_recipe(recipe)["passed"]


def test_real_ranked_candidate_has_observed_growth_signals_for_auto_gate():
    signals = derive_topic_growth_signals(
        {"source": "douyin", "url": "https://www.douyin.com/search/ai", "points": 123456}
    )

    assert signals == ["observed_engagement", "source_provenance"]
