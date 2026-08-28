import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from content_platform.trends import DirectTrendSource
from scripts.wechat_official_signal_collector import build_wechat_official_contracts


CAPTURED_AT = "2026-08-27T01:30:00+00:00"


def _snapshot(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def test_wewrite_hotspot_becomes_official_keyword_with_complete_provenance():
    payload = {"hotspots": [{
        "keyword": "AI 工作流",
        "url": "https://mp.weixin.qq.com/s/example",
        "captured_at": CAPTURED_AT,
        "heat": 42800,
        "rank": 3,
    }]}
    raw = _snapshot(payload)

    result = build_wechat_official_contracts(payload, raw_snapshot=raw, source_kind="wewrite_hotspots")

    assert result["passed"] is True
    assert result["rejected"] == []
    contract = result["contracts"][0]
    assert contract["evidence_type"] == "official_keyword"
    assert contract["signal_type"] == "hot_list"
    assert contract["signals"] == ["AI 工作流"]
    assert contract["official_url"] == "https://mp.weixin.qq.com/s/example"
    assert contract["captured_at"] == CAPTURED_AT
    assert contract["heat"] == 42800
    assert contract["rank"] == 3
    assert contract["evidence_sha256"] == hashlib.sha256(raw).hexdigest()


def test_creator_backend_emits_keyword_and_activity_contracts():
    payload = {
        "official_url": "https://mp.weixin.qq.com/cgi-bin/home?t=home/index",
        "captured_at": CAPTURED_AT,
        "backend_visible": True,
        "search_queries": [{"keyword": "智能体教程", "rank": 2}],
        "activities": [{"title": "AI 创作征集", "heat": 9600}],
    }
    raw = _snapshot(payload)

    result = build_wechat_official_contracts(payload, raw_snapshot=raw, source_kind="creator_backend")

    assert result["passed"] is True
    assert {row["evidence_type"] for row in result["contracts"]} == {
        "official_keyword", "official_activity"
    }
    by_type = {row["evidence_type"]: row for row in result["contracts"]}
    assert by_type["official_keyword"]["rank"] == 2
    assert by_type["official_activity"]["heat"] == 9600
    assert all(row["evidence_sha256"] == hashlib.sha256(raw).hexdigest() for row in result["contracts"])


def test_sogou_search_cannot_be_relabelled_official_or_hotspot():
    payload = {"hotspots": [{
        "keyword": "AI 工作流",
        "url": "https://weixin.sogou.com/weixin?query=AI",
        "captured_at": CAPTURED_AT,
        "heat": 99999,
    }]}

    result = build_wechat_official_contracts(
        payload,
        raw_snapshot=_snapshot(payload),
        source_kind="wewrite_hotspots",
    )

    assert result["passed"] is False
    assert result["contracts"] == []
    assert result["rejected"][0]["failures"] == ["sogou_source_forbidden"]


def test_missing_url_time_or_heat_rank_fails_closed():
    payload = {"hotspots": [
        {"keyword": "missing URL", "captured_at": CAPTURED_AT, "heat": 1},
        {"keyword": "missing time", "url": "https://mp.weixin.qq.com/s/a", "rank": 1},
        {"keyword": "missing metric", "url": "https://mp.weixin.qq.com/s/b", "captured_at": CAPTURED_AT},
    ]}

    result = build_wechat_official_contracts(
        payload,
        raw_snapshot=_snapshot(payload),
        source_kind="wewrite_hotspots",
    )

    assert result["passed"] is False
    assert result["contracts"] == []
    assert {failure for row in result["rejected"] for failure in row["failures"]} == {
        "source_url_missing", "captured_at_missing", "heat_or_rank_missing"
    }


def test_trends_wewrite_bridge_returns_only_qualified_official_contracts():
    payload = {"hotspots": [
        {
            "keyword": "合格公众号关键词",
            "url": "https://mp.weixin.qq.com/s/qualified",
            "captured_at": CAPTURED_AT,
            "heat": 88,
            "rank": 4,
        },
        {
            "keyword": "搜狗普通搜索",
            "url": "https://weixin.sogou.com/weixin?query=test",
            "captured_at": CAPTURED_AT,
            "heat": 999,
        },
    ]}
    stdout = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    completed = type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    with patch("content_platform.trends.Path.is_file", return_value=True), patch(
        "content_platform.trends.subprocess.run", return_value=completed
    ):
        items = DirectTrendSource(
            "wewrite_hotspots", {"wewrite_bin": "/tmp/wewrite", "limit": 5}
        ).collect()

    assert len(items) == 1
    assert items[0]["source"] == "wewrite_hotspots"
    assert items[0]["platform"] == "wechat"
    assert items[0]["evidence_type"] == "official_keyword"
    assert items[0]["url"] == "https://mp.weixin.qq.com/s/qualified"
    assert items[0]["points"] == 88
    assert items[0]["rank"] == 4
    assert items[0]["raw_snapshot_sha256"] == hashlib.sha256(stdout.encode("utf-8")).hexdigest()


def test_cli_writes_matrix_and_returns_nonzero_when_no_contracts(tmp_path: Path):
    from scripts.wechat_official_signal_collector import main

    source = tmp_path / "sogou.json"
    output = tmp_path / "matrix.json"
    source.write_text(json.dumps({"items": [{
        "keyword": "普通搜索",
        "url": "https://www.sogou.com/web?query=test",
        "captured_at": CAPTURED_AT,
        "rank": 1,
    }]}), encoding="utf-8")

    assert main(["--input", str(source), "--output", str(output), "--source-kind", "wewrite_hotspots"]) == 2
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["platforms"] == []
    assert saved["passed"] is False
