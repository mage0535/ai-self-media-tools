from content_platform.real_world_ai_triage import triage_real_world_ai_candidate


def _base_row(**overrides):
    row = {
        "platform": "zhihu",
        "title": "设备运维：AI 用振动数据标记异常工单，工程师确认后处理",
        "canonical_url": "https://www.zhihu.com/question/1/answer/2",
        "content_id": "2",
        "source": "zhihu_open_platform",
        "collector": "zhihu_open_platform",
        "observed_at": "2026-09-15T07:03:02Z",
        "raw_response_hash": "a" * 64,
        "metrics": {"likes": 3, "comments": 1},
        "positioning": {"pillar": "industrial_application"},
        "generation_only": True,
        "auto_selection_eligible": False,
    }
    row.update(overrides)
    return row


def test_triage_keeps_search_snapshots_out_of_viral_and_auto_selection():
    result = triage_real_world_ai_candidate(_base_row())
    assert result["tier"] == "research_candidate"
    assert result["evidence_completeness_score"] == 4
    assert result["auto_selection_eligible"] is False
    assert result["viral_claim_eligible"] is False
    assert "body_or_native_page_verification_missing" in result["required_evidence"]


def test_triage_is_observe_only_when_traceability_or_scene_proof_is_missing():
    result = triage_real_world_ai_candidate(_base_row(canonical_url="", positioning={}))
    assert result["tier"] == "observe_only"
    assert "entity_traceability_incomplete" in result["failures"]
    assert "scene_match_unverified" in result["failures"]
