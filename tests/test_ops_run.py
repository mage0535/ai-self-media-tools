from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys


def test_direction_register_blocks_different_titles_in_same_direction(tmp_path: Path):
    from content_platform.ops_run import create_run, record_topic

    create_run(tmp_path, "20260810", lookback_days=7)
    first = record_topic(
        tmp_path,
        "20260810",
        "zhihu",
        "A practical code-review checklist",
        direction="code_review",
    )
    second = record_topic(
        tmp_path,
        "20260810",
        "juejin",
        "How teams catch bugs before release",
        direction="code_review",
    )

    assert first["accepted"] is True
    assert second["accepted"] is False
    assert "direction_already_selected" in second["failed_dimensions"]


def test_direction_register_allows_documented_follow_up_with_distinct_angle(tmp_path: Path):
    from content_platform.ops_run import create_run, record_topic

    create_run(tmp_path, "20260810", lookback_days=7)
    record_topic(tmp_path, "20260810", "zhihu", "Code review checklist", direction="code_review")
    follow_up = record_topic(
        tmp_path,
        "20260810",
        "juejin",
        "Implementing a review bot rule set",
        direction="code_review",
        follow_up_to="zhihu",
        difference_angle="implementation details and repository examples",
        recap_reason="the engineering audience needs executable rules",
    )

    assert follow_up["accepted"] is True
    assert follow_up["record"]["follow_up_to"] == "zhihu"


def test_legacy_topic_gate_rejects_invalid_direction_register(tmp_path: Path):
    from scripts.check_platform_topic_independence import check

    for platform, topic in (("wechat", "Reader interview notes"), ("zhihu", "Retention measurement notes")):
        directory = tmp_path / "data" / ("local_ops_gzh" if platform == "wechat" else f"local_ops_{platform}")
        directory.mkdir(parents=True)
        (directory / "platform_source_matrix_20260810.json").write_text(
            json.dumps({"selected_topic": topic, "source_matrix": {"attempted_sources": ["a", "b", "c", "d", "e"], "successful_sources": ["a", "b", "c"], "platform_internal_verified": True}}),
            encoding="utf-8",
        )
    manifest = tmp_path / "data" / "ops_runs" / "20260810" / "run_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"date": "20260810", "direction_register": [{"platform": "wechat", "direction": "audience_research"}, {"platform": "zhihu", "direction": "audience_research"}]}),
        encoding="utf-8",
    )

    result = check("20260810", ["wechat", "zhihu"], root=tmp_path)

    assert result["passed"] is False
    assert any("direction_register_duplicate" in item["failed_dimensions"] for item in result["failures"])


def test_ops_run_cli_runs_as_a_direct_script():
    root = Path(__file__).resolve().parents[1]
    process = subprocess.run([sys.executable, "scripts/ops_run.py", "--help"], cwd=root, capture_output=True, text=True, check=False)

    assert process.returncode == 0, process.stderr
    assert "Record topic-direction evidence" in process.stdout
