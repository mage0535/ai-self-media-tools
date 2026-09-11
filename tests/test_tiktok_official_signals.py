import hashlib
import json
from datetime import datetime, timezone

from content_platform.tiktok_official_signals import (
    collect_tiktok_creative_center_signals,
    parse_creative_center_top_videos,
)


NOW = "2026-09-11T06:00:00+00:00"


def _payload():
    return {
        "BaseResp": {"StatusCode": 0, "StatusMessage": ""},
        "entityInfos": [{
            "itemInfo": {
                "itemID": 7665338027799104781,
                "title": "AI workflow on a phone in under one minute #aitools",
                "createTime": 1788800000,
            },
            "itemMetrics": {
                "videoViews": 139035868,
                "engagementRate": 0.002848,
                "sixSecondsVTR": 0.221168,
                "organicVideoViews": 6569926,
            },
            "itemAuthorInfo": {"handlerName": "example_creator", "nickName": "Example"},
            "contentTags": [{"contentLabelID": 11015, "contentLabelName": "Technology & Finance"}],
        }],
        "pagination": {"limit": 4, "totalCount": 100, "hasMore": True},
    }


def test_creative_center_top_video_is_official_reference_not_native_hotspot():
    raw = json.dumps(_payload(), ensure_ascii=False).encode()
    result = parse_creative_center_top_videos(
        _payload(),
        captured_at=NOW,
        source_url="https://ads.us.tiktok.com/CreativeOne/Report/CreativeCenterGetTopContentsList",
        snapshot_sha256=hashlib.sha256(raw).hexdigest(),
    )

    assert result["passed"] is True
    row = result["matrix_row"]
    assert row["platform"] == "tiktok"
    assert row["status"] == "verified"
    assert row["evidence_type"] == "official_reference"
    assert row["native_verified"] is False
    assert row["access_level"] == "public_preview"
    detail = row["signal_details"][0]
    assert detail["content_id"] == "7665338027799104781"
    assert detail["canonical_url"] == "https://www.tiktok.com/@example_creator/video/7665338027799104781"
    assert detail["metrics"]["views"] == 139035868
    assert len(detail["author_id_hash"]) == 64


def test_creative_center_response_without_real_items_fails_closed():
    result = parse_creative_center_top_videos(
        {"BaseResp": {"StatusCode": 38001001, "StatusMessage": "InvalidLogin"}, "entityInfos": []},
        captured_at=NOW,
        source_url="https://ads.us.tiktok.com/CreativeOne/Report/CreativeCenterGetTopContentsList",
        snapshot_sha256="a" * 64,
    )

    assert result["passed"] is False
    assert result["matrix_row"] == {}
    assert "creative_center_api_failed" in result["failures"]


def test_current_ranking_keeps_older_creation_time_without_calling_it_recent():
    payload = _payload()
    payload["entityInfos"][0]["itemInfo"]["createTime"] = 1780704000

    result = parse_creative_center_top_videos(
        payload,
        captured_at=NOW,
        source_url="https://ads.us.tiktok.com/CreativeOne/Report/CreativeCenterGetTopContentsList",
        snapshot_sha256="a" * 64,
    )

    assert result["passed"] is True
    assert result["matrix_row"]["ranking_window_days"] == 30
    assert result["matrix_row"]["signal_details"][0]["published_at"].startswith("2026-06-")


def test_collector_uses_latest_cutoff_and_never_exposes_cookie_values(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"cookies": [{"name": "sessionid", "value": "private-value", "domain": ".tiktok.com"}]}),
        encoding="utf-8",
    )
    calls = []

    def fake_fetch(url, *, params=None):
        calls.append((url, params))
        if params is None:
            return {"lastDailyEndTimestamp": 1788800000000}
        return _payload()

    row, status = collect_tiktok_creative_center_signals(
        tmp_path / "output", state_file=state, fetch_json=fake_fetch
    )

    assert row["access_level"] == "public_preview"
    assert calls[1][1]["periodEndTimestamp"] == "1788800000"
    assert calls[1][1]["contentLabelIDs"] == "11015"
    assert "private-value" not in json.dumps(status)
    assert status["state_used"] is True
