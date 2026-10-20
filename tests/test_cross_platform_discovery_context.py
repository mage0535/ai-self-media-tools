import json

from content_platform.platform_workflow_context import load_platform_workflow_context
from content_platform.run_contract import bound_stage_payload, build_run_contract


def _write_discovery(tmp_path):
    intel = tmp_path / "intel"
    intel.mkdir()
    (intel / "cross_platform_real_world_ai_discovery_latest.json").write_text(json.dumps({
        "version": "cross_platform_real_world_ai_discovery_v1",
        "observed_at": "2026-09-15T07:42:00Z",
        "source_class": "public_web_search_discovery",
        "platform_status": {
            "bilibili": "discovery_candidates_available",
            "kuaishou": "first_party_collector_authorization_or_session_required_no_public_work_candidate"
        },
        "candidates": [{
            "platform": "bilibili", "content_id": "BV1test", "canonical_url": "https://www.bilibili.com/video/BV1test",
            "title": "AI 设备运维候选", "pillar": "industrial_application"
        }]
    }), encoding="utf-8")


def test_external_discovery_candidates_are_generation_only_and_platform_scoped(monkeypatch, tmp_path):
    _write_discovery(tmp_path)
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(tmp_path))
    context = load_platform_workflow_context("bilibili")
    discovery = context["external_discovery_candidates"]
    assert discovery["generation_only"] is True
    assert discovery["auto_selection_eligible"] is False
    assert discovery["candidates"][0]["content_id"] == "BV1test"
    payload = bound_stage_payload(build_run_contract("bilibili"), "generate", {
        "external_discovery_candidates": discovery, "platform_intelligence_constraints": context["platform_intelligence_constraints"]
    })
    assert payload["external_discovery_candidates"]["viral_claim_eligible"] is False


def test_kuaishou_discovery_reports_authorization_block_and_no_candidates(monkeypatch, tmp_path):
    _write_discovery(tmp_path)
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(tmp_path))
    discovery = load_platform_workflow_context("kuaishou")["external_discovery_candidates"]
    assert discovery["candidates"] == []
    assert "authorization_or_session_required" in discovery["status"]
