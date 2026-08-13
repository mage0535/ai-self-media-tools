from content_platform.voice_plan import build_voice_plan, validate_voice_plan


def test_voice_plan_assigns_distinct_controls_to_hook_and_explanation():
    plan = build_voice_plan(["This is the hook.", "Here is the practical explanation."])

    assert validate_voice_plan(plan)["passed"] is True
    assert plan[0]["style"] == "urgent"
    assert plan[1]["style"] == "calm"
    assert plan[0]["rate"] != plan[1]["rate"]

