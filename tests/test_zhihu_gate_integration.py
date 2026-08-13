"""Regression test: generator must emit WORKFLOW names (not platform names) in
content_generation_brief.source_inputs, and the FULL_OPS gate must pass for zhihu."""
import json

from content_platform.generator import DraftGenerator
from content_platform.media_quality import _full_ops_gates

MANDATORY_WORKFLOW_INPUTS = {
    "account_analysis",
    "same_lane_account_analysis",
    "cross_platform_trend_analysis",
    "topic_selection",
    "quantity_plan",
    "content_brief",
}


def _zhihu_context():
    return {
        "platform_source_matrix": {
            "platform": "zhihu",
            "platform_internal_verified": True,
            "attempted_sources": [
                {"source": "zhihu_hot", "status": "ok", "topic_signal": "AI efficiency"},
                {"source": "github", "status": "ok", "topic_signal": "AI efficiency"},
                {"source": "wechat", "status": "ok", "topic_signal": "AI efficiency"},
                {"source": "bilibili", "status": "degraded", "topic_signal": "AI efficiency"},
                {"source": "account_history", "status": "ok", "topic_signal": "AI efficiency"},
                {"source": "juejin", "status": "ok", "topic_signal": "AI efficiency"},
                {"source": "x", "status": "ok", "topic_signal": "AI efficiency"},
                {"source": "search_trend", "status": "ok", "topic_signal": "AI efficiency"},
            ],
        },
        "language": "zh",
        "style": {"cta": "cta", "opening_patterns": ["数字开场"]},
        "strategy": {"content_form": "article", "asset_plan": ["cover", "article", "caption"],
                     "primary_platforms": ["zhihu"], "reason": {"trend_stage": "emerging"}},
        "trend_stage": "emerging", "trend_angle": "方法拆解",
        "reference_titles": [], "source_summary": "", "source_catalog": [],
        "topic_clusters": [], "niche_report": {}, "viral_score": {"total_score": 80},
        "viral_growth_report": {}, "hashtags": ["AI效率"], "image_prompt": "", "video_prompt": "",
    }


def _zhihu_draft_payload():
    return {
        "title": "AI 效率工具实战：职场人的效率架构师之路",
        "body": "三十天前我还在手写每一个单元测试。三十天后我的习惯彻底变了：先让 AI 生成第一版，我负责审，再补边界。",
    }


class TestZhihuGeneratorGateIntegration:
    def test_generator_emits_workflow_names_in_brief_source_inputs(self):
        gen = DraftGenerator({})
        draft = gen._coerce_provider_draft(json.dumps(_zhihu_draft_payload()), "t")
        normalized = gen._normalize(draft, _zhihu_context(), "hermes-cli", "t", {"platform": "zhihu"})
        dm = normalized["draft_meta"]
        strategy = dm.get("strategy_brief") or {}
        brief = strategy.get("content_generation_brief") or {}
        wf = strategy.get("content_workflow_inputs") or {}
        # brief.source_inputs must NOT be platform names; must carry workflow names
        assert "bilibili" not in brief.get("source_inputs", [])
        assert MANDATORY_WORKFLOW_INPUTS.issubset(set(brief.get("source_inputs") or []))
        assert MANDATORY_WORKFLOW_INPUTS.issubset(set(wf.get("source_inputs") or []))

    def test_full_ops_gate_passes_for_zhihu_with_generator_output(self):
        gen = DraftGenerator({})
        draft = gen._coerce_provider_draft(json.dumps(_zhihu_draft_payload()), "t")
        normalized = gen._normalize(draft, _zhihu_context(), "hermes-cli", "t", {"platform": "zhihu"})
        dm = normalized["draft_meta"]
        packet = {}
        for source in (dm.get("strategy", {}), dm, normalized):
            if isinstance(source, dict):
                packet.update(source)
        packet["platform"] = "zhihu"
        packet["id"] = "regression"
        packet["title"] = normalized["title"]
        packet["body"] = normalized["body"]

        gates = _full_ops_gates(packet, "zhihu")
        failed = [k for k, v in gates.items() if not v.get("passed")]
        assert not failed, f"gate failures: {failed}"
        assert gates["content_workflow_inputs"]["passed"] is True
