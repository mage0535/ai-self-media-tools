from content_platform.content_blueprint import build_content_blueprint, validate_content_blueprint

# Blueprints are compiled from the task's own analysis, so each test slot carries a scenario contract.
SCENARIO = {
    "actor": "busy teams",
    "inputs": "meeting transcript",
    "process": "turn the summary into owned action items",
    "outcome": "every decision has an owner and a date",
    "boundaries": "summaries do not become actions",
    "human_handoff": "the team lead confirms owners before sending",
}


def _video_blueprint():
    return build_content_blueprint(
        "tiktok",
        "AI meeting notes",
        {
            "audience": "busy teams", "user_pain": "summaries do not become actions", "content_form": "short_video",
            "topic_keywords": ["AI"], "scenario_contract": SCENARIO,
            "subtitle_and_pacing_plan": {"segments": [{"start": 0, "end": 3, "text": "Who owns this decision?"}]},
        },
        {"trend_evidence": {"samples": [{"url": "https://example.test/trend"}]}},
    )


def test_ai_blueprints_get_no_cat_or_dog_roles():
    """MED58 (owner 11-07): cats and dogs appear only in the douyin_pet account."""
    blueprint = _video_blueprint()
    assert validate_content_blueprint(blueprint)["passed"] is True and blueprint["mascot_roles"] == {}
    article = build_content_blueprint(
        "juejin",
        "Claude Code vs Codex：Computer Use 实现原理深度拆解",
        {"audience": "developers", "user_pain": "unclear tool choice", "content_form": "technical_article",
         "scenario_contract": SCENARIO},
        {"trend_evidence": {"samples": [{"url": "https://example.test/trend"}]}},
    )
    assert article["mascot_roles"] == {} and article["cat_dog_role_plan_when_ai_knowledge_lane"]["applicable"] is False
    assert validate_content_blueprint(article)["passed"] is True


def test_blueprint_rejects_generic_platform_style_and_missing_value():
    blueprint = _video_blueprint()
    blueprint["platform_style"] = "generic"
    blueprint["user_pain"] = ""
    result = validate_content_blueprint(blueprint)
    assert "platform_style_generic" in result["failures"]
    assert "user_pain_missing" in result["failures"]
