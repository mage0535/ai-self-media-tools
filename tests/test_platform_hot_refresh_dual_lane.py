from pathlib import Path


def test_platform_hot_refresh_materializes_dual_lane_review_plan_snapshot():
    script = Path("scripts/run_platform_hot_refresh.sh").read_text(encoding="utf-8")
    assert "dual_lane_planning_run import build_dual_lane_work_plans" in script
    assert "dual_lane_work_plans_latest.json" in script
