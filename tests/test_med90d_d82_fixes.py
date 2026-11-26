"""MED90-d / d82 unit tests: Bucket A quality/consistency fixes and Bucket B draft-first cold-start rulebook definitions."""
import json
from pathlib import Path

from content_platform import asset_semantic_review
from content_platform.generator import DraftGenerator
from content_platform.growth_policy import build_growth_strategy
from content_platform.humanize import naturalize_copy
from content_platform.pipeline import Pipeline

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_d82_semantic_review_prompt_rejects_garbled_text_and_fake_ui_on_untitled_images(tmp_path: Path):
    img = tmp_path / "section-01.png"
    img.write_bytes(b"fake")
    captured = {}

    def fake_invoke(cmd, *, input, **kwargs):
        captured["prompt"] = input

        class Proc:
            returncode = 0
            stdout = json.dumps({"type": "system", "subtype": "init", "model": "gpt-6.2-sol", "session_id": "s1"}) + "\n" + json.dumps(
                {
                    "type": "result",
                    "exit_code": 0,
                    "text": json.dumps(
                        {
                            "score": 0.45,
                            "reason": "contains fake UI text",
                            "observed_subject": "dashboard with garbled labels",
                            "topic_relation": "partial",
                            "image_observed": True,
                        }
                    ),
                }
            )
            stderr = ""

        return Proc()

    cfg = tmp_path / "cfg.json"
    cfg.write_bytes(b"{}")
    audit = {}
    route = {"hermes_command": "hermes", "hermes_provider": "openai-codex", "hermes_model": "gpt-6.2-sol"}
    asset_semantic_review._review_call(
        audit, route, img, b"fake", {"topic": "t", "section": "s"}, None, None, cfg, b"{}", fake_invoke, lambda r: "native"
    )
    assert "Visual hygiene" in captured["prompt"]
    assert "0.55 or lower" in captured["prompt"]
    assert "garbled/pseudo text" in captured["prompt"]


def test_d82_pipeline_asset_mix_and_background_kind_match_zhihu_juejin_policy():
    assets = [
        {"scene_id": "cover", "origin": "ai_generated", "source_url": "generated:cloudflare"},
        {"scene_id": "section-01", "origin": "ai_generated", "source_url": "generated:openai-codex"},
    ]
    zhihu_mix = Pipeline._rendered_asset_mix(
        assets, {"draft_meta": {"strategy": {"primary_platforms": ["zhihu"]}}}
    )
    assert "cover tried licensed stock photo search first" in zhihu_mix["real_material_retrieval"]
    assert "cloudflare -> openai-codex" in zhihu_mix["real_material_retrieval"]
    assert "every image" not in zhihu_mix["real_material_retrieval"]


def test_d82_generator_requirements_enforce_juejin_code_block_and_forbid_meta_notes():
    req, _ = DraftGenerator._generation_requirements(
        {"strategy": {"content_form": "technical_article", "primary_platforms": ["juejin"]}}
    )
    assert "runnable code snippet" in req
    assert "封面计划用" in req


def test_d82_growth_strategy_uses_text_metrics_for_articles_and_video_metrics_for_video():
    zhihu = build_growth_strategy(["zhihu"], "long_article")
    assert "three_second_view_rate" not in zhihu["post_publish_review_plan"]["diagnosis_dimensions"]
    assert "read_completion_rate" in zhihu["post_publish_review_plan"]["diagnosis_dimensions"]
    assert "first_screen_opening" in zhihu["retention_plan"]

    pet = build_growth_strategy(["douyin_pet"], "short_video")
    assert "three_second_view_rate" in pet["post_publish_review_plan"]["diagnosis_dimensions"]
    assert "first_3_seconds" in pet["retention_plan"]


def test_d82_humanize_strips_orphan_commas_and_cover_meta_notes_while_keeping_code():
    raw = (
        "## 一、为什么会翻车\n"
        "封面计划用一张工厂产线实景图突出对比。\n"
        "，\n"
        "遇到超时不能直接当合格，，必须保留人工复核。\n\n"
        "```python\nx = [1, 2]\n```\n"
    )
    out = naturalize_copy(raw, {"strategy": {"content_form": "technical_article"}, "style": {"cta": ""}})
    body = out["body"]
    assert "封面计划用" not in body
    assert "，，" not in body
    assert not any(line.strip() in {",", "，"} for line in body.splitlines())
    assert "```python\nx = [1, 2]\n```" in body


def test_d82_rulebook_cover_layouts_and_draft_first_cold_start_definitions():
    rulebook = json.loads((REPO_ROOT / "config" / "channel_content_rulebook.json").read_text(encoding="utf-8"))
    allowed = set(rulebook["global_hard_gates"]["adaptive_cover_layout_policy"]["allowed_layouts"])
    for key in ("hero_conflict", "diagonal_split", "evidence_interface", "checklist_poster", "magazine_story", "result_reveal"):
        assert key in allowed
    assert "automated_draft_first_cold_start_policy" in rulebook["global_hard_gates"]
    for plat in ("juejin", "zhihu", "xiaohongshu"):
        defs = rulebook["channel_rules"][plat]["quality_gate_definitions"]
        for gate in (
            "account_data_analysis",
            "growth_quality_plan",
            "same_lane_account_benchmark",
            "cross_platform_hot_trend_analysis",
            "topic_quantity_decision",
            "full_ops_workflow",
            "content_workflow_inputs",
            "asset_mix_plan",
            "source_rights",
            "seven_day_all_channel_dedup",
        ):
            assert gate in defs, f"{plat} missing {gate}"
    assert "zhihu_pin_anti_spam_similarity" in rulebook["channel_rules"]["zhihu"]["quality_gate_definitions"]
