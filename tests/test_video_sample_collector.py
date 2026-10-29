import hashlib
import json
from datetime import datetime, timedelta, timezone

from content_platform import video_sample_collector as videos


def _feed(*items):
    return lambda url, referer="": (b"{}", {"data": {"list": list(items)}})


def test_pet_feed_keeps_cats_and_dogs_but_not_pandas():
    get = _feed({"bvid": "BV1", "title": "小猫第一次洗澡", "tname": "动物二创"},
                {"bvid": "BV2", "title": "巴啦啦小熊猫", "tname": "电子竞技"},
                {"bvid": "BV3", "title": "大熊猫吃竹子", "tname": "野生动物"},
                {"bvid": "BV4", "title": "今日份", "tname": "汪星人"})
    assert [row["id"] for row in videos.bilibili_candidates("pet", get=get)] == ["BV1", "BV4"] * 4


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


def test_observation_passes_the_video_breakdown_gate(tmp_path, monkeypatch):
    from content_platform.task_source_inputs import _observed_strategy_inputs

    published = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    meta = tmp_path / "meta.json"
    meta.write_bytes(b"{}")
    monkeypatch.setattr(videos, "_metadata", lambda candidate, work: (
        {"title": "AI 剪辑实战", "author": "up", "published_at": published, "duration": 300,
         "metrics": {"view": 10}}, meta, hashlib.sha256(b"{}").hexdigest()))
    clip = tmp_path / "clip.mp4"
    monkeypatch.setattr(videos, "_download", lambda url, work, run: (clip.write_bytes(b"x"), clip)[1])
    monkeypatch.setattr(videos, "_probe_duration", lambda clip, run: 120.0)
    monkeypatch.setattr(videos, "_scene_cuts", lambda clip, run: [3.0, 9.5])
    sheet = tmp_path / "sheet.jpg"
    sheet.write_bytes(b"jpg")
    frames = [{"t": float(i), "path": str(tmp_path / f"f{i}.jpg"), "sha256": "0" * 64} for i in range(videos.FRAMES)]
    monkeypatch.setattr(videos, "_keyframes", lambda clip, duration, work, run: (frames, sheet))
    monkeypatch.setattr(videos, "_transcribe", lambda clip, work, run: {
        "language": "zh", "segments": [{"start": 0, "end": 2, "text": "今天教你用AI剪辑"}]})
    monkeypatch.setattr(videos, "_describe", lambda sheet, context, run: {
        "frames": ["剪辑软件界面"] * videos.FRAMES, "motion": ["鼠标拖动时间线"], "transitions": ["hard cut"],
        "content_structure": ["开场演示"], "writing_style": "口语", "topic_direction": "AI剪辑", "assets": ["screen recording"],
        "theme_template": "暗色界面"})
    candidate = {"id": "BV1", "url": "https://www.bilibili.com/video/BV1", "feed_url": "f", "feed_sha256": "0" * 64}

    row = videos.observe_video(candidate, tmp_path)

    assert row["voiceover"]["status"] == "verified" and row["copy_or_script"] == "今天教你用AI剪辑"
    assert row["transition_combination"]["cuts_per_minute"] == 1.0 and not clip.exists()
    stored = json.loads(open(row["raw_snapshot_ref"]["path"], encoding="utf-8").read())
    assert stored["visual_evidence"] == row["visual_evidence"]
    result = _observed_strategy_inputs("bilibili", {"items": [row]})
    assert result["viral_breakdown"]["status"] == "ready"
