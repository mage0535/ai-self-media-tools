from content_platform.content_depth import build_content_depth_plan, validate_content_depth_plan


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


def test_strip_continuation_claims_keeps_the_rest_of_a_single_post():
    # r63: a copied "-01" course title led the model to promise a next episode with no series plan.
    from content_platform.content_depth import claims_continuation, strip_continuation_claims

    body = "先看工位怎么拍。\n模型标出可疑件。下一期我们讲标注流程！最后复核一遍。\n后续再分享部署细节。"
    cleaned = strip_continuation_claims(body)
    assert cleaned == "先看工位怎么拍。\n模型标出可疑件。最后复核一遍。\n"
    assert not claims_continuation(cleaned)
    plan = build_content_depth_plan("质检工位复核", cleaned, evidence=["https://example.com/case"])
    assert plan["continuation_claimed"] is False
