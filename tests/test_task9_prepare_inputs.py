import json
from pathlib import Path

from scripts.task9_prepare_inputs import prepare_inputs


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
