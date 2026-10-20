from datetime import datetime, timezone

from content_platform.content_blueprint import build_content_blueprint, validate_content_blueprint
from content_platform.platform_workflow_context import load_platform_workflow_context


def _plan():
    return {
        "version": "dual_lane_work_plan_v1",
        "platform": "bilibili",
        "lane": "real_world_ai_implementation",
        "decision": "review_required",
        "planning_mode": "public_signal_candidate",
        "generation_only": True,
        "permissions": {"allow_viral_claims": False, "allow_automated_learning": False},
        "evidence_refs": {"public_web_observation": ["public-001"], "authorized_owned_analytics": []},
        "scenario_contract": {
            "actor": "客服主管", "inputs": "40条工单", "process": "AI初步分类",
            "outcome": "待核验的优先级清单", "boundaries": "不得自动回复客户",
            "human_handoff": "主管审核高风险工单",
        },
        "hook_hypothesis": "先展示漏掉的高风险工单",
        "narrative_structure": ["hook", "task", "process", "evidence", "boundary", "cta"],
        "success_metric": "saves_and_substantive_comments",
        "planned_at": datetime.now(timezone.utc).isoformat(),
    }


def test_workflow_context_projects_only_bounded_dual_lane_plan():
    context = load_platform_workflow_context("bilibili", plan={"dual_lane_work_plan": _plan()})
    projected = context["dual_lane_work_plan"]
    assert projected["planning_mode"] == "public_signal_candidate"
    assert projected["permissions"]["allow_viral_claims"] is False
    assert "scenario_contract" in projected


def test_content_blueprint_carries_plan_boundary_without_viral_claim_permission():
    plan = _plan()
    blueprint = build_content_blueprint(
        "bilibili", "AI先分类客服工单，人工审核高风险问题",
        {"dual_lane_work_plan": plan}, {"trend_evidence": {"samples": []}},
    )
    assert validate_content_blueprint(blueprint)["passed"] is True
    assert blueprint["intelligence_plan"]["planning_mode"] == "public_signal_candidate"
    assert blueprint["intelligence_plan"]["allow_viral_claims"] is False
    assert blueprint["intelligence_plan"]["scenario_contract"]["human_handoff"]
