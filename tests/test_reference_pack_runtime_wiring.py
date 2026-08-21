from pathlib import Path

from content_platform.content_quality_reference import load_content_quality_reference_pack
from content_platform.content_blueprint import build_content_blueprint, validate_content_blueprint
from content_platform.generator import DraftGenerator
from content_platform.platform_workflow_context import load_platform_workflow_context
from content_platform.run_contract import build_run_contract


def test_blueprint_embeds_reference_pack_requirements():
    pack = load_content_quality_reference_pack("xiaohongshu", content_form="manual_carousel")
    blueprint = build_content_blueprint(
        "xiaohongshu",
        "AI inbox triage checklist",
        {"topic_keywords": ["AI"], "content_form": "manual_carousel"},
        {"trend_evidence": {"samples": [{"url": "https://example.test/source"}]}},
        quality_reference_pack=pack,
    )

    assert validate_content_blueprint(blueprint)["passed"] is True
    assert blueprint["quality_reference"]["version"] == pack["version"]
    assert "image_text_card_gate" in blueprint["quality_reference"]["sections"]
    assert "cover_design_gate" in blueprint["quality_requirements"]


def test_platform_context_proves_reference_pack_is_loaded():
    context = load_platform_workflow_context("douyin_ai")

    reference = context["content_quality_reference_pack"]
    assert reference["loaded"] is True
    assert reference["version"] == "content_quality_reference_pack_v1"
    assert reference["sha256"]
    assert "content_quality_reference_pack" in context["selected_tools"]
    assert Path(reference["path"]).name == "content_quality_reference_pack.json"


def test_generator_provider_brief_receives_reference_pack_from_bounded_input():
    generator = DraftGenerator()
    contract = build_run_contract("tiktok")
    pack = load_content_quality_reference_pack("tiktok", content_form="short_video")
    brief = {
        "run_contract": contract,
        "bounded_model_input": {
            "content_blueprint": {"topic": "AI meeting notes"},
            "claim_ledger": [],
            "tool_selection_plan": {},
            "content_quality_reference_pack": pack,
        },
        "private_unbounded_history": "must not reach the model",
    }

    bounded = generator._provider_brief(brief)

    assert "private_unbounded_history" not in bounded
    assert bounded["content_quality_reference_pack"]["video_director_gate"]["scene_contract"]["min_scenes"] >= 6
