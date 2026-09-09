import json
from datetime import datetime, timezone

from content_platform.kuaishou_official_signals import collect_kuaishou_public_hot_rank, creator_page_requires_login, parse_kuaishou_creator_text, parse_kuaishou_public_hot_rank, upsert_official_signal_matrix


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


def test_parse_kuaishou_public_hot_rank_keeps_official_reference_separate_from_native_association():
    html = r'''"VisionHotRankItem:AI工作流":{"rank":3,"id":"AI工作流","name":"AI工作流","viewCount":null,"hotValue":"123.4万","iconUrl":null,"poster":"https:\u002F\u002Fexample.test\u002Fposter.jpg","tagType":"新","photoIds":{"type":"json","json":["photo-1","photo-2"]},"__typename":"VisionHotRankItem"}'''

    result = parse_kuaishou_public_hot_rank(
        html,
        captured_at="2026-09-09T01:00:00+00:00",
        source_url="https://www.kuaishou.com/brilliant",
        snapshot_sha256="b" * 64,
    )

    assert result["passed"] is True
    row = result["matrix_row"]
    assert row["signals"] == ["AI工作流"]
    assert row["signal_details"][0]["hot_value"] == 1234000
    assert row["signal_details"][0]["photo_ids"] == ["photo-1", "photo-2"]
    assert row["evidence_type"] == "official_public_hot_rank"
    assert row["native_verified"] is False


def test_kuaishou_public_hot_rank_retries_one_transient_network_failure(tmp_path, monkeypatch):
    html = '"VisionHotRankItem:AI":{"rank":1,"id":"AI","name":"AI","hotValue":"10万","photoIds":{"type":"json","json":["p1"]},"__typename":"VisionHotRankItem"}'.encode("utf-8")
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return html

    def urlopen(_request, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise OSError("handshake timeout")
        return Response()

    monkeypatch.setattr("content_platform.kuaishou_official_signals.urllib.request.urlopen", urlopen)

    row, status = collect_kuaishou_public_hot_rank(tmp_path, timeout=7)

    assert row["signals"] == ["AI"]
    assert status["status"] == "ok"
    assert status["attempts"] == 2
    assert calls == [7, 7]
