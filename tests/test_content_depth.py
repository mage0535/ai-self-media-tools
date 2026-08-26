from content_platform.content_depth import build_content_depth_plan, remove_unplanned_continuation, validate_content_depth_plan


def test_depth_plan_rejects_empty_continuation_promise():
    plan = build_content_depth_plan(
        "Practical workflow",
        "First use a baseline, then review the output. The next episode will show the template.",
    )
    assert "continuation_without_series_plan" in validate_content_depth_plan(plan)["failures"]


def test_depth_plan_accepts_actionable_content_with_evidence():
    plan = build_content_depth_plan(
        "Practical workflow",
        "Start with a baseline. Measure the result. Keep the review checklist.",
        evidence=["https://example.test/report"],
        actions=["create a baseline", "run the checklist", "record the result"],
    )
    assert validate_content_depth_plan(plan)["passed"] is True


def test_depth_plan_requires_three_knowledge_points_and_a_case():
    plan = build_content_depth_plan("Practical workflow", "Short advice.", actions=["one step"])
    result = validate_content_depth_plan(plan)
    assert "knowledge_points_insufficient" in result["failures"]
    assert "case_or_demo_missing" in result["failures"]


def test_remove_unplanned_continuation_drops_only_the_empty_future_promise():
    body = "先建立基线。下一篇我会分享完整模板。现在先把本次结果记录下来。"
    cleaned = remove_unplanned_continuation(body)
    assert "下一篇" not in cleaned
    assert "先建立基线" in cleaned
    assert "记录下来" in cleaned
