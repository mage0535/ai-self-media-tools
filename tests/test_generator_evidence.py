from content_platform.generator import DraftGenerator
from content_platform.content_quality_reference import load_content_quality_reference_pack
from content_platform.run_contract import build_run_contract
import pytest


def test_growth_recipe_carries_real_kuaishou_trend_samples_into_the_publish_packet():
    draft_meta = {"strategy": {"primary_platforms": ["kuaishou"]}}
    brief = {
        "platform_source_matrix": {
            "platform": "kuaishou",
            "platform_internal_verified": True,
            "attempted_sources": [
                {"source": "kuaishou_hot", "status": "ok", "topic_signal": "AI workflow", "url": "https://example.test/1"},
                {"source": "kuaishou_search", "status": "ok", "topic_signal": "AI workflow", "url": "https://example.test/2"},
                {"source": "kuaishou_creator", "status": "ok", "topic_signal": "AI workflow", "url": "https://example.test/3"},
            ],
        }
    }

    DraftGenerator._attach_growth_recipe(brief, {}, draft_meta)

    evidence = draft_meta["trend_evidence"]
    assert evidence["source"] == "kuaishou_hot"
    assert evidence["collected_at"]
    assert len(evidence["samples"]) == 3


def test_normalized_draft_carries_depth_and_adaptive_cover_contract():
    generator = DraftGenerator({"allow_fallback": True})
    brief = {
        "platform": "juejin",
        "platforms": ["juejin"],
        "platform_source_matrix": {
            "attempted_sources": [{"source": "juejin", "status": "ok", "url": "https://example.test/source"}],
            "trend_evidence": {"samples": [{"url": "https://example.test/source"}]},
        },
    }
    draft = generator.generate("AI workflow", brief)
    meta = draft["draft_meta"]
    assert meta["content_depth_plan"]["version"] == "content_depth_plan_v1"
    assert meta["content_depth_plan"]["evidence"]
    assert meta["cover_design"]["layout_key"] in {
        "hero_conflict", "diagonal_split", "evidence_interface", "checklist_poster", "magazine_story", "result_reveal"
    }


def test_compiled_generation_uses_only_bounded_model_input():
    generator = DraftGenerator()
    contract = build_run_contract("tiktok")
    pack = load_content_quality_reference_pack("tiktok", content_form="short_video")
    brief = {
        "run_contract": contract,
        "bounded_model_input": {
            "content_blueprint": {"topic": "AI meeting notes"},
            "claim_ledger": [],
            "tool_selection_plan": {},
            "strategy": {"version": "compiled_strategy_v1"},
            "content_quality_reference_pack": pack,
            "strategy": {"version": "compiled_strategy_v1"},
        },
        "private_unbounded_history": "must not reach the model",
    }
    bounded = generator._provider_brief(brief)
    assert "private_unbounded_history" not in bounded
    assert bounded["content_blueprint"]["topic"] == "AI meeting notes"
    assert bounded["content_quality_reference_pack"]["loaded"] is True
    assert bounded["strategy"]["version"] == "compiled_strategy_v1"


def test_compiled_generation_rejects_oversized_provider_response():
    generator = DraftGenerator()
    contract = build_run_contract("tiktok")
    contract["bounds"]["provider_response_bytes"] = 10
    with pytest.raises(ValueError, match="provider response exceeds"):
        generator._bounded_provider_content("x" * 20, {"run_contract": contract})


def test_video_draft_also_gets_an_adaptive_cover_contract():
    generator = DraftGenerator({"allow_fallback": True})
    draft = generator.generate("AI meeting notes", {
        "platform": "tiktok",
        "platforms": ["tiktok"],
        "content_form": "short_video",
        "content_blueprint": {
            "user_pain": "AI summaries omit ownership",
            "mascot_roles": {"cat": {"narrative_function": "draft"}, "dog": {"narrative_function": "verify"}},
        },
    })
    design = draft["draft_meta"]["cover_design"]
    assert design["layout_key"]
    assert design["focal_subjects"] == ["cat", "dog"]
    assert design["safe_zone_verified"] is True


def test_blueprint_content_form_controls_generation_context():
    draft = DraftGenerator({"allow_fallback": True}).generate("AI checklist", {
        "platform": "twitter", "platforms": ["twitter"],
        "content_blueprint": {"content_form": "short_post", "audience": "operators", "platform_style": "compact"},
    })
    assert draft["draft_meta"]["content_form"] == "short_post"
