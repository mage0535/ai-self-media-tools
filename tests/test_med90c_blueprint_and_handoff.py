import json
from pathlib import Path

from content_platform.content_blueprint import build_content_blueprint
from content_platform.creative_strategy import load_catalog, select_combination
from content_platform.generator import DraftGenerator


def test_cat_dog_duo_only_selects_for_pet_lane():
    catalog = load_catalog()
    entry = next(item for item in catalog["entries"] if item["id"] == "character.cat_dog_duo")
    assert entry["lanes"] == ["pet_healing"]

    for platform in ("zhihu", "xiaohongshu", "juejin"):
        for idx in range(5):
            combo = select_combination(
                platform,
                f"工业视觉质检与分拣流水线案例 {idx}",
                content_form="article" if platform != "xiaohongshu" else "manual_carousel",
                evidence_text="产线 工位 质检 分拣 复核",
                history=[],
                catalog=catalog,
            )
            assert combo["picks"].get("character") != "character.cat_dog_duo"


def test_blueprint_populates_non_empty_asset_plan_when_slot_omits_it():
    slot = {
        "content_form": "article",
        "scenario_contract": {
            "actor": "产线工程师",
            "inputs": "工位图像与缺陷样本",
            "process": "模型初筛加人工复核",
            "outcome": "可复现的漏判与误报统计口径",
            "boundaries": "未覆盖低照度遮挡场景",
            "human_handoff": "高风险工位由质检员终审",
        },
    }
    matrix = {"trend_evidence": {"samples": [{"url": "https://example.com/case-1", "title": "案例 1"}]}}
    bp = build_content_blueprint("zhihu", "工业视觉质检落地边界", slot, matrix)
    plan = bp["asset_and_evidence_plan"]["asset_plan"]
    assert isinstance(plan, list) and len(plan) >= 4
    assert plan[0]["role"] == "cover"


def test_generator_attaches_zhihu_and_juejin_anti_spam_and_form_differentiation_plans():
    gen = DraftGenerator({})
    body = "## 背景\n第一段说明。\n\n## 方案\n第二段说明。\n\n## 边界\n第三段说明。"
    for platform, form in (("zhihu", "evidence_answer"), ("juejin", "technical_article")):
        draft_meta = {"strategy": {"content_form": form, "primary_platforms": [platform]}}
        gen._attach_article_packet_evidence(
            topic="视觉AI质检避坑",
            brief={"platforms": [platform], "audience": "工程师"},
            body=body,
            context={},
            draft_meta=draft_meta,
        )
        sb = draft_meta["strategy_brief"]
        assert "anti_spam_similarity_plan" in draft_meta
        assert "anti_spam_similarity_plan" in sb
        assert sb["content_workflow_inputs"]["anti_spam_similarity_plan_required"] is True
        if platform == "zhihu":
            assert "content_form_differentiation_plan" in draft_meta
            assert "content_form_differentiation_plan" in sb
            assert sb["content_workflow_inputs"]["content_form_differentiation_plan_required"] is True
            assert draft_meta["content_form_differentiation_plan"]["planned_content_form"] == "evidence_answer"
            assert draft_meta["content_form_differentiation_plan"]["delivery_payload_kind"] == "article"
            assert draft_meta["anti_spam_similarity_plan"]["dedup_window_days"] == 14


def test_rulebook_defines_pre_delivery_operator_delivery_receipt_for_xhs():
    rb = json.loads(
        (Path(__file__).resolve().parents[1] / "config" / "channel_content_rulebook.json").read_text(encoding="utf-8")
    )
    defs = rb["channel_rules"]["xiaohongshu"]["quality_gate_definitions"]
    assert "operator_delivery_receipt" in defs
    assert "原生审核发生在向操作者投递手动包之前" in defs["operator_delivery_receipt"]
