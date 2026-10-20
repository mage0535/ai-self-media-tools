from datetime import datetime, timezone

from content_platform.dual_lane_work_planner import build_work_plan


def _public_observation():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "version": "intelligence_provenance_v1",
        "evidence_id": "public-001",
        "source_class": "public_web_observation",
        "origin_platform": "bilibili",
        "observed_at": now,
        "ingested_at": now,
        "collector_id": "bilibili_search_api",
        "content_locator": "https://www.bilibili.com/video/BV1test",
        "integrity": {"sha256": "b" * 64},
        "use_policy": {},
        "title": "AI客服工单分类案例：人工仍审核高风险问题",
        "public_metrics": {"views": 1200, "likes": 96},
    }


def test_public_signal_produces_review_required_generation_only_work_plan():
    plan = build_work_plan(
        platform="bilibili",
        lane="real_world_ai_implementation_v1",
        public_observations=[_public_observation()],
        owned_rows=[],
    )
    assert plan["decision"] == "review_required"
    assert plan["planning_mode"] == "public_signal_candidate"
    assert plan["generation_only"] is True
    assert plan["permissions"] == {"allow_viral_claims": False, "allow_automated_learning": False}
    assert plan["scenario_contract"]["human_handoff"]
    assert plan["evidence_refs"]["public_web_observation"] == ["public-001"]


def test_owned_rows_never_upgrade_public_candidate_to_viral_or_auto_learning():
    plan = build_work_plan(
        platform="bilibili",
        lane="real_world_ai_implementation_v1",
        public_observations=[_public_observation()],
        owned_rows=[{
            "job_id": "job-1", "platform_content_id": "BVself", "views": 1000,
            "likes": 100, "comments": 10, "shares": 5,
        }],
    )
    assert plan["owned_review"]["eligible_count"] == 1
    assert plan["permissions"]["allow_viral_claims"] is False
    assert plan["permissions"]["allow_automated_learning"] is False


def test_planner_rejects_public_observation_without_real_world_ai_task_contract():
    row = _public_observation()
    row["title"] = "AI模型发布跑分榜单"
    plan = build_work_plan(
        platform="bilibili", lane="real_world_ai_implementation_v1", public_observations=[row], owned_rows=[]
    )
    assert plan["decision"] == "blocked"
    assert "no_eligible_public_signal" in plan["reason_codes"]


def test_planner_profiles_cover_every_canonical_ai_platform():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / "config" / "real_world_ai_implementation_v1.json").read_text(encoding="utf-8"))
    profiles = json.loads((root / "config" / "platform_work_planning_profiles_v1.json").read_text(encoding="utf-8"))

    assert profiles["policy_profile"] == policy["policy_profile"]
    assert set(profiles["platforms"]) == set(policy["platforms"])
    assert len(profiles["platforms"]) == 18


def test_planner_fails_closed_when_platform_profile_is_missing(monkeypatch):
    from content_platform import dual_lane_work_planner

    monkeypatch.setattr(dual_lane_work_planner, "_profiles", lambda: {})
    plan = build_work_plan(
        platform="bilibili", lane="real_world_ai_implementation_v1", public_observations=[_public_observation()], owned_rows=[]
    )

    assert plan["decision"] == "blocked"
    assert plan["reason_codes"] == ["platform_planning_profile_missing"]


def test_planner_rejects_non_ai_platform_even_if_a_profile_is_injected(monkeypatch):
    from content_platform import dual_lane_work_planner

    monkeypatch.setattr(
        dual_lane_work_planner,
        "_profiles",
        lambda: {"xiaohongshu": {"content_form": "note", "hook": "hook", "structure": ["task"], "success_metric": "saves"}},
    )
    row = _public_observation()
    row["origin_platform"] = "xiaohongshu"
    plan = build_work_plan(
        platform="xiaohongshu", lane="real_world_ai_implementation_v1", public_observations=[row], owned_rows=[]
    )

    assert plan["decision"] == "blocked"
    assert plan["reason_codes"] == ["platform_not_in_canonical_ai_policy"]


def test_planner_rejects_unrelated_title_even_when_summary_contains_ai_terms():
    row = _public_observation()
    row["title"] = "日式霸凌题材MV"
    row["excerpt"] = "AI 智能制造 设备运维"
    plan = build_work_plan(
        platform="bilibili", lane="real_world_ai_implementation_v1", public_observations=[row], owned_rows=[]
    )
    assert plan["decision"] == "blocked"
