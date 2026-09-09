import json
from datetime import datetime, timezone

from content_platform.kuaishou_official_signals import creator_page_requires_login, parse_kuaishou_creator_text, upsert_official_signal_matrix


def test_parse_kuaishou_creator_text_extracts_ranked_inspiration_and_activity():
    text = """
创作灵感
查看更多
ai工具
15.6万人参与·高热涨粉·为你推荐
学霸秘籍
108.2万人参与·潜力爆款·高热播放
激励活动
活动多多 奖励多多
凛冬下的罪恶二创大赛
发稿必有奖·明星娱乐·影视综·热点创作
精选
"""
    result = parse_kuaishou_creator_text(
        text,
        captured_at="2026-09-06T04:00:00+00:00",
        source_url="https://cp.kuaishou.com/profile",
        snapshot_sha256="a" * 64,
    )

    assert result["passed"] is True
    row = result["matrix_row"]
    assert row["signals"] == ["ai工具", "学霸秘籍"]
    assert row["signal_details"][0]["participants"] == 156000
    assert "为你推荐" in row["signal_details"][0]["labels"]
    assert row["activities"][0]["title"] == "凛冬下的罪恶二创大赛"
    assert row["native_verified"] is False
    assert row["evidence_type"] == "official_keyword"


def test_upsert_official_signal_matrix_preserves_other_platforms(tmp_path):
    now = datetime(2026, 9, 6, 4, 0, tzinfo=timezone.utc)
    target = tmp_path / "overnight" / "2026-09-06" / "official-platform-signal-matrix-v3.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({
        "schema": "official-platform-signal-matrix-v3",
        "platforms": [{"platform": "zhihu", "status": "verified"}, {"platform": "kuaishou", "status": "old"}],
    }), encoding="utf-8")
    row = {"platform": "kuaishou", "status": "backend_loaded", "signals": ["ai工具"]}

    written = upsert_official_signal_matrix(tmp_path, row, now=now)
    payload = json.loads(written.read_text(encoding="utf-8"))

    assert [item["platform"] for item in payload["platforms"]] == ["zhihu", "kuaishou"]
    assert payload["platforms"][1]["status"] == "backend_loaded"
    assert payload["updated_at"] == now.isoformat()


def test_kuaishou_public_creator_landing_page_is_login_required():
    assert creator_page_requires_login("快手创作者服务平台\n立即登录\n平台热点") is True
    assert creator_page_requires_login("创作灵感\nai工具\n15.6万人参与\n激励活动") is False
