from pathlib import Path

from content_platform.platform_workflow_context import load_platform_workflow_context
from content_platform.wechat_blowup_intelligence import build_wechat_blowup_report


def test_platform_workflow_context_loads_rules_strategy_skills_and_publish_mode():
    platforms = ["kuaishou", "tiktok", "youtube", "douyin_ai", "xiaohongshu", "wechat", "bilibili", "shipinhao", "x"]
    for platform in platforms:
        context = load_platform_workflow_context(platform)
        assert context["loaded"] is True
        assert context["platform"] == platform
        assert context["rulebook"]["entry_loaded"] is True
        assert context["platform_rules_2026"]["matched"] is True
        assert Path(context["strategy"]["path"]).is_file()
        assert all(item["exists"] for item in context["skills"])
        assert context["content_quality_reference_pack"]["loaded"] is True
        assert context["content_quality_reference_pack"]["sha256"]
        assert context["content_quality_reference_pack"]["hook_title_gate"]
        assert context["runtime_capabilities"]["version"] == "runtime_capabilities_v1"
        assert "tools" in context["runtime_capabilities"]
        assert "content_quality_reference_pack" in context["selected_tools"]
        assert context["selected_tools"]
        if platform == "wechat":
            assert context["wechat_blowup_intelligence"]["status"] in {"missing", "research_ready", "strategy_ready", "blocked"}


def test_wechat_context_reads_blowup_artifact_from_configured_shared_data_dir(tmp_path, monkeypatch):
    artifact = tmp_path / "intel" / "wechat_blowup_intelligence_latest.json"
    artifact.parent.mkdir()
    row = {
        "platform": "wechat", "title": "AI Agent 实践", "canonical_url": "https://mp.weixin.qq.com/s/shared-data", "account_name": "AI 实践观察",
        "published_at": "2026-09-15T08:00:00+08:00", "observed_at": "2026-09-15T10:00:00+08:00", "source_kind": "authorized_vendor_export",
        "source_vendor": "licensed_vendor", "metric_name": "hot_rank", "metric_value": 1, "metric_definition": "licensed daily hot rank",
        "raw_snapshot_ref": "source:licensed_vendor", "raw_snapshot_sha256": "b" * 64,
    }
    artifact.write_text(__import__("json").dumps(build_wechat_blowup_report([row]), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(tmp_path))

    context = load_platform_workflow_context("wechat")

    assert context["wechat_blowup_intelligence"]["status"] == "blocked"
    assert context["wechat_blowup_intelligence"]["counts"]["G3"] == 1
