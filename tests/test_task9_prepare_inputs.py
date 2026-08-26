import json
import subprocess
import sys
from pathlib import Path

from scripts.task9_prepare_inputs import _fit, prepare_inputs


def test_one_explicit_lane_keyword_meets_minimum_fit_without_inflation():
    assert _fit("AI tools worth using", "xiaohongshu") == 0.55
    assert _fit("unrelated entertainment", "xiaohongshu") == 0.0


def test_prepare_inputs_uses_real_same_lane_evidence_and_reports_missing(tmp_path: Path):
    data = tmp_path / "data"
    pack = data / "intel" / "hot_work_parameter_pack_latest.json"
    pack.parent.mkdir(parents=True)
    pack.write_text(json.dumps({"platforms": {"juejin": {"top_samples": [{
        "title": "AI workflow engineering", "url": "https://juejin.cn/post/1",
        "captured_at": "2026-08-26T00:00:00Z", "evidence_strength": "strong_logged_search_result",
    }]}}}), encoding="utf-8")

    result = prepare_inputs(data, tmp_path / "canary")

    assert any(row["platform"] == "juejin" for row in result["prepared"])
    assert any(row["platform"] == "twitter" for row in result["missing"])
    saved = json.loads((tmp_path / "canary" / "_inputs" / "hotspots" / "juejin.json").read_text(encoding="utf-8"))
    assert saved["evidence_type"] == "same_lane_hot_work"
    assert saved["source_url"].startswith("https://juejin.cn/")


def test_prepare_inputs_script_entrypoint_imports_from_repo_root():
    result = subprocess.run(
        [sys.executable, "scripts/task9_prepare_inputs.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--artifact-root" in result.stdout
