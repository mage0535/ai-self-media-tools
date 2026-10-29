import hashlib
import json

import pytest
from datetime import datetime, timedelta, timezone

from content_platform import video_sample_collector as videos


def _feed(*items):
    return lambda url, referer="": (b"{}", {"data": {"list": list(items)}})


def test_pet_feed_keeps_cats_and_dogs_but_not_pandas():
    get = _feed({"bvid": "BV1", "title": "小猫第一次洗澡", "tname": "动物二创"},
                {"bvid": "BV2", "title": "巴啦啦小熊猫", "tname": "电子竞技"},
                {"bvid": "BV3", "title": "大熊猫吃竹子", "tname": "野生动物"},
                {"bvid": "BV4", "title": "今日份", "tname": "汪星人"})
    assert [row["id"] for row in videos.bilibili_candidates("pet", get=get)] == ["BV1", "BV4"]


def test_ai_feed_matches_whole_ascii_words_only():
    get = _feed({"bvid": "BV1", "title": "DeepSeek 新功能", "tname": "计算机技术"},
                {"bvid": "BV2", "title": "Switch 再见", "tname": "数码"},
                {"bvid": "BV3", "title": "AI 剪辑实战", "tname": "数码"})
    assert [row["id"] for row in videos.bilibili_candidates("ai", get=get)] == ["BV1", "BV3"]


def test_unobservable_video_is_skipped_with_its_reason(tmp_path):
    def observe(candidate, out_dir):
        if candidate["id"] == "BV1":
            raise ValueError("video_download_failed")
        return {"content_id": candidate["id"]}

    rows = videos.collect_samples([{"id": "BV1"}, {"id": "BV2"}, {"id": "BV2"}], tmp_path, observe=observe)
    assert rows == [{"content_id": "BV2"}]
    assert "video_download_failed" in (tmp_path / "skipped-BV1.txt").read_text()


def _fake_pipeline(tmp_path, monkeypatch, language="zh"):
    published = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    meta = tmp_path / "meta.json"
    meta.write_bytes(b"{}")
    monkeypatch.setattr(videos, "_metadata", lambda candidate, work, run: (
        {"title": "AI 剪辑实战", "author": "up", "published_at": published, "duration": 300,
         "metrics": {"view": 10}}, meta, hashlib.sha256(b"{}").hexdigest()))
    clip = tmp_path / "clip.mp4"
    monkeypatch.setattr(videos, "_download", lambda platform, url, duration, work, run: (clip.write_bytes(b"x"), clip)[1])
    monkeypatch.setattr(videos, "_probe_duration", lambda clip, run: 120.0)
    monkeypatch.setattr(videos, "_scene_cuts", lambda clip, run: [3.0, 9.5])
    sheet = tmp_path / "sheet.jpg"
    sheet.write_bytes(b"jpg")
    frames = [{"t": float(i), "path": str(tmp_path / f"f{i}.jpg"), "sha256": "0" * 64} for i in range(videos.FRAMES)]
    monkeypatch.setattr(videos, "_keyframes", lambda clip, duration, work, run: (frames, sheet))
    monkeypatch.setattr(videos, "_transcribe", lambda platform, clip, work, run: {
        "language": language, "segments": [{"start": 0, "end": 2, "text": "今天教你用AI剪辑"}]})
    monkeypatch.setattr(videos, "_describe", lambda sheet, context, run: {
        "frames": ["剪辑软件界面"] * videos.FRAMES, "motion": ["鼠标拖动时间线"], "transitions": ["hard cut"],
        "content_structure": ["开场演示"], "writing_style": "口语", "topic_direction": "AI剪辑", "assets": ["screen recording"],
        "theme_template": "暗色界面"})
    return clip


CANDIDATE = {"platform": "bilibili", "id": "BV1", "url": "https://www.bilibili.com/video/BV1",
             "feed_url": "f", "feed_sha256": "0" * 64}


def test_observation_passes_the_video_breakdown_gate(tmp_path, monkeypatch):
    from content_platform.task_source_inputs import _observed_strategy_inputs

    clip = _fake_pipeline(tmp_path, monkeypatch)
    row = videos.observe_video(CANDIDATE, tmp_path)

    assert row["voiceover"]["status"] == "verified" and row["copy_or_script"] == "今天教你用AI剪辑"
    assert row["transition_combination"]["cuts_per_minute"] == 1.0 and not clip.exists()
    stored = json.loads(open(row["raw_snapshot_ref"]["path"], encoding="utf-8").read())
    assert stored["visual_evidence"] == row["visual_evidence"]
    result = _observed_strategy_inputs("bilibili", {"items": [row]})
    assert result["viral_breakdown"]["status"] == "ready"


def test_speech_in_another_language_than_the_lane_is_rejected(tmp_path, monkeypatch):
    _fake_pipeline(tmp_path, monkeypatch, language="hi")
    with pytest.raises(ValueError, match="video_language_mismatch:hi"):
        videos.observe_video(dict(CANDIDATE, platform="youtube"), tmp_path)


def test_feed_keeps_recent_ai_videos_most_viewed_first():
    now = datetime.now(timezone.utc).timestamp()
    entries = [{"id": "old", "title": "AI agent", "timestamp": now - 40 * 86400, "view_count": 9e6},
               {"id": "dance", "title": "dance trend", "timestamp": now, "view_count": 8e6},
               {"id": "a", "title": "Codex builds a board", "description": "#ai", "timestamp": now, "view_count": 10},
               {"id": "b", "title": "ChatGPT tips", "timestamp": now, "view_count": 500}]
    rows = videos._ranked("tiktok", [dict(row, uploader="openai") for row in entries], "feed", "0" * 64)
    assert [row["id"] for row in rows] == ["b", "a"]
    assert rows[0]["url"] == "https://www.tiktok.com/@openai/video/b" and rows[0]["platform"] == "tiktok"


def test_bilibili_risk_control_code_is_an_error_not_an_empty_feed(monkeypatch):
    import io

    class Opener:
        def __init__(self):
            self.urls = []

        def open(self, request, timeout):
            self.urls.append(request.full_url)
            return io.BytesIO(b"<html>" if request.full_url.endswith(".com/") else b'{"code": -352, "data": null}')

    opener = Opener()
    monkeypatch.setattr(videos.urllib.request, "build_opener", lambda *handlers: opener)
    monkeypatch.setattr(videos, "_VISITOR", videos.http.cookiejar.CookieJar())
    with pytest.raises(ValueError, match="bilibili_api_code_-352"):
        videos._get_json("https://api.bilibili.com/x/web-interface/ranking/v2?rid=188&type=all")
    assert opener.urls[0] == "https://www.bilibili.com/"


def test_short_videos_are_downloaded_whole_and_long_ones_cut(tmp_path):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        (tmp_path / "clip.mp4").write_bytes(b"x")
        return __import__("types").SimpleNamespace(returncode=0, stderr="")

    videos._download("tiktok", "u", 61, tmp_path, run)
    videos._download("bilibili", "u", 900, tmp_path, run)
    assert "--download-sections" not in commands[0] and "--download-sections" in commands[1]
