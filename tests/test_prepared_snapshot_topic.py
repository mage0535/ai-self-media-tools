import json

from content_platform.task_source_inputs import _prepared_snapshot_items


def test_newest_prepare_snapshot_supplies_the_prepared_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_PLATFORM_TREND_CACHE_DIR", str(tmp_path))
    item = {"title": "飞书多维表格+豆包AI实战：从0搭建智能CRM", "source": "bilibili:scenario", "raw_response_hash": "h"}
    (tmp_path / "trend_snapshot_2026-11-01.json").write_text(json.dumps({"items": [dict(item, raw_response_hash="old")]}))
    (tmp_path / "trend_snapshot_2026-11-02.json").write_text(json.dumps({"items": [item, {"title": "other"}]}))
    found = _prepared_snapshot_items(item["title"])
    assert [row["raw_response_hash"] for row in found] == ["h"]
    assert found[0]["prepared_snapshot_ref"].endswith("trend_snapshot_2026-11-02.json")
    assert _prepared_snapshot_items("not prepared") == []
