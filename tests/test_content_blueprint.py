from content_platform.content_blueprint import build_content_blueprint, validate_content_blueprint
import json
from pathlib import Path


def test_generic_ai_blueprint_does_not_require_cat_and_dog_roles():
    blueprint = build_content_blueprint(
        "tiktok",
        "AI meeting notes",
        {"audience": "busy teams", "user_pain": "summaries do not become actions", "content_form": "short_video", "topic_keywords": ["AI"]},
        {"trend_evidence": {"samples": [{"url": "https://example.test/trend"}]}},
    )
    assert validate_content_blueprint(blueprint)["passed"] is True
    assert blueprint["mascot_roles"] == {}
    assert blueprint["mascot_decision"]["selected"] is False


def test_topic_matched_ai_blueprint_selects_functional_cat_and_dog_roles():
    blueprint = build_content_blueprint(
        "tiktok",
        "Use a curious cat and watchful dog to explain AI task review",
        {"audience": "AI beginners", "topic_keywords": ["AI"]},
        {},
    )

    assert blueprint["mascot_decision"]["selected"] is True
    assert blueprint["mascot_roles"]["cat"]["narrative_function"]
    assert blueprint["mascot_roles"]["dog"]["narrative_function"]


def test_explicit_no_mascot_overrides_pet_word_in_topic():
    blueprint = build_content_blueprint(
        "youtube", "AI workflow for pet care", {"use_mascots": False}, {}
    )

    assert blueprint["mascot_roles"] == {}
    assert blueprint["mascot_decision"]["reason"] == "explicitly_disabled"


def test_channel_rulebook_makes_ai_mascots_optional_and_content_driven():
    rulebook = json.loads((Path(__file__).resolve().parents[1] / "config" / "channel_content_rulebook.json").read_text(encoding="utf-8"))
    policy = rulebook["global_hard_gates"]["ai_knowledge_cat_dog_role_policy"]

    assert policy["enforced"] is True
    assert policy["required"] is False
    assert policy["selection_mode"] == "optional_content_fit"


def test_blueprint_rejects_generic_platform_style_and_missing_value():
    blueprint = build_content_blueprint("tiktok", "topic", {}, {})
    blueprint["platform_style"] = "generic"
    blueprint["user_pain"] = ""
    result = validate_content_blueprint(blueprint)
    assert "platform_style_generic" in result["failures"]
    assert "user_pain_missing" in result["failures"]
