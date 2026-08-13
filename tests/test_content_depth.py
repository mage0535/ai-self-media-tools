from content_platform.content_depth import build_content_depth_plan, validate_content_depth_plan
from pathlib import Path
import json
import subprocess
import sys


def test_depth_plan_rejects_empty_continuation_promise():
    plan = build_content_depth_plan(
        "Practical workflow",
        "First use a baseline, then review the output. The next episode will show the template.",
    )

    result = validate_content_depth_plan(plan)

    assert result["passed"] is False
    assert "continuation_without_series_plan" in result["failures"]


def test_depth_plan_accepts_actionable_content_with_a_real_series_plan():
    plan = build_content_depth_plan(
        "Practical workflow",
        "Start with a baseline. Measure the result. Keep the review checklist. Then record the next decision.",
        evidence=["measured before/after", "repository example"],
        actions=["create a baseline", "run the checklist", "record the result"],
        series_plan={"next_topic": "Review the recorded result", "delivery_window": "next weekly operations run"},
    )

    result = validate_content_depth_plan(plan)

    assert result["passed"] is True


def test_content_quality_gate_exposes_the_depth_contract_cli(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    plan = build_content_depth_plan(
        "Practical workflow",
        "Start with a baseline. Measure the result. Keep the review checklist. Then record the next decision.",
        evidence=["measured before/after"],
        actions=["create a baseline", "run the checklist"],
    )
    payload = tmp_path / "depth.json"
    payload.write_text(json.dumps(plan), encoding="utf-8")

    process = subprocess.run(
        [sys.executable, "scripts/content_quality_gate.py", "--check-depth", "--data", payload.read_text(encoding="utf-8")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["pass"] is True
