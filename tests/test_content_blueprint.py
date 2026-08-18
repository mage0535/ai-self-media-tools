from content_platform.content_blueprint import build_content_blueprint, validate_content_blueprint


def test_ai_blueprint_assigns_non_decorative_cat_and_dog_roles():
    blueprint = build_content_blueprint(
        "tiktok",
        "AI meeting notes",
        {"audience": "busy teams", "user_pain": "summaries do not become actions", "content_form": "short_video", "topic_keywords": ["AI"]},
        {"trend_evidence": {"samples": [{"url": "https://example.test/trend"}]}},
    )
    assert validate_content_blueprint(blueprint)["passed"] is True
    assert blueprint["mascot_roles"]["cat"]["narrative_function"]
    assert blueprint["mascot_roles"]["dog"]["narrative_function"]


def test_blueprint_rejects_generic_platform_style_and_missing_value():
    blueprint = build_content_blueprint("tiktok", "topic", {}, {})
    blueprint["platform_style"] = "generic"
    blueprint["user_pain"] = ""
    result = validate_content_blueprint(blueprint)
    assert "platform_style_generic" in result["failures"]
    assert "user_pain_missing" in result["failures"]
