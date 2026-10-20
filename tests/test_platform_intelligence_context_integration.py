import json

from content_platform.platform_workflow_context import load_platform_workflow_context


def test_workflow_context_allows_only_fresh_usable_platform_intelligence(monkeypatch, tmp_path):
    intel = tmp_path / "intel"
    intel.mkdir()
    (intel / "platform_intelligence_runtime_latest.json").write_text(json.dumps({
        "policy_profile": "real_world_ai_implementation_v1",
        "policy_revision": "2026-09-16-universal-ai-lane-r2",
        "source_bundle_version": "platform_hot_evidence_bundle_v1",
        "platforms": {"zhihu": {"runtime_collection": {
            "state": "fresh_usable", "usable_for_generation_context": True,
            "observed_at": "2026-09-15T07:15:35Z", "age_seconds": 1, "reason_codes": []
        }}}
    }), encoding="utf-8")
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(tmp_path))
    constraints = load_platform_workflow_context("zhihu")["platform_intelligence_constraints"]
    assert constraints["allow_topic_signals"] is True
    assert constraints["runtime_collection"]["state"] == "fresh_usable"
    assert constraints["allow_viral_claims"] is False


def test_workflow_context_blocks_topic_signals_when_runtime_snapshot_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTENT_PLATFORM_DATA_DIR", str(tmp_path))
    constraints = load_platform_workflow_context("zhihu")["platform_intelligence_constraints"]
    assert constraints["allow_topic_signals"] is False
    assert "platform_hot_evidence_missing_snapshot" in constraints["required_disclaimers"]
