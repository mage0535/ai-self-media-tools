import json
from datetime import datetime, timezone

from content_platform.dual_lane_planning_run import build_dual_lane_work_plans


def _item(platform="bilibili", title="AI客服工单分类案例：人工审核高风险问题"):
    return {
        "platform": platform,
        "content_id": "BV1test", "canonical_url": "https://www.bilibili.com/video/BV1test",
        "title": title, "source": "bilibili_search_api", "collector": "bilibili_search_api",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "raw_response_hash": "c" * 64, "metrics": {"views": 1200, "likes": 100},
    }


def test_refresh_runner_emits_only_review_required_public_plan_for_eligible_observation():
    result = build_dual_lane_work_plans({"items": [_item()]}, lane="real_world_ai_implementation_v1")
    plan = result["plans"]["bilibili"]
    assert plan["decision"] == "review_required"
    assert plan["generation_only"] is True
    assert plan["permissions"]["allow_viral_claims"] is False


def test_refresh_runner_does_not_convert_topic_signal_into_work_plan():
    row = _item(platform="douyin")
    row.pop("content_id")
    row["canonical_url"] = "https://www.douyin.com/hot"
    result = build_dual_lane_work_plans({"items": [row]}, lane="real_world_ai_implementation_v1")
    assert result["plans"]["douyin_ai"]["decision"] == "blocked"
    assert "no_eligible_public_signal" in result["plans"]["douyin_ai"]["reason_codes"]


def test_refresh_runner_profiles_every_canonical_ai_platform():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / "config" / "real_world_ai_implementation_v1.json").read_text(encoding="utf-8"))
    result = build_dual_lane_work_plans({"items": []}, lane=policy["policy_profile"])

    assert set(result["plans"]) == set(policy["platforms"])
    assert len(result["plans"]) == 18


def test_refresh_runner_output_is_json_serializable():
    result = build_dual_lane_work_plans({"items": [_item()]}, lane="real_world_ai_implementation_v1")
    assert json.loads(json.dumps(result))["version"] == "dual_lane_work_plans_snapshot_v1"
